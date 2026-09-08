# Fase 5 - Remanejamento: Motor de Compensacao

Quinta fase do plano de 7 fases do novo fluxo de Remanejamento Compensado.
Recebe um plano de alocacao (Fase 4: quais origens fornecem quanto para cada
item do destino) e calcula o plano de compensacao determinístico - para cada
unidade de material pronto que muda de origem para destino, uma obrigacao
equivalente muda de destino para origem. Nenhuma escrita no banco.

## Nota sobre a Fase 4 (atualizada)

O prompt desta Fase 5 foi recebido antes do da Fase 4, entao o motor foi
implementado como um servico standalone que aceita o contrato de alocacao
(`destination_item_id` + `[source_proposal_id, source_item_id,
allocated_quantity]`) diretamente pelos IDs, sem depender de nenhuma tela -
exatamente o "backend/servico oficial deve ser capaz de recalcular o plano a
partir dos IDs e quantidades" pedido na secao 4 daquele prompt. A Fase 4 foi
implementada depois (ver [[FASE4_REMANEJAMENTO_ALOCACAO_ORIGENS]]) e monta
`RemanagementFlowState.allocations` exatamente nesse formato - o motor
descrito abaixo nao precisou de nenhuma mudanca para ser consumido por ela.
A Fase 6 (ver [[FASE6_REMANEJAMENTO_REVISAO_SIMULACAO_CONFIRMACAO]]) passou a
consumir esse motor de fato: `_load_compensation_snapshots` (o carregamento
de saldo desta funcao) foi extraida para ser reaproveitada por
`simulate_remanagement_review` sem duplicar a leitura de saldo.

## Regra de remanejamento existente reaproveitada (inventario)

- `_item_allocation_balance`/`calculate_item_balance` (Fases 1-3): mesmo
  calculo de saldo, usado para a necessidade do item destino
  (`destination_need`) e o saldo pronto da origem (`ready_available`).
- `items_are_compatible` (`remanagement.py:83-98`): mesma regra oficial de
  correspondencia (codigo, unidade, galvanizacao, produce_internally,
  flow_defined) chamada diretamente pelo motor novo via
  `items_are_compatible(source_snapshot, destination_snapshot)` - os
  snapshots tem exatamente os atributos que essa funcao espera, entao nao ha
  reimplementacao da regra, apenas reuso com objetos leves.
- `apply_remanagement` (`service.py:1035+`), mecanismo real ja existente:
  cria `ProductionAllocationTransfer(from_item=destination_item,
  to_item=source_item, quantity=qty)` - **a obrigacao sai do item destino
  (`from`) e vai para o item origem (`to`)**. O novo `FutureMutationPlan`
  espelha exatamente essa direcao em `production_obligation_transfers`
  (`from_item_id`=destino, `to_item_id`=origem) sem executar nada.
- Decisao deliberada: **nao foi feito refactor de `apply_remanagement`** para
  extrair as regras de "status previsto apos a transferencia" (que la sao
  condicionais internas acopladas a mutacao real do ORM). A secao 29 do
  prompt torna isso condicional ("o motor PODE calcular predicted_status SE
  o dominio ja possuir funcoes puras de derivacao") - como essas funcoes nao
  existem separadamente hoje, e duplicar a logica arriscaria divergir do
  caminho de escrita real ja testado, o `FutureMutationPlan.status_recalculations`
  apenas **lista os itens/propostas afetados**, sem prever o status exato -
  a frase da secao 16/17 ("status devera ser recalculado futuramente
  conforme as regras atuais") foi lida como descritiva, nao como pedido de
  previsao antecipada.

## Arquivos criados e alterados

- **`api/app/modules/proposals/compensation.py`** (novo) - motor puro, sem
  I/O: `ItemSnapshot`, `RequestedItem`, `Allocation`, `CompensationLine`,
  `CompensationProduct`, `CompensationError`, `FutureMutationPlan`,
  `CompensationPlan`, `assert_quantity_conservation()`,
  `build_compensation_plan()`, `CompensationInvariantViolation`.
- **`api/app/modules/proposals/service.py`** -
  `build_remanagement_compensation_plan(session, payload)`: carrega o
  destino e revalida cada item pedido contra a necessidade atual (mesmo
  clamp da Fase 3), carrega os itens de origem citados nas alocacoes em lote
  (`_batch_item_allocation_balances`, ja criada na Fase 3 - zero N+1), monta
  os `ItemSnapshot` e chama o motor puro.
- **`api/app/modules/proposals/schemas.py`** -
  `RemanagementCompensationRequest`/`RemanagementCompensationPlanResponse` e
  tipos auxiliares (`CompensationTransfer`, `CompensationProductPlan`,
  `CompensationPlanError`, `FutureMutationPlanOut`).
- **`api/app/modules/proposals/router.py`** -
  `POST /shipping/remanagements/compensation-plan` (mesma permissao
  `EXPEDITION_UPDATE` dos demais endpoints de remanejamento; nunca chama
  `session.commit()`).
- **Desktop** (`app/integrations/api/proposals_client.py`,
  `app/services/api_proposal_storage.py`, `app/services/backend_adapter.py`)
  - `remanagement_compensation_plan()` encadeado ate a API, mesmo padrao dos
  metodos anteriores. Nenhuma tela nova.

## Como a obrigacao pendente do destino foi resolvida

Nao foi criada nenhuma coluna nova. `ItemSnapshot.available_for_transfer` do
item **destino** e a mesma `destination_need` ja calculada pela Fase 2/3
(`_item_allocation_balance`); do item **origem** e o mesmo `ready_available`
usado desde a Fase 1. O motor puro so compara/soma esses dois numeros - a
"obrigacao" nunca ganha uma representacao paralela.

## Equivalencia 1:1 garantida

Cada `CompensationLine` nasce de uma unica `qty` (`ready_quantity_to_destination
== obligation_quantity_to_source` por construcao, nunca dois valores
calculados separadamente). `assert_quantity_conservation()` e uma funcao
isolada e testável que revalida essa igualdade linha a linha e o total do
plano, e lanca `CompensationInvariantViolation` se algo divergir - defesa
explicita pedida na secao 26, nao apenas "confianca na construcao".

## Varias origens / varios produtos / cobertura parcial

- Multiplas `Allocation` para o mesmo `destination_item_id` geram uma
  `CompensationLine` por origem, cada uma preservando `source_item_id`
  (secao 20/21) - a obrigacao devolvida a cada origem e exatamente o que ela
  forneceu, nunca redistribuída.
- Cada `product_code` e resolvido de forma independente (chave e o
  `destination_item_id`, nao apenas o codigo, entao dois itens destino com o
  mesmo codigo nunca se misturam).
- `coverage` por produto: `COMPLETE` quando `allocated_quantity >=
  requested_quantity`, `PARTIAL` caso contrario (a diferenca fica em
  `remaining_quantity` e gera warning; nenhuma linha ficticia e criada para
  o restante).

## Codigos/unidades incompativeis

Bloqueados via `items_are_compatible` (codigo `PRODUCT_INCOMPATIBLE`, com a
mensagem original da funcao - "mesmo codigo de produto", "mesma unidade",
etc.) e, separadamente, itens de origem pendentes de galvanizacao
(`requires_galvanization == "SIM"`) via `OPERATIONAL_STATE_NOT_SUPPORTED` -
a mesma exclusao ja aplicada por `compatible_remanagement_items` desde a
Fase 3.

## Impactos futuros sem gravacao

`CompensationPlan.future_mutations` (`FutureMutationPlan`) descreve, em
listas simples de dicts, o que a Fase 7 tera que aplicar:
`expedition_ready_transfers` (pronto que muda de origem para destino),
`production_obligation_transfers` (obrigacao que muda de destino para
origem, mesma direcao de `ProductionAllocationTransfer`),
`status_recalculations` (quais itens/propostas precisarao ter status
recalculado) e `movement_records` (previa dos registros de auditoria). Nada
disso e persistido nesta fase.

## Nenhuma entrega, nenhuma escrita

O motor nunca importa nada de entrega/fiscal; nao chama `session.commit()`
em nenhum caminho; `build_compensation_plan` e uma funcao pura (dataclasses
`frozen=True`, sem efeito colateral).

## Testes

- **`api/tests/test_remanagement_compensation.py`** (19, puro Python, sem
  banco): conservacao (uma origem, varias origens, varios produtos,
  violacao detectada), correspondencia (codigo/unidade/galvanizacao/origem
  igual ao destino/origem nao pertence a proposta alegada), cobertura
  completa/parcial/vazia, parcial-dentro-do-item, multiplas
  origens/produtos, direcao do `FutureMutationPlan`. Executam junto com os 7
  testes existentes de `test_compensated_remanagement.py` sem conflito (26
  passed).
- **`api/tests/test_proposals_integration.py`** (4 novos, contra Postgres
  real): origem unica conserva quantidade; cobertura parcial com duas
  origens; codigo incompativel e origem=destino bloqueados; alocacao acima
  do saldo real da origem (nao apenas do que o cliente alegou) e bloqueada.
  **Nao foi possivel executa-los desta vez**: a suite de migrations do
  banco de teste isolado (`controle_producao_test`) esta falhando ao aplicar
  a revisao mais recente por um indice duplicado
  (`ix_proposals_parent_proposal_id` ja existe), um problema anterior/
  paralelo a este trabalho, nao relacionado a remanejamento. Os 4 testes
  estao escritos e prontos; ficam bloqueados ate essa migracao ser
  corrigida.

## Resultado da suite

- Motor puro + regressao do modulo de remanejamento existente: 26 passed.
- `python -m py_compile` e importacao direta de `compensation.py`,
  `schemas.py`, `service.py`, `router.py`: sem erros.
- Suite de integracao contra Postgres real: bloqueada nesta rodada por uma
  migracao com indice duplicado, nao relacionada a esta fase (ver acima).
