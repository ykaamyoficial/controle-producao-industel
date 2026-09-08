# API Fundacao

Data: 20/07/2026

## 1. Objetivo

Esta etapa cria a fundacao tecnica da futura API REST do Sistema de Controle de Producao Industel.

A API ainda nao substitui o desktop, nao acessa o SQLite atual e nao executa regras de negocio. Ela existe de forma isolada para preparar a migracao gradual para:

```text
Aplicativo Desktop -> API REST FastAPI -> PostgreSQL
```

## 2. Arquitetura atual da fundacao

```text
api.app.main
  |
  |-- core: configuracao, logs e erros
  |-- shared: request ID e respostas padronizadas
  |-- database: infraestrutura futura SQLAlchemy/PostgreSQL
  `-- modules/system: health, readiness e version
```

O banco oficial do sistema continua sendo o SQLite usado pelo aplicativo desktop. A API nao conecta nele.

## 3. Estrutura de pastas

```text
api/
|-- app/
|   |-- main.py
|   |-- core/
|   |   |-- config.py
|   |   |-- logging.py
|   |   |-- exceptions.py
|   |   `-- error_codes.py
|   |-- database/
|   |   |-- session.py
|   |   |-- health.py
|   |   `-- base.py
|   |-- modules/
|   |   `-- system/
|   |       |-- router.py
|   |       |-- schemas.py
|   |       `-- service.py
|   `-- shared/
|       |-- responses.py
|       `-- request_context.py
|-- alembic/
|-- tests/
|-- alembic.ini
|-- .env.example
`-- pyproject.toml
```

## 4. Como criar o ambiente

Use um ambiente virtual separado para desenvolvimento:

```bash
python -m venv .venv
.venv\Scripts\activate
```

## 5. Como instalar dependencias

Para desenvolvimento completo do projeto:

```bash
python -m pip install -r requirements-dev.txt
```

As dependencias da API adicionadas nesta etapa sao:

- FastAPI
- Uvicorn
- SQLAlchemy 2.x
- asyncpg
- Alembic
- Pydantic Settings
- httpx para testes

As dependencias do desktop e testes existentes continuam declaradas no `requirements.txt`, incluindo PySide6, pdfplumber, PyMuPDF e Pillow.

## 6. Como configurar variaveis

Copie o exemplo se quiser rodar com arquivo local:

```bash
copy api\.env.example api\.env
```

Variaveis previstas:

```env
APP_ENV=development
API_HOST=127.0.0.1
API_PORT=8000
API_LOG_LEVEL=INFO

DATABASE_URL=
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_CONNECT_TIMEOUT=10

SECRET_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=15

CORS_ALLOWED_ORIGINS=
```

Nesta etapa, `DATABASE_URL` pode ficar vazio e `SECRET_KEY` nao deve ter valor real no repositorio.

## 7. Como iniciar a API

No Windows:

```bat
scripts\start_api_dev.bat
```

Ou diretamente:

```bash
python -m uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --reload
```

O script nao instala dependencias, nao aplica migrations e nao altera banco.

## 8. Como executar testes

Testes antigos do desktop:

```bash
python -m unittest discover -s tests -v
```

Testes especificos da API:

```bash
python -m unittest discover -s api/tests -v
```

## 9. OpenAPI

Com a API rodando localmente:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## 10. Health e readiness

Endpoints disponiveis:

```http
GET /api/v1/system/health
GET /api/v1/system/ready
GET /api/v1/system/version
```

`/health` confirma apenas que o processo da API esta ativo.

`/ready` informa se a infraestrutura esta pronta. Sem `DATABASE_URL`, retorna `database: not_configured`, que e esperado na fundacao.

`/version` usa versionamento proprio da API:

```json
{
  "api_version": "0.1.0",
  "api_stage": "foundation",
  "database_revision": null
}
```

## 11. Request ID

Toda requisicao recebe um identificador:

- Header aceito: `X-Request-ID`.
- Se o cliente enviar ID valido, a API reutiliza.
- Se nao enviar, a API gera um UUID.
- O ID volta na resposta.
- O ID aparece nas respostas de erro e nos logs.

## 12. Erros padronizados

Formato:

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Nao foi possivel concluir a operacao.",
    "request_id": "uuid"
  }
}
```

A API possui handlers para:

- validacao;
- rota nao encontrada;
- metodo nao permitido;
- erro interno;
- indisponibilidade futura do banco.

As respostas nao devem expor tracebacks, `DATABASE_URL`, senhas, tokens, chaves Nomus ou caminhos internos sensiveis.

## 13. PostgreSQL futuro

A infraestrutura inicial esta preparada para:

- SQLAlchemy 2.x async;
- asyncpg;
- Alembic;
- `DATABASE_URL`.

Nesta etapa:

- nenhuma tabela foi criada;
- nenhum model funcional foi criado;
- `create_all()` nao e usado;
- nenhuma migration foi executada;
- a API inicia sem banco configurado.

## 14. Alembic

Estrutura criada em `api/alembic`.

Comandos futuros:

```bash
cd api
alembic revision --autogenerate -m "descricao"
alembic upgrade head
alembic downgrade -1
alembic current
alembic history
```

Migrations de producao devem ser executadas de forma controlada no servidor, nunca automaticamente por cada computador desktop.

## 15. Limitacoes desta etapa

- Nao existe autenticacao.
- Nao existe CRUD de propostas.
- Nao existe integracao com o desktop.
- Nao existe conexao obrigatoria com PostgreSQL.
- Nao existe migracao de dados.
- Nao existe endpoint funcional de producao, galvanizacao, expedicao, almoxarifado, fiscal ou relatorios.

## 16. Proxima etapa recomendada

Proxima etapa: preparar o PostgreSQL de desenvolvimento e criar a primeira configuracao real de conexao, ainda sem migrar o desktop.

Apos isso, a migracao deve comecar por autenticacao e endpoints somente leitura, mantendo o comportamento atual do desktop preservado.
