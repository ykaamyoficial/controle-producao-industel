# Fase 1 — Réplica local SQLite: núcleo de sincronização na API

## Objetivo

Dar à API a capacidade de dizer a cada Desktop "o que mudou desde a versão N",
base da réplica local SQLite (diagnóstico em
`FASE0_REPLICA_SQLITE_DIAGNOSTICO.md`). Esta fase é só servidor: nenhum código
do Desktop consome os endpoints ainda (Fase 2).

## Implementação

- `api/app/modules/sync/models.py` — `ChangeLog` (tabela `change_log`): outbox
  com `seq` (versão global, identity), `entity`, `entity_id`, `op`
  (`upsert`/`delete`) e `changed_at`. Evento leve, sem payload.
- `api/app/modules/sync/registry.py` — `SYNC_ENTITIES`: entidades replicadas e
  a permissão exigida para cada uma (`proposals`, `proposal_items`,
  `galvanization_loads`, `galvanization_load_items`, `expedition_items`,
  `fiscal_records`, `fiscal_items`, `fiscal_invoices`, `fiscal_invoice_items`)
  e `SYNC_SCHEMA_VERSION`.
- `api/app/modules/sync/capture.py` — listeners do SQLAlchemy: `after_flush`
  anota linhas inseridas/alteradas/removidas, `before_commit` grava no
  `change_log` sob `pg_advisory_xact_lock`, `after_rollback` descarta.
  `record_change` cobre escritas fora do ORM.
- `api/app/modules/sync/service.py` + `router.py` + `schemas.py`:
  - `GET /sync/head` — `seq` atual, `min_seq_available`, `schema_version` e
    entidades permitidas ao usuário;
  - `GET /sync/changes?since=N&limit=` — eventos após `N`, colapsados por linha
    e hidratados com o estado **atual** da linha; `next_seq`, `has_more`,
    `resync_required`;
  - `GET /sync/snapshot?entity=&after_id=&limit=` — carga inicial paginada por
    `id`.
- Migration `20261006_0034_create_change_log.py` (`ADDITIVE` em
  `migration_risk_registry.json`); `EXPECTED_DATABASE_REVISION`, checksums e
  `alembic/env.py` atualizados; router registrado em `api/app/main.py`.
- Testes: `api/tests/test_sync_service.py` (unitários) e
  `api/tests/test_sync_integration.py` (PostgreSQL real).
- `api/tests/test_postgresql_integration.py`: lista de tabelas estruturais
  ganhou `change_log` e `proposal_attachments` (esta já faltava antes).

Protocolo do cliente (a implementar na Fase 2): ler `head`, baixar cada
entidade por `snapshot`, depois pedir `changes` a partir do `seq` lido no
início; em regime, repetir `changes` até `has_more=false`. `resync_required`
ou `schema_version` diferente: descartar a réplica e recomeçar.

## Garantias

1. Evento e dado são gravados na mesma transação: rollback não deixa evento, e
   não existe dado alterado pelo ORM sem evento.
2. A ordem dos `seq` é a ordem dos commits (advisory lock do INSERT até o
   COMMIT): um cliente que aplicou até o `seq` N nunca perde um evento ≤ N.
3. Reaplicar eventos é idempotente: `changes` devolve o estado atual da linha,
   nunca um delta; linha que não existe mais chega como `delete`.
4. Leituras (`GET`) não geram eventos.
5. Um usuário só recebe entidades para as quais tem permissão de visualização;
   `snapshot` de entidade não permitida ou inexistente responde 403. O cursor
   avança mesmo sobre eventos que o usuário não pode ver.
6. Cursor mais antigo que o log retido, ou à frente do banco (restauração de
   backup), recebe `resync_required=true` em vez de dados parciais.
7. Usuários, perfis, sessões, eventos de segurança, chat, anexos e tabelas
   `*_events` não são replicados.

## Validação

```
python -m compileall -q app api/app
python scripts/check_migration_checksums.py
python scripts/check_migration_safety.py
python -m pytest api/tests/test_sync_service.py api/tests/test_migration_state.py -q
python -m pytest api/tests/test_sync_integration.py -q
```

- `compileall`: sem erros. Checksums e política de risco das migrations: OK.
- Unitários de sync + estado de migration: `18 passed`.
- Integração de sync (PostgreSQL 17 descartável): `16 passed`.

Suíte da API, em duas partes, com `-o timeout=120` e PostgreSQL 17 descartável:

- arquivos até `test_proposals_integration.py`: `2 failed, 653 passed, 2 skipped`;
- demais arquivos: `1 failed, 316 passed`.

Total: **969 passed, 3 failed, 2 skipped**.

Homologação (`controle_producao_industel_dev`, cópia dos dados de produção,
migration 0034 aplicada):

| Operação | Resultado |
|---|---|
| Carga inicial completa (9 entidades) | 5 803 linhas, 3,0 MB, 1,1 s |
| `GET /sync/changes` com cliente em dia | 44 ms |

## Pendência encontrada

- **3 falhas, todas já registradas antes desta fase** (na validação da Fase 0,
  reproduzidas também no commit `0befc0a`):
  `test_app_initializes_and_serves_against_fresh_database` e
  `test_readiness_with_available_database` (503 em vez de 200) e
  `test_events_endpoint_triggers_its_own_drain_caller_never_has_to_drain_manually`.
- **Não executados:** `test_docker_release_integration.py` e
  `test_deployment_rollback_integration.py` constroem imagem Docker no
  `setUpClass`, estouram o `timeout=25` do `pytest.ini` e derrubam o processo
  do pytest.
- **`timeout=25` era insuficiente para a suíte da API:** os testes de
  concorrência de `test_proposals_integration.py` levam 6–12 s isolados e
  passavam de 25 s no meio da suíte. Medido com a captura ligada e desligada:
  sem diferença relevante, não é efeito desta fase. Resolvido em
  `api/tests/conftest.py`, que aplica 120 s aos testes de `api/tests`; o
  Desktop continua com 25 s.
- **Suíte do Desktop não executada:** nenhum arquivo de `app/` foi alterado e a
  suíte está caindo por falha de segmentação intermitente (QThread).
- **Limite conhecido:** `UPDATE`/`DELETE` em massa via Core não passam pelos
  listeners; hoje nenhum código das entidades replicadas faz isso.
- **Retenção do `change_log`** (expurgo periódico) fica para a Fase 6; até lá a
  tabela só cresce.
- **Sem aviso em tempo real:** o push por WebSocket (`/sync/ws`) é a Fase 3.
