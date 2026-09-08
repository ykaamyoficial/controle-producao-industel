# Runtime de Desenvolvimento da API

## Problema encontrado

Na Etapa 3, a API e os testes PostgreSQL funcionaram de forma estavel dentro da rede Docker, mas o `asyncpg` executado diretamente no Windows falhou ao conectar em `127.0.0.1:5432`.

Erro observado:

```text
asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the middle of operation
```

## Diagnostico realizado

Validacoes executadas:

- Python Windows: `3.14.6`, 64 bits;
- Python Docker: `3.12`;
- Docker Desktop: containers Linux;
- PostgreSQL Docker: `16.14`;
- porta `127.0.0.1:5432` alcançavel por TCP;
- `psql` do Windows nao esta no PATH;
- `psql` dentro da rede Docker conecta corretamente;
- `asyncpg` no Windows falha em `127.0.0.1:5432`;
- SQLAlchemy async no Windows falha na mesma camada;
- `asyncpg` dentro do Docker conecta corretamente por `postgres:5432`;
- API em Docker responde ao Windows por `http://127.0.0.1:8000`.

Tambem foi observado conflito/ambiguidade na porta `5432` no Windows:

```text
postgres local escutando 5432
Docker backend escutando 5432
localhost resolvendo IPv6 (::1) e IPv4 (127.0.0.1)
```

Os logs do PostgreSQL no container registraram resets vindos do cliente:

```text
could not receive data from client: Connection reset by peer
unexpected EOF on client connection with an open transaction
```

## Causa identificada

A causa foi isolada no caminho de rede e runtime do host Windows:

```text
Python/asyncpg no Windows -> porta publicada 5432 -> PostgreSQL Docker
```

Nao houve evidencia de falha no PostgreSQL, no Alembic ou no SQLAlchemy quando todos rodam no mesmo runtime Docker. A porta `5432` no host estava ambigua por haver PostgreSQL local e Docker escutando ao mesmo tempo.

## Runtime oficial escolhido

Runtime oficial:

```text
API FastAPI em Docker
PostgreSQL em Docker
Alembic executado em Docker
Testes de integracao executados em Docker
```

Arquitetura:

```text
Windows
  -> http://127.0.0.1:8000
API Docker
  -> postgresql+asyncpg://...@postgres:5432/controle_producao_dev
PostgreSQL Docker
```

Alternativa suportada:

```text
PostgreSQL em Docker com porta local 55432 para diagnostico ou ferramentas administrativas.
```

Alternativa nao recomendada:

```text
API no Windows conectando diretamente ao PostgreSQL Docker pela porta publicada.
```

## Justificativa tecnica

O runtime Docker completo:

- elimina conflito entre PostgreSQL local e Docker na `5432`;
- usa Python 3.12, versao oficial da API;
- usa hostname interno `postgres`, sem depender de IPv4/IPv6 do Windows;
- torna Alembic, testes e API reprodutiveis;
- prepara melhor o caminho para CI e servidor;
- mantem o Windows acessando somente HTTP, como o desktop fara futuramente.

## Pre-requisitos

- Docker Desktop em modo Linux containers;
- porta `8000` livre no Windows;
- senha local definida via variavel de ambiente.

Exemplo:

```bat
set POSTGRES_PASSWORD=sua_senha_local
set POSTGRES_DB=controle_producao_dev
set POSTGRES_USER=controle_dev
set POSTGRES_PORT=55432
set API_PORT=8000
```

## Versao do Python

Versao oficial da API:

```text
Python 3.12
```

Registrado em:

```text
.python-version
api/Dockerfile
```

## Iniciar ambiente

```bat
scripts\start_dev_environment.bat
```

Esse comando sobe:

- `controle_producao_postgres_dev`;
- `controle_producao_api_dev`.

Ele nao executa migrations automaticamente.

## Executar migrations

```bat
scripts\run_api_migrations.bat
```

## Consultar status

```bat
scripts\show_dev_status.bat
```

## Consultar logs

```bat
scripts\show_dev_logs.bat
```

## Executar testes

Testes unitarios da API:

```bat
scripts\run_api_tests.bat
```

Testes de integracao PostgreSQL:

```bat
scripts\run_api_integration_tests.bat
```

Os testes de integracao usam banco separado:

```text
controle_producao_test
```

## Acessar API pelo Windows

```text
http://127.0.0.1:8000/api/v1/system/health
http://127.0.0.1:8000/api/v1/system/ready
http://127.0.0.1:8000/api/v1/system/version
```

## Parar ambiente

```bat
scripts\stop_dev_environment.bat
```

Esse comando preserva o volume de desenvolvimento.

## Volumes

O volume `postgres_dev_data` nao deve ser removido por scripts normais.

Remocao de volume e destrutiva e deve ser feita manualmente, com consciencia:

```bat
docker compose -f docker-compose.dev.yml down -v
```

## Variaveis de ambiente

Local oficial para desenvolvimento:

- variaveis do terminal antes de chamar os scripts;
- `api/.env` apenas para execucao local alternativa, nao recomendada;
- Compose para runtime oficial Docker.

Nenhuma senha real deve ser versionada.

## Dependencias

Padrao adotado:

- `requirements.txt`: dependencias do desktop e empacotamento legado;
- `requirements-dev.txt`: instala o conjunto amplo para validacoes locais existentes;
- `api/requirements.txt`: dependencias de runtime da API;
- `api/requirements-dev.txt`: dependencias da API para testes;
- `api/pyproject.toml`: metadados e referencia tecnica da API.

O container da API instala somente `api/requirements-dev.txt` porque esta imagem e de desenvolvimento e tambem executa testes. Ele nao instala PySide6, PyInstaller ou dependencias do desktop.

## Bancos

Desenvolvimento:

```text
controle_producao_dev
```

Testes:

```text
controle_producao_test
```

## Limitacoes conhecidas

- API no Windows conectando ao PostgreSQL Docker pela porta publicada nao e considerada estavel neste ambiente;
- `psql` nao esta no PATH do Windows;
- existe PostgreSQL local escutando na `5432`;
- testes mostram aviso deprecado do `fastapi.testclient`/`httpx`, sem falha funcional.

## Criterios para iniciar a Etapa 4

- ambiente oficial Docker iniciando;
- API acessivel pelo Windows;
- readiness funcionando com banco ativo e parado;
- Alembic em `head`;
- testes unitarios da API aprovados;
- testes de integracao PostgreSQL aprovados repetidamente;
- desktop e SQLite sem alteracao.
