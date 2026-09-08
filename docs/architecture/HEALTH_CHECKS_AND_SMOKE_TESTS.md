# Health Checks e Smoke Tests Pós-Deployment (Fase 06)

Camada que diferencia com precisão três perguntas diferentes sobre uma instância
do servidor: o processo está vivo? pode receber tráfego? as funcionalidades
essenciais realmente respondem? Nenhuma automação futura de deployment deve
considerar uma atualização bem-sucedida só porque o processo FastAPI iniciou ou
a porta HTTP abriu.

## Onde vive o mecanismo

Separação entre coleta/avaliação (independente de HTTP) e exposição HTTP
(Seção 6 do prompt):

| Camada | Arquivo |
| --- | --- |
| Modelos tipados | `api/app/health/models.py` |
| Check de banco + schema | `api/app/health/checks/database.py` |
| Check de versão | `api/app/health/checks/version.py` |
| Avaliação (liveness/readiness) | `api/app/health/service.py` (`HealthService`) |
| Smoke test runner + CLI | `api/app/health/smoke.py` (`SmokeTestRunner`) |
| Exposição HTTP | `api/app/modules/health/router.py` + `schemas.py` |

## Inventário de health checks existentes (antes desta fase)

Já existiam `GET /system/health` (liveness simples, sem tocar banco) e
`GET /system/ready` (verifica `database_check()` — conectividade + revisão —
e `settings.auth_ready`), ambos em `api/app/modules/system/`. **Não foram
duplicados nem removidos** — continuam respondendo exatamente como antes, para
não quebrar consumidores existentes (Desktop, `docs/architecture/*`, testes já
publicados). O `docker-compose.dev.yml` já tinha um `healthcheck:` para o
serviço `api` apontando para `/system/health` — esse sim foi **evoluído**
(Seção 5: "se já houver health check, evolua-o de forma compatível") para
apontar para o novo `/health/ready`, já que um healthcheck de container deveria
refletir prontidão real para tráfego, não apenas processo vivo (mesmo padrão já
usado pelo `healthcheck:` do serviço `postgres`, que testa `pg_isready`, não
apenas "o processo existe"). Não havia `startup`/`shutdown` hooks de FastAPI
adicionais além do `lifespan` já existente (`sync_official_permissions`/
`ensure_default_admin`), e nenhum script de smoke test/diagnóstico
pré-existente.

A nova camada `/health/*` **reutiliza a mesma infraestrutura** que `/system/*`
já usava (`api.app.database.health.database_check()`, `EXPECTED_DATABASE_REVISION`
da Fase 01, `api.app.core.versioning` da Fase 01, `api.app.core.migration_state`
da Fase 04) — nenhuma consulta SQL nova foi escrita, nenhum timeout novo foi
inventado. `/health/*` e `/system/*` não são endpoints "concorrentes" com
semânticas diferentes: são duas superfícies HTTP (uma simples/legada, uma
tipada/rica com `checks[]` por dependência) sobre exatamente a mesma lógica de
avaliação.

## Liveness — `GET /api/v1/health/live`

```json
{"status": "alive", "server_version": "0.8.0"}
```

Nunca consulta o banco (garantido estruturalmente: `HealthService.liveness()`
só chama `run_version_check()`, que não faz I/O — testado explicitamente
patchando `database_check` para levantar `AssertionError` se for chamado).
Sempre `200` enquanto o processo Python conseguir responder.

## Readiness — `GET /api/v1/health/ready`

Retorna o `HealthReport` completo (Seção 10), com `200` quando
`overall_status` é `HEALTHY` ou `DEGRADED` ("estado aceito como pronto" —
Seção 15), `503` quando `UNHEALTHY`. **Nunca `200` com corpo de erro** — o
código HTTP sozinho já permite que Docker/pipeline decidam sem parsing frágil.

```json
{
  "overall_status": "HEALTHY",
  "checked_at_utc": "2026-08-10T20:15:30.123456+00:00",
  "server_version": "0.8.0",
  "api_contract_version": "v1",
  "database_revision": "20260810_0015",
  "checks": [
    {"name": "version", "status": "PASS", "critical": false, "duration_ms": 0, "message": "server_version=0.8.0 api_contract_version=v1", "error_code": null},
    {"name": "database", "status": "PASS", "critical": true, "duration_ms": 4, "message": "Conexao com PostgreSQL OK (SELECT 1).", "error_code": null},
    {"name": "schema_revision", "status": "PASS", "critical": true, "duration_ms": 4, "message": "Revisao do banco '20260810_0015' compativel com a esperada.", "error_code": null}
  ]
}
```

### Checks críticos vs. não críticos (Seção 14)

| Check | Crítico? | O quê |
| --- | --- | --- |
| `database` | **Sim** | `SELECT 1` via a engine oficial (`api.app.database.session`), somente leitura |
| `schema_revision` | **Sim** | Revisão real aplicada (`alembic_version`, Fase 04) comparada com `EXPECTED_DATABASE_REVISION` |
| `version` | Não | `API_VERSION`/`API_CONTRACT_VERSION` (Fase 01) carregam e validam; falha aqui vira `DEGRADED`, nunca `UNHEALTHY` sozinha |

`database` e `schema_revision` são derivados de **uma única chamada** a
`database_check()` (não abre uma segunda conexão só para separar os dois
conceitos). O timeout já é o existente (`DATABASE_CONNECT_TIMEOUT`, Fase
01/04) — nenhum timeout novo foi introduzido; o "timeout total do readiness"
(Seção 16) é, na prática, esse mesmo valor mais o overhead desprezível do
check de versão (sem I/O).

`overall_status`:
- `HEALTHY`: todo check crítico `PASS`.
- `DEGRADED`: nenhum crítico falhou, mas há `WARN`/`FAIL` não crítico.
- `UNHEALTHY`: qualquer check crítico `FAIL`.

### Divergência de schema

Reutiliza `api.app.core.migration_state.build_migration_state()` (Fase 04,
preparado exatamente para este momento) para diferenciar, na mensagem do
check: revisão divergente mas conhecida no histórico (release atrasada/
adiantada) vs. revisão totalmente fora do histórico conhecido (`
migration_history_consistent=False`, sinal mais grave). Em nenhum dos dois
casos o health check tenta corrigir o schema — apenas diagnostica
(`error_code=SCHEMA_REVISION_MISMATCH`/`SCHEMA_UNVERSIONED`); migration
pertence ao fluxo de deployment de uma fase futura.

## Smoke Test Runner

`SmokeTestRunner` (Seção 18) roda uma bateria curta, **somente leitura e
idempotente** (Seção 20 — nenhum passo escreve dado operacional; a interface
`SmokeHttpClient` só expõe `.get()`, não há como um passo fazer POST/PUT/DELETE
por engano):

1. `GET /health/live` — também confere `server_version` contra
   `--expected-server-version`, se informado.
2. `GET /health/ready`
3. `GET /system/compatibility` — confere `server_version`/`api_contract_version`/
   `database_revision` coerentes.
4. `GET /system/version` — consulta essencial somente leitura que também chega
   ao banco (rota pública distinta, Fase 01/02), confirmando que o contrato
   legado continua respondendo após um deployment.

A execução para cedo (sem tentar os passos seguintes) se `health_live` ou
`health_ready` falharem — não faz sentido testar mais nada se o processo nem
está pronto.

**Passo de autenticação técnica (item 4 da Seção 18) foi deliberadamente
omitido**: o prompt o torna condicional ("se existir fixture segura"), e este
projeto não tem nenhuma credencial técnica dedicada e segura para smoke test —
login exige usuário real. Criar uma agora seria inventar uma superfície de
autenticação nova só para este propósito, fora do escopo desta fase. Se uma
fase futura introduzir uma credencial técnica formal, este passo pode ser
adicionado sem alterar a arquitetura do runner.

### CLI

```bash
python -m api.app.health.smoke --base-url http://servidor:8000
python -m api.app.health.smoke --base-url http://servidor:8000 --expected-server-version 0.9.0 --json
```

`exit 0` = PASS, `exit != 0` (1) = FAIL — verificado manualmente contra o
container de desenvolvimento real (`http://127.0.0.1:8000`, todos os 4 passos
PASS) e contra um endpoint inexistente (timeout, `FAIL`, `exit=1`). Sem
credenciais hardcoded; `--base-url`/`--timeout`/`--expected-server-version`
configuráveis; saída humana por padrão, `--json` para consumo por
script/pipeline; não usa PySide nem qualquer dependência de UI.

## Integração Docker

`docker-compose.dev.yml`, serviço `api`, `healthcheck:` evoluído de
`/system/health` para `/health/ready`:

```yaml
healthcheck:
  test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=8).read()\""]
  interval: 10s
  timeout: 12s
  retries: 5
  start_period: 20s
```

Usa só a biblioteca padrão (`urllib.request`, já presente em qualquer imagem
Python) — não foi adicionado `curl`/`wget` por conveniência. `timeout: 12s` >
`DATABASE_CONNECT_TIMEOUT` (10s padrão) para não derrubar o check por um
timeout do Docker mais curto que o timeout interno do próprio readiness.
`start_period: 20s` dá tempo do `lifespan` (bootstrap de permissões/admin) e da
primeira conexão ao Postgres completarem sem contar como falha durante o boot
normal — readiness continua podendo responder `503` legitimamente nesse
intervalo (não usamos `sleep` fixo como prova de prontidão; o próprio
`/health/ready` decide, honestamente, a cada tentativa).

**Nota operacional**: esta alteração está no arquivo `docker-compose.dev.yml`;
o container de desenvolvimento já em execução não recarrega a definição de
`healthcheck:` sozinho (diferente do código Python, que já recarrega via
`--reload` porque `./api` é montado como volume) — só passa a valer após um
`docker compose up -d api` (recriação do serviço), que não foi executado
automaticamente nesta fase.

## Timeouts / retries / estados

Nenhum timeout novo foi inventado — tudo reaproveita `DATABASE_CONNECT_TIMEOUT`
(Fase 01/04) para o readiness, e o `--timeout` do `SmokeTestRunner`/CLI para as
chamadas HTTP externas. Sem retry automático em nenhum nível (Seção 16: "nenhum
retry infinito") — o readiness é reavaliado do zero a cada chamada (Seção 17:
"nunca mascarar falha por cache longo" — não há cache nenhum, os checks atuais
são baratos o bastante para rodar direto). O smoke runner para cedo em vez de
insistir quando um passo crítico falha.

## Segurança e logs

Nenhuma mensagem de check/step inclui senha, `PGPASSWORD`, DSN completo ou
stack trace — `_evaluate_connectivity` usa mensagens fixas e seguras
(`"PostgreSQL indisponivel (...)"`) em vez de propagar a exceção bruta,
testado explicitamente (`test_unavailable_database_fails_without_leaking_internal_detail`).
`api/app/modules/health/router.py` loga apenas em **transição** de estado
(`HEALTH_STATE_TRANSITION`, com o(s) nome(s) do(s) check(s) crítico(s) que
falharam, `server_version`, `database_revision`) — nunca a cada polling normal,
evitando spam de log.

## Testes criados

39 testes novos (36 unitários sempre-ativos + 3 de integração real com Postgres):

- `test_health_models.py` (7): serialização de `HealthReport`/`SmokeTestReport`, `is_ready`, `exit_code`.
- `test_health_checks.py` (9): conectado+compatível, não configurado, indisponível sem vazar detalhe, revisão divergente, não versionado, criticidade, check de versão.
- `test_health_service.py` (10): matriz completa de `_overall_status` (PASS/WARN/FAIL × crítico/não-crítico), liveness nunca toca o banco, readiness saudável/degradada/não saudável, revisão divergente, sem vazamento de secrets.
- `test_smoke_runner.py` (9): PASS completo, para cedo em falha de `ready`, falha de rede, versão inesperada, versão esperada batendo, formato inválido, garantia estrutural de somente-leitura, uso do clock injetado.
- `test_health_router.py` (6): liveness não toca banco via HTTP, 200 em `HEALTHY`/`DEGRADED`, 503 em `UNHEALTHY` (nunca 200 com erro), 503 sem banco configurado, forma da resposta.
- `test_health_smoke_integration.py` (3, Postgres real): os três cenários da Seção 27.

## Resultado dos testes de integração

Os três cenários da Seção 27 foram executados **de verdade** contra o
PostgreSQL de teste descartável (mesmo já usado nas Fases 04/05):

- **Cenário A** (API + DB corretos): `live` 200, `ready` 200 `HEALTHY`, smoke `PASS` (todos os 4 passos).
- **Cenário B** (DB indisponível — `DATABASE_URL` vazia): `live` 200, `ready` 503 `UNHEALTHY`, smoke `FAIL` (para em `health_ready`).
- **Cenário C** (schema divergente — banco rebaixado para `20260803_0013` via Alembic real): `live` 200, `ready` 503 com `schema_revision` marcado `FAIL`/`SCHEMA_REVISION_MISMATCH`, smoke `FAIL`.

Adicionalmente, `SmokeTestRunner`/CLI foi executado contra o container de
desenvolvimento real já em execução (`controle_producao_api_dev`, que recarregou
o novo código via `--reload`): todos os 4 passos `PASS`, `exit=0`; e contra um
endereço inexistente: `FAIL`/`exit=1`.
