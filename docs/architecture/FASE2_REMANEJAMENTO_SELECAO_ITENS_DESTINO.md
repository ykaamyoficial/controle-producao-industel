# Fase 2 - Remanejamento: Selecao dos Itens da Proposta Destino

Segunda fase do plano de 7 fases do novo fluxo de Remanejamento Compensado.
Continua [[FASE1_REMANEJAMENTO_PROPOSTA_DESTINO]]: depois de escolher a
proposta destino, o usuario escolhe exatamente quais itens dela precisam
receber material e quanto de cada um - sem ainda buscar origem, sem
compensar producao e sem gravar nada.

## Servicos/modelos analisados (inventario)

- Regra de necessidade ja existente: `ItemAllocationBalance.destination_need`
  (`api/app/modules/proposals/remanagement.py:25-27`) = `max(0, requested -
  delivered - ready_available)`, calculada por `calculate_item_balance()`
  a partir de um unico item - **nao depende de uma proposta de origem**.
- `_item_allocation_balance(session, item)` (`api/app/modules/proposals/service.py:845-868`)
  ja monta esse balance para um item isolado (usada tanto por
  `compatible_remanagement_items` quanto pela fila de producao
  `_loaded_item_balance`/`_production_item_row`) - reaproveitada tal e qual,
  sem nenhuma formula nova.
- Endpoint existente `GET /shipping/remanagements/compatible-items` exige
  origem E destino (nao serve para a Fase 2, que so tem o destino). Nao havia
  nenhuma consulta readonly que devolvesse a necessidade de TODOS os itens de
  uma unica proposta destino - por isso foi criada uma consulta nova que
  **reusa a mesma funcao de balanco**, em vez de inventar uma formula.

## Como a necessidade remanejavel foi calculada sem duplicar regra de negocio

Novo `service.remanagement_destination_items(session, destination_proposal_id)`
(`api/app/modules/proposals/service.py`, logo apos `compatible_remanagement_items`):
para cada item ativo do destino, chama `_item_allocation_balance` (a mesma
funcao que a compensacao real usa) e le `.destination_need`. `already_attended`
e derivado por construcao (`requested - destination_need`), nunca calculado
por conta propria na UI. Novo endpoint readonly:

```
GET /shipping/remanagements/destination-items?destination_proposal_id=...
```

(`api/app/modules/proposals/router.py`, mesmo permissionamento
`EXPEDITION_UPDATE` do endpoint irmao `compatible-items`, por consistencia).

## Elegibilidade / bloqueio de itens

Sem regra nova: um item fica `selectable=False` somente quando
`product_code` esta vazio (`block_reason`: "Item sem codigo de produto para
busca de remanejamento.") ou `destination_need <= 0` (`block_reason`: "Item
sem necessidade pendente de remanejamento."). Itens cancelados/inativos ja
nao aparecem, pois `_active_items()` (reaproveitada) os filtra antes de
chegar na resposta - a mesma filtragem usada pelo fluxo legado.

## Quantidade parcial

`RemanagementItemSelectionStepDialog` mantem a selecao (`_checked`) e as
quantidades (`_quantities`) por `item_id`, fora da tabela - filtrar por
busca ou reconstruir linhas nunca perde a selecao. Ao marcar um item, a
quantidade "Remanejar" comeca igual a necessidade; editar o campo clampa
automaticamente para `[0, necessidade]` (nunca ultrapassa e nunca fica
negativo); `Decimal` e preservado (nenhuma conversao para inteiro).

## Arquivos criados e alterados

**API:**
- `api/app/modules/proposals/schemas.py` - `RemanagementDestinationItem`.
- `api/app/modules/proposals/service.py` - `remanagement_destination_items()`.
- `api/app/modules/proposals/router.py` - `GET /shipping/remanagements/destination-items`.
- `api/tests/test_proposals_integration.py` - 2 testes novos (necessidade +
  bloqueio por falta de codigo; proposta inexistente/cancelada).

**Desktop:**
- `app/integrations/api/proposals_client.py`,
  `app/services/api_proposal_storage.py`, `app/services/backend_adapter.py` -
  `remanagement_destination_items()` encadeado ate a API (mesmo padrao dos
  metodos de remanejamento existentes).
- `app/services/remanagement_flow_state.py` - `RemanagementItemSelection`
  (payload conceitual `RemanagementDestinationSelection` do prompt) e
  `RemanagementFlowState.item_selections`/`set_item_selections()`.
  `set_destination()` agora descarta `item_selections`/`selected_item_ids`/
  `allocations`/`simulation` sempre que o `destination_proposal_id` muda de
  fato (trocar destino nunca reaproveita item_id de outra proposta).
- `app/ui/remanagement_item_selection_dialog.py` - nova
  `RemanagementItemSelectionStepDialog` (Etapa 2).
- `app/ui/remanagement_destination_step_dialog.py` - Etapa 1 passou a aceitar
  um `RemanagementFlowState` compartilhado (`state=`) em vez de sempre criar
  o seu proprio, para que voltar da Etapa 2 preserve o destino escolhido; a
  logica de "nada selecionado na tabela" so limpa o estado se nunca houve
  destino (filtro de busca escondendo a linha nao apaga mais a selecao).
- `app/ui/process_page.py` - `open_early_remanagement_delivery` agora e uma
  pequena maquina de 3 estagios (`destination` -> `items` -> `legacy_bridge`)
  sobre um unico `RemanagementFlowState` compartilhado.
- `tests/test_remanagement_item_selection_dialog.py` - 21 testes novos.
- `tests/test_remanagement_destination_step_dialog.py` - sem mudanca de
  contagem, todos os 14 testes existentes continuam passando com o novo
  construtor.

## Nenhuma busca de origem foi antecipada

`RemanagementItemSelectionStepDialog` so chama
`early_delivery_destination_candidates` (para o cabecalho/revalidacao do
destino) e `remanagement_destination_items` (itens do destino). Nenhum
candidato de origem/Expedicao e consultado nesta fase.

## Nenhuma escrita no banco

Abrir a Etapa 2, buscar, marcar/desmarcar, editar quantidade, "Selecionar
elegiveis", "Limpar selecao" e "Buscar materiais disponiveis" apenas leem
dados e atualizam `RemanagementFlowState` em memoria. O novo endpoint da API
e `GET` puro. "Buscar materiais disponiveis" abre a ponte temporaria da
Fase 1 (tela legada) com o destino travado - a mesma ponte que ja existia,
sem nenhuma escrita nova adicionada aqui.

## Testes e resultado da suite

- `tests/test_remanagement_item_selection_dialog.py` (21) e
  `tests/test_remanagement_destination_step_dialog.py` (14): 35 passed.
- Suite completa (`pytest tests/`): 1207 passed, 2 skipped, 0 failed.
- `api/tests/test_proposals_integration.py -k destination_items` contra
  Postgres real (banco `controle_producao_test` isolado via
  `scripts/run_api_integration_tests.bat`): 2 passed.

## Atualizacao (Fase 3)

A ponte legada apos a Etapa 2 foi de fato substituida - agora fica entre a
Etapa 3 (busca automatica na Expedicao) e o fluxo legado, nao mais logo
apos a Etapa 2. `ProcessPage.open_early_remanagement_delivery` ganhou o
estagio `"availability"` entre `"items"` e `"legacy_bridge"`. Detalhes em
[[FASE3_REMANEJAMENTO_BUSCA_EXPEDICAO]].
