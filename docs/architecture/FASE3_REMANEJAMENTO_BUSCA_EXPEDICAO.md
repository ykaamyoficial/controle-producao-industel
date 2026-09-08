# Fase 3 - Remanejamento: Busca Automatica na Expedicao

Terceira fase do plano de 7 fases do novo fluxo de Remanejamento Compensado.
Recebe o `destination_proposal_id` da Fase 1 e os itens/quantidades da
Fase 2 e descobre automaticamente, somente leitura, quais outras propostas
tem saldo pronto compativel na Expedicao - o operador nao escolhe mais a
origem manualmente, o sistema apresenta onde ela existe.

## Como o saldo de Expedicao e calculado hoje (inventario)

- `ItemAllocationBalance.ready_available` (`api/app/modules/proposals/remanagement.py:17,25-27,54`)
  = `max(0, available_quantity - delivered_quantity - remanaged_quantity)`
  de um unico item, sem depender de nenhuma outra proposta - a mesma
  formula que a Fase 3 usa como "saldo disponivel de origem" (secao 6 do
  prompt), sem nenhuma coluna nova.
- `_item_allocation_balance(session, item)` (`service.py:846-869`) e o
  wrapper assincrono existente que le `item.expedition_item` e soma
  `ProductionAllocationTransfer` para montar esse balanco - reaproveitado
  tal e qual, item a item, para os itens do **destino** (revalidacao de
  necessidade) e em lote para os **candidatos** de origem.
- `items_are_compatible(source_item, destination_item)` (`remanagement.py:83-98`)
  - mesma regra oficial de compatibilidade (product_code, unit,
  requires_galvanization, produce_internally, flow_defined) ja usada pela
  gravacao real (`_evaluate_remanagement`) - reaproveitada sem alteracao. A
  exclusao de item com `requires_galvanization == "SIM"` como origem
  (`compatible_remanagement_items`) tambem foi preservada.
- `_proposal_operational_clause()`/`_sync_expedition_from_available_items()`
  (`service.py:120-126`, `2033+`) - mesmo filtro "proposta ativa e nao
  cancelada" e mesma sincronizacao de itens prontos ja usados por
  `list_expedition_proposals`, chamados antes da busca em lote.

## Servico novo, sem N+1

`find_remanagement_sources(session, payload)` (`service.py`, logo apos
`remanagement_destination_items`) e o contrato readonly da Fase 3:

1. Carrega o destino, revalida cada `destination_item_id` pedido (pertence
   ao destino? tem `product_code`?) e reclampa `requested_quantity` contra a
   necessidade **atual** (`_item_allocation_balance` do item destino) -
   nunca confia cegamente no valor que a Fase 2 mandou.
2. Roda `_sync_expedition_from_available_items` (mesma sincronizacao das
   telas de Expedicao existentes).
3. Uma unica consulta em lote (`select(ProposalItem).join(Proposal)...
   where(func.upper(product_code).in_(codes)).where(proposal_id !=
   destino)...`) traz todos os candidatos de todos os codigos pedidos de
   uma vez - nao ha um `SELECT` por item nem por proposta.
4. `_batch_item_allocation_balances()` (novo) e a versao em lote de
   `_item_allocation_balance`: as mesmas 3 agregacoes sobre
   `ProductionAllocationTransfer`, mas com `GROUP BY item_id` /
   `item_id.in_(...)` em vez de uma consulta por item - continua chamando a
   mesma `calculate_item_balance()` pura, so troca "uma consulta por item"
   por "uma consulta para todos os itens".
5. Agrupa por `product_code`, filtra cada grupo pelo `items_are_compatible`
   do item destino especifico (preserva rastreabilidade quando dois itens
   do destino compartilham o mesmo codigo), ordena por saldo disponivel
   decrescente e calcula `total_available`/`coverage_status`
   (`SUFICIENTE`/`PARCIAL`/`SEM_DISPONIBILIDADE`).

Endpoint: `POST /shipping/remanagements/availability` (`router.py`) -
POST por ter corpo estruturado (lista de itens), mas nunca chama
`session.commit()`; mesma permissao `EXPEDITION_UPDATE` dos endpoints
irmaos de remanejamento (Fase 1/2 ja seguem essa mesma convencao).

## Desktop

- `app/services/remanagement_flow_state.py` - `RemanagementSourceCandidate`,
  `RemanagementItemAvailability` e `RemanagementFlowState.availability`/
  `set_availability()`. Mudar a selecao de itens (Fase 2) ou o destino
  (Fase 1) descarta a disponibilidade anterior, forcando nova busca.
- `app/ui/remanagement_availability_dialog.py` -
  `RemanagementAvailabilityStepDialog`: busca dispara sozinha ao abrir
  (sem campo de busca obrigatorio), um grupo por item do destino (codigo,
  descricao, solicitado, tabela de candidatos ou estado vazio, total e
  cobertura), botao "Atualizar" readonly, "Avancar para alocacao" so
  habilita se pelo menos um item tiver candidato.
- `ProcessPage.open_early_remanagement_delivery` - a maquina de estados
  ganhou o estagio `"availability"` entre `"items"` e `"legacy_bridge"`:
  destino -> itens -> disponibilidade -> ponte legada, com "Voltar"
  encadeado entre as quatro telas sobre o mesmo `RemanagementFlowState`.

## Nenhuma alocacao antecipada

A tela nao tem checkbox de origem, campo de quantidade por candidato nem
botao de sugestao - exatamente como a REGRA DE ESCOPO pede. "Avancar para
alocacao" apenas continua para a ponte temporaria da Fase 1 (tela legada),
que ja faz sua propria escolha de origem/mapeamento sem depender dos
candidatos desta tela; a Fase 4 e quem vai consumir
`RemanagementFlowState.availability` de fato.

## Testes

- `tests/test_remanagement_availability_dialog.py` (14): busca automatica
  sem input extra, payload da requisicao, grupos/estado vazio, rotulos de
  cobertura, erros de carregamento (destino sumiu, sem itens, falha do
  servico), Voltar sem escrita, Avancar, atualizar refaz a busca.
- `api/tests/test_proposals_integration.py` (4 novos, contra Postgres real
  via `controle_producao_test`): correspondencia por codigo + ordenacao por
  saldo + exclusao do proprio destino + cobertura parcial; saldo zerado
  apos entrega total exclui o candidato; dois produtos geram grupos
  independentes e a quantidade pedida acima da necessidade real e
  clampada; validacao de destino inexistente/cancelado e item que nao
  pertence ao destino.
- Suite completa de dialogos de remanejamento (`test_remanagement_*dialog*.py`,
  49 testes) roda limpa em conjunto.

## Atualizacao (Fase 4 e Fase 5)

A ponte legada apos a Etapa 3 foi de fato substituida pela Etapa 4 (tela de
alocacao manual/sugestao automatica) - ver
[[FASE4_REMANEJAMENTO_ALOCACAO_ORIGENS]]. O motor de compensacao da Fase 5
(que consome o plano da Etapa 4) ja existe como servico standalone desde
antes - ver [[FASE5_REMANEJAMENTO_MOTOR_COMPENSACAO]]; a ponte legada agora
fica entre a Etapa 4 e o fluxo legado, ate a Fase 6 ter uma tela propria de
revisao/confirmacao.
