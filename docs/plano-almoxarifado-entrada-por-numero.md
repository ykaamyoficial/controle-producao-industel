# Plano: Almoxarifado com entrada por número, abas e baixa de estoque

**Objetivo:** o Almoxarifado só mostra propostas que o Henrique digitou, em duas abas (Propostas e Itens), tira as entregues depois da baixa no estoque e mostra um contador de baixas pendentes.

**Arquitetura:** API FastAPI (módulo `proposals`) ganha filtro de visibilidade, entrada por número, baixa e rota de itens; o Desktop ganha `WarehouseAreaPage` no mesmo desenho de `ExpeditionAreaPage`. Duas colunas novas em `proposals` (migration aditiva com backfill).

**Tecnologias:** Python, FastAPI, SQLAlchemy async, Alembic, PySide6, pytest.

**Especificação:** [spec-almoxarifado-entrada-por-numero.md](spec-almoxarifado-entrada-por-numero.md) (decisões D1 a D13, sem perguntas em aberto).

**Restrições globais**
- Só API de dev (8001). Nada na oficial (8000) sem autorização explícita.
- Cada tarefa termina com testes da área passando e **commit local** (regra permanente do cérebro). Sem push.
- Mensagens de commit em português, imperativo, com `git add` por caminho. Nunca `git add -A`.
- Migration nova só passa com entrada em `api/alembic/migration_risk_registry.json` (skill `migration-check`). Telas novas seguem a skill `qt-industrial-ui`.
- Suíte do Desktop tem timeout; ao mockar `QMessageBox`, o patch vai no módulo do diálogo.

## Fatos do código que o plano usa (conferidos em 2026-11-07)

- `list_warehouse_proposals` em `api/app/modules/proposals/service.py` (~linha 555) hoje filtra `warehouse_status IN WAREHOUSE_STATUSES OR NULL`. `_warehouse_proposal_summary` (~6899) monta a linha. Rotas em `router.py` (~275 e ~287).
- `update_warehouse_status` exige `version` e grava o evento `WAREHOUSE_STATUS_CHANGED` com `metadata.previous_warehouse_status`.
- O desfazer (Fase 14, `undo.py`) já separa pistas: `lane_of` classifica por `WAREHOUSE_STATUS_CHANGED`. **Evento novo de baixa cairia na pista GERAL** e bloquearia o desfazer geral; por isso `lane_of` precisa reconhecê-lo (T4).
- Desfazer a entrada por número restaura `previous_warehouse_status = None`, ou seja, a proposta some da aba. Comportamento desejado.
- A réplica SQLite do Desktop (`app/replica`) não cobre Almoxarifado: sem teste de paridade nem espelho a manter.
- `warehouse_rows` no Desktop pede `limit=200, offset=0` fixo. Com o filtro novo a lista encolhe; manter, mas registrar o teto.
- Última migration: `20261106_0043_fiscal_invoice_cancellation.py`. A nova é `20261107_0044`.
- `warehouse_status` também é lido em `admin_correction.py` (campo editável), `remanagement_rows.py` (filha herda da mãe) e `undo.py`. Nenhum desses depende de a proposta aparecer na aba. O módulo `almox_integration` (Almox+) não usa `warehouse_status`.

## Tarefas

Ordem: T1 -> T2 -> T3 -> T4 -> T5 (API); T6 -> T7 -> T8 -> T9 -> T10 (Desktop); T11 fecha.

### T1. Migration, modelo e backfill
- Arquivos: `api/alembic/versions/20261107_0044_warehouse_stock_deduction.py` (novo), `api/alembic/migration_risk_registry.json`, `api/app/modules/proposals/models.py`.
- Produz: colunas `Proposal.warehouse_stock_deducted_at` (`DateTime(timezone=True)`, nula) e `Proposal.warehouse_stock_deducted_by_user_id` (FK `users.id`, nula, `ondelete=SET NULL`). Backfill: `UPDATE proposals SET warehouse_stock_deducted_at = now() WHERE warehouse_status = 'ALMOXARIFADO_ENTREGUE'` (decisão D12; usuário nulo). Downgrade remove as colunas.
- Registro de risco: classificar `DATA_MIGRATION` (adiciona coluna e preenche), com justificativa curta.
- Passos: escrever teste da migration (colunas existem, backfill só marca entregues) falhando; implementar; rodar `python scripts/check_migration_safety.py` e o teste; commit.
- Pronto quando: safety check passa e o backfill está testado.

### T2. Visibilidade da lista, campos de baixa e contador
- Arquivos: `service.py`, `schemas.py`, `router.py` do módulo `proposals`; `api/tests/test_warehouse_*.py` (novo).
- Interfaces: `WarehouseProposalSummary` ganha `stock_deducted: bool`, `stock_deducted_at: datetime | None`. `PaginatedWarehouseProposalResponse` ganha `pending_stock_deduction: int`. Função `_warehouse_visible_clause()` única, usada pela lista, pelo contador e pelo endpoint de itens (T5).
- Regra de visibilidade (spec): status em `EM_SEPARACAO`, `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL`, `SEM_PARAFUSOS`, ou `ALMOXARIFADO_ENTREGUE` com `warehouse_stock_deducted_at IS NULL`. Fora: `NULL`, `AGUARDANDO_CONFIRMACAO`, entregue com baixa.
- Contador (D13): `COUNT` no SQL das propostas visíveis com status `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL` ou `ALMOXARIFADO_ENTREGUE` e baixa nula; independe de `limit/offset` e do filtro de busca.
- Remover `NAO_DEFINIDO` do filtro `status` aceito (ninguém mais é "não definido" na aba). `_warehouse_sort_key` continua, sem o ramo 0.
- Passos: testes primeiro (cada status visível/oculto, contador com mais de uma página, filho nunca aparece, cancelada nunca aparece); implementar; commit.

### T3. Entrada por número
- Arquivos: `service.py`, `schemas.py`, `router.py`, `api/tests/test_warehouse_enter.py` (novo).
- Interfaces: `POST /warehouse/proposals/enter`, corpo `WarehouseEnterRequest{numbers: list[str]}` (1 a 200, normalizados: trim, sem vazios, sem repetidos, ordem preservada). Resposta `WarehouseEnterResponse{items: list[WarehouseEnterResult{number, result, proposal_id|None, message}]}`; `result` em `ENTROU | JA_NA_ABA | JA_ENTREGUE | NAO_ENCONTRADA | CANCELADA | PROPOSTA_PARCIAL`. Função `enter_warehouse_by_numbers(session, payload, actor, *, request_id)`.
- Regras: permissão igual à de `update_warehouse_status`. `ENTROU` só se status `NULL` ou `AGUARDANDO_CONFIRMACAO`; grava `EM_SEPARACAO`, `_touch`, e o evento `WAREHOUSE_STATUS_CHANGED` com `metadata={"source":"entrada_por_numero","previous_warehouse_status": <valor anterior>}` e o mesmo `request_id` por proposta. Uma transação por chamada; resultado de cada número independente. Idempotente.
- Número com espaços e maiúsculas/minúsculas: comparar normalizado, como a busca atual de propostas.
- Passos: testes (mistura de válidos, inexistente, cancelada, filha, repetida, segunda chamada igual) falhando; implementar; commit.

### T4. Baixa no estoque e pista do desfazer
- Arquivos: `service.py`, `schemas.py`, `router.py`, `undo.py`, `api/tests/test_warehouse_stock_deduction.py` (novo), `api/tests/test_proposal_undo_rules.py` (acrescentar caso).
- Interfaces: `POST /warehouse/proposals/{proposal_id}/stock-deduction`, corpo `WarehouseStockDeductionRequest{version: int, deducted: bool}`; devolve `WarehouseProposalSummary`. Eventos `WAREHOUSE_STOCK_DEDUCTED` e `WAREHOUSE_STOCK_DEDUCTION_REVERTED` (rótulos nos dois mapas de eventos de `service.py`, ~4569 e ~7150, área ALMOXARIFADO). Em lote, o Desktop chama a rota por proposta (sem rota nova).
- Regras: confirmar só com status `SEPARADO`, `ALMOXARIFADO_ENTREGUE_PARCIAL` ou `ALMOXARIFADO_ENTREGUE`; senão 409 `PROPOSAL_INVALID_STATE`. Confirmar já confirmada ou desfazer já pendente é idempotente (sem evento novo). Grava `warehouse_stock_deducted_at` e `..._by_user_id`; desfazer zera os dois. Valida `version` (`_ensure_version`) e incrementa via `_touch`.
- Pista: em `undo.py`, `lane_of` passa a devolver `LANE_WAREHOUSE` também para os dois eventos novos. A baixa não entra no desfazer da Fase 14 (o botão próprio já desfaz): sem handler, ela aparece como "não suportada" na pilha do Almoxarifado, e a pilha do GERAL não é afetada.
- Desfazer da transição de status (D14): em `undo.py`, o handler do Almoxarifado (~linha 292) passa a restaurar também `warehouse_stock_deducted_at = None` e `warehouse_stock_deducted_by_user_id = None` no `proposal_restore`, e a pré-visualização de mudanças (`FIELD_LABELS`, ~linha 89) mostra "Baixa no estoque" quando ela for zerada. Para o desfazer enxergar a baixa, a confirmação de baixa não pode virar a "última ação" da pista: o desfazer da transição de status continua sendo oferecido mesmo com baixa posterior (a baixa é anulada junto).
- Passos: testes (confirmar, desfazer, status inválido, versão velha, idempotência, `lane_of` dos eventos novos, desfazer geral não bloqueado por baixa, desfazer do status zera a baixa e o contador) falhando; implementar; commit.

### T5. Itens do Almoxarifado
- Arquivos: `service.py`, `schemas.py`, `router.py`, `api/tests/test_warehouse_items.py` (novo).
- Interfaces: `GET /warehouse/items?search&limit&offset`, resposta `PaginatedWarehouseItemResponse{items: list[WarehouseItemRow{proposal_id, proposal_number, customer_name, item_number, product_code, description, quantity, unit, total_weight, warehouse_status}], total, limit, offset}`.
- Regra: `ProposalItem.active` das propostas que passam em `_warehouse_visible_clause()` (T2); busca por proposta e por código/descrição, como em `list_expedition_items`; ordem só por ids (`Proposal.id, ProposalItem.id`) e filtro e paginação no SQL.
- Passos: testes (só itens ativos, só propostas visíveis, busca, paginação) falhando; implementar; commit.

### T6. Cliente, storage e adaptador no Desktop
- Arquivos: `app/integrations/api/proposals_client.py`, `app/services/api_proposal_storage.py`, `app/services/backend_adapter.py`, `tests/test_api_warehouse_client.py` (novo), `tests/test_api_proposal_storage.py`.
- Interfaces: `ProposalsApiClient.enter_warehouse(token, numbers)`, `.set_stock_deduction(token, proposal_id, payload)`, `.list_warehouse_items(token, **filters)`; `OfficialProposalApiStorage.warehouse_enter(numbers)`, `.warehouse_set_stock_deduction(proposal_id, version, deducted)`, `.warehouse_items_queue(filters)`; os mesmos nomes no `BackendService`. `_api_warehouse_to_process` passa a trazer `baixa_estoque` (bool) e `baixa_estoque_em`; `warehouse_rows` devolve também `pending_stock_deduction` (guardar em atributo do storage lido por `BackendService.warehouse_pending_count()`).
- Passos: testes do cliente (URL, corpo, resposta) e do mapeamento falhando; implementar; commit.

### T7. WarehouseAreaPage e aba Itens
- Arquivos: `app/ui/warehouse_items_page.py` (novo: `WarehouseItemsPage` e `WarehouseAreaPage`), `app/ui/main_window.py` (~linha 435: registrar `WarehouseAreaPage` para `"ALMOXARIFADO"` ao lado de `ExpeditionAreaPage`), `tests/test_warehouse_area_page.py` (novo).
- Interfaces: `WarehouseAreaPage(service)` com `tabs`, `proposals_page = ProcessPage(service, "ALMOXARIFADO", "Almoxarifado")`, `items_page = WarehouseItemsPage(service)`; mesmos métodos `refresh` e `deactivate_transient_modes` de `ExpeditionAreaPage`. Abas "Propostas" e "Itens" via `configure_operational_tabs(..., area="ALMOXARIFADO")`. A página de itens segue `ExpeditionItemsPage` (consulta, busca, menu "Detalhes da proposta", carregamento em worker).
- Passos: teste (duas abas, trocar de aba atualiza a página, FakeService completo para não abrir `QMessageBox`) falhando; implementar; commit.

### T8. Diálogo "Adicionar propostas"
- Arquivos: `app/ui/warehouse_enter_dialog.py` (novo), `app/ui/process_page.py` (botão visível só na área ALMOXARIFADO e com permissão de status), `tests/test_warehouse_enter_dialog.py` (novo).
- Interfaces: `WarehouseEnterDialog(service, parent)`; campo multilinha, parser `parse_proposal_numbers(text) -> list[str]` (vírgula, ponto e vírgula, espaço e quebra de linha; sem repetidos), um botão primário "Adicionar", resultado por número com selo (entrou, já estava, não encontrada...). Chama `service.warehouse_enter(numbers)` em worker; ao fechar com algo `ENTROU`, a página recarrega. Padrão de tela sobreposta da skill `qt-industrial-ui`.
- Passos: teste do parser (separadores, vazios, repetidos, 200 máx.) e do diálogo falhando; implementar; commit.

### T9. Ação "Confirmar baixa" (individual e em lote) e coluna Baixa
- Arquivos: `app/ui/action_center/provider.py` e `handlers/warehouse.py` (ação), `app/ui/action_center/batch_action_center.py` (card para ALMOXARIFADO), `app/models/process_table_model.py` (coluna/selo "Baixa"), `app/ui/process_page.py` se necessário, `tests/test_action_center.py` e `tests/test_batch_action_center.py`.
- Interfaces: `ActionDescriptor` "Confirmar baixa no estoque" (categoria primária quando o status é `SEPARADO` ou entregue sem baixa) e "Desfazer baixa" (categoria normal, quando baixada). Handler chama `service.warehouse_set_stock_deduction(proposal_id, version, deducted)`; no lote, uma chamada por proposta com relatório de sucesso e falha por número. Usar o agente `action-center-reviewer` depois de editar.
- Passos: testes (ação aparece só nos status certos; lote com uma falha no meio não derruba as outras; mock de `QMessageBox` no módulo do diálogo) falhando; implementar; commit.

### T10. Contador no cabeçalho
- Arquivos: `app/ui/process_page.py` ou `WarehouseAreaPage`, `tests/test_warehouse_area_page.py`.
- Interfaces: selo pequeno ao lado do título "Almoxarifado" mostrando `format_count_badge(n)` com `n = pending_stock_deduction`; escondido quando 0; tooltip "N propostas aguardando baixa no estoque"; atualiza em cada `refresh` e depois de baixa. Pintado em `paintEvent` (convenção do projeto), nunca via `setText`.
- Passos: teste (zero esconde, N mostra, atualiza após baixa) falhando; implementar; commit.

### T11. Fechamento
- Rodar `python scripts/check_migration_safety.py` e `python -m pytest tests api/tests -q` (sem `| tail` antes de commitar).
- Testar de ponta a ponta contra a API de dev (8001): digitar números, baixar, desfazer, conferir contador. Se algo travar a suíte, usar o agente `test-doctor`.
- Doc de fechamento `docs/architecture/FASE15_ALMOXARIFADO_ENTRADA_POR_NUMERO.md` (skill `fase-report`), commit.
- Subir a migration na API de dev só com o `maestro`/Henrique ciente; oficial só com autorização.

## Foco de revisão (a spec implica, nenhum teste óbvio cobre)

1. Entrada por número em proposta cuja `version` mudou durante a chamada (duas telas): a entrada não usa `version`; conferir que não sobrescreve um status mais avançado (só entra se NULL ou AGUARDANDO_CONFIRMACAO, dentro da transação, com a linha travada).
2. Proposta mãe em Separado com filha parcial: a filha herda `warehouse_status` da mãe (`remanagement_rows.py`) mas nunca aparece na aba nem no contador (`parent_proposal_id IS NULL`).
3. Desfazer (Fase 14) da transição de status de uma proposta que já tem baixa confirmada: decidido pelo Henrique (D14), o desfazer **zera a baixa** junto com o status, num único passo, e o contador reflete isso. Cobrir também o caso em que o status volta para `NULL` (a proposta some da aba).
4. `warehouse_rows` com teto de 200: se a aba passar disso, o contador (da API) e a lista (cortada) divergem. Registrar o teto no teste.
5. Colar números com caracteres estranhos (aspas, ponto final de e-mail, ` `) e lista com mais de 200 números.

## Autorrevisão

- Cada exigência da spec tem tarefa: abas (T7), entrada (T3, T8), propostas fora da aba (T2), entregue com baixa (T2, T4), baixa individual e em lote (T4, T9), contador (T2, T6, T10), Itens (T5, T7), backfill (T1), pista do desfazer (T4), SEM_PARAFUSOS mantido e nova transição `EM_SEPARACAO -> SEM_PARAFUSOS` (**falta tarefa**: incluir em T4 ou T2 a mudança em `WAREHOUSE_NEXT_STATUSES` com teste; adicionada abaixo).
- Nomes consistentes entre tarefas: `_warehouse_visible_clause`, `pending_stock_deduction`, `stock_deducted`, `warehouse_enter`, `warehouse_set_stock_deduction`, `warehouse_items_queue`.

**Complemento de T4:** em `WAREHOUSE_NEXT_STATUSES` (service.py ~209) acrescentar `"EM_SEPARACAO": {"SEPARADO", "SEM_PARAFUSOS"}` (decisão D11), com teste de transição permitida e de `SEPARADO -> SEM_PARAFUSOS` ainda negada.

## Execução recomendada

Pelo seu padrão de equipe, o agente `maestro` coordena: `feature-backend-implementer` faz T1 a T5, depois `feature-frontend-implementer` faz T6 a T10 usando o contrato real da API, `action-center-reviewer` revisa T9 e `test-doctor` entra se a suíte travar. T11 fica comigo. Cada tarefa termina em commit local. Tudo na API de dev.
