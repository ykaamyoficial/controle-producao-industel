# Baseline 3.0.0 - Arquitetura Oficial

Data do congelamento: 2026-07-27

Este documento consolida a base oficial do Sistema de Controle de Producao Industel apos a migracao para a arquitetura Desktop -> API -> PostgreSQL.

## Versao oficial da arquitetura

Baseline arquitetural: 3.0.0

Esta versao define que o desktop e apenas cliente da API. O banco oficial do sistema e PostgreSQL, acessado exclusivamente pela API FastAPI.

## Arquitetura oficial

```text
Desktop PySide6
    |
    | HTTP REST
    v
API FastAPI
    |
    v
PostgreSQL
```

Regras oficiais:

- O desktop nao acessa o banco operacional diretamente.
- A API e a unica camada com credenciais do PostgreSQL.
- Regras de negocio, validacoes, permissoes, historico e auditoria ficam centralizadas na API.
- O SQLite nao faz parte do fluxo operacional oficial.
- Itens historicos do SQLite permanecem apenas como referencia, ferramenta arquivada ou documentacao de migracao.

## Modulos homologados

- Login e sessao.
- Usuarios, perfis e permissoes.
- Cadastro e edicao de propostas.
- Controle Geral.
- Producao.
- Galvanizacao.
- Cargas e retornos.
- Almoxarifado.
- Expedicao.
- Fiscal.
- Historico operacional.
- Parciais.
- Correcao administrativa.
- Diagnostico API/PostgreSQL.

## Fluxo operacional oficial

1. Usuario abre o desktop.
2. Desktop valida conexao com a API.
3. Login e feito pela API.
4. API autentica, carrega usuario, roles e permissoes no PostgreSQL.
5. Desktop consome endpoints REST para propostas, itens e operacoes.
6. API aplica regras de negocio em transacao.
7. PostgreSQL persiste estado, historico e auditoria.
8. Desktop atualiza as telas com os dados retornados pela API.

## Ambiente de desenvolvimento

Ambiente padrao:

- PostgreSQL via Docker Compose.
- API FastAPI via Docker Compose.
- Desktop executado localmente em Python.
- Migrations controladas por Alembic.

Scripts oficiais:

- `scripts/start_dev_environment.bat`
- `scripts/run_api_migrations.bat`
- `scripts/create_api_admin.bat`
- `scripts/run_api_tests.bat`
- `scripts/run_api_integration_tests.bat`

Configuracao Docker de desenvolvimento:

- Banco: `controle_producao_dev`
- Usuario: `controle_dev`
- Porta PostgreSQL local: `55432`
- Porta API local: `8000`
- URL API desktop: `http://127.0.0.1:8000`

## Dependencias oficiais

Desktop:

- Python 3.11+
- PySide6
- Cliente HTTP REST para a API

API:

- Python 3.12+
- FastAPI
- Uvicorn
- SQLAlchemy
- Alembic
- Pydantic Settings
- asyncpg

Banco:

- PostgreSQL 16+

Infraestrutura:

- Docker Desktop
- Docker Compose

## Versoes registradas

- Baseline arquitetural: 3.0.0
- Desktop atual: 2.5.2
- Build desktop: 2026.07.20
- API: 0.8.0
- API stage: official-fiscal
- Revisao Alembic esperada: 20260727_0010
- PostgreSQL minimo: 16
- PostgreSQL validado em desenvolvimento: 16.14
- Docker validado: 29.6.1
- Python da API: 3.12+

## Estrutura dos testes

Suite oficial:

- `tests/`
- `api/tests/`

Configuracao oficial:

- `pytest.ini`

O `pytest.ini` limita a coleta oficial para a suite Desktop/API/PostgreSQL e exclui areas arquivadas ou separadas, como `tools/` e `admin-platform/`.

Resultado oficial registrado:

- Comando: `python -m pytest tests api/tests -q`
- Resultado: 330 passed, 35 skipped, 0 failed

## Decisoes arquitetonicas

- PostgreSQL e o banco oficial.
- FastAPI e a camada unica de acesso aos dados.
- Desktop nao possui fluxo operacional SQLite.
- Permissoes e RBAC sao retornados pela API e respeitados pelo desktop.
- Admin Platform foi deixado fora da arquitetura operacional atual, pois o sistema passa a atender uma unica empresa.
- Ferramentas antigas de migracao e testes historicos permanecem arquivados para consulta.
- Migrations estruturais do banco oficial sao Alembic.
- Dados antigos SQLite de teste nao foram migrados para producao.

## Itens arquivados

SQLite legado:

- `tools/legacy_sqlite_runtime/`
- `tools/legacy_sqlite_migration/`
- `tools/legacy_sqlite_runtime/archived_tests/`

Admin Platform:

- `admin-platform/` fica separado da suite principal e nao faz parte do fluxo operacional oficial atual.

Documentos historicos:

- Documentos antigos em `docs/architecture/` continuam preservados para rastreabilidade da migracao.

## Requisitos minimos do ambiente

Servidor/API:

- Windows Server ou Linux com Docker, ou Python 3.12+ instalado.
- PostgreSQL 16+.
- Porta da API liberada para os desktops autorizados.
- Backup PostgreSQL configurado no servidor.
- Variaveis de ambiente da API configuradas com segredo forte.

Desktop:

- Windows 10 ou superior.
- Acesso de rede ao endereco da API.
- Python/instalador compativel com PySide6, quando executado fora do executavel.

## Estado final

A baseline 3.0.0 fica congelada como base oficial para novas evolucoes do sistema. Novas funcionalidades devem ser desenvolvidas sobre Desktop -> API -> PostgreSQL, sem reintroduzir fluxo operacional SQLite.
