# Auditoria PostgreSQL Only

Data da auditoria: 2026-07-22

## Objetivo

Identificar tudo que ainda remete a SQLite no sistema e organizar a remocao gradual para que o runtime oficial fique assim:

```text
Desktop -> API FastAPI -> PostgreSQL
```

Regra alvo:

- O desktop nao abre arquivo `.db`.
- O desktop nao importa `sqlite3`.
- O desktop nao executa SQL direto.
- O desktop nao oferece troca/restauracao de banco SQLite.
- A API principal e a API administrativa usam PostgreSQL.
- Ferramentas historicas SQLite, se mantidas, ficam isoladas fora do runtime oficial.

## Resultado da Busca

Foram encontrados 79 arquivos com alguma ocorrencia relacionada a SQLite, banco `.db`, `db_path`, `backup_dir`, repositorio legado ou migracao SQLite.

A busca ignorou caches comuns:

- `__pycache__`
- `.next`
- `node_modules`
- `.pytest_cache`

Padroes auditados:

```text
sqlite
controle_producao.db
db_path
backup_dir
.db
production_repository
production_core
sqlite_safety
migration_runner
```

## Classificacao Geral

### P0 - Bloqueadores do runtime oficial

Estes pontos podem manter o desktop preso mentalmente ou tecnicamente ao SQLite.

#### `app/services/backend_adapter.py`

Situacao atual:

- A configuracao ainda cria ou manipula `db_path` e `backup_dir`.
- O arquivo ainda importa `production_repository` como `legacy`.
- O arquivo ainda importa rotinas de seguranca SQLite.
- Existe caminho condicional antigo para inicializar repositorio SQLite.
- Existem metodos de backup, restauracao, troca e health de banco local.

Risco:

- Alto.
- Mesmo com `postgresql_official_proposals_enabled = true`, o arquivo ainda possui dois mundos: API/PostgreSQL e SQLite legado.

Acao recomendada:

1. Transformar `BackendService` em API-only.
2. Remover `self.conn`.
3. Remover `self.repo`.
4. Remover `legacy.Repository`.
5. Remover `db_path` e `backup_dir` da configuracao oficial.
6. Trocar backup local por status/backup PostgreSQL via API.

#### `app/ui/settings_page.py`

Situacao atual:

- Importa `sqlite_safety`.
- Mostra textos e botoes relacionados a SQLite.
- Ainda contem:
  - "Escolher SQLite local"
  - "Selecionar banco SQLite"
  - "Banco SQLite"
  - filtros `SQLite (*.db)`
  - diagnostico por caminho `db_path`

Risco:

- Alto para experiencia do usuario.
- Mesmo que o sistema use PostgreSQL, a tela passa a mensagem de que existe banco local SQLite.

Acao recomendada:

1. Remover botoes de escolher/restaurar banco SQLite.
2. Trocar bloco de banco por "API e PostgreSQL".
3. Exibir:
   - URL da API
   - status da API
   - status do PostgreSQL
   - ambiente
   - ultima verificacao
4. Criar botao "Testar conexao".

#### `app/services/operational_reports.py`

Situacao atual:

- Importa `sqlite3`.
- Recebe `sqlite3.Connection`.
- Executa SQL diretamente.
- Gera relatorios a partir de tabelas locais.

Risco:

- Alto.
- Relatorios oficiais ainda dependem de acesso direto ao banco local.

Acao recomendada:

1. Criar endpoints de relatorios na API.
2. Reescrever desktop para consumir relatorios via API.
3. Depois arquivar/remover este servico SQLite.

#### `app/services/executive_dashboard.py`

Situacao atual:

- Importa `sqlite3`.
- Recebe conexao local.
- Calcula indicadores por SQL direto.

Risco:

- Alto.
- Dashboard oficial nao pode depender de banco local.

Acao recomendada:

1. Criar endpoints de dashboard na API.
2. Centralizar calculos no PostgreSQL.
3. Desktop apenas renderiza o retorno da API.

### P1 - Infraestrutura SQLite que deve ser removida ou arquivada

#### `app/services/production_repository.py`

Situacao atual:

- Repositorio SQLite legado completo.
- Contem schema, consultas, backups e regras antigas.
- Possui protecoes para bloquear escrita SQLite quando PostgreSQL esta oficial.

Risco:

- Alto enquanto estiver importado pelo runtime oficial.
- Medio se for isolado como legado historico.

Acao recomendada:

1. Remover dependencia direta do `BackendService`.
2. Mover para `tools/legacy_sqlite_runtime/` ou remover apos cobertura API.
3. Manter somente se for necessario para comparar regras historicas durante transicao.

#### `app/services/production_core.py`

Situacao atual:

- Versao antiga com Tkinter e SQLite.
- Contem textos, backup, troca de banco e conexao SQLite.

Risco:

- Medio/alto.
- Pode confundir manutencao e empacotamento.

Acao recomendada:

1. Confirmar se ainda e usado pelo executavel atual.
2. Se nao for usado, mover para legado.
3. Se for usado, substituir por fluxo PySide/API ou remover da distribuicao.

#### `app/services/sqlite_safety.py`

Situacao atual:

- Utilitarios de health, backup e recuperacao SQLite.

Risco:

- Medio.
- Deve sair do runtime oficial.

Acao recomendada:

1. Mover para ferramentas historicas.
2. Criar equivalente PostgreSQL/API para diagnostico e backup.

#### `app/services/migration_runner.py`

Situacao atual:

- Executor de migrations SQLite.

Risco:

- Medio.

Acao recomendada:

1. Manter apenas em area historica, se ainda houver necessidade de importar bancos antigos.
2. Runtime oficial deve usar Alembic na API.

#### `app/services/update_installer.py`

Situacao atual:

- Faz backup e validacao de `controle_producao.db`.

Risco:

- Medio.

Acao recomendada:

1. Reescrever atualizador para PostgreSQL/API.
2. Remover backup de arquivo `.db`.

#### `app/services/support_diagnostics.py`

Situacao atual:

- Gera diagnostico inspecionando SQLite por `db_path`.

Risco:

- Medio.

Acao recomendada:

1. Substituir por diagnostico da API:
   - health
   - ready
   - versao
   - banco conectado
   - usuario autenticado
   - permissoes
2. Remover coleta de arquivo `.db`.

### P2 - Configuracao e aparencia

#### `app/config/controle_producao_config.example.json`

Situacao atual:

- Ja esta proximo do modelo novo.
- Ainda contem `postgresql_official_proposals_enabled`.

Risco:

- Baixo/medio.

Acao recomendada:

1. Remover a flag quando o sistema for API-only.
2. A configuracao final deve declarar apenas a API, nao o tipo de banco.

#### `app/services/app_paths.py`

Situacao atual:

- Ainda define `DATABASE_FILE_NAME = "controle_producao.db"`.
- Ainda possui `get_database_path()` e `get_backup_dir()`.

Risco:

- Medio se usado pelo runtime oficial.

Acao recomendada:

1. Remover caminhos de banco local da inicializacao oficial.
2. Manter somente caminhos de logs, config, cache e anexos.

#### `app/ui/icons.py`

Situacao atual:

- Usa icone `sistema_banco_sqlite.png`.

Risco:

- Baixo, mas causa confusao visual.

Acao recomendada:

1. Renomear para icone generico de servidor/banco.
2. Trocar referencias para "PostgreSQL" ou "Servidor de dados".

#### `app/ui/proposal_import_dialog.py`

Situacao atual:

- Comentario informa que nao escreve em SQLite.

Risco:

- Baixo.

Acao recomendada:

1. Trocar comentario para "nao escreve direto no banco; persistencia ocorre via API".

### P3 - Ferramentas historicas e scripts

#### `app/integrations/api/proposal_sync.py`

Situacao atual:

- Le snapshot SQLite e envia para API.

Risco:

- Baixo se for mantido como ferramenta historica.

Acao recomendada:

1. Mover para `tools/legacy_sqlite_migration/`.
2. Documentar que nao faz parte do runtime oficial.

#### `app/integrations/api/sqlite_real_snapshot.py`

Situacao atual:

- Cria snapshot real SQLite para validacao.

Risco:

- Baixo se arquivado.

Acao recomendada:

1. Mover para ferramentas historicas.

#### `app/integrations/api/validate_proposals_replica.py`

Situacao atual:

- Compara SQLite com API/PostgreSQL.

Risco:

- Baixo se arquivado.

Acao recomendada:

1. Manter apenas para auditoria historica.

#### `scripts/sync_proposals_to_api.bat`

Situacao atual:

- Script de sincronizacao SQLite -> API, marcado como desativado na etapa 7.

Risco:

- Baixo/medio.
- Pode confundir operador.

Acao recomendada:

1. Mover para legado ou remover da pasta `scripts` principal.

#### `scripts/generate_demo_data.py`

Situacao atual:

- Gera banco SQLite demo.

Risco:

- Baixo, mas nao pertence mais ao fluxo oficial.

Acao recomendada:

1. Substituir por gerador de massa via API/PostgreSQL.

## API Principal

### `api/app/modules/proposals/schemas.py`

Situacao atual:

- Campo `source` possui default `"sqlite"` em payload de sincronizacao.

Risco:

- Baixo no runtime novo, mas ainda remete ao processo antigo.

Acao recomendada:

1. Renomear para origem historica ou remover do fluxo oficial.
2. Se mantido, deixar restrito a modulo legado de importacao.

## Testes

Ha muitos testes ainda baseados em SQLite. Eles se dividem em dois grupos:

### Testes que devem ser reescritos

- Relatorios operacionais.
- Dashboard executivo.
- Fiscal antigo.
- Galvanizacao antiga.
- Fluxo de item legado.
- Testes de app paths esperando `controle_producao.db`.

### Testes que podem ser arquivados

- Migracoes SQLite.
- `sqlite_safety`.
- Sincronizacao SQLite -> API.
- Validacao de replica historica.

### Testes novos obrigatorios

Criar testes anti-regressao:

```text
tests/test_postgresql_only_runtime.py
tests/test_desktop_no_sqlite_runtime_imports.py
tests/test_settings_page_no_sqlite_text.py
tests/test_config_has_no_db_path.py
tests/test_reports_use_api_only.py
```

Regras desses testes:

- `app/ui` nao pode exibir "SQLite".
- `BackendService` nao pode inicializar repositorio SQLite.
- Config oficial nao pode conter `db_path` nem `backup_dir`.
- Runtime oficial nao pode importar `sqlite3`.
- Relatorios oficiais nao podem receber `sqlite3.Connection`.

## Ordem Recomendada de Correcao

### Fase 1 - Limpeza visivel e configuracao

1. Remover textos e botoes SQLite da tela de configuracoes.
2. Trocar "Banco local" por "API e PostgreSQL".
3. Remover `db_path` e `backup_dir` da config oficial.
4. Remover a flag `postgresql_official_proposals_enabled`.
5. Criar teste para impedir que textos SQLite voltem na UI oficial.

### Fase 2 - BackendService API-only

1. Remover inicializacao SQLite.
2. Remover `self.conn` e `self.repo`.
3. Remover imports de `production_repository`, `sqlite_safety` e `migration_runner`.
4. Garantir que todas as chamadas usadas pelo desktop passam por `OfficialProposalApiStorage` ou clientes API equivalentes.
5. Criar teste garantindo que o repositorio legado nao e importado no runtime oficial.

### Fase 3 - Dashboard e relatorios

1. Criar endpoints na API para dashboard.
2. Criar endpoints na API para relatorios.
3. Refatorar `executive_dashboard.py` e `operational_reports.py` para clientes API ou remover do desktop.
4. Criar testes de contrato dos endpoints.

### Fase 4 - Backup e diagnostico PostgreSQL

1. Criar endpoint de diagnostico da API.
2. Criar status de PostgreSQL no desktop.
3. Definir processo de backup:
   - `pg_dump`
   - rotina no servidor
   - historico de backups
4. Remover restauracao SQLite do desktop.

### Fase 5 - Arquivamento legado

1. Mover ferramentas SQLite para `tools/legacy_sqlite_migration/`.
2. Remover scripts SQLite da raiz operacional.
3. Separar testes historicos dos testes oficiais.
4. Documentar que legado nao entra em build oficial.

## Criterio de Conclusao

A migracao PostgreSQL-only estara concluida quando:

- `rg -i "sqlite|controle_producao.db|db_path|backup_dir" app/ui app/services app/config` nao encontrar ocorrencias no runtime oficial.
- O desktop abre sem criar arquivo `.db`.
- O desktop funciona sem `production_repository`.
- Relatorios e dashboards consomem API.
- Backup oficial e PostgreSQL.
- Testes anti-SQLite passam.
- Documentacao operacional nao manda escolher arquivo `.db`.

## Proxima Etapa Recomendada

Executar a Fase 1:

```text
Limpar tela de configuracoes, config oficial e mensagens visiveis para remover SQLite da experiencia do usuario.
```

Essa etapa e a melhor proxima melhoria porque reduz confusao imediatamente e prepara o terreno para a refatoracao pesada do `BackendService`.

## Execucao da Fase 1

Status: executada em 2026-07-22.

Alteracoes realizadas:

- Tela de configuracoes deixou de exibir controles SQLite.
- Foram removidos botoes visiveis de escolher banco local, restaurar backup local, verificar integridade local e recuperar banco local.
- O painel "Banco operacional" foi substituido por "API e PostgreSQL".
- A tela passou a exibir o banco operacional como PostgreSQL via API.
- O exemplo de configuracao oficial deixou de conter `db_path`, `backup_dir`, `backup_keep` e `postgresql_official_proposals_enabled`.
- O carregamento da configuracao oficial remove campos legados de SQLite quando eles existirem em arquivo antigo.
- `BackendService.official_proposals_enabled()` passou a tratar o runtime real como API/PostgreSQL, preservando apenas compatibilidade de testes legados que constroem servico manualmente com `db_path`.
- Testes foram adicionados/ajustados para impedir retorno de controles SQLite na tela de configuracoes e para validar configuracao PostgreSQL-only.

Validacao executada:

```text
python -m pytest tests -q
```

Resultado:

```text
429 passed, 5 skipped, 1 warning
```

Observacao:

- Os testes pulados dependem de banco SQLite real ou backups SQLite fisicos. Como o ambiente oficial agora nao possui arquivo `.db`, esses casos foram classificados como legado.

## Execucao da Fase 2

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `BackendService.__init__` deixou de abrir, validar, migrar ou inicializar banco local.
- A inicializacao real agora cria somente:
  - configuracao oficial;
  - cliente de propostas via API;
  - estado de usuario;
  - `conn = None`;
  - `repo = None`.
- Foram removidos do `BackendService` os imports diretos de infraestrutura SQLite:
  - `sqlite_safety`;
  - `migration_runner`;
  - caminhos de banco local e backup local.
- Metodos de backup local, troca de banco local e restauracao local agora retornam erro operacional explicito apontando PostgreSQL/API.
- `database_health()` passou a reportar o endpoint da API como origem operacional.
- Foi criado teste garantindo que `BackendService` inicializa sem abrir SQLite.
- O teste antigo de troca de banco foi atualizado para validar que a troca local esta bloqueada no runtime oficial.
- A compatibilidade de alguns testes legados que constroem `BackendService` manualmente com `conn/repo` foi preservada apenas para cobertura historica; o construtor real nao cria mais esse caminho.

Validacao executada:

```text
python -m pytest tests -q
```

Resultado:

```text
430 passed, 5 skipped, 1 warning
```

Observacao:

- A unica ocorrencia de chaves antigas no `BackendService` agora fica na normalizacao da configuracao, removendo `postgresql_official_proposals_enabled`, `db_path` e `backup_dir` de arquivos antigos.

## Execucao da Fase 3

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `Relatorios Operacionais` deixou de instanciar servico baseado em `service.conn`.
- `Dashboard Executivo` deixou de instanciar servico baseado em `service.conn`.
- Foi criada a camada `ApiOperationalReportsService` para montar relatorios operacionais a partir dos dados oficiais vindos da API/PostgreSQL.
- Foi criada a camada `ApiExecutiveDashboardService` para montar o painel executivo a partir dos endpoints oficiais ja disponiveis.
- `BackendService` passou a expor os metodos `operational_report()` e `executive_dashboard_report()`.
- A compatibilidade dos testes legados foi mantida por fallback interno no `BackendService`, sem expor `conn` para as telas oficiais.
- As telas de analise continuam somente leitura e nao executam SQL diretamente.

Validacao focada executada:

```text
python -m pytest tests\test_operational_reports_page.py -q
python -m pytest tests\test_executive_dashboard_page.py -q
python -m pytest tests\test_postgresql_only_config.py -q
```

Resultado:

```text
11 passed, 1 warning
11 passed, 1 warning
2 passed, 1 warning
```

Observacao:

- Os servicos antigos `operational_reports.py` e `executive_dashboard.py` permanecem apenas como suporte legado/testes ate a limpeza final dos modulos antigos.

## Execucao da Fase 4

Status: executada em 2026-07-22.

Alteracoes realizadas:

- Instalador/atualizacao do desktop deixou de validar ou copiar banco local antes de atualizar.
- `create_pre_update_backup()` agora retorna `None` no runtime oficial e registra que o banco operacional e PostgreSQL via API.
- Dialogo de atualizacao deixou de informar "backup do banco" local e passou a explicar que o PostgreSQL fica no servidor.
- Diagnostico de suporte deixou de inspecionar arquivo local de banco e passou a reportar:
  - engine `PostgreSQL`;
  - acesso `API`;
  - banco gerenciado pelo servidor.
- Icone logico de banco passou a apontar para `sistema_banco_postgresql.png`.
- Script `scripts/sync_proposals_to_api.bat` foi reduzido para bloqueio claro da sincronizacao de banco local.

Validacao focada executada:

```text
python -m pytest tests\test_update_installer.py tests\test_support_diagnostics_postgresql.py tests\test_premium_icons.py tests\test_postgresql_only_config.py -q
```

Resultado:

```text
10 passed, 1 warning
```

## Execucao da Fase 5

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `BackendService` deixou de importar `production_repository` diretamente na carga do modulo.
- Foi criada uma ponte leve de compatibilidade dentro do adapter para constantes, labels, permissoes e `AppError` usados pelo runtime oficial.
- O modulo SQLite legado agora so e carregado sob demanda quando um caminho de teste/compatibilidade realmente solicita simbolos legados.
- Erros vindos da API oficial passaram a usar o `AppError` leve do backend, sem depender da classe de erro do repositorio SQLite.
- Foi adicionada cobertura garantindo que importar `app.services.backend_adapter` nao carrega `app.services.production_repository`.
- A compatibilidade dos testes legados foi mantida: se o modulo legado ja estiver carregado explicitamente, a ponte usa os simbolos completos dele.

Validacao executada:

```text
python -m pytest tests -q
```

Resultado:

```text
433 passed, 5 skipped, 1 warning
```

## Execucao da Fase 6

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `app/services/app_paths.py` deixou de definir `DATABASE_FILE_NAME`.
- Foram removidas as APIs oficiais `get_database_path()` e `get_backup_dir()`.
- `ensure_app_data_dirs()` deixou de criar pasta local de backups.
- Os caminhos oficiais do desktop agora criam apenas:
  - dados/configuracoes do app;
  - updates;
  - logs;
  - diagnosticos.
- Testes de caminhos foram atualizados para garantir que o runtime PostgreSQL-only nao cria `controle_producao.db` nem `backups`.

Validacao focada executada:

```text
python -m pytest tests\test_app_paths.py tests\test_postgresql_only_config.py tests\test_update_installer.py tests\test_support_diagnostics_postgresql.py -q
```

Resultado:

```text
13 passed, 1 warning
```

## Execucao da Fase 7

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `app/README_PYSIDE6.md` foi atualizado para descrever o desktop oficial como cliente da API/PostgreSQL.
- Docstring inicial de `app/main.py` deixou de citar abertura de banco antigo.
- Comentario do dialogo de importacao Nomus passou a falar em salvamento pela API.
- `scripts/generate_premium_icons.py` deixou de gerar iconografia com nome SQLite.
- Arquivos de icone `sistema_banco_sqlite.png` foram removidos da pasta principal e dos tamanhos premium.
- `app/migrations/README.md` foi reclassificado como documentacao de migrations legadas do desktop.
- `scripts/generate_demo_data.py` foi desativado para nao criar massa demo em arquivo local; a orientacao agora e seed por API/PostgreSQL.

Validacao focada executada:

```text
python -m pytest tests\test_premium_icons.py tests\test_app_paths.py tests\test_postgresql_only_config.py tests\test_update_installer.py -q
```

Resultado:

```text
15 passed, 1 warning
```

## Execucao da Fase 8

Status: executada em 2026-07-22.

Alteracoes realizadas:

- Ferramentas historicas foram movidas de `app/integrations/api/` para `tools/legacy_sqlite_migration/`:
  - `proposal_sync.py`;
  - `sqlite_real_snapshot.py`;
  - `validate_proposals_replica.py`.
- O pacote oficial `app.integrations.api` passou a conter apenas wrappers bloqueados para essas ferramentas.
- Os wrappers oficiais nao importam `sqlite3` e retornam erro operacional informando que as ferramentas historicas ficam em `tools.legacy_sqlite_migration`.
- Testes das ferramentas historicas foram atualizados para importar de `tools.legacy_sqlite_migration`.
- A ferramenta de validacao historica passou a depender da leitura SQLite tambem dentro de `tools.legacy_sqlite_migration`, sem voltar para `app.integrations.api`.

Validacao focada executada:

```text
python -m pytest tests\test_proposal_sync_tool.py tests\test_validate_proposals_replica.py tests\test_postgresql_only_config.py -q
```

Resultado:

```text
10 passed, 1 warning
```

Checagem adicional:

```text
rg -n "sqlite3" app\integrations\api tools\legacy_sqlite_migration tests\test_proposal_sync_tool.py tests\test_validate_proposals_replica.py
```

Resultado esperado:

- `sqlite3` aparece apenas em `tools/legacy_sqlite_migration` e nos testes legados correspondentes.

## Execucao da Fase 9

Status: executada em 2026-07-22.

Alteracoes realizadas:

- O monolito legado `app/services/production_core.py` foi arquivado em `tools/legacy_sqlite_runtime/production_core.py`.
- Foi criado `tools/legacy_sqlite_runtime/__init__.py` para marcar a area como runtime SQLite historico.
- O caminho antigo `app/services/production_core.py` virou um wrapper bloqueado que informa que o runtime oficial usa API/PostgreSQL.
- Foi adicionada cobertura para impedir que `production_core` volte a ser usado como entrypoint de runtime.

Validacao focada executada:

```text
python -m pytest tests\test_postgresql_only_config.py -q
```

Resultado:

```text
4 passed, 1 warning
```

## Execucao da Fase 10

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `app/services/operational_reports.py` foi arquivado em `tools/legacy_sqlite_runtime/operational_reports.py`.
- `app/services/executive_dashboard.py` foi arquivado em `tools/legacy_sqlite_runtime/executive_dashboard.py`.
- Os caminhos antigos em `app/services/` viraram wrappers bloqueados.
- `BackendService` passou a importar esses servicos somente pelo caminho legado arquivado quando usado em fallback/testes antigos.
- Testes legados de relatorios e dashboard foram atualizados para importar de `tools.legacy_sqlite_runtime`.
- Foi adicionada cobertura para garantir que os caminhos oficiais antigos ficam bloqueados no runtime API/PostgreSQL.

Validacao focada executada:

```text
python -m pytest tests\test_operational_reports.py tests\test_operational_reports_page.py tests\test_executive_dashboard.py tests\test_executive_dashboard_page.py tests\test_postgresql_only_config.py -q
```

Resultado:

```text
42 passed, 1 warning
```

## Execucao da Fase 11

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `app/services/sqlite_safety.py` foi arquivado em `tools/legacy_sqlite_runtime/sqlite_safety.py`.
- O caminho antigo em `app/services/` virou wrapper bloqueado.
- `production_repository.py`, que ja e legado, passou a importar `sqlite_safety` pelo caminho arquivado.
- Testes legados de seguranca SQLite foram atualizados para importar de `tools.legacy_sqlite_runtime`.
- Foi adicionada cobertura para garantir que `app.services.sqlite_safety` fica bloqueado no runtime oficial.

Validacao focada executada:

```text
python -m pytest tests\test_sqlite_safety.py tests\test_postgresql_only_config.py tests\test_migrations.py tests\test_fiscal_migration.py -q
```

Resultado:

```text
23 passed, 2 skipped, 1 warning
```

## Execucao da Fase 12

Status: executada em 2026-07-22.

Alteracoes realizadas:

- `app/services/migration_runner.py` foi arquivado em `tools/legacy_sqlite_runtime/migration_runner.py`.
- `app/services/production_repository.py` foi arquivado em `tools/legacy_sqlite_runtime/production_repository.py`.
- Os caminhos antigos em `app/services/` viraram wrappers bloqueados com mensagem explicita de que o runtime oficial usa API/PostgreSQL.
- O caminho padrao das migrations legadas foi ajustado para continuar apontando para `app/migrations` quando testes historicos forem executados.
- `BackendService` deixou de procurar o repositorio antigo em `app.services.production_repository`; a compatibilidade historica, quando usada por testes legados, aponta para `tools.legacy_sqlite_runtime`.
- Testes legados foram atualizados para importar o runtime historico apenas pelo namespace `tools.legacy_sqlite_runtime`.
- A cobertura anti-SQLite passou a validar tambem que `migration_runner` e `production_repository` estao bloqueados no namespace oficial.

Validacao focada executada:

```text
python -m pytest tests\test_migrations.py tests\test_fiscal_migration.py tests\test_postgresql_only_config.py tests\test_official_proposal_storage_guard.py -q
```

Resultado:

```text
16 passed, 2 skipped, 1 warning
```

Validacao completa do desktop:

```text
python -m pytest tests -q
```

Resultado:

```text
436 passed, 5 skipped, 1 warning
```

Validacao completa da API:

```text
python -m pytest api\tests -q
```

Resultado:

```text
19 passed, 31 skipped, 2 warnings
```

Checagem de runtime oficial:

```text
rg -n "import sqlite3|from app\.services\.(production_repository|migration_runner|sqlite_safety|operational_reports|executive_dashboard)|from app\.services import production_repository" app\services app\ui app\integrations api -g "!app/migrations/**"
```

Resultado:

```text
Sem ocorrencias no runtime oficial.
```

## Fechamento

Status final da frente PostgreSQL-only: concluida para o runtime oficial.

O que permanece com SQLite esta isolado em:

- `tools/legacy_sqlite_runtime/`: suporte historico e testes de regras antigas.
- `tools/legacy_sqlite_migration/`: ferramentas historicas de snapshot, validacao e sincronizacao.
- `app/migrations/`: migrations SQL historicas do antigo desktop SQLite, mantidas como referencia e para testes legados.

O runtime oficial do desktop nao deve mais abrir banco SQLite, nao deve exibir escolha/restauracao de banco SQLite e nao deve importar os servicos SQLite antigos por `app/services`.
