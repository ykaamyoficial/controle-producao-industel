# Controle de Producao Industel

Sistema de controle de producao industrial da Industel.

Baseline arquitetural oficial: 3.0.0

Arquitetura oficial:

```text
Desktop PySide6 -> API FastAPI -> PostgreSQL
```

O desktop opera como cliente da API. A API centraliza autenticacao, permissoes, regras de negocio, historico, auditoria e persistencia no PostgreSQL.

## Tecnologias

- Desktop: Python 3.11+, PySide6
- API: Python 3.12+, FastAPI, Uvicorn, SQLAlchemy, Alembic
- Banco: PostgreSQL 16+
- Infraestrutura: Docker e Docker Compose
- Empacotamento: PyInstaller

## Executar localmente

1. Suba PostgreSQL e API:

```bat
scripts\start_dev_environment.bat
```

2. Rode as migrations da API:

```bat
scripts\run_api_migrations.bat
```

3. Crie ou confirme o administrador inicial:

```bat
scripts\create_api_admin.bat
```

4. Abra o desktop:

```bat
python -m app.main
```

API local padrao:

```text
http://127.0.0.1:8000
```

## Testes

Suite oficial (Desktop e API sem banco; a API pula os testes que exigem Postgres):

```bat
python -m pytest tests api/tests -q
```

Suite da API com Postgres descartavel (leva cerca de 1 hora). O nome do banco precisa ter `test`:

```bat
set APP_ENV=test
set POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://USUARIO:SENHA@127.0.0.1:5432/controle_producao_test
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

`test_docker_release_integration.py` e `test_deployment_rollback_integration.py` exigem Docker real e
ambiente proprio e travam a suite com Docker ativo. Rode-os a parte, com timeout:

```bat
python -m pytest api/tests/test_docker_release_integration.py api/tests/test_deployment_rollback_integration.py -q --timeout=600
```

Resultado da rodada final de 2026-11-19 (HEAD 2c8166e):

```text
Desktop:                  2488 passed, 22 skipped, 0 failed (220 arquivos)
API sem banco:             995 passed, 527 skipped, 0 failed
API com Postgres (suite inteira, sem os 2 arquivos Docker): 1520 passed, 2 skipped, 0 failed
```

## Gerar o executavel

Caminho oficial (Python 3.11, na raiz do repositorio): `-m PyInstaller Updater.spec`,
`ControleProducao.spec` e `Launcher.spec` (cada um com `--clean --noconfirm`), depois
`installer\ControleProducao.iss` no ISCC (Inno Setup), `scripts\build_update_package.py` e
`scripts\generate_release_manifest.py`. Os `.spec` e `.bat` antigos da raiz
(`gerar_exe_pyside6.bat`, `gerar_exe_setup.bat`, `Controle Producao 2.0.spec`,
`Controle Producao Industel Telecom.spec`) sao legados e nao servem para release.

## Documentacao

- `docs/BASELINE_3.0.0.md`
- `docs/MIGRACAO_SQLITE_POSTGRESQL_FINALIZADA.md`
- `docs/architecture/`
