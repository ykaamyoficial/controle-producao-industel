# Fase 6 - Remanejamento: Revisao, Simulacao e Confirmacao

Sexta fase do plano de 7 fases do novo fluxo de Remanejamento Compensado.
Consolida tudo o que foi escolhido nas Fases 1-5 numa revisao final: mostra
separadamente o material pronto que muda de origem para destino e a
obrigacao produtiva que muda em sentido contrario, exige motivo, revalida
saldos sob demanda e so entao libera a confirmacao - sem persistir nada.

## Nao recalcula com regra paralela (inventario)

A Fase 5 (`build_remanagement_compensation_plan`) tinha toda a leitura de
saldo (destino + origens) misturada com a montagem do plano numa unica
funcao. Ela foi dividida (refactor comportamentalmente neutro, sem mudar a
resposta do endpoint da Fase 5 - confirmado pelos 26 testes puros de
`compensation.py`/`remanagement.py` continuando verdes) em:

- `_load_compensation_snapshots(session, payload)` - carrega destino, revalida
  a necessidade *atual* de cada item pedido e o saldo *atual* de cada origem
  alocada (`_item_allocation_balance`/`_batch_item_allocation_balances`, as
  MESMAS funcoes da Fase 1-3). Isso sozinho ja e a "revalidacao de
  disponibilidade" pedida na secao 16 do prompt: como os saldos sao lidos de
  novo a cada chamada, nunca confiam no `available_snapshot` congelado pela
  Fase 4.
- `build_remanagement_compensation_plan` (Fase 5, inalterada em
  comportamento) e a nova `simulate_remanagement_review` (Fase 6) agora
  chamam essa mesma funcao e o mesmo motor puro `build_compensation_plan`
  (`compensation.py`) - a Fase 6 so acrescenta o comparativo antes/depois e a
  validacao do motivo por cima do resultado ja calculado.

## Antes/depois sem inventar coluna persistida

`ItemSnapshot.available_for_transfer` (Fase 5) ja e exatamente o "antes":
`destination_need` para o item destino, `ready_available` para o item
origem. O "depois simulado" e puramente aritmetico (`antes - quantidade
transferida`), nunca uma tentativa de reproduzir a logica completa de
transicao de status por proposta (que e multi-item e vive em
`apply_remanagement`) - a mesma decisao ja tomada na Fase 5 para
`predicted_status`. Cada `RemanagementReviewSource` carrega
`source_before`/`source_after_simulated` (numerico) - a UI e quem junta isso
com o texto (proposta/cliente) que ja tem em cache da Fase 3.

## Conservacao 1:1

Garantida pelo motor da Fase 5 (`assert_quantity_conservation`,
`ready_quantity_to_destination == obligation_quantity_to_source` sempre) -
a Fase 6 apenas expõe os dois lados (`ready_transfer`/
`production_compensation`) sem recalcular nada.

## Cobertura completa/parcial/nao alocado/invalido

Calculada por item a partir do MESMO `CompensationProduct` da Fase 5
(`allocated_quantity` vs `requested_quantity`), mais uma checagem adicional:
se qualquer erro do motor (`CompensationError.destination_item_id`) apontar
para aquele item, o status vira `INVALIDO` mesmo que a soma alocada parecesse
suficiente - cobre "saldo insuficiente"/"codigo incompativel"/etc de uma vez.

## Motivo obrigatorio, mas nao bloqueia "Revalidar"

`RemanagementReviewRequest.reason` nao tem `min_length` no schema de
proposito: "Revalidar" pode ser clicado antes do usuario digitar o motivo
(ele so quer conferir saldo). O backend valida o trim/vazio e adiciona um
`CompensationPlanError(code="REASON_REQUIRED")` estruturado em vez de um 422
cru - a UI trata esse codigo especificamente (nao bloqueia a exibicao do
resto da revisao, so o botao Confirmar). O limite de 1000 caracteres reusa
o mesmo `Field(max_length=1000)` ja usado por
`ExpeditionRemanagementDeliveryRequest.reason` (fluxo legado) - nenhum
limite novo inventado.

## Arquivos criados e alterados

**API:**
- `api/app/modules/proposals/schemas.py` - `RemanagementReviewRequest`,
  `RemanagementReviewSource`, `RemanagementReviewItem`,
  `RemanagementReviewSummary`, `RemanagementReviewResult`.
- `api/app/modules/proposals/service.py` - `_load_compensation_snapshots`
  (extraida da Fase 5), `simulate_remanagement_review` (Fase 6).
- `api/app/modules/proposals/router.py` - `POST /shipping/remanagements/review`
  (mesma permissao `EXPEDITION_UPDATE`, nunca chama `session.commit()`).

**Desktop:**
- `app/services/remanagement_flow_state.py` - `RemanagementReviewSource`,
  `RemanagementReviewItem`, `RemanagementReviewSummary`,
  `RemanagementReviewError`, `RemanagementReviewResult`, `review_from_api()`;
  `RemanagementFlowState` ganhou `reason`/`simulation` com setters proprios
  (`set_reason`, `set_simulation`). `set_allocations`/`set_availability`
  agora limpam `simulation` (alterar alocacao ou disponibilidade sempre
  invalida uma revisao anterior - secao 27/28 do prompt); `reason` so e
  descartado ao trocar de destino (as demais voltas preservam o motivo
  digitado, como pedido na secao 40).
- `app/ui/remanagement_review_dialog.py` (novo) -
  `RemanagementReviewStepDialog`: card fixo de destino+resumo no topo,
  secoes por produto com blocos SEPARADOS "MATERIAL PRONTO (origem ->
  destino)" e "OBRIGACAO DE PRODUCAO (destino -> origem)" (nunca uma frase
  generica de "troca"), antes/depois por origem, aviso de cobertura parcial,
  erros bloqueantes destacados em vermelho por produto, motivo obrigatorio,
  Revalidar/Voltar/Confirmar. Confirmar abre uma confirmacao curta
  (`QMessageBox.question`, mesmo padrao ja usado pelo dialogo legado) e fica
  desabilitado imediatamente ao clicar (protecao contra duplo clique) -
  reabilitado apenas se o usuario cancelar a confirmacao.
- `app/ui/process_page.py` - novo estagio `"review"` entre `"allocation"` e
  `"legacy_bridge"`.

## Erros bloqueantes vs avisos, e onde aparecem

Erros com `destination_item_id` sao anexados DENTRO do card daquele produto
(vermelho, texto explicito - nunca um `QMessageBox` generico de "operacao
invalida"). Avisos (`plan.warnings`, ex.: cobertura parcial) aparecem numa
faixa separada, visualmente distinta dos erros. O botao Confirmar so
habilita quando nao ha nenhum erro (exceto o efemero `REASON_REQUIRED`,
resolvido localmente assim que o campo e preenchido) e o motivo (apos trim)
nao esta vazio.

## Nao persiste, nao registra entrega

Nenhum caminho do dialogo ou do endpoint escreve no banco; a tela declara
explicitamente que a operacao nao registra entrega ao cliente. "Confirmar"
apenas salva `reason`/`simulation` no `RemanagementFlowState` compartilhado
e segue para a ponte legada (`EarlyRemanagementDeliveryDialog`) - a mesma
ponte de todas as fases anteriores, ja que a Fase 7 (persistencia real)
ainda nao existe. Nao foi criado um dataclass `FinalRemanagementPlan`
separado: `state.allocations` + `state.simulation` + `state.reason` juntos
ja carregam exatamente essa informacao, prontos para a Fase 7 consumir.

## Testes

- `tests/test_remanagement_review_dialog.py` (18): carregamento/resumo,
  chamada automatica ao abrir, motivo vazio/so-espacos bloqueia confirmar,
  motivo preservado no estado, blocos MATERIAL PRONTO/OBRIGACAO separados
  (e na ordem certa), antes/depois exibido, cobertura parcial com aviso,
  item invalido bloqueia e mostra o erro, Revalidar chama o servico de novo,
  Voltar sem escrita, erros de carregamento (destino sumiu, sem alocacao),
  confirmar aceita no Sim/cancela no Nao, duplo clique so abre uma
  confirmacao, `state.simulation` populado.
- `api/tests/test_proposals_integration.py` (5 novos, escritos e prontos):
  plano valido com antes/depois e resumo corretos; motivo ausente vira
  `REASON_REQUIRED` sem quebrar o resto da revisao; cobertura parcial;
  queda de saldo entre a alocacao (Fase 4) e a revisao e detectada e aponta
  o item exato; multiplos produtos com resumo independente.
  **Nao executados desta vez**: a mesma migracao com indice duplicado
  (`ix_proposals_parent_proposal_id`) que ja bloqueava a suite da Fase 5
  continua sem correcao, impedindo qualquer teste contra o banco de teste
  isolado neste momento - confirmado reproduzindo em banco totalmente
  limpo. Os modulos importam sem erro dentro do proprio container da API.
- Suite de dialogos de remanejamento (`test_remanagement_*.py`, Fases 1-4 e
  6): 97 passed, isolada e de forma reprodutível.
- `api/tests/test_remanagement_compensation.py` +
  `test_compensated_remanagement.py` (26, sem banco): continuam 100% verdes
  apos o refactor de `build_remanagement_compensation_plan` - confirma que a
  extracao de `_load_compensation_snapshots` nao mudou nenhum comportamento
  da Fase 5.

## Ponto exato que a Fase 7 devera substituir

`ProcessPage.open_early_remanagement_delivery` (`app/ui/process_page.py`):
o estagio `"legacy_bridge"` (que hoje abre `EarlyRemanagementDeliveryDialog`
apos a Etapa 6 confirmar) e o trecho a trocar pela persistencia
transacional real, consumindo `RemanagementFlowState.allocations` +
`.reason` + `.simulation` (ja validados e prontos) para revalidar dentro da
transacao e gravar atomicamente.

## Atualizacao (Fase 7)

O estagio `"legacy_bridge"` foi removido de fato - ver
[[FASE7_REMANEJAMENTO_PERSISTENCIA_AUDITORIA_TESTES]]. A gravacao acontece
dentro do proprio `RemanagementReviewStepDialog._confirm_clicked` (chamando
`service.remanagement_confirm(...)`), nao mais em `process_page.py`; o
dialogo legado continua existindo e testado, apenas nao e mais chamado por
este fluxo.
