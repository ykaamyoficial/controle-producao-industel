# Fase 4 - Diagnostico

## Objetivo

Transformar os testes de conectividade existentes em um diagnóstico técnico
confiável, capaz de dizer não só "conectou ou não conectou", mas **onde** a
cadeia Desktop → configuração → rede → API → PostgreSQL falhou, com códigos
de causa estáveis e mensagens orientadas a ação — sem que o Desktop jamais
abra conexão direta com o PostgreSQL.

## Diagnóstico inicial (auditoria)

| Componente | Situação encontrada |
|---|---|
| Configuração `API_BASE_URL` | Já centralizada (`DesktopApiConfigStore`, Fase 2) |
| Cliente HTTP | Já central (`DesktopApiClient`), com timeouts, retries e hierarquia de exceções (`ApiConnectionError`/`ApiTimeoutError`/`ApiUnavailableError`/...), mas **erros HTTP não-2xx descartavam o corpo da resposta** (`_parse_response` sempre levanta exceção, mesmo quando o corpo tinha informação útil, como o 503 estruturado de `/health/ready`) |
| Health da API | `/api/v1/health/ready` (Fase 1) já retorna `overall_status` + lista de `checks` nomeados (incluindo `"database"`), com 200/503 — contrato **já suficiente**, não precisou evoluir |
| Check do PostgreSQL | Já somente leitura, dentro da API (`SELECT 1` equivalente), sem devolver credenciais/DSN (confirmado na Fase 1) |
| Tela de diagnóstico | `ApiDiagnosticDialog` já existia (aberta via "Configurações → API e PostgreSQL", admin-only), mas com testes avulsos (`Testar conexão`, `Testar compatibilidade`) que só logavam texto solto — sem cadeia determinística, sem catálogo de códigos, sem "Copiar relatório" |
| Logs | Já usam `sanitize_secret` nas exceções da API; nenhum log de credencial encontrado |
| Testes existentes | Cobriam config/bootstrap/cliente HTTP, mas nada testava classificação de causa de falha de rede (DNS vs. recusa vs. timeout) |

**Gap real corrigido:** `DesktopApiClient` mapeava *qualquer* HTTP 503 para
um `ApiUnavailableError` genérico ("service unavailable"), descartando o
corpo estruturado que `/health/ready` devolve (`checks: [{"name":
"database", "status": "FAIL", ...}]`). Sem isso, o diagnóstico não
conseguiria dizer *qual* dependência falhou.

## Arquivos alterados/criados

- `app/services/diagnostic_service.py` (novo) — `DiagnosticResult`,
  `DiagnosticCheck`, `DiagnosticStatus`, `DiagnosticErrorCode`,
  `run_diagnostics()`, `classify_connect_exception()`, `build_report_text()`.
- `app/integrations/api/client.py` — novo método
  `DesktopApiClient.get_status_and_payload()`: GET que nunca levanta exceção
  por status HTTP, preservando o corpo em qualquer código (necessário só
  para o diagnóstico; os demais métodos do cliente continuam com o
  comportamento de exceção de sempre).
- `app/ui/api_diagnostic_dialog.py` — novo bloco "Diagnóstico de conexão" no
  topo do diálogo existente (não foi criado um segundo diálogo).
- Testes novos: `tests/test_diagnostic_service.py` (15),
  `tests/test_api_diagnostic_dialog.py` (5).

## Serviço de diagnóstico e cadeia de checks

`run_diagnostics(config_store, client_factory)` executa, em ordem
determinística, exatamente os 7 checks da Seção 3 do prompt técnico:

```text
CONFIG_PRESENT -> URL_VALID -> HOST_RESOLUTION -> API_REACHABLE
  -> HEALTH_HTTP -> API_HEALTH -> DATABASE_HEALTH
```

Uma etapa que falha marca **todas** as seguintes como `NOT_TESTED` (nunca
gera ruído de dependência). `HOST_RESOLUTION` usa `socket.getaddrinfo`
diretamente quando o host é um nome DNS; para IP literal, é considerado OK
sem round-trip (Seção 3: "quando aplicável"). `API_REACHABLE` +
`HEALTH_HTTP` + `API_HEALTH` + `DATABASE_HEALTH` derivam de uma **única**
chamada `GET /api/v1/health/ready` — sem round-trips redundantes.

Não depende de ICMP/ping em nenhum ponto; usa exclusivamente a mesma rota
TCP/HTTP do sistema real.

## Catálogo de erros e mapeamento de exceções

`DiagnosticErrorCode`: `CFG_MISSING`, `CFG_INVALID`,
`HOST_RESOLUTION_FAILED`, `CONNECT_TIMEOUT`, `CONNECTION_REFUSED`,
`NETWORK_UNREACHABLE`, `HTTP_UNEXPECTED`, `API_UNHEALTHY`, `DB_UNAVAILABLE`
— exatamente o catálogo da Seção 5.

`classify_connect_exception()` percorre a cadeia `__cause__`/`__context__`
de uma falha de conexão (preservada porque `DesktopApiClient` sempre usa
`raise ... from exc`) procurando o sinal mais específico disponível:
`socket.gaierror`/"getaddrinfo failed" → `HOST_RESOLUTION_FAILED`;
`ConnectionRefusedError`/"10061" → `CONNECTION_REFUSED`; "network is
unreachable"/"10051"/"10065" → `NETWORK_UNREACHABLE`; sem sinal específico,
assume `CONNECTION_REFUSED` (causa mais comum de "API não está rodando").
httpx não expõe um tipo de exceção dedicado para cada caso — por isso a
inspeção da cadeia de causas, em vez de comparar apenas o tipo da exceção
externa.

401/403 nunca são classificados como rede: como `get_status_and_payload()`
nunca levanta exceção por status HTTP, qualquer resposta HTTP (mesmo
401/403/404/500) já prova que a etapa `API_REACHABLE` foi bem-sucedida —
a falha correspondente (se houver) aparece só em `HEALTH_HTTP` (contrato
inesperado), nunca reclassificada como "servidor offline".

## Health da API

Contrato final: **inalterado**, reaproveitado integralmente de
`GET /api/v1/health/ready` (Fase 1) — 200 quando `HEALTHY`/`DEGRADED`, 503
quando `UNHEALTHY`, corpo com `overall_status` e `checks[]` nomeados
(`database`, `schema_revision`, `version`), sem credenciais, sem stack
trace, somente leitura. Não foi necessário evoluir o contrato porque ele já
distinguia API de PostgreSQL adequadamente.

## UI — Configurações > API e PostgreSQL

Nenhuma tela nova foi criada. `ApiDiagnosticDialog` (já aberta pelo mesmo
botão de sempre, restrito a administradores) ganhou um bloco no topo:

- Status geral (`OK`/`ATENCAO`/`ERRO`/`NAO EXECUTADO`), servidor
  configurado, horário do último teste e tempo total.
- Botão **Executar diagnóstico** — roda `run_diagnostics()` em `QThread` via
  `start_worker` (mesmo mecanismo já usado pelas outras ações do diálogo);
  o botão desabilita durante a execução e reabilita ao final, sem travar a
  interface.
- Lista com as 7 etapas, cada uma com marcador textual de estado (`[OK]`,
  `[ATENCAO]`, `[ERRO]`, `[NAO TESTADO]`) + detalhe, e sugestão de ação
  quando aplicável — texto e estado juntos, sem depender só de cor.
- Botão **Copiar relatório** — habilitado só após uma execução, copia o
  texto sanitizado (`build_report_text`) para a área de transferência via
  `QApplication.clipboard()` (mesmo padrão já usado em `operational_reports_page.py`).
- Uma nova execução limpa e substitui a lista anterior (sem sobrepor
  widgets).

## Segurança

- `get_status_and_payload()` só lê (`GET`); nenhum novo caminho de escrita.
- `DiagnosticResult.api_base_url_sanitized` remove qualquer userinfo
  (`usuario:senha@`) do endereço antes de aparecer em tela ou no relatório
  (testado explicitamente — ver `test_report_text_is_sanitized_and_contains_no_secrets`).
- O relatório copiável nunca inclui `Authorization`/tokens (não há nenhum
  cabeçalho de autenticação no fluxo de diagnóstico, que é sempre anônimo/
  somente leitura).
- Permissão inalterada: o diagnóstico continua restrito a
  `self.service.can_admin()` na tela de Configurações, como já era.

## Testes

```bash
python -m unittest tests.test_diagnostic_service -v                         # 15 testes
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_api_diagnostic_dialog -v   # 5 testes
```

Regressão consolidada (159 testes, incluindo todo o material de Fase 2/3
mais os módulos tocados nesta fase — `client.py`, `api_diagnostic_dialog.py`):

```bash
QT_QPA_PLATFORM=offscreen python -m unittest \
  tests.test_diagnostic_service tests.test_api_diagnostic_dialog \
  tests.test_bootstrap_service tests.test_first_access_dialog tests.test_startup_bootstrap \
  tests.test_desktop_api_config tests.test_desktop_api_client tests.test_api_proposal_storage \
  tests.test_update_audit_client tests.test_update_distribution_client tests.test_startup_compatibility_check \
  tests.test_system_api_client_compatibility tests.test_update_coordinator tests.test_api_session_concurrency \
  tests.test_settings_dialog tests.test_postgresql_only_config -v
# Ran 159 tests -- OK
```

Cobertura da lista mínima do prompt técnico (Seção 12): configuração
ausente → `CFG_MISSING` + demais `NOT_TESTED`; URL inválida → `CFG_INVALID`
sem chamada HTTP; falha de resolução de host → `HOST_RESOLUTION_FAILED`;
timeout → `CONNECT_TIMEOUT`; connection refused → `CONNECTION_REFUSED`;
200+health ok+DB ok → `OK` geral; 503+DB indisponível → API alcançável e
`DB_UNAVAILABLE`; 500 → API alcançável, falha interna, nunca confundida com
rede; 401 → resposta do servidor, nunca "offline"; nenhum teste abre
conexão direta ao PostgreSQL (todos usam `httpx.MockTransport`/arquivos
temporários).

## Validação manual

Executada via simulação com `httpx.MockTransport` (equivalente determinístico
aos cenários "API parada"/"DB parado"/"endereço errado"/"servidor lento" da
Seção 13 — timeout, connection refused, 503 com banco indisponível, 500
genérico e 404 foram todos exercitados nos testes automatizados acima).
**Não foi possível validar contra um servidor físico real** (mesma
limitação já registrada nas Fases 1 e 3: não há segundo computador nem IP
oficial do servidor disponível neste momento).

## Pendências

- Validação em ambiente físico real (Windows Server + rede da empresa)
  continua pendente, como nas fases anteriores.
- Nenhuma dependência nova do Windows Server foi introduzida por esta fase.

## Confirmação de escopo

Não foram implementados: HTTPS/certificados/reverse proxy (Fase 5),
negociação de compatibilidade de versão (já existente de uma fase interna
anterior, não alterada aqui), instalador/atualizador (Fase 7), acesso
externo, ou qualquer alteração de regra de negócio/migration. O contrato de
`/health/ready` foi reaproveitado sem alteração.
