# Fase 15 — Almoxarifado com entrada por número, abas e baixa de estoque

Spec: `docs/spec-almoxarifado-entrada-por-numero.md` (D1 a D14). Plano: `docs/plano-almoxarifado-entrada-por-numero.md`. Desenvolvido e testado só no ambiente de dev; **nada foi aplicado na API oficial nem no banco de dev**.

## Objetivo

- A aba Almoxarifado deixa de listar toda proposta ativa: só aparece o que o Henrique digitou pelo número (entra em `EM_SEPARACAO`).
- Duas abas no topo, **Propostas** e **Itens**, no mesmo desenho de Expedição.
- Proposta entregue sai da aba somente depois da **baixa no estoque** confirmada; contador discreto das baixas pendentes no título.

## Implementação

- Migration `20261107_0044_warehouse_stock_deduction` (classificada `DATA_MIGRATION`): colunas `proposals.warehouse_stock_deducted_at` e `warehouse_stock_deducted_by_user_id`; backfill marca como baixadas as propostas já `ALMOXARIFADO_ENTREGUE`. `EXPECTED_DATABASE_REVISION` em `api/app/core/config.py` e `migration_checksums.json` atualizados.
- `api/app/modules/proposals/service.py`: `_warehouse_visible_clause()` única (lista, contador e itens); `list_warehouse_proposals` com `stock_deducted`, `stock_deducted_at` e `pending_stock_deduction` calculado no SQL; entrada por número com resultado por número (`ENTROU`, `JA_NA_ABA`, `JA_ENTREGUE`, `NAO_ENCONTRADA`, `CANCELADA`, `PROPOSTA_PARCIAL`); baixa e desfazer da baixa; transição `EM_SEPARACAO -> SEM_PARAFUSOS`.
- Rotas: `POST /warehouse/proposals/enter`, `POST /warehouse/proposals/{id}/stock-deduction`, `GET /warehouse/items`; `GET /warehouse/proposals` com os campos novos.
- `api/app/modules/proposals/undo.py`: `lane_of` classifica os eventos `WAREHOUSE_STOCK_DEDUCTED` e `WAREHOUSE_STOCK_DEDUCTION_REVERTED` na pista ALMOXARIFADO; `pick_latest` ignora grupos só de baixa; desfazer a transição de status restaura também a baixa (zera), D14.
- Desktop: `WarehouseAreaPage` e `WarehouseItemsPage` (`app/ui/warehouse_items_page.py`), `WarehouseEnterDialog` (`app/ui/warehouse_enter_dialog.py`), `CountPill` (`app/ui/components/count_pill.py`), ações de baixa no Action Center individual e em lote (`handlers/warehouse.py`, `batch_action_center.py`), coluna Baixa em `ProcessTableModel`, cliente/storage/serviço (`proposals_client.py`, `api_proposal_storage.py`, `backend_adapter.py`).
- Correções da revisão da T9: "Desfazer baixa" não é oferecido para proposta filha ou cancelada; o relatório da baixa em lote detalha por número e o diálogo não fecha quando tudo falha; testes blindados contra `QMessageBox` real.
- Fora do plano, necessário: dois testes do desfazer (`test_proposal_undo.py`) corrigidos, que já falhavam antes da fase (helper perdia `?lane=` com `params={}` no httpx 0.28; um teste pedia a pista GERAL para `WAREHOUSE_STATUS`).

## Garantias

1. Liberar uma proposta nunca a coloca no Almoxarifado; só a entrada por número (ou o status já existente) a mostra.
2. Nenhuma linha é apagada: "sumir da aba" é filtro de listagem.
3. Proposta entregue sem baixa continua na aba; com baixa confirmada, sai.
4. O contador vem da API, não da página carregada; não inclui `SEM_PARAFUSOS` nem filhas parciais.
5. Entrada por número é idempotente e independente por número; só promove proposta sem status ou em `AGUARDANDO_CONFIRMACAO`.
6. Baixa só com status `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL` ou `ALMOXARIFADO_ENTREGUE`; repetir o mesmo estado não gera evento novo.
7. Evento de baixa nunca vira "última ação" da pista geral do desfazer.
8. Desfazer a transição de status zera a baixa no mesmo passo.

## Decisões posteriores (Henrique, 2026-11-07)

1. Confirmar ou desfazer a baixa **não notifica** criador nem participantes; o evento segue no histórico e na atividade da proposta.
2. Se a correção administrativa ou o sync legado mudarem o `warehouse_status`, a baixa é zerada no mesmo passo, só quando o status realmente mudou (status igual preserva). A correção administrativa hoje não grava `warehouse_status`; a trava vale para quando gravar. O avanço normal (`SEPARADO` -> `ALMOXARIFADO_ENTREGUE`) mantém a baixa.
3. Proposta entregue com baixa sai da lista e nada será construído para isso: desfazer a baixa continua pelo Action Center ou pelo desfazer do status.

## Validação

Ambiente da API: Postgres descartável (`cp_test_pg_tmp`, porta 55440, banco `controle_test`), `APP_ENV=test`, `SECRET_KEY` de teste, `POSTGRES_TEST_DATABASE_URL` apontando só para ele.

```
python -m compileall -q app api/app                      # exit 0
python scripts/check_migration_safety.py                 # OK (conferido pelo maestro)
python -m pytest tests -q                                # 2285 passed, 21 skipped, 1 failed
python -m pytest tests/test_nomus_phase6_performance.py -q   # 3 passed
python -m pytest api/tests -q --deselect api/tests/test_replica_views_parity.py
                                                         # 1426 passed, 2 skipped, 4 failed, 4 deselected
```

- Decisões posteriores (mesmo Postgres descartável, `-p no:cacheprovider`): `test_warehouse_stock_deduction.py` + `test_proposal_undo_rules.py` = 61 passed; `test_warehouse_enter/items/list.py`, `test_notifications_service.py`, `test_proposal_undo.py` = 53 passed; depois do item 2, `test_warehouse_*.py`, `test_administrative_correction_rules.py`, `test_proposal_undo*.py`, `test_legacy_sync_integration.py`, `test_sync_service.py`, `test_remanagement_rows.py`, `test_terminal_proposal_cancellation.py`, `test_notifications_service.py` = 170 passed, 0 skipped; `test_proposals_integration.py -k "administrative or correction or sync"` = 7 passed. Testes novos: zero notificação ao confirmar e desfazer em 3 propostas seguidas (com controle que prova que o avanço de status notifica) e evento no histórico; sync legado zera a baixa só com status diferente; avanço normal mantém a baixa; correção administrativa zera (e a prévia mostra) só com status diferente; filha do remanejamento nasce sem baixa.
- Desktop: a única falha foi `test_nomus_phase6_performance.py::test_controlled_benchmark_and_load_matrix`, benchmark de tempo que estourou porque duas cópias da suíte rodaram ao mesmo tempo; sozinho passa (3 passed).
- API: falham `test_deployment_rollback_integration.py` (2), `test_docker_release_integration.py` (1), que dependem de container Docker de release ficar saudável, e `test_update_audit_router.py` (1), que o `maestro` informou já falhar em `6c7daf9`, antes da fase (não reconferido por mim). `test_replica_views_parity.py` foi deixado de fora (4 deselected): o `maestro` informou 2 falhas nele também anteriores à fase.

## Pendência encontrada

- **Nada foi testado contra a API de dev (8001)** e a migration não subiu no banco de dev; o visual (inclusive tema escuro) não foi conferido por captura; os testes de tela usam worker síncrono.
- A D14 zera a baixa sempre que um status é desfeito, mesmo se a baixa foi confirmada antes da transição desfeita (baixa em SEPARADO, depois ENTREGUE; desfazer ENTREGUE->SEPARADO zera a baixa).
- `warehouse_rows` mantém o teto de 200 linhas: acima disso o contador (API) e a lista cortada divergem (registrado em teste).
- Baixa em lote e Action Center mandam `version=None` e o serviço busca a versão atual: na prática o controle otimista fica desligado; se a consulta do estado da baixa falhar, o card some sem aviso; o lote decide por cache de seleção que pode estar velho.
- `GET /proposals/{id}` não traz `stock_deducted`; o Action Center faz uma consulta extra à lista do Almoxarifado por número ao abrir (recomendado expor o campo no detalhe).
- Parser de números separa por espaço; um número com espaço interno no banco viraria dois (banco real não conferido). Status legado fora de `WAREHOUSE_STATUSES` não aparece na aba e a entrada o trata como `JA_NA_ABA` (sem teste).
- Título do diálogo de lote sem acento ("Acoes em lote").

## Conclusão

Implementação das tarefas T1 a T10 concluída e commitada localmente (14 commits, `7fae696` a `74f05d1`), com Desktop verde e API sem falhas atribuíveis à fase. Falta validar na API de dev antes de qualquer uso real; nada vai à oficial sem autorização.
