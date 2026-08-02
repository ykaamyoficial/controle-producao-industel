# Auditoria da Arquitetura Atual

Projeto: Controle de Producao Industel

Data da auditoria: 20/07/2026

Base de referencia: `ARQUITETURA_MIGRACAO_API_POSTGRESQL.md`

## 1. Resumo executivo

O sistema atual e uma aplicacao desktop Python com PySide6, SQLite local/arquivo e camada de servico propria em `app/services`. A arquitetura ja evoluiu alem de um script unico: existe pacote `app`, migrations SQL versionadas, testes automatizados, servicos de relatorio, dashboard, atualizacao, seguranca de SQLite e importacao Nomus/PDF.

Mesmo com essa evolucao, o acesso aos dados ainda acontece diretamente pelo desktop. A camada mais importante e `app/services/backend_adapter.py`, que inicializa o banco SQLite, aplica migrations, cria backups e expoe metodos para a interface. Por baixo dele, `app/services/production_repository.py` concentra a maior parte das regras de negocio e consultas SQL. Esse arquivo e o principal candidato para ser dividido futuramente em services/repositories da API.

Conclusao principal: a migracao para `Desktop -> API REST -> PostgreSQL` deve comecar criando a API sem alterar as regras atuais, usando `BackendService`/`production_repository.py` como mapa de comportamento. A primeira fase deve expor leitura/autenticacao e so depois mover operacoes com efeitos encadeados, como status, carga de galvanizacao, fiscal, parciais e remanejamento.

## 2. Escopo da auditoria

Foram analisados:

- Codigo ativo em `app/`.
- Migrations SQLite em `app/migrations/`.
- Banco real de desenvolvimento em `app/data/controle_producao.db`.
- Testes em `tests/`.
- Scripts em `scripts/`.
- Documentos em `README.md` e `docs/`.
- Arquivos de instalacao/empacotamento: `.spec`, `.bat`, `setup.py`, `setup_cxfreeze.py`, `installer/ControleProducao.iss`.

Nao foram usados como fonte principal:

- `dist/` e `build/`, por serem artefatos gerados.
- `versoes_antigas/`, por representar historico e prototipos antigos.
- Bancos de backup como fonte de estrutura oficial, exceto como evidencia de rotina de backup.

Nenhuma funcionalidade, tabela, migration ou regra foi alterada nesta etapa.

## 3. Metodologia utilizada

1. Leitura da estrutura de arquivos do projeto.
2. Busca por acessos SQLite, comandos SQL e transacoes.
3. Leitura das migrations SQL existentes.
4. Inspecao do banco real via `PRAGMA table_info`, `PRAGMA foreign_key_list`, `PRAGMA index_list`, `PRAGMA integrity_check` e `PRAGMA foreign_key_check`.
5. Leitura dos pontos centrais de negocio: `backend_adapter.py`, `production_repository.py`, `operational_reports.py`, `executive_dashboard.py`, telas e dialogos.
6. Conferencia de documentacao existente para identificar divergencias.
7. Mapeamento de riscos e proposta documental de API.

## 4. Visao geral da arquitetura atual

Fluxo atual real:

```text
Usuario
  |
  v
App Desktop PySide6
  |
  v
BackendService
  |
  v
production_repository.py / servicos SQLite
  |
  v
SQLite: app/data/controle_producao.db
```

Fluxo alvo definido:

```text
App Desktop PySide6
  |
  | HTTPS / REST
  v
API FastAPI
  |
  v
PostgreSQL
```

Observacao importante: `BackendService` ja funciona como uma fachada entre UI e backend local. Isso reduz o risco da migracao, pois permite trocar internamente o backend por um cliente HTTP futuramente, sem reescrever todas as telas de uma vez.

## 5. Estrutura do projeto

Arvore resumida do projeto ativo:

```text
.
|-- app/
|   |-- main.py
|   |-- version.py
|   |-- config/
|   |-- migrations/
|   |-- services/
|   |-- controllers/
|   |-- models/
|   |-- ui/
|   `-- assets/
|-- docs/
|-- installer/
|-- scripts/
|-- tests/
|-- README.md
|-- requirements.txt
|-- ControleProducao.spec
|-- gerar_exe_pyside6.bat
`-- ARQUITETURA_MIGRACAO_API_POSTGRESQL.md
```

Responsabilidades principais:

| Area | Responsabilidade atual |
| --- | --- |
| `app/main.py` | Inicializa QApplication, icone, logs, checagem de atualizacao e janela principal. |
| `app/version.py` | Define versao atual: `2.5.2`, build `2026.07.20`. |
| `app/services/backend_adapter.py` | Fachada usada pela UI; carrega config, abre SQLite, aplica migrations, inicializa repository e expoe metodos para telas. |
| `app/services/production_repository.py` | Repositorio/servico central: regras de negocio, SQL, status, usuarios, cargas, fiscal, parciais, remanejamento, relatorios basicos, historico e auditoria. |
| `app/services/migration_runner.py` | Executor de migrations SQL numeradas com checksum. |
| `app/services/sqlite_safety.py` | Validacao e backups seguros do arquivo SQLite. |
| `app/services/operational_reports.py` | Relatorios operacionais somente leitura. |
| `app/services/executive_dashboard.py` | Indicadores executivos e consultas agregadas. |
| `app/services/nomus_*` | Integracao Nomus via API/configuracao e servicos auxiliares. |
| `app/services/proposal_import/` | Importacao de proposta/PDF Nomus, extracao, normalizacao e validacao. |
| `app/ui/` | Telas e dialogos PySide6. |
| `app/models/` | Table models Qt para processos, fiscal e relatorios. |
| `tests/` | Testes automatizados de regras, UI, migrations, relatórios, Nomus, fiscal, atualizador e seguranca SQLite. |
| `scripts/` | Geracao de dados demo, icones e arquivos de release. |
| `installer/` | Script Inno Setup. |

Linguagem/framework:

- Python informado no README: 3.11.
- Ambiente atual da auditoria: Python 3.14.6.
- UI: PySide6.
- Banco atual: SQLite.
- Empacotamento: PyInstaller e Inno Setup.

## 6. Mapeamento dos acessos ao SQLite

Arquivos ativos com acesso direto ou indireto ao SQLite:

| Arquivo | Classe/funcao | Tabelas principais | Operacao | Regra relacionada | Risco | Destino futuro |
| --- | --- | --- | --- | --- | --- | --- |
| `app/services/backend_adapter.py` | `BackendService.__init__` | schema inteiro | abre banco, aplica migrations, backup | bootstrap do backend local | Alto | configuracao/API client no desktop; bootstrap de DB ficara na API |
| `app/services/backend_adapter.py` | metodos diversos | processos, cargas, fiscal, usuarios | delega chamadas ao repository | fachada da UI | Medio | cliente HTTP ou adapter hibrido |
| `app/services/production_repository.py` | `db_connect` | SQLite arquivo | connect, PRAGMA, timeout | conexao e concorrencia local | Critico | removido do desktop; pool SQLAlchemy na API |
| `app/services/production_repository.py` | `initialize_database` | todas as tabelas base | CREATE/ALTER/INSERT/UPDATE | bootstrap, status, admin, legado | Critico | migrations Alembic + seed controlado |
| `app/services/production_repository.py` | `authenticate` | usuarios | SELECT | login local | Alto | `POST /auth/login` |
| `app/services/production_repository.py` | `save_process` | processos, proposta_itens, historico_status, auditoria, proposta_importacoes_pdf | INSERT/UPDATE | cadastro/edicao/proposta CP00000/importacao PDF | Critico | service + transaction na API |
| `app/services/production_repository.py` | `update_status` | processos, proposta_itens, historico_status, auditoria, fiscal_* | UPDATE/INSERT | fluxo de status, cascatas, parciais, fiscal | Critico | endpoints de acao por area |
| `app/services/production_repository.py` | cargas de galvanizacao | cargas_galvanizacao, cargas_galvanizacao_itens, detalhes, retornos | SELECT/INSERT/UPDATE/DELETE | montagem, liberacao e retorno de carga | Critico | modulo `galvanization_loads` na API |
| `app/services/production_repository.py` | fiscal | fiscal_processos, fiscal_itens, fiscal_emissoes, fiscal_movimentacoes | SELECT/INSERT/UPDATE | emissao, baixa/retirada NF, status fiscal | Critico | modulo `fiscal` na API |
| `app/services/production_repository.py` | parciais/remanejamento | processos, proposta_itens, remanejamentos_itens | SELECT/INSERT/UPDATE | subprocessos parciais, pendencias, remanejamento | Critico | service transacional na API |
| `app/services/production_repository.py` | historico/auditoria | historico_status, auditoria | INSERT/SELECT | rastreabilidade | Alto | modulo `audit` centralizado |
| `app/services/operational_reports.py` | `OperationalReportsService` | processos, cargas, itens, remanejamentos | SELECT | relatorios somente leitura | Medio | endpoints de relatorios |
| `app/services/executive_dashboard.py` | `ExecutiveDashboardService` | processos, historico, fiscal, cargas | SELECT agregados | dashboard executivo | Medio | endpoints de dashboard |
| `app/services/migration_runner.py` | `apply_migrations` | schema_migrations | CREATE/SELECT/INSERT | controle de migrations SQLite | Alto | substituido por Alembic |
| `app/services/sqlite_safety.py` | validacoes | sqlite_master, PRAGMA | integridade, backup seguro | seguranca de arquivo | Medio | permanece parcialmente em ferramenta de migracao/backups antigos |
| `app/services/update_installer.py` | backup pre-update | SQLite arquivo | connect/backup | atualizacao segura | Medio | atualizar para backup via API/PostgreSQL dump |
| `scripts/generate_demo_data.py` | varias funcoes | varias tabelas | seed/dados demo | populacao de demo | Medio | script de seed via API ou PostgreSQL |
| `tests/*` | varios testes | varias tabelas | fixtures SQLite | validacao automatizada atual | Baixo | adaptar gradualmente para API e Postgres |

Contagem de chamadas SQLite no codigo ativo `app/`:

| Arquivo | execute | executescript | commit | rollback | connect | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `app/services/production_repository.py` | 229 | 1 | 21 | 8 | 2 | 261 |
| `app/services/production_core.py` | 134 | 1 | 15 | 0 | 4 | 154 |
| `app/services/backend_adapter.py` | 16 | 0 | 2 | 1 | 0 | 19 |
| `app/services/migration_runner.py` | 6 | 0 | 2 | 1 | 0 | 9 |
| `app/services/sqlite_safety.py` | 4 | 0 | 0 | 0 | 3 | 7 |
| `app/services/update_installer.py` | 2 | 0 | 0 | 0 | 1 | 3 |
| `app/services/operational_reports.py` | 2 | 0 | 0 | 0 | 0 | 2 |
| `app/services/executive_dashboard.py` | 1 | 0 | 0 | 0 | 0 | 1 |

Observacao: `production_core.py` parece ser uma versao anterior/monolitica ainda presente. O sistema ativo usa `backend_adapter.py` importando `production_repository.py`, mas `production_core.py` ainda representa risco de duplicidade conceitual e deve ser tratado antes da migracao final.

## 7. Estrutura atual do banco

Banco analisado:

```text
app/data/controle_producao.db
Tamanho: 286720 bytes
PRAGMA integrity_check: ok
PRAGMA foreign_key_check: sem violacoes
Migrations aplicadas: 8
```

Tabelas identificadas:

| Tabela | Registros | Finalidade | PK | Relacionamentos principais | Modulo |
| --- | ---: | --- | --- | --- | --- |
| `usuarios` | 1 | Usuarios, login, hash de senha, perfil legado e areas legadas | `id` | sem FK | auth/users |
| `usuario_permissoes` | 0 | Permissoes granulares por area | `id` | `usuario_id -> usuarios.id` | permissions |
| `processos` | 3 | Proposta/processo principal e subprocessos parciais | `id` | `processo_pai_id -> processos.id` | proposals/flow |
| `status_opcoes` | 27 | Catalogo de status por area | `id` | sem FK | status/system |
| `historico_status` | 22 | Historico de mudancas de status | `id` | `processo_id -> processos.id` | audit/history |
| `auditoria` | 5 | Auditoria de alteracoes de entidade/campo | `id` | sem FK | audit |
| `bloqueios_edicao` | 0 | Lock otimista/manual de edicao | `processo_id` | `processo_id -> processos.id` | concurrency |
| `configuracoes` | 1 | Configuracoes chave/valor no banco | `chave` | sem FK | system |
| `proposta_itens` | 28 | Itens de proposta, fluxo por item, peso e flags | `id` | `processo_principal_id`, `processo_atual_id -> processos.id` | proposal_items |
| `entregas_itens` | 0 | Entregas por item | `id` | processo e item | shipping |
| `remanejamentos_itens` | 0 | Remanejamento entre propostas | `id` | destino/origem/item | remanagement |
| `cargas_galvanizacao` | 0 | Cabecalho de carga de galvanizacao | `id` | sem FK | loads |
| `cargas_galvanizacao_itens` | 0 | Propostas vinculadas a carga | `id` | carga/processo | loads |
| `cargas_galvanizacao_item_detalhes` | 0 | Itens detalhados enviados/retornados em carga | `id` | carga, carga_item, processo, proposta_item | loads/returns |
| `retornos_galvanizacao` | 0 | Evento de retorno de carga | `id` | `carga_id -> cargas_galvanizacao.id` | galvanization_returns |
| `retornos_galvanizacao_itens` | 0 | Itens retornados por evento | `id` | retorno/carga/item/processo | galvanization_returns |
| `fiscal_processos` | 3 | Entrada fiscal por processo retornado | `id` | `processo_id -> processos.id` | fiscal |
| `fiscal_itens` | 19 | Itens fiscais faturaveis/faturados | `id` | fiscal/processo/item | fiscal |
| `fiscal_movimentacoes` | 6 | Movimentacoes/status fiscal | `id` | fiscal/processo | fiscal |
| `fiscal_emissoes` | 3 | Emissoes de nota/controladas | `id` | fiscal_processo | fiscal |
| `fiscal_emissao_itens` | 19 | Itens incluidos em emissao fiscal | `id` | emissao/fiscal_item | fiscal |
| `proposta_importacoes_pdf` | 0 | Metadados seguros de importacao PDF Nomus | `id` | `processo_id -> processos.id` | importacao_pdf |
| `schema_migrations` | 8 | Controle de migrations SQLite aplicadas | `id` | sem FK | migrations |

Pontos estruturais importantes:

- Datas sao armazenadas como `TEXT`, geralmente `dd/mm/yyyy` ou `dd/mm/yyyy hh:mm:ss`.
- Pesos e quantidades financeiras/operacionais usam `REAL`; em PostgreSQL recomenda-se `numeric`.
- Booleanos sao armazenados como `INTEGER` (`0/1`) ou `TEXT` (`sim/nao/indefinido`, `SIM/NAO/NAO_DEFINIDO`).
- Ha FKs relevantes, mas algumas relacoes sao historicas/duplicadas por texto, como `proposta` em `historico_status`, `fiscal_processos` e `cargas_galvanizacao_itens`.
- `auditoria.entidade_id` nao tem FK, pois referencia entidades diferentes.
- `status_opcoes` e a lista de status tambem sao mantidas no codigo, criando dupla fonte de verdade.
- `processos.proposta` possui UNIQUE e padrao validado em codigo `CP00000`.
- `proposta_itens` tem UNIQUE por `(processo_principal_id, numero_item)`.

Inconsistencias ou pontos de atencao encontrados:

- `README.md` informa Python 3.11, enquanto a arquitetura alvo define Python 3.12+ e o ambiente atual exibiu Python 3.14.6.
- `production_repository.initialize_database` ainda cria/altera tabelas alem das migrations; isso duplica responsabilidade de schema.
- `production_core.py` contem estrutura monolitica com regras parecidas com `production_repository.py`, podendo gerar divergencia se voltar a ser usado.
- O banco atual tem `usuario_permissoes` com 0 registros apesar de existir 1 usuario; a permissao admin provavelmente vem por perfil, nao pela tabela granular.
- Existem tabelas fiscais com dados e cargas/retornos/remanejamentos vazios no banco analisado; isso nao significa que nao sejam usadas, apenas que o banco atual esta com poucos dados.
- Nenhum registro orfao foi encontrado nas checagens feitas para historico, itens e fiscal.

## 8. Modulos e funcionalidades

| Modulo | Responsabilidade | Telas/arquivos | Tabelas | Operacoes | Risco migracao |
| --- | --- | --- | --- | --- | --- |
| Autenticacao | Login e sessao local | `login_dialog.py`, `backend_adapter.py`, `production_repository.py` | usuarios | autenticar, reparar admin | Alto |
| Usuarios/permissoes | Perfis e permissao por area | `user_dialog.py`, `settings_page.py` | usuarios, usuario_permissoes | criar/editar/desativar, permissoes | Alto |
| Controle Geral/propostas | Cadastro e edicao de propostas | `process_page.py`, `process_form_dialog.py` | processos, proposta_itens, historico, auditoria | criar, editar, cancelar, importar PDF | Critico |
| Itens da proposta | Itens, pesos e fluxo por item | `item_weight_dialog.py`, `item_flow_dialog.py` | proposta_itens | definir peso, produzir internamente, precisa galvanizacao | Critico |
| Producao | Fluxo produtivo e parciais | `status_dialog.py`, `batch_status_dialog.py` | processos, proposta_itens | iniciar, pausar, finalizar, finalizar parcial | Critico |
| Galvanizacao | Disponibilidade, carga e retorno | `galvanization_load_dialog.py` | cargas_*, retornos_*, processos, proposta_itens | montar carga, liberar, retornar, retorno parcial por item | Critico |
| Expedicao | Separacao, entrega, remanejamento | `status_dialog.py`, `early_remanagement_dialog.py` | processos, entregas_itens, remanejamentos_itens | separar, entregar parcial, entregar, remanejar | Critico |
| Almoxarifado | Controle de parafusos/almoxarifado | `process_page.py`, status | processos | confirmar, separar, entregar, sem parafusos | Alto |
| Fiscal | Entrada fiscal e emissao NF | `fiscal_page.py`, `fiscal_emission_dialog.py` | fiscal_* | criar entrada, emitir parcial/completa, retirar NF | Critico |
| Dashboard | Indicadores gerais e executivos | `dashboard_page.py`, `executive_dashboard_page.py` | processos, cargas, fiscal, historico | consultar, agregar, drilldown | Medio |
| Relatorios | Relatorios operacionais | `operational_reports_page.py` | processos, cargas, fiscal, itens | consultar/exportar CSV | Medio |
| Historico/auditoria | Rastreabilidade | `process_detail_dialog.py`, `data_page.py` | historico_status, auditoria | consultar e registrar eventos | Alto |
| Importacao Nomus/PDF | Ler proposta PDF/API Nomus | `proposal_import_dialog.py`, `nomus_*` | processos, proposta_itens, proposta_importacoes_pdf, configuracoes | extrair, validar, salvar metadata | Alto |
| Atualizacao | Checar release e instalar | `update_checker.py`, `update_dialog.py`, `update_installer.py` | arquivo SQLite/backups | baixar, validar hash, backup, instalar | Medio |
| Backup/banco | Backup/restauracao e integridade | `sqlite_safety.py`, `settings_page.py` | arquivo SQLite | backup, restore, integrity_check | Alto |

## 9. Operacoes por modulo

Operacoes criticas e seus efeitos atuais:

| Operacao | Origem UI | Funcao principal | Validacoes | Tabelas afetadas | Historico/auditoria | Transacao |
| --- | --- | --- | --- | --- | --- | --- |
| Login | LoginDialog | `Repository.authenticate` | usuario ativo, senha PBKDF2 | usuarios | nao | leitura |
| Criar proposta | ProcessFormDialog | `save_process` | cliente, proposta CP00000, duplicidade, datas, peso, permissao | processos, proposta_itens, historico_status, auditoria, opcional proposta_importacoes_pdf | sim | sim, rollback |
| Editar proposta | ProcessFormDialog | `save_process` | permissao controle geral, duplicidade, datas/peso | processos, proposta_itens, auditoria | sim | sim, rollback |
| Alterar status | StatusDialog/BatchStatusDialog | `update_status` | permissao por area, area disponivel, sequencia, regras parciais | processos, proposta_itens, historico_status, fiscal_* | sim | parcial, com commit final |
| Finalizar producao parcial | StatusDialog | `update_status` + `create_partial_subprocess` | nao pode parcial de parcial, itens/peso | processos, proposta_itens, historico | sim | sim |
| Montar carga | GalvanizationLoadDialog | `save_galvanization_load` | permissao, motorista, peso, itens, saldo, duplicidade em carga | cargas_galvanizacao, cargas_itens, detalhes, processos, historico | sim | commit final |
| Liberar carga | LoadManager | `release_galvanization_load` | carga aguardando liberacao e com itens | processos, cargas_galvanizacao, historico | sim | commit final |
| Retorno carga completa | LoadManager | `mark_galvanization_load_returned` | carga liberada e com itens | processos, proposta_itens, cargas, fiscal_*, historico | sim | sim, rollback |
| Retorno parcial por item | GalvanizationReturnDialog | `register_galvanization_partial_return` | carga liberada/retorno parcial, itens validos | retornos_*, detalhes, processos, fiscal_*, historico | sim | sim, rollback |
| Entrega/remanejamento | EarlyRemanagementDialog/status | `deliver_by_material_remanagement`, `remanage_material_to_production` | origem finalizada, destino valido, item_ids/observacao | processos, proposta_itens, remanejamentos_itens, historico, auditoria | sim | sim |
| Emissao fiscal | FiscalEmissionDialog | `register_fiscal_emission` | permissao fiscal, itens, quantidades/pesos | fiscal_itens, fiscal_emissoes, fiscal_emissao_itens, fiscal_movimentacoes | sim | sim |
| Relatorio operacional | OperationalReportsPage | `OperationalReportsService` | SELECT somente leitura | leitura | nao | leitura |
| Backup | SettingsPage | `backup_database`/`sqlite_safety` | integrity_check, caminho | arquivo SQLite | log tecnico | arquivo |
| Atualizacao | UpdateDialog | update services | hash SHA-256, backup pre-update | arquivo instalador, backup DB | log tecnico | fora do banco |

## 10. Regras de negocio

Regras misturadas no desktop que devem migrar para a API:

- Numeracao de proposta no padrao `CP00000` e parciais `CP00000-Pn`.
- Bloqueio de proposta duplicada.
- Permissoes por area e perfis.
- Sequencia oficial de status por area.
- Cancelamento apenas no Controle Geral.
- Proposta cancelada nao pode ser alterada fora do Controle Geral.
- Area so pode alterar status se o processo estiver disponivel naquela area.
- Producao parcial cria subprocesso parcial.
- Subprocesso parcial nao pode gerar outro subprocesso parcial.
- Status parcial nao deve encerrar a area indevidamente.
- Entrega completa de proposta parcial/pendente exige regra de remanejamento ou conclusao permitida.
- Retorno parcial de galvanizacao deve ser por item/carga, nao por simples status manual.
- Carga de galvanizacao agrupa propostas e impede envio acima do saldo disponivel.
- Itens sem necessidade de galvanizacao pulam para Expedicao.
- Almoxarifado pode ser `SEM_PARAFUSOS` e sair do fluxo do almoxarifado.
- Fiscal e criado automaticamente quando retorna da galvanizacao, exceto cenarios de remanejamento/pendencia.
- Emissao fiscal controla quantidades/pesos faturados e status dos itens.
- Historico e auditoria acompanham alteracoes criticas.

Regras que podem permanecer no cliente como validacao auxiliar, mas devem ser revalidadas pela API:

- Campos obrigatorios do formulario.
- Formato visual de datas.
- Peso numerico.
- Habilitar/desabilitar botoes por permissao.
- Filtros e ordenacao visual.

Regras exclusivamente de apresentacao:

- Cores, icones, badges e temas.
- Ordem/formatacao de colunas.
- Drill-down visual de dashboard e relatorios.
- Tamanho de dialogos e layout responsivo.

## 11. Fluxos de status

Status por area, conforme `STATUS_OPTIONS`, `STATUS_FLOW_ORDER` e `allowed_status_transitions`:

| Modulo | Status atual | Acao/proximo permitido | Condicoes | Permissao | Historico |
| --- | --- | --- | --- | --- | --- |
| Controle Geral | vazio | `NAO_LIBERADO` | cadastro inicial | control_general edit | sim |
| Controle Geral | `NAO_LIBERADO` | `LIBERADO_PRODUCAO`, `CANCELADA` | proposta ativa | control_general edit | sim |
| Controle Geral | `LIBERADO_PRODUCAO` | `CANCELADA` | cancelamento centralizado | control_general edit | sim |
| Producao | vazio | `NAO_INICIADO` | liberacao por cascata | production/control flow | sim |
| Producao | `NAO_INICIADO` | `INICIADO` | area disponivel | production edit | sim |
| Producao | `ITEM_PENDENTE_FABRICACAO` | `INICIADO` | remanejamento pendente | production edit | sim |
| Producao | `INICIADO` | `PARADO`, `FINALIZADO`, `FINALIZADO_PARCIAL` | validacao de itens/fluxo para finalizar | production edit | sim |
| Producao | `PARADO` | `INICIADO` | retomada | production edit | sim |
| Producao | `FINALIZADO_PARCIAL` | `FINALIZADO` | saldo restante | production edit | sim |
| Galvanizacao | vazio | `AGUARDANDO_ENVIO` | producao finalizada e precisa galvanizacao | galvanization edit | sim |
| Galvanizacao | `AGUARDANDO_ENVIO` | `EM_CARGA` | montagem de carga | galvanization/expedition edit | sim |
| Galvanizacao | `DISPONIVEL_PARCIAL` | `EM_CARGA` | subprocesso/parcial disponivel | galvanization/expedition edit | sim |
| Galvanizacao | `EM_CARGA` | `ENVIADO_GALVANIZACAO` | carga liberada | galvanization/expedition edit | sim |
| Galvanizacao | `ENVIADO_GALVANIZACAO` | `RETORNOU_GALVANIZACAO` | retorno completo via carga | galvanization/expedition edit | sim |
| Expedicao | vazio | `EM_SEPARACAO` | retorno da galvanizacao ou sem galvanizacao | expedition edit | sim |
| Expedicao | `EM_SEPARACAO` | `SEPARACAO_INICIADA` | inicio separacao | expedition edit | sim |
| Expedicao | `AGUARDANDO_SEPARACAO_PARCIAL` | `SEPARACAO_INICIADA` | retorno parcial/subprocesso | expedition edit | sim |
| Expedicao | `SEPARACAO_INICIADA` | `SEPARADO` | separacao concluida | expedition edit | sim |
| Expedicao | `SEPARADO` | `ENTREGUE`, `ENTREGUE_PARCIAL` | entrega completa bloqueada se parcial pendente | expedition edit | sim |
| Expedicao | `ENTREGUE_PARCIAL` | `ENTREGUE_PARCIAL`, `ENTREGUE` | entrega completa exige regras de pendencia/remanejamento | expedition edit | sim |
| Almoxarifado | vazio | `AGUARDANDO_CONFIRMACAO` | necessita almoxarifado indefinido/sim | warehouse edit | sim |
| Almoxarifado | `AGUARDANDO_CONFIRMACAO` | `EM_SEPARACAO`, `SEM_PARAFUSOS` | confirma necessidade ou marca sem parafusos | warehouse edit | sim |
| Almoxarifado | `EM_ANDAMENTO` | `EM_SEPARACAO`, `SEM_PARAFUSOS` | legado tratado como aguardando confirmacao | warehouse edit | sim |
| Almoxarifado | `EM_SEPARACAO` | `SEPARADO` | separacao almoxarifado | warehouse edit | sim |
| Almoxarifado | `SEPARADO` | `ALMOXARIFADO_ENTREGUE`, `ALMOXARIFADO_ENTREGUE_PARCIAL` | entrega almoxarifado | warehouse edit | sim |
| Almoxarifado | `ALMOXARIFADO_ENTREGUE_PARCIAL` | `ALMOXARIFADO_ENTREGUE` | conclusao restante | warehouse edit | sim |

Status finais por area:

- Controle Geral: `ENTREGUE`, `FINALIZADO`, `CANCELADA`.
- Producao: `FINALIZADO`.
- Galvanizacao: `RETORNOU_GALVANIZACAO`.
- Expedicao: `ENTREGUE`, `UNIFICADA_PRINCIPAL`.
- Almoxarifado: `ALMOXARIFADO_ENTREGUE`, `SEM_PARAFUSOS`.

Fluxos especiais:

- `FINALIZADO_PARCIAL` em producao cria subprocesso parcial.
- `DISPONIVEL_PARCIAL` aparece na galvanizacao para processo parcial.
- Retorno parcial de galvanizacao e controlado por tabelas `retornos_galvanizacao*` e detalhes por item.
- Remanejamento leva origem para `ITEM_PENDENTE_FABRICACAO`.
- `SEM_PARAFUSOS` define `necessita_almoxarifado = NAO`.

## 12. Transacoes e concorrencia

Operacoes que exigem transacao forte na API:

| Operacao | Tabelas envolvidas | Estado atual | Risco se falhar | Recomendacao API |
| --- | --- | --- | --- | --- |
| Criar/editar proposta | processos, proposta_itens, historico, auditoria, pdf_metadata | usa try/rollback em `save_process` | proposta sem itens ou historico incompleto | transacao unica |
| Alterar status | processos, historico, auditoria, fiscal, itens | varios updates e inserts | status sem cascata/historico | transacao unica por acao |
| Producao parcial | processos pai/filho, itens, historico | encadeado | parcial duplicada ou saldo incorreto | transacao com lock por processo |
| Montar/editar carga | cargas, carga_itens, detalhes, processos | commit final, sem rollback explicito no trecho principal | processo preso em carga se erro | transacao unica |
| Liberar carga | cargas, processos, historico | commit final | carga liberada sem status nos processos | transacao unica |
| Retornar carga | cargas, processos, proposta_itens, fiscal, historico | try/rollback | fiscal/status incompleto | transacao unica |
| Retorno parcial | retornos, detalhes, processos, fiscal, historico | try/rollback | item retornado sem atualizar carga | transacao unica |
| Remanejamento | origem/destino, itens, remanejamentos, historico | encadeado | origem nao volta para producao | transacao unica |
| Emissao fiscal | fiscal_itens, fiscal_emissoes, emissao_itens, movimentacoes | transacional | quantidades fiscais inconsistentes | transacao unica |
| Backup/restauracao | arquivo SQLite | copia arquivo | perda/corrupcao se em uso | substituir por backup PostgreSQL gerenciado |

Concorrencia atual:

- SQLite usa `timeout=30`, `busy_timeout=30000`, `foreign_keys=ON`.
- Journal mode: `WAL` para caminho local e `DELETE` para caminho de rede.
- Existe `bloqueios_edicao` para lock de edicao por processo.
- Em ambiente multiusuario real, SQLite em rede continua sendo risco; PostgreSQL com transacoes e locks por linha resolve melhor.

## 13. Autenticacao e permissoes

Como funciona atualmente:

- Senhas sao salvas em `usuarios.senha_salt` e `usuarios.senha_hash`.
- Hash: PBKDF2-HMAC-SHA256 com 180000 iteracoes.
- Verificacao usa `hmac.compare_digest`.
- Sessao fica em memoria no `BackendService.user`.
- Perfil `admin` tem privilegios administrativos.
- Permissoes granulares existem em `usuario_permissoes` com niveis `NONE`, `VIEW`, `EDIT`.
- Existe compatibilidade com permissao legada em `usuarios.areas_acesso`.

Pontos a centralizar na API:

- Login e emissao de token.
- Renovacao/expiracao de sessao.
- Verificacao final de permissao por endpoint.
- Politica de senha e reset.
- Auditoria de login, falhas e acoes administrativas.
- Remocao gradual de permissao baseada apenas na interface.

Riscos:

- Hoje o desktop possui toda regra de permissao e credenciais SQLite.
- Um usuario com acesso ao arquivo `.db` poderia tentar manipulacao direta.
- Em API, o desktop deve receber apenas token; credenciais PostgreSQL ficam somente no servidor.

## 14. Integracoes externas

Integracoes encontradas:

| Integracao | Onde esta | Credenciais/dados | Falhas/logs | Destino futuro |
| --- | --- | --- | --- | --- |
| Nomus API | `nomus_api_client.py`, `nomus_api_config.py`, dialogs Nomus | configuracoes locais/banco; dados de propostas/produtos | testes de client/config/importer | API backend deve fazer chamadas Nomus e proteger credenciais |
| PDF Nomus | `proposal_import/*`, `proposal_import_dialog.py` | arquivo PDF local; hash SHA-256 salvo | avisos/confirmacoes; nao salva bruto | API pode receber upload futuro, mas desktop pode extrair local inicialmente |
| Atualizacao GitHub/releases | `update_checker.py`, `update_downloader.py`, docs release | URL release, SHA-256 instalador | logs e dialogo | permanecer no desktop, mas controle de versao pode consultar API futuramente |
| Backup SQLite | `sqlite_safety.py`, `update_installer.py` | arquivo SQLite | integrity_check/backup seguro | migrar para backup PostgreSQL no servidor |
| Relatorios/exportacao | `operational_reports.py`, telas | dados operacionais; sem financeiro | readonly assertions | API de relatorios |

Pendencia: a auditoria nao confirmou uma integracao fiscal externa real; o modulo fiscal atual controla emissao internamente, mas nao foi encontrada chamada externa fiscal.

## 15. Atualizacao e instalacao

Instalacao/empacotamento:

- `ControleProducao.spec`, `Controle Producao 2.0.spec`, `Controle Producao Industel Telecom.spec`.
- `gerar_exe_pyside6.bat`, `gerar_exe_setup.bat`.
- `installer/ControleProducao.iss`.
- `setup.py` e `setup_cxfreeze.py`.

Atualizacao:

- `app/main.py` executa checagem de atualizacao antes de abrir a janela.
- `update_checker.py`, `update_downloader.py`, `update_installer.py`, `update_state.py`.
- Documentacao em `docs/PUBLICAR_RELEASE_GITHUB.md`.
- Atualizacao valida SHA-256 e cria backup antes de instalar.

Impacto na migracao:

- O atualizador precisa considerar versoes antigas que ainda acessam SQLite.
- Ao mover para API, versoes desktop antigas devem ser bloqueadas, atualizadas ou direcionadas para modo somente leitura.
- Backup pre-update de SQLite perdera relevancia quando o banco oficial for PostgreSQL.

## 16. Riscos encontrados

| Risco | Nivel | Evidencia | Impacto | Probabilidade | Mitigacao futura |
| --- | --- | --- | --- | --- | --- |
| SQL e regras concentradas no desktop | Critico | 261 operacoes SQLite em `production_repository.py` | Desktop continua autoridade dos dados | Alta | Mover regras para services da API |
| Bootstrap de schema fora de migrations | Alto | `initialize_database` cria/altera tabelas e atualiza dados | Divergencia entre migration e runtime | Media | Alembic como unica fonte de schema |
| Duplicidade `production_core.py` e `production_repository.py` | Alto | ambos contem Repository/regras/status | Manutencao confusa | Media | Definir arquivo ativo e congelar/remover legado em etapa propria |
| Permissoes verificadas no desktop | Critico | UI/BackendService chama `can_edit` local | Usuario pode contornar se tiver DB | Alta | Autorizacao obrigatoria na API |
| SQLite multiusuario/arquivo rede | Critico | `journal_mode` muda se rede | Locks, corrupcao, latencia | Media/Alta | PostgreSQL no servidor |
| Datas como texto | Alto | varias colunas `TEXT` | Ordenacao/filtro incorreto em Postgres se migrar direto | Alta | Converter para `date/timestamp` na migracao |
| Pesos e quantidades como REAL | Medio | colunas `REAL` | Arredondamento | Media | Usar `numeric` |
| Status em codigo e tabela | Alto | `STATUS_OPTIONS` + `status_opcoes` | Dupla fonte de verdade | Media | Seed/migration e enum controlado na API |
| Operacoes encadeadas sem padrao unico de rollback | Alto | alguns metodos tem try/rollback, outros commit final | Estado parcial em falha | Media | Unit of Work/transacao por endpoint |
| Integracoes Nomus no cliente | Alto | client/config local | Credencial exposta e duplicidade | Media | API executa integracao |
| Backup por copia de arquivo | Alto | SQLite file backup | Nao atende PostgreSQL | Alta | Politica de backup no servidor |
| Atualizador com banco local | Medio | update_installer cria backup SQLite | Fluxo antigo conflita com API | Media | Atualizador so atualiza app; dados no servidor |
| Versoes antigas do desktop | Alto | dist/versoes antigas e app local | Cliente antigo pode gravar direto SQLite | Alta | Plano de corte e bloqueio de versao |
| Operacoes longas na UI | Medio | importacao/retorno/relatorios com workers parciais | Travamento/interrupcao | Media | Jobs/filas na API para operacoes longas |

## 17. Regras que deverao migrar para a API

Prioridade alta:

- Autenticacao e permissao.
- Cadastro/edicao de proposta e itens.
- Validacao CP00000 e duplicidade.
- Todas as mudancas de status.
- Fluxo de parciais e subprocessos.
- Montagem/liberacao/retorno de cargas.
- Remanejamento.
- Fiscal.
- Historico e auditoria.

Prioridade media:

- Dashboards e relatorios.
- Importacao Nomus API.
- Configuracoes compartilhadas.
- Notificacoes futuras.

Pode permanecer no desktop:

- Layout, temas, icones.
- Preferencias visuais locais.
- Seletores de arquivo.
- Exportacao local, desde que os dados venham da API.
- Checagem de atualizacao do executavel.

## 18. Dados que deverao migrar para PostgreSQL

Tabelas a migrar:

- `usuarios`
- `usuario_permissoes`
- `processos`
- `proposta_itens`
- `status_opcoes`
- `historico_status`
- `auditoria`
- `bloqueios_edicao` ou equivalente de lock/sessao
- `configuracoes`
- `cargas_galvanizacao`
- `cargas_galvanizacao_itens`
- `cargas_galvanizacao_item_detalhes`
- `retornos_galvanizacao`
- `retornos_galvanizacao_itens`
- `entregas_itens`
- `remanejamentos_itens`
- `fiscal_processos`
- `fiscal_itens`
- `fiscal_movimentacoes`
- `fiscal_emissoes`
- `fiscal_emissao_itens`
- `proposta_importacoes_pdf`

Conversoes recomendadas:

- `INTEGER PRIMARY KEY AUTOINCREMENT` -> `bigserial`/identity.
- `TEXT` de data -> `date` ou `timestamp with time zone`.
- `REAL` de peso/quantidade -> `numeric(12,3)` ou criterio oficial.
- `INTEGER 0/1` -> `boolean`.
- Status textuais -> `text` com CHECK ou enums/tabelas controladas.
- `areas_acesso` legado -> migrar para `usuario_permissoes`.

## 19. Divisao sugerida dos modulos da API

| Modulo API | Responsabilidade | Tabelas | Prioridade |
| --- | --- | --- | --- |
| `auth` | login, token, sessao | usuarios | 1 |
| `users` | cadastro de usuarios | usuarios | 2 |
| `permissions` | permissao por area | usuario_permissoes | 2 |
| `proposals` | propostas/processos | processos | 3 |
| `proposal_items` | itens, pesos e fluxo por item | proposta_itens | 4 |
| `status_flow` | transicoes e catalogos de status | status_opcoes, processos | 5 |
| `production` | acoes da producao e parciais | processos, proposta_itens | 6 |
| `galvanization` | area galvanizacao | processos, proposta_itens | 7 |
| `galvanization_loads` | cargas e retornos | cargas_*, retornos_* | 8 |
| `shipping` | expedicao e entregas | processos, entregas_itens | 9 |
| `warehouse` | almoxarifado/parafusos | processos | 10 |
| `remanagement` | remanejamento de material | remanejamentos_itens, processos, itens | 11 |
| `fiscal` | entrada/emissao/retirada NF | fiscal_* | 12 |
| `audit` | historico e auditoria | historico_status, auditoria | 13 |
| `reports` | relatorios operacionais | leitura varias tabelas | 14 |
| `dashboard` | indicadores gerenciais | leitura varias tabelas | 15 |
| `nomus` | integracao Nomus/API/PDF metadata | configuracoes, proposta_importacoes_pdf | 16 |
| `system` | health, versao, configuracoes | configuracoes, schema info | 1 |

## 20. Proposta inicial de endpoints

Base: `/api/v1`

Autenticacao:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/auth/login` | autenticar usuario | publica | login/senha | token + usuario | validar ativo e senha |
| POST | `/auth/logout` | encerrar sessao | autenticado | token | ok | invalidar/registrar sessao |
| GET | `/auth/me` | dados do usuario atual | autenticado | token | usuario/permissoes | nao expor hash |

Sistema:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/system/health` | saude da API | publica/interna | - | status | nao expor segredo |
| GET | `/system/version` | versao da API e minimo desktop | autenticado | - | versoes | ajuda bloquear app antigo |
| GET | `/system/status-options` | listar status por area | autenticado | area opcional | lista | fonte oficial |

Propostas e itens:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/proposals` | listar/pesquisar propostas | view area | filtros | lista paginada | aplicar permissao |
| GET | `/proposals/{id}` | detalhe da proposta | view area | id | proposta | incluir status/itens |
| POST | `/proposals` | criar proposta | control_general edit | dados proposta/itens | proposta criada | CP00000, duplicidade, historico |
| PUT | `/proposals/{id}` | editar proposta | control_general edit | dados permitidos | proposta | auditar campos |
| GET | `/proposals/{id}/items` | listar itens | view area | id | itens | respeitar permissao |
| PUT | `/proposals/{id}/items` | substituir/editar itens | control_general edit | itens | resumo | transacao |
| PATCH | `/proposal-items/{id}/flow` | definir fluxo do item | production/control edit | produzir/galvanizar/motivo | item | validar motivo |
| PATCH | `/proposal-items/{id}/weight` | ajustar peso | production/control edit | peso | item | auditar |

Fluxo/status:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/proposals/{id}/status-options` | proximos status permitidos | view area | area | lista | regra da API |
| POST | `/proposals/{id}/status/{area}` | alterar status | edit area | status, observacao, itens/peso quando preciso | processo | cascata, historico, transacao |
| POST | `/proposals/status/batch` | alterar status em lote | edit area | area, ids, status, observacao | resultado por item | validar cada proposta |
| POST | `/proposals/{id}/cancel` | cancelar proposta | control_general edit | motivo | processo | centralizado |

Producao:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/production/{id}/start` | iniciar producao | production edit | observacao | processo | sequencia |
| POST | `/production/{id}/finish` | finalizar producao | production edit | peso/itens | processo | validar fluxo itens |
| POST | `/production/{id}/finish-partial` | produzir parcial | production edit | itens/peso/descricao | subprocesso | criar parcial |
| GET | `/production/partials` | listar pendencias/parciais | production view | filtros | lista | separar principal/parcial |

Galvanizacao e cargas:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/galvanization/candidates` | propostas disponiveis para carga | galvanization view | filtros | lista | saldo e itens |
| GET | `/loads` | listar cargas | galvanization view | filtros | lista | incluir contagem/peso |
| POST | `/loads` | montar carga | galvanization/expedition edit | motorista, peso, previsao, itens | carga | agrupar e impedir duplicidade/saldo excedido |
| PUT | `/loads/{id}` | editar carga aguardando liberacao | galvanization/expedition edit | dados carga/itens | carga | apenas aguardando |
| POST | `/loads/{id}/release` | liberar carga | galvanization/expedition edit | observacao | carga | status enviado |
| GET | `/loads/{id}/return-items` | listar itens pendentes retorno | galvanization view | - | itens | por carga/item |
| POST | `/loads/{id}/return` | registrar retorno completo | galvanization/expedition edit | observacao | carga | fiscal automatico |
| POST | `/loads/{id}/partial-return` | retorno parcial por item | galvanization/expedition edit | itens retornados | retorno | transacao |

Expedicao, almoxarifado e remanejamento:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/shipping/{id}/start-separation` | iniciar separacao | expedition edit | obs | processo | sequencia |
| POST | `/shipping/{id}/mark-separated` | marcar separado | expedition edit | obs | processo | sequencia |
| POST | `/shipping/{id}/deliver-partial` | entregar parcial | expedition edit | itens/obs | processo | nao encerrar pendencia |
| POST | `/shipping/{id}/deliver` | entregar completo | expedition edit | obs | processo | bloquear parcial sem regra |
| POST | `/remanagement/deliver-with-source` | entrega com material remanejado | expedition edit | destino, origem, itens, obs | resultado | origem volta para producao |
| GET | `/warehouse` | listar almoxarifado | warehouse view | filtros | lista | esconder finalizados |
| POST | `/warehouse/{id}/no-bolts` | marcar sem parafusos | warehouse edit | obs | processo | status `SEM_PARAFUSOS` |
| POST | `/warehouse/{id}/deliver` | entregar almoxarifado | warehouse edit | parcial/obs | processo | sequencia |

Fiscal, auditoria e relatorios:

| Metodo | Rota | Objetivo | Permissao | Entrada | Resposta | Regras |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/fiscal/processes` | listar fiscal | fiscal view | filtros | lista | somente fiscal autorizado |
| POST | `/fiscal/{id}/emissions` | registrar emissao | fiscal edit | itens, controle, obs | emissao | quantidades/pesos |
| POST | `/fiscal/{id}/invoice-withdrawal` | registrar retirada NF | fiscal/expedition edit | obs | fiscal | atualizar situacao |
| GET | `/audit/history` | historico de status | history view | filtros | lista | paginar |
| GET | `/audit/events` | auditoria tecnica | history view/admin | filtros | lista | paginar |
| GET | `/reports/operational/{type}` | relatorio operacional | operational_reports view | filtros | cards/linhas | readonly |
| GET | `/dashboard/general` | painel geral | dashboard view | filtros opcionais | indicadores | readonly |
| GET | `/dashboard/executive` | dashboard executivo | executive_dashboard view | filtros | indicadores | readonly |

## 21. Plano de migracao por modulo

| Ordem | Modulo | Dependencias | Complexidade | Risco | Alteracao no desktop | Testes minimos | Criterio de conclusao |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | Infra API base | nenhuma | Media | Medio | nenhum ou config URL | health/config | API sobe local |
| 2 | PostgreSQL + Alembic | schema auditado | Alta | Alto | nenhum | migrations em DB vazio | schema equivalente criado |
| 3 | Auth/users/permissions | usuarios | Media | Alto | login via API opcional | login/permissoes | token e permissoes iguais ao desktop |
| 4 | Leitura de propostas | processos/itens | Media | Medio | trocar listagens para API em modo piloto | filtros/paginacao | telas listam sem SQL direto |
| 5 | Historico/auditoria leitura | historico/auditoria | Baixa | Medio | telas consomem API | paginacao/filtros | historico fiel |
| 6 | Cadastro/edicao proposta | auth/permissoes | Alta | Critico | formulario salva via API | duplicidade, CP00000, itens | transacao e auditoria |
| 7 | Status simples Controle/Producao | proposals | Alta | Critico | StatusDialog chama API | sequencias/status | regras preservadas |
| 8 | Itens e fluxo por item | proposals | Alta | Critico | dialogos de itens via API | precisa galvanizacao, pesos | bloqueios corretos |
| 9 | Parciais/remanejamento | status/itens | Muito alta | Critico | fluxos via API | cenarios parciais | sem regressao |
| 10 | Cargas/retornos galvanizacao | status/itens | Muito alta | Critico | dialogos cargas via API | carga, retorno parcial | transacao completa |
| 11 | Expedicao/almoxarifado | status | Alta | Alto | acoes via API | entregas, sem parafusos | fluxo correto |
| 12 | Fiscal | cargas/retorno | Alta | Critico | fiscal via API | emissao parcial/total | itens e status consistentes |
| 13 | Dashboards/relatorios | leituras | Media | Medio | servicos trocados por API | readonly | mesmos indicadores |
| 14 | Nomus/API/PDF metadata | proposals | Media | Alto | credenciais saem do desktop | duplicidade hash | credencial protegida |
| 15 | Ferramenta SQLite -> PostgreSQL | schema final | Alta | Critico | fora do app | contagens, FKs, checks | migracao validada em homologacao |
| 16 | Corte producao | todos | Alta | Critico | desktop sem SQLite | smoke end-to-end | banco protegido |

Recomendacao de estrategia:

- Criar API inicialmente sem remover SQLite do desktop.
- Criar testes comparando respostas da API com o repository atual.
- Migrar leituras antes de escritas.
- Migrar operacoes criticas uma por vez.
- Manter feature flag/config para alternar `backend local` e `backend API` durante homologacao.

## 22. Pendencias e pontos nao confirmados

- Nao foi confirmado se `production_core.py` ainda e usado por algum fluxo ativo fora de testes/legado. A importacao ativa vista em `backend_adapter.py` usa `production_repository.py`.
- Nao foi confirmada integracao fiscal externa real; o modulo fiscal parece interno.
- Nao foi feita comparacao entre todos os bancos de backup e o banco atual.
- Foi feita execucao completa com `python -m unittest discover -s tests -v`. Resultado: 203 testes descobertos, 29 erros de importacao por dependencias ausentes no ambiente (`PySide6`, `pdfplumber`, `fitz/PyMuPDF`, `PIL`). Os testes carregados que nao dependiam dessas bibliotecas executaram sem falha funcional observada na saida.
- Nao foi confirmado ambiente oficial de Python: README diz 3.11, arquitetura alvo diz 3.12+, ambiente atual esta em 3.14.6.
- Nao foi confirmado se todas as colunas criadas dinamicamente por `initialize_database` estao refletidas nas migrations; o banco atual possui `codigo_produto` em `proposta_itens`, presente no bootstrap, mas nao evidente nas migrations listadas.
- Nao foi encontrado modulo real de chat/notificacoes persistidas; aparecem como possibilidades futuras/documentais.

## 23. Recomendacao da proxima etapa

Proxima etapa recomendada: criar a estrutura base da API sem migrar regras ainda.

Entregaveis da proxima etapa:

- Pasta `api/` conforme arquitetura oficial.
- FastAPI com `/api/v1/system/health`.
- Configuracao `.env.example`.
- SQLAlchemy configurado, mas sem portar todas as tabelas ainda.
- Alembic inicial configurado.
- Documento curto de decisoes tecnicas: autenticacao, padrao de erro, transacoes e versionamento.
- Nenhuma alteracao funcional no desktop, exceto talvez uma configuracao futura para URL da API quando chegar a hora.

Regra de ouro para a proxima etapa: primeiro criar a fundacao, depois migrar o menor fluxo de leitura possivel.
