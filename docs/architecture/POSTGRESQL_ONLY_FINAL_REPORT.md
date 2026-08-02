# Relatorio Final - Sistema PostgreSQL Only

Data: 2026-07-22

## Resultado Executivo

A frente planejada para remover o SQLite do runtime oficial foi concluida.

O sistema desktop passou a operar como cliente da API, usando PostgreSQL como banco oficial. O codigo SQLite restante foi isolado fora do caminho oficial, em pastas de legado e ferramentas historicas, para preservar testes e referencia tecnica sem permitir uso acidental pela aplicacao.

Percentual da frente: 100% concluido.

## Arquitetura Atual

```text
Desktop PySide6
    -> Cliente HTTP
    -> API FastAPI
    -> SQLAlchemy/Alembic
    -> PostgreSQL
```

Regras atuais:

- Desktop nao acessa banco operacional diretamente.
- Escrita/leitura oficial de propostas, producao, galvanizacao, expedicao, fiscal, relatorios e dashboard passam pela API.
- Credenciais do PostgreSQL ficam na API.
- Migrations oficiais do banco usam Alembic.
- SQLite nao aparece mais como banco selecionavel na interface oficial.

## O Que Foi Removido do Runtime Oficial

- Caminhos de configuracao `db_path`, `backup_dir`, `backup_keep` e flag antiga de virada.
- Tela de escolher/restaurar banco SQLite.
- Backups locais SQLite no instalador/diagnostico oficial.
- Iconografia e textos operacionais de SQLite.
- Import direto do repositorio SQLite pelo `BackendService`.
- Servicos SQLite antigos em `app/services`:
  - `production_core.py`;
  - `production_repository.py`;
  - `migration_runner.py`;
  - `sqlite_safety.py`;
  - `operational_reports.py`;
  - `executive_dashboard.py`.

## O Que Permanece Como Legado Controlado

Estes arquivos continuam apenas para historico, testes e comparacao:

- `tools/legacy_sqlite_runtime/`
- `tools/legacy_sqlite_migration/`
- `app/migrations/`

Os caminhos antigos em `app/services` agora sao wrappers bloqueados. Se alguem tentar usar esses modulos pelo caminho oficial, recebe erro claro informando que foram arquivados.

## Evidencias de Validacao

Validacao focada da ultima etapa:

```text
16 passed, 2 skipped, 1 warning
```

Suite completa do desktop:

```text
436 passed, 5 skipped, 1 warning
```

Suite da API:

```text
19 passed, 31 skipped, 2 warnings
```

Varredura anti-SQLite no runtime oficial:

```text
Sem ocorrencias de import sqlite3 ou imports oficiais dos servicos SQLite arquivados.
```

## Estado Funcional

Areas oficiais cobertas pelo fluxo API/PostgreSQL:

- Login pela API.
- Cadastro e edicao de propostas.
- Itens de proposta.
- Producao e fluxo por item.
- Galvanizacao, cargas e retorno.
- Expedicao, separacao, entrega parcial e remanejamento.
- Fiscal.
- Dashboard e relatorios operacionais via API.
- Historico/auditoria via API.

## Riscos Restantes

- Ainda existem documentos historicos citando SQLite porque registram as etapas antigas da migracao.
- Testes legados continuam usando SQLite em memoria para preservar regras antigas, mas fora do runtime oficial.
- Antes de producao real, ainda e recomendado fazer teste manual completo com API/PostgreSQL ligados no ambiente oficial da empresa.

## Proximo Passo Recomendado

Executar homologacao operacional com usuarios reais:

1. Subir PostgreSQL e API dev/homologacao.
2. Criar usuario administrador.
3. Abrir o desktop.
4. Cadastrar proposta nova.
5. Passar por producao, galvanizacao, expedicao e fiscal.
6. Conferir dashboard, relatorios e auditoria.
7. Validar que nenhum arquivo `.db` novo foi criado no ambiente do desktop.
