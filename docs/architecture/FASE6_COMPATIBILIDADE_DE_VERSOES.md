# Fase 6 - Compatibilidade de Versões

## Objetivo

Impedir combinações inseguras de Desktop/API: um Desktop antigo demais para
a API atual, ou um Desktop novo apontando para uma API antiga demais —
detectado **antes** do login, com bloqueio seguro e diagnóstico claro.

## Diagnóstico inicial (auditoria)

O sistema já possuía, de fases internas anteriores do projeto, uma
implementação de compatibilidade **muito mais madura** do que a fase parte
do princípio:

| Item do prompt técnico | Situação encontrada |
|---|---|
| Fonte única Desktop | `app/version.py` — `APP_VERSION = "2.5.2"` |
| Fonte única API | `api/app/core/config.py` — `API_VERSION`, `MINIMUM_DESKTOP_VERSION`, `RECOMMENDED_DESKTOP_VERSION`, `MAXIMUM_DESKTOP_VERSION` |
| Comparador SemVer | `app/versioning/parser.py` — comparação **numérica** por tupla (`(3,10,0) > (3,9,0)`), já correta; nenhuma comparação textual encontrada |
| Endpoint pré-login | `GET /api/v1/system/version` e `GET /api/v1/system/compatibility` já existiam, sem autenticação, somente leitura |
| Estados de compatibilidade | `CompatibilityStatus` já tinha `COMPATIBLE/UPDATE_AVAILABLE/UPDATE_RECOMMENDED/UPDATE_REQUIRED/INCOMPATIBLE/MAINTENANCE/CHECK_FAILED` |
| Integração com bootstrap | `run_startup_compatibility_check()` já roda em `main.py`, depois do bootstrap da Fase 3, antes do login, com `CompatibilityGateDialog` (tela de bloqueio já existente) |
| Fail-safe de metadados inválidos | `CompatibilityPolicy.__post_init__` já valida SemVer e `run_compatibility_check()` já mapeia `ValueError` para `CHECK_FAILED` |
| Enforcement server-side | `api/app/updates/policy.py` já implementa um sistema de enforcement **muito mais sofisticado** que o pedido (grace period, canais de rollout, releases autorizadas) |

**Gaps reais encontrados** (únicos pontos implementados nesta fase):

1. **Faltava o lado "Desktop → API mínima" da verificação bidirecional**
   (REGRA B do prompt). O sistema só comparava `api_contract_version`
   (string, ex. `"v1"`) por igualdade — protege contra ruptura de contrato,
   mas **não** contra uma API semanticamente desatualizada que ainda declara
   o mesmo contrato `"v1"`. Não existia `MINIMUM_API_VERSION` nem estado
   `SERVER_UPDATE_REQUIRED` em nenhum lugar do código.
2. **Faltava a segunda barreira no backend** (Seção 10/11): o cliente HTTP
   central (`DesktopApiClient`) nunca enviava a versão do Desktop em nenhum
   header (`User-Agent` estático, sem versão); a API não tinha nenhum
   mecanismo de rejeitar chamadas de negócio de um cliente abaixo do mínimo.
3. **Faltava a etapa de compatibilidade no diagnóstico da Fase 4**
   (`diagnostic_service.py`, construído nesta mesma sessão) — a cadeia
   parava em `DATABASE_HEALTH`, sem verificar `/system/compatibility`.

## Arquivos alterados/criados

**Desktop:**
- `app/version.py` — novo `MINIMUM_API_VERSION`.
- `app/versioning/models.py` — novo estado `CompatibilityStatus.SERVER_UPDATE_REQUIRED`.
- `app/versioning/compatibility.py` — `evaluate_startup_compatibility()` ganhou o parâmetro opcional `minimum_api_version`.
- `app/versioning/versions.py` / `__init__.py` — novo `get_minimum_api_version()`.
- `app/services/compatibility_check.py` — passa `minimum_api_version` na chamada real.
- `app/ui/compatibility_gate_dialog.py` — mensagem e bloqueio para `SERVER_UPDATE_REQUIRED`.
- `app/integrations/api/client.py` — header `X-Client-Version` em toda requisição.
- `app/services/diagnostic_service.py` — novas etapas `VERSION_ENDPOINT`/`COMPATIBILITY`, 4 novos códigos de erro.

**API:**
- `api/app/core/error_codes.py` — `CLIENT_VERSION_UNSUPPORTED`.
- `api/app/core/config.py` — `client_version_enforcement_enabled` (default `False`).
- `api/app/core/client_version_middleware.py` (novo) — segunda barreira defensiva.
- `api/app/main.py` — registra o novo middleware.
- `api/.env.example` — documenta `CLIENT_VERSION_ENFORCEMENT_ENABLED`.

**Testes:** `tests/test_compatibility_check.py` (+7), `tests/test_diagnostic_service.py` (+7),
`tests/test_api_diagnostic_dialog.py` (ajustado), `api/tests/test_client_version_middleware.py` (novo, 7 testes).

## Fonte única Desktop / API (valores atuais)

- `DESKTOP_VERSION` → `app.version.APP_VERSION` = `"2.5.2"`.
- `MINIMUM_API_VERSION` (Desktop) = `"0.8.0"` — igual ao `API_VERSION` atual (nenhuma versão anterior da API é conhecida como necessária; o valor só deve subir quando o Desktop passar a depender de verdade de algo novo da API).
- `API_VERSION` (API) = `"0.8.0"`; `MINIMUM_DESKTOP_VERSION` = `"2.5.2"`; `RECOMMENDED_DESKTOP_VERSION` = `"2.5.2"`.

Nenhum número de versão real do projeto foi alterado só para "testar" a fase — todos os cenários de bloqueio foram cobertos por testes com valores sintéticos, como pedido explicitamente no prompt técnico.

## Endpoint

Reaproveitado sem alterações: `GET /api/v1/system/compatibility` (e `/system/version` para metadados simples). Sem autenticação, somente leitura, schema Pydantic tipado, nunca devolve segredos.

## Algoritmo (ordem de prioridade final)

```text
1. maintenance_mode == True                                -> MAINTENANCE
2. api_contract_version != contrato suportado pelo Desktop  -> INCOMPATIBLE
3. server_version < MINIMUM_API_VERSION do Desktop          -> SERVER_UPDATE_REQUIRED   (NOVO)
4. server_desktop_state (quando o servidor já calculou)     -> usa diretamente
5. sem desktop_state: comparação local min/recomendado      -> COMPATIBLE / UPDATE_AVAILABLE / UPDATE_REQUIRED
```

O passo 3 é verificado **antes** de consultar `server_desktop_state`: um
servidor desatualizado demais não é uma fonte confiável para dizer se um
Desktop mais novo pode operar com ele.

## Bootstrap (ponto exato do check)

Inalterado — já existia e já está no lugar certo:
`app/main.py:main()` → `run_startup_bootstrap()` (Fase 3: config/rede/health)
→ `run_startup_compatibility_check()` (Fase 6: `/system/compatibility` +
`evaluate_startup_compatibility`, com `CompatibilityGateDialog` bloqueando
antes de `MainWindow`/login) → `run_startup_update_check()` → login.

## Backend — proteção defensiva (segunda barreira)

- `DesktopApiClient` agora envia `X-Client-Version: <APP_VERSION>` em toda
  requisição (GET/POST/PATCH/DELETE/bytes), usando o pipeline central de
  headers já existente — sem duplicar lógica.
- `ClientVersionMiddleware` (novo, API): quando
  `CLIENT_VERSION_ENFORCEMENT_ENABLED=true` (**desligado por padrão** —
  rollout controlado, Seção 11), rejeita com `HTTP 426`
  `{"code": "CLIENT_VERSION_UNSUPPORTED", "minimum_desktop_version": "..."}`
  qualquer chamada de negócio sem o header ou abaixo do mínimo. `/health` e
  os endpoints pré-login (`/system/health`, `/system/ready`,
  `/system/version`, `/system/compatibility`, `/system/maintenance`)
  permanecem sempre isentos. Header malformado nunca vira 500 — é tratado
  como versão rejeitada, mesma resposta 426.
- A versão do cliente **nunca** substitui autenticação/RBAC — é usada
  apenas para compatibilidade/observabilidade, exatamente como exigido.

## Diagnóstico (Fase 4) — duas etapas novas

Sem criar uma segunda tela: `diagnostic_service.py` ganhou `VERSION_ENDPOINT`
e `COMPATIBILITY` ao final da mesma cadeia de 7 etapas da Fase 4 (agora 9),
reutilizando `evaluate_startup_compatibility` (nenhuma regra de comparação
duplicada). A chamada a `/system/compatibility` no diagnóstico é
**deliberadamente somente leitura**: não envia `installation_id`, para nunca
disparar o heartbeat/registro de canal que esse parâmetro aciona no
servidor (testado explicitamente).

Novos códigos: `CLIENT_UPDATE_REQUIRED`, `SERVER_UPDATE_REQUIRED`,
`VERSION_METADATA_INVALID`, `VERSION_ENDPOINT_UNAVAILABLE`. `UPDATE_AVAILABLE`/`UPDATE_RECOMMENDED` aparecem como `WARNING` (não bloqueiam); `MAINTENANCE` também vira `WARNING` informativo, distinto de um erro de versão de verdade.

Exemplo real capturado em teste:

```text
CONFIG_PRESENT: OK
URL_VALID: OK
HOST_RESOLUTION: OK
API_REACHABLE: OK
HEALTH_HTTP: OK
API_HEALTH: OK
DATABASE_HEALTH: OK
VERSION_ENDPOINT: OK
COMPATIBILITY: ERROR - Desktop: 2.5.2 | API: 0.0.1 | Min Desktop: 0.0.1
```

## Logs

`compatibility_check.py` já registrava `[INFO] Verificacao de
compatibilidade concluida | local_desktop_version=... | server_version=...
| compatibility_state=...` sem segredos (inalterado). `ClientVersionMiddleware`
registra `CLIENT_VERSION_MISSING`/`CLIENT_VERSION_MALFORMED`/`CLIENT_VERSION_REJECTED`
com path e versão recebida — nunca `Authorization`/tokens/payload.

## Testes

```bash
python -m unittest tests.test_compatibility_check -v      # 27 testes (7 novos)
python -m unittest tests.test_diagnostic_service -v        # 33 testes (7 novos)
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_api_diagnostic_dialog -v   # 5 testes (ajustados)
python -m unittest api.tests.test_client_version_middleware -v   # 7 testes (novo)
```

Regressão consolidada Desktop (228 testes) e suíte completa da API via
Docker (743 testes) — resultado idêntico ao já registrado nas Fases 1-5:
apenas as mesmas falhas/erros pré-existentes e ambientais (arquivos fora do
mount do container de teste, `pytest`/`scripts` ausentes), **zero
regressões novas**.

## Matriz Desktop/API validada por teste

| Desktop | API | Min Desktop | Min API (Desktop) | Resultado |
|---|---|---|---|---|
| 3.2.0 | 3.2.0 | 0.0.1 | — | COMPATIBLE |
| 2.5.2 | 0.0.1 | 0.0.1 | — | CLIENT_UPDATE_REQUIRED |
| 3.2.0 | 3.0.0 | 3.1.0 (min desktop irrelevante aqui) | 3.1.0 | SERVER_UPDATE_REQUIRED |
| 3.2.0 | 3.1.0 | — | 3.1.0 | COMPATIBLE (limite exato) |

## Validação real

**VALIDAÇÃO FÍSICA PENDENTE.** Não há executável empacotado nem segundo
computador disponíveis neste ambiente para validar um EXE real contra o
servidor. Todos os cenários (compatível, Desktop antigo, API antiga,
recomendação, endpoint inválido) foram exercitados via `httpx.MockTransport`
nos testes automatizados acima — isso comprova a lógica, não substitui a
validação física exigida pela Seção 17 do prompt técnico.

## Pendências

- Validação com executável real / segundo computador (acima).
- Habilitar `CLIENT_VERSION_ENFORCEMENT_ENABLED=true` em produção é uma
  decisão administrativa futura, só depois de confirmar que a frota
  suportada já envia `X-Client-Version` (Seção 11) — não fizemos essa
  ativação nesta fase, permanece `false`.
- Qualquer decisão de release/pacote que dependa da Fase 7 (instalador).

## Confirmação de escopo

Não foi implementado nenhum mecanismo de download, instalação ou
atualização automática — `CompatibilityGateDialog` continua sem botão
funcional de "Atualizar agora" além do que já existia (Fase 13 interna,
delega ao `UpdateCoordinator` já existente, não construído por esta fase).
PostgreSQL continua invisível ao Desktop; nenhuma migration foi criada;
nenhuma regra de negócio foi alterada.
