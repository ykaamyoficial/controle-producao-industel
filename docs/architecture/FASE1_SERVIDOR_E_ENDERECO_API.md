# Fase 1 - Servidor e Endereco Oficial da API

## Objetivo

Fazer a API deixar de responder apenas em `127.0.0.1` (a propria maquina) e
passar a ser alcancavel por outros computadores da rede local da empresa, por
um endereco estavel, preparando a base para a Fase 2 (configuracao central do
Desktop).

Esta fase e exclusivamente de infraestrutura/conectividade. Nenhuma regra de
negocio, tabela, migration ou funcionalidade existente foi alterada.

## Diagnostico encontrado (antes desta fase)

A API ja possuia, de fases anteriores do projeto (ver `API_FUNDACAO.md`,
`API_RUNTIME_DEV.md`, `HEALTH_CHECKS_AND_SMOKE_TESTS.md`, `DOCKER_RELEASE_IMAGES.md`):

- `API_HOST`/`API_PORT` configuraveis por variavel de ambiente
  (`api/app/core/config.py`), com default `127.0.0.1:8000` em desenvolvimento;
- o processo Uvicorn dentro do container ja sobe com `--host 0.0.0.0` tanto em
  desenvolvimento (`docker-compose.dev.yml`) quanto em producao
  (`api/Dockerfile`, `CMD`);
- endpoints de health check maduros: `/api/v1/health/live` (liveness, nunca
  toca banco) e `/api/v1/health/ready` (readiness, valida PostgreSQL e a
  revisao do schema, sem expor credenciais/stack trace/connection string);
  tambem existe o endpoint legado `/api/v1/system/health`;
- PostgreSQL nunca e exposto ao host em producao (`docker-compose.prod.yml`
  nao publica a porta 5432).

**Gap real identificado:** em `docker-compose.prod.yml`, a porta da API era
publicada como `"127.0.0.1:${API_PORT:-8000}:8000"`. Ou seja, mesmo com o
processo escutando em `0.0.0.0` *dentro* do container, o Docker só aceitava
conexões vindas da própria máquina do host (o bind de publicação da porta
ficava restrito ao loopback). Na prática, nenhum outro computador da rede
local conseguia alcançar a API, mesmo com o servidor fisico já rodando o
container corretamente.

## Alteracao realizada

`docker-compose.prod.yml`, servico `api`:

```yaml
ports:
  - "${API_BIND_HOST:-0.0.0.0}:${API_PORT:-8000}:8000"
```

- Default passa a ser `0.0.0.0` (todas as interfaces do host), tornando a API
  alcançável pela LAN.
- Permanece configurável via `API_BIND_HOST` para quem quiser restringir a
  publicação a uma interface especifica do servidor, sem precisar editar o
  compose.
- PostgreSQL continua **sem** publicar porta nenhuma (inalterado).
- O acesso continua sendo delimitado pelo firewall do servidor (ver secao
  "Firewall" abaixo) — esta mudanca nao abre a API para a internet, apenas
  deixa de restringi-la a propria maquina.

`api/app/main.py`, inicio do `lifespan`: passa a logar explicitamente onde o
processo esta escutando e o status da conexao com o PostgreSQL, sem nunca
logar segredos:

```text
[INFO] api_started service=controle-producao-api version=0.8.0 ... env=production ...
[INFO] api_listening host=0.0.0.0 port=8000
[INFO] api_postgresql_status status=connected
```

## Arquitetura resultante

```text
PC CLIENTE (LAN)
  v
http://<IP_DO_SERVIDOR>:8000
  v
SERVIDOR (rede local da empresa)
  |-- API FastAPI (container, bind 0.0.0.0:8000, publicado em 0.0.0.0:8000 do host)
  v
PostgreSQL (container, sem porta publicada para o host)
```

## Endereco oficial da API (API_INTERNAL_ADDRESS)

```text
http://<IP_DO_SERVIDOR>:8000
```

**Pendente de preenchimento.** O IP/hostname LAN real do servidor Industel
ainda não foi informado — não deve ser inventado. Assim que definido
(IP estático ou reserva DHCP), preencher:

```text
Nome/identificacao: <preencher>
IP LAN:              <preencher>
API host (bind):      0.0.0.0
API port:              8000
Endpoint de health:   http://<IP_DO_SERVIDOR>:8000/api/v1/health/ready
```

## Endereco estavel do servidor

Nao foi realizada nenhuma alteracao de rede (nem poderia ser feita a partir
deste repositorio). Duas estrategias possiveis, a decidir por quem administra
a infraestrutura fisica da empresa:

- IP estatico configurado diretamente no servidor; ou
- reserva DHCP para o MAC do servidor no roteador/servidor DHCP.

Qualquer uma das duas atende ao requisito de "endereco que nao muda sozinho".
A aplicacao ja esta preparada para qualquer uma delas, pois nao depende do IP
em nenhum lugar do codigo (so do bind `0.0.0.0`, que e independente do IP
atribuido).

## Preparacao para DNS interno futuro

Como o Desktop (Fase 2) consumira a API por uma unica fonte de configuracao
(`API_BASE_URL`), trocar `http://<IP_DO_SERVIDOR>:8000` por
`http://api.industel.local` no futuro nao exige nenhuma mudanca nesta camada
— e apenas um valor de configuracao diferente apontando para o mesmo bind
`0.0.0.0:8000`.

## Firewall do servidor

Nao foi alterado nenhum firewall a partir deste repositorio (fora do escopo,
depende do servidor fisico real). Instrucao para quem for aplicar em
producao, no servidor Windows onde o Docker roda:

```powershell
New-NetFirewallRule -DisplayName "Controle Producao API (LAN)" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 `
  -RemoteAddress <SUB-REDE_LAN, ex. 192.168.1.0/24> -Action Allow
```

- Restringir sempre a sub-rede da LAN da empresa (`-RemoteAddress`), nunca
  `Any -> Any`.
- Nao desabilitar o Windows Firewall.
- Nao abrir a porta 5432 (PostgreSQL) para a rede — ela nunca e publicada
  pelo compose, entao nao ha nada a liberar nela.

## Testes automatizados adicionados

- `api/tests/test_release_compose_policy.py`:
  `ProductionComposeApiPortIsLanReachableTests` — garante que
  `docker-compose.prod.yml` nunca volte a restringir a porta da API a
  `127.0.0.1`, e que o servico PostgreSQL continue sem publicar porta.
- `api/tests/test_api_foundation.py`:
  - `test_default_host_stays_loopback_for_local_development` — o default de
    fabrica de `API_HOST` continua `127.0.0.1` (desenvolvimento local
    preservado);
  - `test_production_style_host_bind_is_accepted` — `API_HOST=0.0.0.0` e
    aceito pela configuracao (bind de producao).

## Fora do escopo desta fase

Nao foram implementados: configuracao automatica do Desktop, tela de primeiro
acesso, descoberta automatica de servidor, HTTPS, acesso pela internet,
abertura de porta no roteador, instalador, controle de compatibilidade de
versoes, migracao de banco ou qualquer alteracao de regra de negocio. Esses
itens pertencem as proximas fases.
