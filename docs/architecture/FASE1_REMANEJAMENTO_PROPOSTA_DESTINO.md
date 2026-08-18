# Fase 1 - Remanejamento: Novo Fluxo de Proposta Destino

Primeira fase de um plano de 7 fases para reformular o "Remanejamento
Compensado entre Propostas". Objetivo desta fase: trocar o ponto de entrada
atual (escolher Destino + Origem de uma vez) por uma primeira etapa que pede
somente o destino - "Qual proposta precisa receber material pronto?".

## Fluxo legado encontrado (inventario)

- Dialogo: `EarlyRemanagementDeliveryDialog` (`app/ui/early_remanagement_dialog.py`),
  aberto por `ProcessPage.open_early_remanagement_delivery`
  (`app/ui/process_page.py`).
- Destino e origem eram escolhidos lado a lado, em duas `QTableWidget`
  independentes, cada uma com seu proprio campo de busca.
- Candidatos a destino: `service.early_delivery_destination_candidates(search)`
  (`app/services/backend_adapter.py`) - todas as propostas (ate 200), filtradas
  por texto livre em proposta/cliente/obra-site. **Fase 1 reaproveita esta
  mesma consulta sem alterar sua regra.**
- Candidatos a origem: `service.remanagement_source_candidates(destino_id, search)`
  - propostas de expedicao com status `SEPARADO`/`ENTREGUE_PARCIAL`, excluindo
    o destino. Nao alterado nesta fase.
- Compatibilidade de item e simulacao/confirmacao permanecem na API
  (`api/app/modules/proposals/remanagement.py`, `service.py`) - nenhuma regra
  de negocio foi movida para o PySide.

## O que foi implementado

- `app/services/remanagement_flow_state.py` - `RemanagementFlowState`: estado
  do novo fluxo (`destination_proposal_id`, `destination_version` preenchidos
  nesta fase; `selected_item_ids`/`allocations`/`simulation` reservados para
  as Fases 2, 4 e 6).
- `app/ui/remanagement_destination_step_dialog.py` -
  `RemanagementDestinationStepDialog`: nova Etapa 1. Busca unica (proposta,
  cliente, obra/site), tabela somente leitura, resumo da proposta selecionada,
  botao "Avancar" habilitado apenas com destino valido e que revalida a
  elegibilidade (recarrega candidatos e confere presenca do ID) antes de
  aceitar. Nenhuma escrita no banco em nenhuma acao desta tela.
- Ponte temporaria: `EarlyRemanagementDeliveryDialog` ganhou o parametro
  `preselected_destination_id`. Quando presente, a tabela/campo de busca de
  destino sao selecionados e desabilitados (`_lock_destination`), e um botao
  "Voltar" (`RESULT_BACK = 2`) aparece ao lado de Cancelar/Confirmar para
  devolver o controle a Etapa 1 sem reescrever o destino. O restante do fluxo
  legado (origem, mapeamento, simulacao, confirmacao) continua identico.
- `ProcessPage.open_early_remanagement_delivery` agora abre primeiro
  `RemanagementDestinationStepDialog`; ao avancar, abre a tela legada com o
  destino travado; se o usuario clicar "Voltar", reabre a Etapa 1 com o mesmo
  destino pre-selecionado (`initial_destination_id`).

## Nenhuma escrita adicionada

Busca, filtro, selecao/desselecao de destino, avancar e cancelar na nova
Etapa 1 apenas leem `early_delivery_destination_candidates`. Nenhum destes
caminhos chama qualquer metodo de escrita do servico.

## Testes adicionados

`tests/test_remanagement_destination_step_dialog.py` (14 casos):
listagem/elegibilidade, busca por proposta/cliente/obra-site, selecao e troca
de selecao, `Avancar` habilitado/desabilitado, revalidacao ao avancar com
destino removido, cancelar sem escrita, pre-selecao via
`initial_destination_id`, trava do destino na ponte legada, exibicao
condicional do botao "Voltar" e o codigo de resultado customizado que ele
retorna.

Suite completa (`pytest tests/`): 1186 passed, 2 skipped, 0 failed.

## Atualizacao (Fase 2)

A ponte legada apos a Etapa 1 foi de fato substituida - agora fica entre a
Etapa 2 (selecao de itens) e o fluxo legado, nao mais logo apos a Etapa 1.
`RemanagementDestinationStepDialog` passou a aceitar um `RemanagementFlowState`
compartilhado (`state=`) em vez de sempre criar o seu proprio, e
`ProcessPage.open_early_remanagement_delivery` virou uma maquina de 3 estagios
(`destination -> items -> legacy_bridge`) sobre esse unico estado. Detalhes em
[[FASE2_REMANEJAMENTO_SELECAO_ITENS_DESTINO]].
