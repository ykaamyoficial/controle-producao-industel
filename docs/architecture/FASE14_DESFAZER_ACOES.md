# Fase 14 — Desfazer a última ação de uma proposta

## Objetivo

Permitir que a pessoa que errou desfaça a **última ação** de uma proposta (v1), sem apagar
histórico: o desfazer é um novo evento de auditoria, não uma edição do passado.

Decisões fechadas:

- Quem pode: o **autor** da ação **ou** um superusuário, sempre com a **permissão da ação
  original**. Sem permissão nova e **sem migration**.
- Só a **última** ação (pilha, LIFO por `request_id`). Um grupo que já contém `ACTION_UNDONE`
  nunca é candidato.
- Cancelar proposta fica fora do desfazer.
- Desfazer a liberação **não avisa o Almox+**; a conciliação horária acerta o estado.
- Ações sem inverso seguro (remanejamento, concluir itens, galvanização/cargas — inclusive
  encerrar carga —, entrega, NF, atualizar proposta) ficam `undoable=false` com texto de
  alternativa.
- Sem desfazer em lote.

## Implementação

### API — `api/app/modules/proposals/`

- `undo.py`: agrupa os eventos por `request_id`, escolhe o último grupo candidato e executa o
  handler inverso. Endpoints em `router.py`:
  - `GET /api/v1/proposals/{id}/undo/candidate`
  - `POST /api/v1/proposals/{id}/undo` — corpo com `extra=forbid`: `expected_version`,
    `target_request_id`, `reason` (1–1000) e `idempotency_key` (8–100); devolve `ProposalDetail`.
- Handlers desfazíveis, com a classe de reversão e a permissão exigida:
  - `RELEASE_PROPOSAL` (C, `PROPOSALS_CHANGE_STATUS`)
  - `WAREHOUSE_STATUS` (A)
  - `START_PRODUCTION`, `PAUSE_PRODUCTION`, `RESUME_PRODUCTION` (A, `PRODUCTION_UPDATE`)
  - `START_SEPARATION` e `SEPARATE_ITEMS` (B, `EXPEDITION_UPDATE`)
- Snapshots `previous_*` passam a ser gravados nos eventos originais (`service.py`): liberar,
  status do almoxarifado, iniciar/pausar/retomar produção, iniciar separação e separar itens.
  Ações antigas sem snapshot de liberar, iniciar produção e iniciar separação ficam
  `undoable=false`; pausar, retomar e status do almoxarifado funcionam também em eventos antigos.
- Auditoria: evento `ACTION_UNDONE` com o `request_id` do POST e metadata `undone_request_id`,
  `undone_events`, `handler`, `reason`, `idempotency_key`, `expected_version`,
  `resulting_version` e snapshots antes/depois. Entra em `_NOTIFY_PROPOSAL_EVENTS`. O desfazer
  incrementa `proposal.version`.
- `schemas.py`: o Histórico ganha `undone` e `undone_by_event_id`.
- `admin_correction.py`: a correção administrativa ignora eventos desfeitos.
- `api/app/core/error_codes.py`: códigos `UNDO_*`.
- Ordem de validação do POST: idempotência → `UNDO_ACTION_NOT_FOUND` (404) →
  `UNDO_ALREADY_UNDONE` (409) → `UNDO_NOT_LATEST` (409, `details.latest_request_id`) →
  `PROPOSAL_VERSION_CONFLICT` (409) → permissão (403) → `UNDO_NOT_SUPPORTED` (409) →
  `UNDO_BLOCKED` (409, `details.blockers`). Reuso da chave com conteúdo diferente:
  `UNDO_IDEMPOTENCY_CONFLICT` (409).
- Bloqueios (`blockers`): `PROPOSAL_CANCELLED`, `STATE_CHANGED`, `PRODUCTION_ALREADY_STARTED`,
  `ITEM_CHANGED`.

### Desktop

- `app/integrations/api/proposals_client.py`, `app/services/api_proposal_storage.py` e
  `app/services/backend_adapter.py`: `undo_candidate` e `undo_last_action`, preservando
  `error_code` e `details` da API.
- `UndoActionProvider` (`app/ui/action_center/provider.py`, handler em
  `app/ui/action_center/handlers/undo.py`): embrulha o provider existente e acrescenta o card
  "Desfazer última ação" na categoria ATTENTION, fora de `PRIMARY_ACTION_KEYS`. O card some se o
  GET falhar e aparece também com `can_undo=false` para explicar o motivo.
- `UndoActionDialog` (`app/ui/action_center/undo_dialog.py`): mudanças antes/depois, avisos e
  bloqueios, motivo obrigatório, um único botão primário "Desfazer", `idempotency_key` `uuid4`,
  erros em linha via `UNDO_ERROR_MESSAGES`, sem `QMessageBox`. Ícone reaproveita `AppIcons.HISTORY`.
- `app/ui/process_detail_dialog.py`: botão ghost "Desfazer última ação" nos Detalhes da proposta,
  só quando há um único `process_id`; recarrega os Detalhes ao desfazer.
- `app/ui/process_detail/historico_tab.py`: linha desfeita riscada, em cor discreta, com
  "Desfeita" na coluna Status e sem botão por linha.

### Documentação

- `docs/architecture/ALMOX_INTEGRATION.md`: nota de que desfazer a liberação não avisa o Almox+.

### Commits

`dafd340` (API), `06640f8` (nota Almox+), `2fccbea` (cliente/serviço Desktop), `035d5c9`
(diálogo e card), `87e6138` (botão nos Detalhes), `e64893a` (Histórico).

## Garantias

1. Só a última ação da proposta pode ser desfeita; um grupo já desfeito, ou que é ele mesmo um
   `ACTION_UNDONE`, nunca é candidato.
2. Só o autor da ação ou um superusuário desfaz, e sempre com a permissão da ação original.
3. O histórico nunca é apagado: o desfazer grava `ACTION_UNDONE` apontando o `request_id`
   desfeito, e a linha original é marcada `undone`.
4. Versão desatualizada (`expected_version`) não desfaz: devolve `PROPOSAL_VERSION_CONFLICT`.
5. Se o estado mudou depois da ação, a produção já começou, a proposta foi cancelada ou um item
   mudou, o desfazer é bloqueado (`UNDO_BLOCKED`) e nada é alterado.
6. Ação sem snapshot ou sem inverso seguro fica `undoable=false`; nunca é revertida por
   aproximação.
7. A mesma `idempotency_key` repete o resultado; com conteúdo diferente, falha com
   `UNDO_IDEMPOTENCY_CONFLICT`.
8. Cancelar proposta não é desfazível.
9. Nenhuma migration nem permissão nova; `scripts/check_migration_safety.py` continua OK.
10. Nenhuma execução desta fase tocou a API oficial (8000).

## Validação

Backend, com PostgreSQL efêmero e descartável (já removido; testes de integração exigem
`APP_ENV=test` e `POSTGRES_TEST_DATABASE_URL`):

- `api/tests/test_proposal_undo.py` + `api/tests/test_proposal_undo_rules.py` → **63 passed**.
- Suítes vizinhas de propostas → **187 passed, 1 skipped**.
- `python scripts/check_migration_safety.py` → **OK**.

Desktop:

- `tests/test_undo_api_client.py` → 9 testes; `tests/test_undo_dialog.py` → 32 testes.

Suíte oficial final (sem banco):

- `python -m pytest tests api/tests -q --timeout=25` → **3151 passed, 462 skipped, 0 failed**
  em 1030 s. Os 462 skipped são 441 testes de integração PostgreSQL da API e 21 do Desktop.
  **Nesta execução final os testes de integração do desfazer foram pulados**; os 63 passed
  acima vêm da rodada com banco efêmero.

## Pendências e riscos

- **Dev:** a API de dev (8001) ainda não roda o código novo. O fluxo nunca foi testado contra a
  API real nem na GUI real; não há screenshot nos temas claro/escuro nem em 1366x768.
- **Almox+:** o comportamento do webhook ao desfazer a liberação não foi testado contra o
  Almox+ real; depende da conciliação horária.
- **Concorrência:** dois POST simultâneos para a mesma proposta não foram testados.
- **Abas ainda sem tratamento:** `fluxo_tab` e `fiscal_entrega_tab` continuam lendo linhas
  desfeitas como eventos normais.
- **Desempenho:** o GET do candidato é síncrono na thread da UI ao abrir a Central de Ações
  (um request a mais por abertura).
- **Autor do grupo:** é o primeiro `actor` não nulo dos eventos do grupo.
- **Teste instável sob carga:** `test_nomus_phase6_performance` (benchmark Nomus) falhou sob
  carga em uma rodada intermediária do Desktop; passou isolado e na suíte final.
- **Liberação na oficial** depende de autorização explícita e do checklist `release-checklist`.
