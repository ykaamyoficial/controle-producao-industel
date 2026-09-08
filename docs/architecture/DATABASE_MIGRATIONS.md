# Migrations Seguras e Compatibilidade do Banco (Fase 04)

Política para evoluir o schema PostgreSQL sem obrigar todos os Desktops e todas as
instâncias da API a atualizarem no mesmo instante. Constrói sobre a infraestrutura
Alembic já existente (`api/alembic/`) — nenhum mecanismo paralelo foi criado.

## Mecanismo oficial

- **Ferramenta**: Alembic (`api/alembic/env.py`, `api/alembic/versions/`), já em uso
  desde a Fase inicial de migração para PostgreSQL. Async-only, lê `DATABASE_URL` via
  `api.app.core.config.get_settings()`.
- **Revisão aplicada**: sempre lida da tabela `alembic_version` (gerenciada pelo
  próprio Alembic), nunca escrita por código de aplicação. Leitura read-only em
  `api/app/database/health.py::database_check()`/`current_database_revision()`.
- **Revisão esperada**: `api.app.core.config.EXPECTED_DATABASE_REVISION` — mantida
  manualmente, mas conferida contra o head real do Alembic por
  `api/tests/test_migration_state.py::test_script_head_matches_expected_database_revision_constant`
  (falha se alguém esquecer de atualizá-la ao adicionar uma migration).
- **Execução**: manual, fora do processo da API (`scripts/run_api_migrations.bat`).
  A API **nunca** roda `alembic upgrade` no próprio startup (confirmado: nenhum
  código em `api/app/main.py`, `api/Dockerfile` ou `docker-compose.dev.yml` dispara
  migration automaticamente) — e esta fase não altera isso.
- **Histórico imutável**: uma vez aplicada em qualquer ambiente compartilhado, uma
  migration nunca é editada. Correção = nova migration. Isto já era aplicado desde o
  incidente documentado em
  [`API_MIGRATION_STABILITY_AND_REPLICA_VALIDATION.md`](API_MIGRATION_STABILITY_AND_REPLICA_VALIDATION.md)
  (migration `0002` congelada); esta fase estende a regra a todo o histórico e a
  reforça com verificação automatizada (ver abaixo).

## Classificação obrigatória de migrations

| Classe | Exemplos | Risco | Regra |
| --- | --- | --- | --- |
| `ADDITIVE` | tabela nova, coluna nullable, coluna com `server_default`, índice | Baixo | Permitida na mesma release |
| `TRANSITIONAL` | dual-write, backfill, constraint validada depois, alargamento de CHECK | Médio | Exige plano expand/migrate |
| `DESTRUCTIVE` | `DROP`, rename definitivo, tipo incompatível, `NOT NULL`/`UNIQUE` sem pré-validação | Alto | Não executar na primeira release |
| `DATA_MIGRATION` | backfill/transformação de dados, DML puro | Variável | Idempotência + validação |

Toda migration — nova ou já existente — precisa de uma entrada em
[`api/alembic/migration_risk_registry.json`](../../api/alembic/migration_risk_registry.json)
com `classification` + `justification`. Isso é **obrigatório e verificado
automaticamente**: `scripts/check_migration_safety.py` escaneia o corpo de
`upgrade()` de cada migration à procura de padrões de risco (sem parser SQL, de
propósito) e falha se:

- a migration não tiver entrada no registro;
- a entrada não tiver `justification`;
- a migration contiver um padrão de risco mas estiver classificada `ADDITIVE`.

Padrões sinalizados hoje: `DROP TABLE`, `DROP COLUMN`, rename de coluna/tabela,
`ALTER ... TYPE`, `SET NOT NULL` (via `alter_column(..., nullable=False)` — loosening
para `nullable=True` não é sinalizado, é sempre seguro), `ADD UNIQUE`/`ADD FOREIGN
KEY` e `TRUNCATE`. **Isto é um sinalizador para revisão humana, não um veredito
automático** — o linter não entende se uma tabela está vazia ou se o `UNIQUE` é
seguro; alguém precisa ler e escrever a justificativa.

Rodar localmente: `python scripts/check_migration_safety.py`. Testado por
`tests/test_migration_safety_policy.py`.

### Achados do inventário desta fase (migrations históricas, não alteradas)

Duas migrations já aplicadas contêm padrões que a política desta fase proíbe para
migrations **novas**. Não foram reescritas (histórico imutável — ver acima); estão
documentadas no registro de risco como `DESTRUCTIVE` com justificativa completa:

- **`20260720_0005`** (make proposals official): `TRUNCATE proposal_items,
  proposals, sync_runs` incondicional + `ALTER COLUMN proposal_items.description
  SET NOT NULL` sem backfill de guarda. Aplicada antes do lançamento oficial do
  módulo de Propostas (tabelas vazias em produção nesta janela).
- **`20260807_0014`** (response requests and notes): `UNIQUE (user_id, message_id,
  notification_type)` em `chat_notifications` sem query de validação de
  duplicidade prévia. Tabela nova (criada dias antes, em `20260801_0011`) e de
  baixo volume na data de aplicação.

Nenhuma das duas causou problema conhecido em produção; ambas violam a disciplina
que esta fase estabelece **daqui para frente**. Migrations novas que repetirem
esses padrões devem ser bloqueadas em revisão de código.

## Estratégia EXPAND → MIGRATE → CONTRACT

Toda mudança potencialmente incompatível é planejada em releases separadas —
nunca condensada:

1. **EXPAND** (release A): adiciona a nova estrutura sem remover a antiga.
2. **MIGRATE** (release B): a aplicação passa a usar a nova estrutura; backfill/
   dual-read/dual-write quando necessário.
3. **CONTRACT** (release C ou posterior): remove a estrutura antiga **somente**
   depois de comprovado que nenhum consumidor (Desktop antigo, API anterior em
   janela de rollback) depende dela.

### Exemplo: renomear `clientes.nome` → `clientes.razao_social`

```
Release A: + razao_social NULL, backfill de nome -> razao_social, mantém nome
Release B: API nova lê razao_social (fallback opcional para nome durante a transição)
Release C: confirma ausência de consumidores antigos, remove nome
```

### Exemplo: tornar uma coluna `NOT NULL`

```
1. adicionar coluna nullable
2. popular valores existentes (backfill)
3. validar que não existem NULL
4. atualizar a aplicação para sempre preencher
5. somente depois aplicar NOT NULL
```

### Exemplo: mudança de tipo incompatível

Usar coluna nova + migração controlada quando `ALTER TYPE` puder perder
informação, bloquear a tabela ou quebrar consumidores antigos. Nunca converter
silenciosamente valores inválidos; validar intervalo/formato antes; documentar se
a operação exige janela de manutenção.

## Pré-condições e pós-condições (migrations de risco médio/alto)

Antes de uma migration `TRANSITIONAL`/`DESTRUCTIVE`/`DATA_MIGRATION`, validar (via
query dentro da própria migration, com `op.get_bind()`/`op.execute`, antes do DDL de
risco):

- revisão atual é exatamente a esperada (o próprio Alembic já garante isso via
  `down_revision`);
- tabela/coluna de origem existe quando exigida;
- dados cumprem os requisitos da transformação;
- não existem duplicidades antes de criar `UNIQUE`;
- não existem `NULL` antes de `NOT NULL`;
- FKs existentes não têm órfãos;
- a migration não está sendo aplicada duas vezes (Alembic já impede isso via
  `alembic_version`, mas DML idempotente — `ON CONFLICT DO NOTHING`/`DO UPDATE` —
  deve ser usado quando a migration também insere dados).

Depois de qualquer migration: head/revisão esperada foi registrada, schema
esperado existe, constraints críticas estão válidas, contagens/relações essenciais
não sofreram perda inesperada, nenhum registro órfão foi criado, e a aplicação
consegue inicializar modelos/queries básicas contra o novo schema (verificado nos
testes de upgrade — ver abaixo).

## Transações, rollback e downgrade

`api/alembic/env.py` já roda cada migration dentro de `context.begin_transaction()`
(DDL transacional do PostgreSQL) — se uma migration falhar, a transação inteira
reverte, `alembic_version` **não avança**, e o banco permanece no estado anterior,
utilizável. Isto foi comprovado com uma migration real, propositalmente quebrada,
em `api/tests/test_migrations_fresh_and_upgrade.py::MigrationFailureAtomicityTests`
(ver seção de testes).

**Rollback de migration não é rollback de backup.** Não force `downgrade()` para
toda migration — para alterações com perda de dados, um downgrade automático pode
ser mais perigoso que manter o schema novo:

| Política | Significado |
| --- | --- |
| `REVERSIBLE` | `downgrade()` tecnicamente seguro (a maioria das migrations aditivas atuais) |
| `FORWARD_FIX_ONLY` | corrigir com uma nova migration, não com downgrade |
| `RESTORE_REQUIRED` | retorno exige restauração de backup (Fase 05) |

Toda migration nova classificada `DESTRUCTIVE` deve declarar explicitamente qual
das três políticas se aplica ao seu `downgrade()`.

## Dependência entre servidor e schema

`api.app.core.config`:

```python
EXPECTED_DATABASE_REVISION = "20260810_0015"  # revisao que este server_version espera
MINIMUM_DATABASE_REVISION = "20260810_0015"   # revisao mais antiga que este server_version ainda opera
```

Hoje os dois valores são iguais porque nenhuma migration foi desenhada ainda com
tolerância retroativa deliberada (esta é a primeira fase a estabelecer essa
disciplina). `MINIMUM_DATABASE_REVISION` só deve ser reduzido (apontar para uma
revisão mais antiga que `EXPECTED_DATABASE_REVISION`) quando uma release futura
publicar uma migration comprovadamente aditiva o suficiente para o servidor operar
corretamente nos dois lados da janela de rollback.

`api/app/core/migration_state.py` conecta esse conceito ao mecanismo real do
Alembic (via `ScriptDirectory`, sem numeração artificial paralela):

```python
from api.app.core.migration_state import build_migration_state

state = build_migration_state(current_revision)
# state.current_revision, state.expected_head_revision,
# state.is_at_head, state.migration_history_consistent
```

`migration_history_consistent` é `False` quando a revisão aplicada no banco não
corresponde a nenhum arquivo de migration conhecido (sinal forte de divergência
entre o histórico esperado e o banco real — Seção 11 do prompt). Esta fase **não**
liga `MigrationState` a nenhum endpoint público nem ao gate de `/system/ready`
(que continua com a comparação exata já existente) — é uma capacidade interna
preparada para as fases de health check/pipeline futuras, sem acoplamento
prematuro.

## Compatibilidade com API anterior (janela de rollback)

Ao revisar uma migration nova, avaliar também contra a última API de produção
anterior (quando a estratégia de deploy permitir rollback de container):

- evitar remover colunas que a API anterior consulta;
- evitar renomear tabelas/colunas publicamente usadas sem transição;
- evitar mudar o significado de um campo existente sem transição;
- preferir adicionar campos/tabelas novas e manter as antigas durante a janela de
  rollback.

## Como criar uma nova migration

1. `scripts/api_revision_dev.bat` (ou `alembic revision -m "..."` a partir de
   `api/`) gera o arquivo com `revision`/`down_revision` corretos.
2. Escreva `upgrade()`/`downgrade()` seguindo EXPAND → MIGRATE → CONTRACT quando a
   mudança não for puramente aditiva.
3. Adicione uma entrada em `api/alembic/migration_risk_registry.json` (chave =
   `revision`) com `classification` e `justification`.
4. Rode `python scripts/check_migration_safety.py` — deve terminar OK.
5. Rode `python scripts/check_migration_checksums.py --update` para registrar o
   checksum da migration nova (mecanismo já existente, que impede editar a
   migration depois).
6. Atualize `EXPECTED_DATABASE_REVISION` em `api/app/core/config.py` para o novo
   head.
7. Se a mudança for aditiva o suficiente para ser tolerada por versões anteriores
   do servidor durante um rollback planejado, avalie também atualizar
   `MINIMUM_DATABASE_REVISION`.
8. Se `test_only_structural_tables_exist` (em `api/tests/test_postgresql_integration.py`)
   precisar de ajuste (tabela nova/removida), atualize a lista esperada.

## Como testar fresh e upgrade

Os testes de migration exigem um PostgreSQL descartável e são pulados (`skipped`)
sem ele — nunca rodam contra um banco de produção:

```bash
export APP_ENV=test
export POSTGRES_TEST_DATABASE_URL="postgresql+asyncpg://usuario:senha@host:porta/algum_nome_com_test"
python -m pytest api/tests/test_migrations_fresh_and_upgrade.py api/tests/test_postgresql_integration.py -q
```

O guard de segurança (`api/tests/_migration_test_support.py::integration_enabled`,
espelhando `test_postgresql_integration.py`) exige `APP_ENV=test` **e** que a
palavra `test` apareça no nome do banco — impossível apontar por acidente para um
banco de produção.

- `FreshDatabaseMigrationTests`: `downgrade base` → `upgrade head`, confere o head
  esperado e que a aplicação consegue responder `/system/ready`.
- `UpgradeFromEarlierRevisionTests`: sobe até a revisão imediatamente anterior à
  mais recente, insere dados representativos com SQL cru (schema daquele ponto do
  histórico), aplica o restante da cadeia e confere que os dados sobreviveram, que
  o backfill das colunas novas (`weight_source`/`weight_status`) ficou correto, e
  que a API atual consegue consultar o resultado via ORM.
- `MigrationFailureAtomicityTests`: copia o diretório real de migrations para uma
  pasta temporária, acrescenta uma migration propositalmente quebrada por cima do
  head real, tenta aplicá-la e confirma que a transação reverte por completo (a
  tabela que ela criava não sobrevive) e que `alembic_version` não avançou.
- `BackwardCompatibilityDetectionTests`: faz downgrade para uma revisão anterior à
  esperada e confirma que `/system/ready` e `/system/compatibility` respondem 503
  (nunca operam silenciosamente com schema desatualizado).
- `scripts/compare_api_schema_paths.py`: compara o schema final de um upgrade
  direto (`downgrade base` → `upgrade head`) com o de um upgrade progressivo
  (revisão por revisão, `0001` → `0015`) — atualizado nesta fase para cobrir toda
  a cadeia (antes só ia até `0005`). Confirmado manualmente nesta fase:
  `Schemas equivalentes: Sim`.

## Quando uma remoção antiga finalmente pode ser feita

Uma coluna/tabela em fase `CONTRACT` só deve ser removida quando, **todos**:

1. já se passou pelo menos uma release completa desde o `MIGRATE` (Desktops e
   instâncias de API antigos tiveram tempo de atualizar);
2. `MINIMUM_DESKTOP_VERSION`/`MINIMUM_DATABASE_REVISION` (Fases 01/03/04) já não
   incluem mais nenhuma versão que dependa da estrutura antiga;
3. não há nenhuma consulta (Desktop, API, relatório, script de suporte) que ainda
   leia a coluna/tabela antiga;
4. a remoção em si é uma nova migration `DESTRUCTIVE`, com justificativa e
   revisão humana — nunca silenciosa.

## Fora de escopo desta fase

Backup automático pré-deployment (Fase 05), restauração automática de backup,
GitHub Actions de produção, Docker pull/deploy automático, rollback automático de
container, Updater.exe, download de releases, maintenance mode administrativo
completo, execução automática de migrations no servidor de produção, janela de
deployment ou agendamento.
