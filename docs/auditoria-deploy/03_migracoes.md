# 03 — Auditoria de migrações Alembic e risco de dados

Data: 2026-11-19. Branch `logistica-melhorias` (HEAD `c1d31a3`). Produção não foi tocada.

**Veredito:** as 9 migrações novas (0039 a 0047) estão sãs. A cadeia é linear, os checksums e o registro de risco estão OK, o upgrade e o downgrade funcionam e o schema final bate com os modelos. Nenhum achado técnico bloqueia o deploy. O ponto fraco é o **rollback**: depois de migrar, a imagem anterior da API não sobe sobre o schema novo. Antes do deploy, corrija os 5 itens marcados "corrigir antes" (versão da imagem e procedimento).

## Onde foi testado

- Banco descartável: container próprio `postgres:16` (16.14), em `127.0.0.1:55499`, sem volume (tmpfs), banco `audit_mig_test_<timestamp>`. O container foi removido no fim. O banco de dev do projeto e o do outro agente não foram usados.
- Revisão de produção usada como alvo: **`20261014_0038`** (provável, não confirmada). Fontes: `docs/plano-migracao-api-servidor.md:224` (virada de 2026-11-04) e o head da `main` (`git ls-tree main` termina em 0038). Confirme no SERVIDOR antes (ver P1).

## Verificações (saída real)

| Verificação | Resultado |
| --- | --- |
| `alembic heads` | 1 head: `20261109_0047` (pai `20261108_0046`) |
| `alembic branches` | vazio (sem ramificação) |
| `alembic history` | 48 revisões lineares, 48 arquivos, 48 chaves no registro de risco. Sem órfãs (`20260813_0010` tem nome fora de ordem, mas está encadeada entre 0020 e 0021). |
| Branches locais | `inspecao-datas` e `integracao-almox` têm um prefixo da mesma cadeia, com conteúdo idêntico. Sem revisão conflitante. |
| `python scripts/check_migration_checksums.py` | `Checksums das migrations OK.` (exit 0). Nenhuma migração antiga foi alterada em relação à main. |
| `python scripts/check_migration_safety.py` | `Politica de risco das migrations OK.` (exit 0) |
| `upgrade base -> head` (do zero) | OK, 6,77 s |
| Downgrade passo a passo, 0047 até 0038 | todos OK: 0047 0,20 s · 0046 0,15 · 0045 0,14 · 0044 0,24 · 0043 1,43 · 0042 0,14 · 0041 0,16 · 0040 0,16 · 0039 0,23 |
| Upgrade passo a passo, 0038 até 0047 (com dados semeados) | todos OK: 0,16 · 0,27 · 0,19 · 0,25 · 0,32 · 0,21 · 0,17 · 0,18 · 0,14 s |
| Uma chamada só, 0038 → 0047 / 0047 → 0038 | 0,29 s / 0,89 s (banco quase vazio; produção tem 103 MB, então espere segundos, não minutos) |
| Schema do upgrade do zero × schema após o ciclo down/up (`pg_dump -s`) | 3011 linhas, **0 diferenças** |
| Schema em 0038 após o downgrade × 0038 criado do zero | **0 diferenças** |
| Autogenerate (modelos × banco), com o app inteiro importado | **0 diferenças** |
| Backfill 0044 | `AUD-1:ALMOXARIFADO_ENTREGUE:true, AUD-2:...:false, AUD-3:NULL:false` |
| Backfill 0043 | `100:CANCELADA:linha cancelada, 200:REGISTRADA:-` (só a NF "fantasma" mudou) |
| Default 0041 | `requires_inspection` = `false` em todas as propostas existentes |
| Downgrade 0043 com número de NF reutilizado | `BLOQUEADO -> Downgrade bloqueado: numero reutilizado apos cancelamento ... [('500', '1')]`, e a revisão permanece em 0047 |
| `evaluate_rollback_schema_compatibility(0038 -> 0047)` | `compatible=True ... 9 migration(oes) ... nenhuma DESTRUCTIVE` |
| pytest (fresh/upgrade, migration_state, warehouse, fiscal cancel, checksums, safety), `--timeout=300` | `39 passed`. Sem `SECRET_KEY` deu `1 failed` (`503 != 200`, ver A12); com uma chave aleatória descartável deu 39 passed. |

## O que cada migração nova faz

| Revisão | O que faz | Classe no registro | Risco para os dados de produção |
| --- | --- | --- | --- |
| 0039 | cria `inspections` e `inspection_events`; adiciona as permissões `inspection.*` ao admin (`ON CONFLICT DO NOTHING`) | ADDITIVE | nenhum (tabelas novas) |
| 0040 | cria `logistics_loads`, `logistics_logs`, `logistics_log_items` (índice único parcial) e `logistics_events`; adiciona as permissões `logistics.*` | ADDITIVE | nenhum |
| 0041 | `proposals.requires_inspection` boolean NOT NULL default false | ADDITIVE | baixo: no PG16 o default não reescreve a tabela |
| 0042 | troca o CHECK de `inspections.stage` (aceita `pendente`) | TRANSITIONAL | nenhum (a tabela nasce vazia) |
| 0043 | `fiscal_invoices.cancelled_at/by/reason` + FK; **UPDATE**: NF REGISTRADA sem nenhuma linha ativa vira CANCELADA; troca a UNIQUE por índice único parcial | TRANSITIONAL | **altera dados fiscais existentes** (A4) |
| 0044 | `proposals.warehouse_stock_deducted_at/by` + FK; **UPDATE**: as entregues recebem `now()` | DATA_MIGRATION | grava a data do deploy, não a data real (A5) |
| 0045 | datas e observação de Inspeção (4 colunas nullable) | ADDITIVE | nenhum (datas da Fase 16) |
| 0046 | `departed_on`, `delivered_on`, `delivery_proof_link` (nullable) | ADDITIVE | nenhum |
| 0047 | `logistics_logs.stage_occurred_on` e `logistics_events.occurred_on/note` (nullable) | ADDITIVE | nenhum (peso/Logística da Fase 17) |

Sobre "produção já ter dados nas colunas novas": em 0038 essas tabelas e colunas não existem. Se alguém tiver criado alguma à mão, o `CREATE TABLE`/`ADD COLUMN` falha e a transação inteira reverte (`env.py:52-55`, DDL transacional). As inserções de permissão são idempotentes. Não há DROP, ALTER TYPE ou NOT NULL sem default nos upgrades.

## Achados

| # | Severidade | Arquivo:linha | Achado | Evidência |
| --- | --- | --- | --- | --- |
| A1 | corrigir antes | `api/app/database/health.py:45` (igual na main), `api/app/modules/system/service.py:43,93`, `api/Dockerfile:84-85`, `docker-compose.servidor.yml:9-11`, `app/services/compatibility_check.py:65-75` | **Só voltar a imagem não funciona.** A API anterior exige a revisão exata `20261014_0038` (`MINIMUM = EXPECTED`). Sobre o banco em 0047, `/health/ready` e `/system/compatibility` respondem 503, o container fica unhealthy, o `cloudflared` depende de `service_healthy` e o Desktop bloqueia (fail-closed). | `git show main:api/app/database/health.py`: `if revision == EXPECTED_DATABASE_REVISION: return "compatible"`; main tem `EXPECTED_DATABASE_REVISION = "20261014_0038"` |
| A2 | corrigir antes | `api/app/deployment/schema_compatibility.py:64-79`, `api/app/core/config.py:21` | O avaliador de rollback libera 0038 → 0047 (`compatible=True`) porque só olha DESTRUCTIVE. Ele não considera que a release anterior tem `MINIMUM_DATABASE_REVISION = EXPECTED`. Na prática, o rollback "permitido" sobe uma API que não fica pronta (A1). | saída real na tabela de verificações |
| A3 | corrigir antes | `api/app/core/config.py:10,14` | `API_VERSION` continua `0.11.0`, igual à produção, mas a revisão esperada mudou de 0038 para 0047. Se a imagem nova sair com a tag `0.11.0`, ela sobrescreve a imagem de rollback. Backups e estado de deploy ficam ambíguos. | `git show main:api/app/core/config.py` → `API_VERSION = "0.11.0"`, `EXPECTED ... "20261014_0038"` |
| A4 | corrigir antes (procedimento) | `api/alembic/versions/20261106_0043_fiscal_invoice_cancellation.py:34-54`, `:65-74` | Muda dados fiscais reais: as NFs REGISTRADA com todas as linhas canceladas passam a CANCELADA. O downgrade **não** devolve esse status. O downgrade também **aborta** se algum número de NF já tiver sido reutilizado depois do deploy. Conte as NFs afetadas antes e faça backup. | backfill `100:CANCELADA`; downgrade `BLOQUEADO ... [('500', '1')]` |
| A5 | pode depois (ciência) | `20261107_0044_warehouse_stock_deduction.py:30-32` | Todas as propostas `ALMOXARIFADO_ENTREGUE` recebem a baixa com a data/hora do deploy (decisão D12), sem usuário. Não é a data real e não se desfaz linha a linha. | `AUD-1:...:true`, as demais `false` |
| A6 | corrigir antes (procedimento) | `api/alembic/env.py:52-55` | As 9 migrações rodam numa **única transação**, sem `lock_timeout`. Ela segura ACCESS EXCLUSIVE em `proposals` e `fiscal_invoices` (e trava `users` pelas FKs) até o fim. Com a API ligada, um ALTER pode esperar uma transação aberta e enfileirar tudo atrás dele. Pare a API antes de migrar. | 0,29 s em banco vazio; não há `lock_timeout` no repo (grep) |
| A7 | corrigir antes (procedimento) | `20261020_0039...py:98-107`, `20261020_0040...py:131-140`, `20261021_0042...py:31`, 0045-0047 `downgrade()` | O downgrade perde dados: apaga as tabelas de Inspeção/Logística, remove as permissões `inspection.*`/`logistics.*` e os vínculos com **todos** os perfis, reescreve `pendente` como `cadastro` e derruba as colunas de datas. Ele também precisa ser rodado com a **imagem nova**, porque a antiga não tem os arquivos 0039-0047 e não acha a revisão 0047. | downgrade passo a passo OK; schema 0038 idêntico ao do zero |
| A8 | pode depois | `api/alembic/env.py:12-22` | `env.py` não importa `api/app/modules/chat/models.py`. Um `alembic revision --autogenerate` proporia **remover as 5 tabelas do chat** e 10 índices. Hoje nenhum script usa autogenerate (`scripts/api_revision_dev.bat:7`). | diff com os imports do env.py: 15 itens (`remove_table:chat_messages`, ...); com o app inteiro: 0 |
| A9 | pode depois | `scripts/check_migration_safety.py:18-29` | O linter não detecta `DROP CONSTRAINT`, `CREATE UNIQUE INDEX` nem `UPDATE` de dados. Em 0042 ele não acusou nada; em 0043/0044 só acusou `ADD_UNIQUE_OR_FK`. As classificações manuais estão corretas, então a falta não esconde nada hoje. | flags reais: 0042 `[]`, 0043 `['ADD_UNIQUE_OR_FK']`, 0044 `['ADD_UNIQUE_OR_FK']` |
| A10 | pode depois | `docs/architecture/DATABASE_MIGRATIONS.md:166-167` | O doc mostra `EXPECTED/MINIMUM = 20260810_0015`; o valor real é `20261109_0047`. O restante do doc (política, scripts) continua válido. | `api/app/core/config.py:14` |
| A11 | pode depois | `api/tests/test_migrations_fresh_and_upgrade.py:76-82` | O teste "fresh" exige `SECRET_KEY` no ambiente e, sem ela, dá 503 em `/system/ready`. É uma questão de ambiente de teste, não bug de migração. | `AssertionError: 503 != 200` sem a chave; 39 passed com a chave |

## Rollback: resposta direta

- **A imagem anterior roda no schema novo?** Pelo conteúdo, sim: todas as mudanças são aditivas para o código antigo (colunas nullable/default, tabelas que ele ignora, índice parcial menos restritivo que a UNIQUE antiga). **Mas ela se recusa a ficar pronta**, por causa da checagem de revisão exata (A1). Na prática, o rollback só de código derruba o sistema.
- **Quais migrações quebram o rollback?** Nenhuma é DESTRUCTIVE para o código antigo. Quem quebra é a trava de revisão. Pelo lado dos dados, só 0043 (status CANCELADA irreversível, downgrade bloqueado se o número for reutilizado) e 0044 (data do deploy) não voltam ao estado exato.
- **Recomendação:**
  1. **Falhou antes de alguém usar as telas novas** (minutos): rode `alembic downgrade 20261014_0038` **com a imagem nova** e suba a imagem anterior. Foi testado: o schema volta idêntico ao 0038. Fica só a mudança de status das NFs fantasma, que é válida para o CHECK antigo.
  2. **Já entrou dado novo** (Inspeção/Logística, cancelamento de NF): prefira **corrigir para frente** (imagem nova corrigida, sem downgrade). O downgrade apaga esses dados, e o restore do backup apaga tudo desde o deploy.
  3. **Restore de backup** só em caso de dado corrompido, e por decisão do Henrique (mesma regra do `plano-migracao-api-servidor.md:200`).
  4. Emergência não testada: `alembic stamp 20261014_0038` mantém o schema novo e deixa a imagem anterior ficar pronta. Para voltar depois, é preciso `stamp 20261109_0047`, não `upgrade`. Só faça com decisão explícita.

## Ordem segura de migração em produção

1. **Checagem somente leitura no SERVIDOR** (o Henrique roda; nada é alterado):
   ```sql
   SELECT version_num FROM alembic_version;                              -- esperado 20261014_0038
   SELECT to_regclass('inspections'), to_regclass('logistics_logs');     -- esperado NULL, NULL
   SELECT count(*) FROM roles WHERE code = 'admin';                      -- esperado 1
   SELECT count(*) FROM fiscal_invoices fi
    WHERE fi.status = 'REGISTRADA'
      AND EXISTS (SELECT 1 FROM fiscal_invoice_items i WHERE i.fiscal_invoice_id = fi.id AND NOT i.active)
      AND NOT EXISTS (SELECT 1 FROM fiscal_invoice_items i WHERE i.fiscal_invoice_id = fi.id AND i.active);  -- NFs que virarão CANCELADA
   SELECT count(*) FROM proposals WHERE warehouse_status = 'ALMOXARIFADO_ENTREGUE';  -- recebem a baixa com a data do deploy
   ```
2. Gere a imagem nova com **tag nova** (ex.: 0.12.0) e confirme que a imagem `0.11.0` atual continua no SERVIDOR (A3).
3. Avise os usuários e **pare só a API** (`postgres` fica no ar). O túnel cai junto, porque depende da API.
4. **Backup** `pg_dump -Fc` com sha256, uma cópia fora do SERVIDOR se já estiver disponível e, de preferência, um restore de teste num banco descartável.
5. **Migre com a imagem nova:** `docker compose ... run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"`. É uma transação única: ou aplica tudo, ou nada.
6. Confira: `alembic current` = `20261109_0047`; NFs CANCELADA novas = contagem do passo 1; propostas com `warehouse_stock_deducted_at` preenchido = entregues do passo 1.
7. Suba a API nova: `/health/ready` 200, login no Desktop, smoke nas telas de Inspeção, Logística e Fiscal.
8. Em caso de falha, siga a árvore de rollback acima.

## Perguntas ao Henrique

- **P1.** A produção está mesmo em `20261014_0038`? Rode a primeira query do passo 1. Nenhuma das 0039-0047 foi aplicada no banco oficial?
- **P2.** A migração 0043 vai marcar como CANCELADA as NFs que já tinham todas as linhas canceladas (a contagem sai da query acima). Está de acordo?
- **P3.** A baixa automática das propostas já entregues com a data do deploy (D12, migração 0044) continua valendo?
- **P4.** Se algo der errado depois que o pessoal já lançou dados de Inspeção/Logística, você prefere corrigir para frente (mantém os dados) ou voltar o backup (perde tudo desde o deploy)?
- **P5.** Qual número de versão a API nova recebe (A3)? Pode ser 0.12.0?
- **P6.** A cópia externa do backup ainda está pendente (`plano-migracao-api-servidor.md:222`). Aceita fazer o deploy só com o backup local?
- **P7.** A migração dá as permissões novas só ao perfil admin. Quais outros perfis precisam de `inspection.*` / `logistics.*` logo no primeiro dia?
