# Fase 5 - HTTPS e Seguranca

## Objetivo

Deixar de depender de HTTP em texto claro como caminho oficial de produção,
introduzindo um reverse proxy com terminação TLS entre os desktops e a API,
sem expor FastAPI/PostgreSQL diretamente aos clientes e sem criar atalhos
inseguros de certificado, autenticação ou firewall.

## Diagnóstico inicial (auditoria)

| Componente | Situação encontrada |
|---|---|
| FastAPI/Uvicorn | Bind `0.0.0.0:8000`, publicado diretamente ao host (`docker-compose.prod.yml`, desde a Fase 1) — nenhum reverse proxy na frente. |
| Reverse proxy | **Nenhum encontrado** — sem Nginx, Caddy, IIS, Traefik ou Apache em qualquer lugar do repositório. |
| Endereço oficial | `http://<IP_DO_SERVIDOR>:8000` (Fase 1), ainda sem IP real definido — ver `FASE1_SERVIDOR_E_ENDERECO_API.md`. |
| Cliente HTTP do Desktop | `DesktopApiClient` usa `httpx.Client(...)` **sem** `verify=False` em nenhum lugar — validação de certificado já ativa por padrão. Confirmado por varredura de todo `app/` e `api/` (nova política de teste, ver abaixo). |
| CORS/TrustedHost | CORS já condicional (`if settings.cors_origins`), sem `*` por padrão (`CORS_ALLOWED_ORIGINS=` vazio no `.env.example`). Nenhum `TrustedHostMiddleware`/`ProxyHeadersMiddleware` configurado — comportamento seguro por omissão enquanto não há proxy. |
| JWT/tokens | `sanitize_secret()` já redige `Authorization`/`Bearer`/tokens de qualquer log (Fase 1). Nenhum token aparece em query string, clipboard ou diagnóstico (confirmado nas Fases 3/4). |
| Windows Firewall | Nenhuma regra aplicada a partir deste repositório (fora do alcance — servidor físico não acessível); Fase 1 já documentou a regra necessária para 8000. |
| Secrets | `SECRET_KEY`/`PROVISIONING_SECRET`/`NOMUS_ENCRYPTION_KEY` continuam exigidos explicitamente em produção (`${VAR:?...}`, sem default), `.env`/`.env.*` fora do Git (`.gitignore`). Nenhum segredo real versionado encontrado. |
| Testes existentes (Fases 1-4) | Todos usam `httpx.MockTransport`/HTTP simulado — nenhum depende de um esquema HTTP fixo além do que já é parametrizado pela Fase 2. |

**Conclusão da auditoria:** o Desktop já está tecnicamente pronto para HTTPS
(validação TLS nunca foi desativada, `normalize_api_base_url` da Fase 2 já
aceita `https://`). O que faltava por completo era a **infraestrutura de
borda** — reverse proxy + certificado — que esta fase prepara em código e
documentação, mas não pode aplicar sozinha num servidor físico que não
existe neste ambiente.

## Decisões confirmadas com o usuário

Como o prompt técnico proíbe explicitamente inventar tecnologia/domínio/
certificado, duas decisões foram confirmadas antes de gerar qualquer
arquivo:

- **Reverse proxy: Caddy** — binário simples para Windows Server, `Caddyfile`
  compacto, TLS declarativo (sem exigir ACME público).
- **Certificado: CA interna** — apropriado para uma rede sem domínio público
  (Seção 4 do prompt: "rede interna com controle dos PCs").

## Arquivos alterados/criados

- `Caddyfile` (novo) — configuração do reverse proxy.
- `docker-compose.prod.yml` — novo serviço `caddy` (443, TLS, upstream
  `api:8000`); serviço `api` **inalterado** (porta 8000 continua publicada
  em paralelo durante a migração).
- `app/services/diagnostic_service.py` — 5 novos códigos TLS
  (`TLS_CERT_UNTRUSTED`, `TLS_HOSTNAME_MISMATCH`, `TLS_CERT_EXPIRED`,
  `TLS_HANDSHAKE_FAILED`, `HTTPS_REQUIRED`), classificador
  `classify_tls_exception()`, detecção de redirect HTTP→HTTPS.
- `api/tests/test_release_compose_policy.py` — testes de política para o
  serviço Caddy e para ausência de `verify=False`/supressão de warnings TLS
  em todo o código de produção.
- `tests/test_diagnostic_service.py` — 12 testes novos (5 de classificação
  TLS pura + 6 de ponta a ponta + 1 de sanitização do relatório).

Nenhuma alteração foi feita no Desktop além do diagnóstico: a Fase 2 já
aceitava `https://` e o cliente HTTP central já validava TLS — não havia
`verify=False` nem bypass para refatorar (confirmado pela auditoria e
travado por teste, ver "Testes" abaixo).

## Reverse proxy — Caddy

`Caddyfile` (raiz do repositório):

```caddyfile
{$CADDY_HOSTNAME}:443 {
	tls /etc/caddy/tls/server.crt /etc/caddy/tls/server.key
	reverse_proxy api:8000 {
		header_up Host {host}
		header_up X-Real-IP {remote_host}
	}
	encode gzip
	log {
		output stdout
		format console
	}
}
```

`docker-compose.prod.yml`, serviço `caddy`: publica `443` (`CADDY_BIND_HOST`,
default `0.0.0.0`, mesmo padrão da Fase 1 para a API), monta o `Caddyfile` e
o par certificado/chave via `CADDY_TLS_CERT_PATH`/`CADDY_TLS_KEY_PATH`
(arquivos reais ficam **fora do repositório**), e usa `depends_on: api` para
subir depois da API. Porta 80 **não** é publicada por padrão (redirect é
opcional, Seção 11) — só habilitar junto com o bloco de redirect comentado
no `Caddyfile`.

Nenhuma variável nova tem valor default silencioso: `CADDY_HOSTNAME`,
`CADDY_TLS_CERT_PATH` e `CADDY_TLS_KEY_PATH` falham explicitamente
(`${VAR:?...}`) se não definidas, mesmo padrão já usado pelas demais
variáveis obrigatórias do compose de produção.

## URL oficial HTTPS

**Ainda não definida.** Depende do hostname que será gravado no certificado
(que por sua vez depende da CA interna ser criada). Mesma situação do IP da
Fase 1: documentado como placeholder, não inventado.

```text
https://<HOSTNAME_OFICIAL>
```

## Estratégia de certificado — CA interna

Não há PKI corporativa existente identificada neste repositório. Passos
administrativos (**fora deste repositório**, dependem do Windows Server
real) para uma CA interna simples:

1. **Gerar a CA raiz** (uma vez), por exemplo com OpenSSL (disponível via
   Git for Windows/WSL) ou `New-SelfSignedCertificate` do PowerShell:
   ```powershell
   # CA raiz (validade longa, ex.: 10 anos) -- guardar a chave privada
   # da CA em local restrito, nunca no repositorio.
   $ca = New-SelfSignedCertificate -Subject "CN=Industel Internal CA" `
     -KeyUsage CertSign,CRLSign,DigitalSignature -KeyLength 4096 `
     -NotAfter (Get-Date).AddYears(10) -CertStoreLocation Cert:\LocalMachine\My
   ```
2. **Emitir o certificado do servidor**, assinado pela CA acima, com o
   `CN`/`SAN` igual ao `<HOSTNAME_OFICIAL>` real (nunca um nome temporário —
   Seção 4: "hostname deve ser decidido antes do certificado").
3. **Exportar** o certificado do servidor (`.crt`/`.pem`) e a chave privada
   (`.key`) para os caminhos que `CADDY_TLS_CERT_PATH`/`CADDY_TLS_KEY_PATH`
   apontarem — com permissão de arquivo restrita ao usuário/serviço Docker.
4. **Distribuir a CA raiz (só o certificado público, nunca a chave
   privada)** para o repositório de certificados confiáveis dos
   computadores da empresa — via GPO (`Computer Configuration → Policies →
   Windows Settings → Security Settings → Public Key Policies → Trusted
   Root Certification Authorities`) ou, manualmente, `certutil -addstore
   Root ca-industel.crt` em cada máquina autorizada.
5. **Documentar** data de expiração, responsável e processo de
   substituição — recomendado: expiração da CA raiz em 10 anos, do
   certificado de servidor em 1–2 anos, com lembrete de renovação
   registrado fora do código (planilha/ticket interno do time de TI).

Renovação (Seção 5): substituir apenas o certificado do servidor mantendo o
mesmo hostname e a mesma CA raiz já distribuída — os desktops continuam
confiando sem qualquer alteração de código; só é preciso recarregar o Caddy
(`docker compose restart caddy` ou `caddy reload`).

**Nenhuma chave privada foi gerada ou versionada neste repositório** — uma
política de teste (`test_no_private_key_file_is_versioned_in_the_repo`)
garante isso continuamente.

## Desktop — validação TLS

Nenhuma alteração de código foi necessária: `DesktopApiClient` usa
`httpx.Client(...)` sem qualquer parâmetro de verificação sobrescrito, ou
seja, já usa a cadeia de confiança padrão do sistema operacional (que passa
a incluir a CA interna assim que o passo 4 acima for aplicado nos PCs).
`normalize_api_base_url` (Fase 2) já aceita `https://` sem exigir mudança.
Confirmado por duas novas políticas de teste que variam o `app/`+`api/`
inteiros procurando `verify=False` e supressão de warnings TLS — nenhuma
ocorrência encontrada.

Migração da URL oficial (`http://<IP>:8000` → `https://<HOSTNAME_OFICIAL>`)
continua sendo uma gravação normal via `DesktopApiConfigStore.save_settings()`
(Fase 2/3) — nenhum código novo necessário, só o valor real quando definido.

## Diagnóstico — novos códigos TLS

Adicionados a `DiagnosticErrorCode` e reaproveitando a mesma cadeia da Fase
4 (nenhuma tela nova, nenhum serviço duplicado):

| Código | Causa | Onde é detectado |
|---|---|---|
| `TLS_CERT_UNTRUSTED` | Cadeia não confiável (self-signed, CA não instalada) | Etapa `API_REACHABLE`, via `classify_tls_exception` |
| `TLS_HOSTNAME_MISMATCH` | Hostname do certificado diverge da URL configurada | Etapa `API_REACHABLE` |
| `TLS_CERT_EXPIRED` | Certificado expirado | Etapa `API_REACHABLE` |
| `TLS_HANDSHAKE_FAILED` | Falha genérica de negociação TLS | Etapa `API_REACHABLE` |
| `HTTPS_REQUIRED` | Endereço configurado ainda em `http://`, servidor redireciona para `https://` | Etapa `HEALTH_HTTP` (detecta 301/302/307/308) |

`classify_tls_exception()` inspeciona a mesma cadeia `__cause__`/`__context__`
já usada por `classify_connect_exception` (Fase 4), procurando
`ssl.SSLCertVerificationError`/`ssl.SSLError` antes de cair para a
classificação de rede genérica — um handshake TLS que falhou **prova** que o
servidor foi alcançado na camada TCP, então nunca é confundido com
`CONNECTION_REFUSED`/`HOST_RESOLUTION_FAILED` (Seção 7: "não mascarar TLS
como rede offline"). Exemplo real de saída (teste automatizado):

```text
CONFIG_PRESENT: OK
URL_VALID: OK
HOST_RESOLUTION: OK
API_REACHABLE: ERROR - O certificado do servidor nao e confiavel.
HEALTH_HTTP: NOT_TESTED
API_HEALTH: NOT_TESTED
DATABASE_HEALTH: NOT_TESTED
```

O relatório copiável (`build_report_text`) continua sanitizado — testado
explicitamente para nunca incluir material de certificado/chave, tokens ou
`Authorization`.

## Proxy headers, CORS e OpenAPI

- **Proxy headers**: decisão deliberada de **não** habilitar confiança em
  `X-Forwarded-*`/`ProxyHeadersMiddleware` nesta fase. A API não gera URLs
  absolutas que dependam do esquema externo nem usa o IP de origem para
  nenhuma regra de segurança — habilitar confiança sem necessidade real
  seria exatamente o "não adicionar por moda" que a Seção 8 veta. Se uma
  necessidade real aparecer (ex.: rate limiting por IP de origem), tratar
  como mudança futura específica, com o endereço do proxy então conhecido.
- **CORS**: já condicional e vazio por padrão — nada a mudar (Desktop
  nativo não depende de CORS).
- **Swagger/ReDoc**: permanecem habilitados (`/docs`, `/redoc`) — uso
  operacional interno já existente, sem necessidade identificada de
  desabilitar numa rede restrita à LAN.

## Firewall (Windows Server) — documentado, não aplicado

Nenhuma alteração de firewall foi executada (servidor físico fora do
alcance deste ambiente). Comandos a aplicar quando o servidor real estiver
disponível, seguindo a ordem seguraa da Seção 9 do prompt técnico:

```powershell
# Etapa A/B - liberar 443 para a LAN, SEM tocar na regra existente da porta 8000 (Fase 1)
New-NetFirewallRule -DisplayName "Controle Producao HTTPS (LAN)" `
  -Direction Inbound -Protocol TCP -LocalPort 443 `
  -RemoteAddress <SUB-REDE_LAN, ex. 192.168.1.0/24> -Action Allow

# Etapa D - SOMENTE depois de validar HTTPS de outro computador da LAN:
# restringir a porta 8000 para nao aceitar mais conexoes da LAN em geral.
# Nao remover a regra da Fase 1 sem ter um plano de rollback testado.
```

A porta 5432 (PostgreSQL) já não é publicada pelo compose desde a Fase 1 —
nenhuma ação adicional necessária.

## Plano de migração e rollback

Reaproveitado literalmente das Etapas A–D do prompt técnico:

1. **A — preparar**: subir `caddy` (este compose já permite isso) mantendo
   `api` publicada em 8000 como está hoje.
2. **B — validar**: de outro computador da LAN, `GET
   https://<HOSTNAME_OFICIAL>/api/v1/health/ready` e login normal.
3. **C — migrar cliente**: gravar `https://<HOSTNAME_OFICIAL>` como
   `API_BASE_URL` oficial (Fase 2/3) e confirmar diagnóstico TLS `OK`.
4. **D — restringir**: só então aplicar a regra de firewall que bloqueia
   8000 para a LAN geral.

**Rollback**: enquanto a Etapa D não for aplicada, o endereço HTTP antigo
continua funcional — reverter é apenas gravar de volta o `API_BASE_URL`
HTTP anterior via Fase 2/3, sem qualquer ação de infraestrutura. Depois da
Etapa D, rollback exige reabrir temporariamente a porta 8000 antes de
reverter a configuração do Desktop.

## Segurança — resumo

- Nenhuma chave privada gerada, versionada ou embutida no instalador.
- Nenhum segredo novo hardcoded encontrado durante a auditoria desta fase
  (os já conhecidos de fases anteriores — defaults de desenvolvimento em
  `.env.example`/`docker-compose.dev.yml` — continuam claramente marcados
  como dev-only e exigidos explicitamente em produção).
- `Authorization`/tokens continuam fora de logs, clipboard e relatório de
  diagnóstico (herdado das Fases 1–4, agora também coberto pelos novos
  testes de TLS).

## Testes

```bash
python -m unittest tests.test_diagnostic_service -v          # 26 testes (14 Fase 4 + 12 Fase 5)
python -m unittest api.tests.test_release_compose_policy -v   # 23 testes (16 existentes + 7 novos)
```

Regressão consolidada (170 testes, todo o material de Fases 2–5):

```bash
QT_QPA_PLATFORM=offscreen python -m unittest \
  tests.test_diagnostic_service tests.test_api_diagnostic_dialog \
  tests.test_bootstrap_service tests.test_first_access_dialog tests.test_startup_bootstrap \
  tests.test_desktop_api_config tests.test_desktop_api_client tests.test_api_proposal_storage \
  tests.test_update_audit_client tests.test_update_distribution_client tests.test_startup_compatibility_check \
  tests.test_system_api_client_compatibility tests.test_update_coordinator tests.test_api_session_concurrency \
  tests.test_settings_dialog tests.test_postgresql_only_config -v
# Ran 170 tests -- OK
```

Cobertura da lista mínima do prompt técnico (Seção 13): `API_BASE_URL`
aceita HTTPS (já era assim desde a Fase 2, testado); sem fallback HTTPS→HTTP
(nenhum código faz isso — o diagnóstico apenas relata `HTTPS_REQUIRED`, não
troca o esquema sozinho); nenhum caminho de produção usa `verify=False`
(travado por política de teste); erro de certificado mapeado para código
TLS (5 testes de classificação + 4 de ponta a ponta); `Authorization` nunca
aparece em relatório (testado); cliente mantém timeout/contratos das Fases
2–4 (nenhuma mudança nesses caminhos, regressão confirma).

## Validação manual na LAN

**Pendente — não realizada.** Não há servidor físico, certificado real nem
segundo computador disponíveis neste ambiente para validar: HTTPS respondendo
de outro PC, certificado não confiável simulado em ambiente real, hostname
divergente, bloqueio real da porta 8000, ou recuperação. Todos os cenários
equivalentes foram exercitados via `httpx.MockTransport` nos testes
automatizados (ver acima), mas isso **não substitui** a validação física
exigida pela Seção 14 — declarado aqui explicitamente, não considerado
"testado" silenciosamente.

## Pendências (dependem de infraestrutura/decisão administrativa real)

- Definir o `<HOSTNAME_OFICIAL>` real (depende do IP/DNS da Fase 1 também
  ainda pendente).
- Gerar a CA interna e o certificado do servidor (passos documentados
  acima, não executáveis a partir deste repositório).
- Distribuir a CA raiz como confiável nos computadores da empresa (GPO ou
  manual).
- Aplicar a regra de firewall da porta 443 no Windows Server real.
- Executar as Etapas A–D de migração no servidor físico e a validação
  manual da Seção 14.
- Só depois disso, aplicar a Etapa D (bloquear 8000 para a LAN).

## Confirmação de escopo

Não foram implementados: controle de compatibilidade de versões (Fase 6),
instalador/atualizador (Fase 7), acesso externo/VPN/tunnel/port forwarding,
troca do mecanismo de autenticação, nem qualquer alteração de regra de
negócio, schema de banco ou migration.
