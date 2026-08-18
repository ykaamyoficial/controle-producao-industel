# Fase 4 - Remanejamento: Alocacao das Propostas de Origem

Quarta fase do plano de 7 fases do novo fluxo de Remanejamento Compensado
(implementada apos a Fase 5, a pedido do usuario - o motor de compensacao ja
existia como servico standalone e passa a ser alimentado pelo plano real
gerado aqui). Recebe os candidatos encontrados na Etapa 3 e deixa o usuario
decidir, por item do destino, quanto retirar de cada origem - manualmente ou
via sugestao automatica - sem transferir nada ainda.

## O que foi implementado

- **`app/services/remanagement_allocation.py`** (novo) - `AllocationCandidate`,
  `SuggestedAllocation`, `suggest_allocation()`: heuristica pura (secao 13/34
  do prompt) - ordena por saldo decrescente, desempata por
  `(source_proposal_id, source_item_id)`, consome o maior candidato primeiro
  e para assim que a necessidade e coberta. Sem solver, sem otimizacao
  combinatoria - exatamente o pedido de "estrategia simples, previsivel e
  explicavel". Nunca ultrapassa `requested_quantity` nem
  `available_quantity` de nenhum candidato (garantido por construcao e
  coberto por 8 testes puros).
- **`app/services/remanagement_flow_state.py`** - `RemanagementSourceAllocation`,
  `RemanagementItemAllocation` (com `allocated_quantity`/`remaining_quantity`/
  `status` como properties derivadas, nunca campos soltos que possam
  divergir) e `RemanagementFlowState.set_allocations()`. Tambem ganhou
  `availability_from_api()`, extraida da Etapa 3 para ser reaproveitada pela
  Etapa 4 (que tambem pode refazer a busca da Fase 3 via "Atualizar
  disponibilidade") sem duplicar a conversao payload -> dataclass.
- **`app/ui/remanagement_allocation_dialog.py`** (novo) -
  `RemanagementAllocationStepDialog`: um grupo por produto (igual a Etapa 3),
  cada um com uma tabela editavel (Origem | Cliente | Disponivel | Retirar),
  indicadores Solicitado/Alocado/Restante/Status em tempo real, botoes
  "Sugerir melhor remanejamento" e "Limpar este item" por grupo, e
  "Atualizar disponibilidade"/"Limpar alocacoes" globais. Nao busca origens
  por conta propria - consome exclusivamente `state.availability`, o mesmo
  resultado oficial da Etapa 3.
- **`app/ui/process_page.py`** - a maquina de estados ganhou o estagio
  `"allocation"` entre `"availability"` e `"legacy_bridge"`.

## Limite por origem e pela necessidade do destino

Toda edicao na coluna "Retirar" passa por `_on_take_changed`, que clampa o
valor digitado em `[0, min(available_quantity_da_origem,
requested_quantity - soma_das_outras_origens_do_mesmo_item)]` - nunca deixa
o usuario digitar acima do saldo de uma origem nem estourar a necessidade do
item somando varias origens (secoes 6 e 7). O clamp e imediato e visivel (o
campo e reescrito com o valor permitido), nunca um erro modal por
tecla digitada.

## Alocado/Restante/Status em tempo real

Calculados diretamente da soma de `self._allocations[item_id]` a cada
edicao/sugestao/limpeza - nunca armazenados como numero solto que possa
ficar desatualizado. Estados: `NAO ALOCADO` (soma 0), `PARCIAL` (0 < soma <
solicitado), `COMPLETO` (soma >= solicitado), `INVALIDO` (qualquer linha
cuja quantidade alocada exceda o saldo *atual* daquele candidato - ver
secao seguinte).

## Sugestao automatica e desempate

`suggest_allocation()` e chamada com os candidatos do produto e a
`requested_quantity` do item; o resultado **substitui** (nao acumula) a
alocacao anterior daquele item especifico, exatamente como pedido na secao
22 ("Reaplicar sugestao"). Desempate por saldo igual usa
`(source_proposal_id, source_item_id)` crescente - nenhuma regra de
prioridade por cliente/data foi inventada, pois nenhuma existe oficialmente
no dominio (secao 15).

## Saldo alterado por refresh (secao 23) - nunca truncado silenciosamente

"Atualizar disponibilidade" chama `service.remanagement_availability()`
(mesmo servico da Fase 3) e reindexar os candidatos. Uma alocacao existente
**nunca e reduzida automaticamente** quando o saldo cai abaixo dela -
`_item_has_invalid_row()` compara, a cada render, a quantidade alocada
contra o `available_quantity` *atual* do candidato (ou `None` se o
candidato sumiu da lista) e marca a linha/item como `INVALIDO` (texto em
vermelho + tooltip explicando o motivo). O botao "Avancar" fica desabilitado
enquanto existir qualquer linha invalida em qualquer item - o usuario deve
corrigir manualmente (editar para um valor dentro do novo limite, limpar o
item ou reaplicar a sugestao) ou atualizar novamente. So uma edicao manual
resolve a invalidez daquela linha, porque o proprio clamp garante que o novo
valor digitado sempre cabe no saldo atual.

## Nenhuma reserva, nenhuma escrita

Digitar "Retirar", sugerir, limpar, atualizar disponibilidade, voltar e
avancar sao 100% operacoes em memoria sobre `RemanagementFlowState` - nenhum
metodo desta fase chama um endpoint de escrita. "Atualizar disponibilidade"
chama a mesma consulta readonly da Fase 3.

## source_item_id/source_proposal_id preservados

A chave interna de cada linha e a tupla `(source_proposal_id,
source_item_id)`, nunca o texto exibido ou o indice visual da linha -
mesma convencao ja usada nas Fases 1-3. `RemanagementItemAllocation` guarda
essa chave explicitamente em cada `RemanagementSourceAllocation`, pronta
para a Fase 5 (o motor de compensacao ja construido) consumir via
`RemanagementCompensationRequest` sem nenhuma tradução adicional.

## Integracao com a Fase 5 (motor ja existente)

O plano gerado aqui tem exatamente a forma que
`service.remanagement_compensation_plan()` (Fase 5, ja implementada como
motor standalone) espera: `destination_item_id` + `requested_quantity` por
item, `source_proposal_id`/`source_item_id`/`allocated_quantity` por
alocacao. A ponte legada (`EarlyRemanagementDeliveryDialog`) que ainda fecha
o fluxo em `process_page.py` **nao consome esse plano ainda** - ela continua
resolvendo origem/compensacao do jeito legado, como ja documentado nas
Fases 1-3. Consumir `state.allocations` para de fato chamar o motor de
compensacao e mostrar o resultado ao usuario e trabalho da Fase 6 (revisao/
simulacao/confirmacao), que substituira essa ponte quando tiver uma tela
propria.

## Testes

- `tests/test_remanagement_allocation.py` (8, puro Python): origem unica
  suficiente, combinacao das maiores, saldo total insuficiente, desempate
  estavel, nunca ultrapassa `requested_quantity`/`available_quantity`, sem
  candidatos, necessidade zero.
- `tests/test_remanagement_allocation_dialog.py` (22): carregamento,
  clamp por origem e por necessidade, valor negativo/zero/decimal, duas e
  tres origens dividindo a quantidade, sugestao (inclusive reaplicar sem
  acumular), limpar item/tudo, multiplos produtos independentes, avancar
  habilita/desabilita corretamente, plano final correto, Voltar sem
  escrita, erros de carregamento, preservacao ao reabrir com estado
  existente, e os dois cenarios de saldo alterado por refresh (reduzido e
  removido) confirmando que nada e truncado silenciosamente.
- Suite completa de dialogos de remanejamento (`test_remanagement_*.py`,
  79 testes: Fases 1-4) roda limpa em conjunto.
- Regressao ampla (`pytest tests/`, excluindo apenas arquivos de
  galvanizacao/lote conhecidos por instabilidade nao relacionada a este
  trabalho): 1148 passed, 19 failed - todas as 19 falhas sao de um
  refactor de cache (`_read_cache` ausente em testes que instanciam
  `BackendService` via `__new__`) e de uma migracao nova ainda nao
  registrada no manifest de checksums/risco, nenhuma delas em arquivo de
  remanejamento.

## Atualizacao (Fase 6)

A ponte legada apos a Etapa 4 foi de fato substituida pela Etapa 6 (revisao/
simulacao/confirmacao) - ver
[[FASE6_REMANEJAMENTO_REVISAO_SIMULACAO_CONFIRMACAO]]. A ponte legada agora
fica entre a Etapa 6 e o fluxo legado, ate a Fase 7 (persistencia
transacional real) existir.
