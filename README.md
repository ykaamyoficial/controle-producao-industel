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

Suite oficial:

```bat
python -m pytest tests api/tests -q
```

Resultado registrado na baseline 3.0.0:

```text
330 passed, 35 skipped, 0 failed
```

## Gerar o executavel

Execute `gerar_exe_pyside6.bat`. O resultado sera criado na pasta `dist`.

## Documentacao

- `docs/BASELINE_3.0.0.md`
- `docs/MIGRACAO_SQLITE_POSTGRESQL_FINALIZADA.md`
- `docs/architecture/`
