# Imagens Docker Versionadas do Servidor (Fase 07)

Transforma o backend em uma unidade de deploy imutável, identificável e
reproduzível: cada imagem carrega uma `server_version` explícita (Fase 01),
metadados de build auditáveis, e nunca é sobrescrita. Esta fase **não**
implementa deploy, rollback ou push automático — apenas o empacotamento e a
validação local de uma release.

## Inventário encontrado (antes desta fase)

- `api/Dockerfile`: single-stage, `FROM python:3.12-slim` (sem pin de patch
  nem digest), instalava `requirements-dev.txt` direto, `COPY api /app/api`
  (copiava `api/tests/` e tudo mais para dentro da imagem), já tinha usuário
  não-root `apiuser` e `CMD` simples com uvicorn — sem `HEALTHCHECK` embutido
  na imagem (o healthcheck vivia só no `docker-compose.dev.yml`, adicionado na
  Fase 06).
- Só existia `docker-compose.dev.yml` — nenhum compose de produção.
  `docker-compose.dev.yml` monta `./api:/app/api` (bind mount) e roda
  `uvicorn --reload`, correto para dev, mas o serviço `api` não declarava
  `image:` — o Compose gera uma tag local implícita (`novapasta-api`, sem
  versão, equivalente a um `:latest` implícito) — confirmado via `docker
  images` antes desta fase.
- Nenhum registry configurado (`ghcr.io`, Docker Hub etc.) em nenhum arquivo.
- Nenhum arquivo de lock de dependências (`requirements.txt`/
  `requirements-dev.txt` usam faixas `>=X,<Y`, não pinagem exata) — mantido
  como está nesta fase (ver "Riscos" no relatório final); não foi trocado o
  gerenciador de dependências.
- Nenhuma migration roda automaticamente no startup — confirmado nas Fases 04
  e 06 e reconfirmado aqui (`api/app/main.py`'s `lifespan` só chama
  `sync_official_permissions()`/`ensure_default_admin()`, DML idempotente, sem
  DDL). Preservado sem alteração.
- `.dockerignore` (raiz) já existia e cobria `.git/`, `.env*`, `backups/` etc.,
  mas não excluía `api/tests/`.

## Convenção de imagem e tag

```
<IMAGE_REGISTRY>/controle-producao-api:<SERVER_VERSION>
```

`SERVER_VERSION` é sempre `api.app.core.config.API_VERSION` (Fase 01) — nunca
digitado manualmente em mais de um lugar. `IMAGE_REGISTRY` é configurável
(nenhum registry real estava configurado no projeto; o valor é definido pelo
operador no momento do build/deploy, ex.: `ghcr.io/sua-organizacao`).
`:latest` nunca é usado em nenhum caminho de produção (`docker-compose.prod.yml`
não o referencia em nenhuma linha, verificado por teste automatizado).

## Arquitetura implementada

```
api/app/core/config.py (API_VERSION)          <- fonte unica da versao
        |
        v
scripts/build_release_image.py
  +--> valida tag == API_VERSION (ou deriva dela)
  +--> commit_sha = git rev-parse --short HEAD
  +--> build_time = agora, UTC
  |
  v
docker build --build-arg SERVER_VERSION/COMMIT_SHA/BUILD_TIME
  |
  v
imagem imutavel <registry>/controle-producao-api:<version>
  +--> labels org.opencontainers.image.*
  +--> valida label version == API_VERSION apos o build
  |
  v
scripts/validate_release_image.py
  +--> sobe container isolado (sem bind mount) na rede do Postgres de teste
  +--> aguarda HEALTHCHECK da propria imagem (Fase 06)
  +--> roda SmokeTestRunner (Fase 06) contra o container
```

## Dockerfile de produção

`api/Dockerfile` — multi-stage:

1. **`builder`**: `python:3.12-slim` pinada por tag **e digest**
   (`@sha256:229a2c5b...`, obtido de `docker pull python:3.12-slim` nesta
   fase), instala `requirements.txt`+`requirements-dev.txt` via
   `pip install --prefix=/install` (dependências determinísticas — mesmo
   mecanismo já adotado pelo projeto, sem trocar gerenciador).
2. **`runtime`**: mesma base pinada, recebe só `/install` copiado (nenhuma
   ferramenta de build, nenhum `requirements*.txt` chega ao runtime), copia
   `api/__init__.py` + `api/app` + `api/alembic` + `api/alembic.ini` com
   `--chown=apiuser:apiuser` (nunca `api/tests/`, excluído via
   `.dockerignore`), roda como usuário não-root `apiuser`, expõe só a porta
   8000, com `HEALTHCHECK` embutido apontando para `/api/v1/health/ready`
   (Fase 06 — biblioteca padrão `urllib`, sem `curl`/`wget` novo), e `CMD`
   simples e determinístico (`uvicorn`, sem migration automática).

`ARG SERVER_VERSION` não tem valor default — uma imagem construída sem passar
esse build-arg fica com a label vazia, o que `scripts/build_release_image.py`
trata como falha explícita logo após o build (nunca um `docker build` "cru"
silenciosamente sem identidade é o caminho suportado).

### Por que a base foi pinada por digest

`FROM python:3.12-slim` sozinho é uma tag móvel — o mesmo nome pode passar a
apontar para uma imagem diferente amanhã (rebuild upstream). Pinar também o
digest (`@sha256:...`) garante que o mesmo `docker build` produz o mesmo
resultado até que alguém atualize o digest deliberadamente. Para atualizar:
`docker pull python:3.12-slim`, copiar o novo `sha256` para o Dockerfile,
validar compatibilidade e rodar a suíte completa (não se troca a *minor*
version do Python nesta fase, só o patch/digest dentro da mesma 3.12).

## `.dockerignore`

Adicionado: `api/tests/`, `api/.pytest_cache/`, `api/__pycache__/`,
`api/pyproject.toml` — reduzem o contexto de build e garantem que testes não
vão parar dentro da imagem de produção (o Dockerfile também já faz `COPY`
seletivo, então isso é defesa em profundidade, não a única barreira).

## `docker-compose.prod.yml` (novo)

Referencia a imagem por tag explícita, nunca builda localmente (`build:`
ausente) e nunca monta o código do host (`volumes:` ausente no serviço `api`)
— o processo em produção roda exatamente o que está dentro da imagem
`${SERVER_VERSION}$`. Variáveis obrigatórias (`IMAGE_REGISTRY`,
`SERVER_VERSION`, `SECRET_KEY`, `PROVISIONING_SECRET`,
`NOMUS_ENCRYPTION_KEY`, credenciais do Postgres) usam a sintaxe
`${VAR:?mensagem}` do Compose — **falham explicitamente** se não definidas,
em vez de subir com um valor vazio/errado (verificado manualmente: `docker
compose -f docker-compose.prod.yml config` sem as variáveis produz
`error while interpolating ... required variable ... is missing a value`).
Não redefine `healthcheck:`/`command:` — reaproveita o que já está embutido na
própria imagem, para a definição de saúde viajar junto com o artefato
versionado.

`docker-compose.dev.yml` **não foi alterado** — continua com bind mount e
`--reload` para desenvolvimento, exatamente como o prompt permite
("no ambiente de desenvolvimento, bind mounts podem continuar existindo").

## Metadados e identidade da release

Labels OCI na imagem:

```
org.opencontainers.image.title=controle-producao-api
org.opencontainers.image.version=0.8.0
org.opencontainers.image.revision=79a888e
org.opencontainers.image.created=2026-08-11T11:40:21Z
org.opencontainers.image.description=API do Sistema de Controle de Producao Industel.
```

Em runtime, `COMMIT_SHA`/`BUILD_TIME` viram `ENV BUILD_COMMIT_SHA`/
`BUILD_TIME_UTC` dentro do container, lidos por
`api.app.core.config.Settings` (novos campos `build_commit_sha`/
`build_time_utc`, default `"unknown"`/vazio quando ausentes — build local/dev
sem esses build-args continua funcionando normalmente, só sem essa
informação extra). Nenhuma segunda fonte de verdade foi criada:
`server_version`/`api_contract_version` continuam vindo exclusivamente de
`api.app.core.versioning` (Fase 01).

Exposto em dois lugares coerentes entre si:

1. **Log de startup** (`api/app/main.py`):
   `api_started service=... version=0.8.0 stage=... contract=v1 schema=... env=... commit=79a888e build_time=2026-08-11T11:40:21Z`
2. **`GET /api/v1/health/ready`** (Fase 06, campos novos `commit_sha`/
   `build_time_utc` adicionados a `HealthReport`/`HealthReportResponse` —
   aditivo, não quebra nenhum consumidor existente do contrato).

Confirmado com uma release real construída e rodando (ver "Resultado do
build" abaixo): os dois lugares reportaram exatamente `79a888e` /
`2026-08-11T11:40:21Z`.

## Segurança e secrets

- `DATABASE_URL`, `SECRET_KEY`, `PROVISIONING_SECRET`, `NOMUS_ENCRYPTION_KEY`
  etc. nunca aparecem no Dockerfile, em nenhum `ARG` persistente, em label ou
  em arquivo copiado — só chegam via variável de ambiente em runtime
  (`docker-compose.prod.yml`/`docker run -e`).
- Verificado automaticamente (teste real, `docker run --rm <imagem> find
  /app -iname '*.env' -o -iname '*secret*'`): nenhum arquivo `.env`/`*secret*`
  existe dentro da imagem construída.
- Usuário não-root (`apiuser`) confirmado em runtime (`docker run --rm
  <imagem> whoami` → `apiuser`).
- Só a porta 8000 é exposta. Sem SSH, sem ferramentas remotas.
- `api/tests/` (fixtures, dados de teste) confirmado ausente da imagem.

## Testes criados

30 testes novos:

- `test_release_image_build.py` (8, sempre ativos, sem Docker): resolução de
  tag (deriva de `API_VERSION`, aceita tag coincidente, rejeita divergente
  com mensagem explícita), `commit_sha` via git (e `"unknown"` fora de um
  repo git), formatação UTC do `build_time`.
- `test_release_compose_policy.py` (14, sempre ativos, análise estática):
  `docker-compose.prod.yml` nunca referencia `:latest`, tag parametrizada por
  `SERVER_VERSION`, sem bind mount de código, sem `build:`, variáveis
  obrigatórias sem default silencioso; `api/Dockerfile` pinado por
  tag+digest, multi-stage, usuário não-root, `ARG SERVER_VERSION` sem
  default, labels OCI presentes, healthcheck reaproveita `/health/ready` sem
  `curl`/`wget`, `CMD` nunca roda `alembic upgrade`.
- `test_docker_release_integration.py` (8, **Docker real**): build real da
  imagem, labels batem com `API_VERSION`/commit real,
  `verify_image_identity` aceita a versão certa e rejeita uma errada, nenhum
  arquivo `.env`/secret dentro da imagem, `api/tests/` ausente, usuário
  `apiuser` confirmado, processo sobe mesmo sem `DATABASE_URL`/`SECRET_KEY`
  configuradas (sem crash loop) — mais um teste de runtime completo
  (**Docker real + PostgreSQL de teste real**): container isolado na mesma
  rede do Postgres de desenvolvimento, aguarda `healthy` de verdade, roda
  `SmokeTestRunner` (Fase 06) contra ele, confirma `server_version` correto.

## Resultado do build da imagem

Build real executado nesta sessão (Docker Desktop, Windows):

```
$ python scripts/build_release_image.py --registry ghcr.io/example-org
Construindo ghcr.io/example-org/controle-producao-api:0.8.0 (commit=79a888e, build_time=2026-08-11T11:40:21Z)...
OK: ghcr.io/example-org/controle-producao-api:0.8.0 construida e identidade validada (version=0.8.0, commit=79a888e).
```

Tamanho final da imagem: ~121MB (`docker image inspect --format='{{.Size}}'`).
`python scripts/build_release_image.py --registry ghcr.io/example-org --tag
9.9.9` (tag propositalmente errada) falhou como esperado, sem construir nada:
`ERRO: Tag solicitada '9.9.9' diverge de server_version '0.8.0' ...`.

## Resultado dos health/smoke tests contra a imagem real

```
$ python scripts/validate_release_image.py \
    --image ghcr.io/example-org/controle-producao-api:0.8.0 \
    --network novapasta_default \
    --database-url "postgresql+asyncpg://controle_dev:controle_dev@postgres:5432/controle_producao_test" \
    --expected-server-version 0.8.0

Healthcheck OK. Rodando smoke tests...
Smoke test: PASS (server_version=0.8.0)
  - health_live: PASS (234ms) http=200 OK
  - health_ready: PASS (76ms) http=200 OK
  - system_compatibility: PASS (60ms) http=200 OK
  - system_version_read_only_query: PASS (60ms) http=200 OK
```

Container removido ao final (`finally:` no script); confirmado depois: nenhum
container/imagem órfã, `controle_producao_test`/`controle_producao_dev`
inalterados.

## Como validar uma release manualmente

```bash
# 1. build + validacao de identidade
python scripts/build_release_image.py --registry ghcr.io/sua-organizacao

# 2. validacao de runtime (container isolado + health + smoke da Fase 06)
python scripts/validate_release_image.py \
  --image ghcr.io/sua-organizacao/controle-producao-api:<versao> \
  --network <rede-onde-o-postgres-de-teste-esta> \
  --database-url "postgresql+asyncpg://usuario:senha@postgres:5432/algum_banco_de_teste" \
  --expected-server-version <versao>

# 3. so depois, manualmente, publicar (nao automatizado nesta fase):
docker push <registry>/controle-producao-api:<versao>
docker image inspect --format='{{index .RepoDigests 0}}' <registry>/controle-producao-api:<versao>
```

O digest imutável do registry só existe **depois** do `docker push` — antes
disso só existe o ID local da imagem. Registre o digest retornado após o
push; ele é a identidade definitiva que uma automação futura (Fase 08+) deve
comparar, não apenas a tag humana.

## Preparação para rollback (Fase 08)

Nada foi implementado ainda — só preparado:

- Tags de release nunca são sobrescritas (a única forma de gerar
  `controle-producao-api:0.8.0` é com o código que corresponde a
  `API_VERSION=0.8.0` no momento do build; uma correção exige `0.8.1`).
- `scripts/build_release_image.py` nunca remove nem sobrescreve uma imagem
  local existente com tag diferente — cada versão fica com sua própria tag,
  lado a lado.
- Nenhuma limpeza automática de imagens antigas foi criada.
- `docker-compose.prod.yml` já é "apontável" para qualquer tag via
  `SERVER_VERSION` — trocar de versão é só mudar essa variável e rodar
  `docker compose up -d` novamente (ainda manual, não automatizado).
- Rollback não foi acoplado a downgrade de schema — schema e imagem são
  eixos independentes, exatamente como as Fases 01-04 já estabeleceram.

## Fora de escopo desta fase

Rollback automático, troca automática entre imagem nova e anterior, deploy
automático no servidor, GitHub Actions de produção, self-hosted runner,
Watchtower/auto-pull, promoção teste→produção, atualização Desktop, manifest
de instalador Desktop, SHA-256 do instalador Desktop, maintenance mode,
restauração automática de backup, downgrade automático do schema, limpeza
automática agressiva de imagens antigas, `docker push` automatizado (fica
como comando manual documentado).
