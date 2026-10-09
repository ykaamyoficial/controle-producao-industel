# Fase 12 — Histórico legível

## Objetivo

A aba Histórico dos Detalhes da proposta mostrava códigos de evento (`PRODUCTION_ITEM_FLOW_UPDATED`) no selo, o dict de metadata cru em Observação e uma linha por item de um mesmo lote. A fase deixa o histórico compreensível sem tocar na auditoria: a frase legível passa a vir pronta da API, e o Desktop só exibe.

## Implementação

### API (`api/app/modules/proposals/`)

- `ProposalHistoryItem` ganha `title` (frase pronta), `detail` (observação ou motivo em texto simples) e `count` (eventos fundidos na linha). `observation` bruto continua existindo para auditoria.
- `_proposal_history_item` monta `title` com `_activity_headline` (a mesma fonte do feed `GET /proposals/{id}/activities`) e `detail` com `_history_detail`, que lê apenas `observation`/`reason` em texto — nunca o dict inteiro.
- `ACTIVITY_TEMPLATES` ganha 12 frases que faltavam: `PROPOSAL_ITEM_CREATED/DELETED`, `EXPEDITION_ITEM_RETURNED_TO_PRODUCTION`, `EXPEDITION_RETURN_TO_PRODUCTION`, `COMPENSATED_REMANAGEMENT_READY_SENT/RECEIVED`, `COMPENSATED_REMANAGEMENT_APPLIED/RECEIVED`, `GALVANIZATION_ITEM_OWNER_CHANGED`, `GALVANIZATION_PROPOSAL_RETURN_RECALCULATED`, `GALVANIZATION_RETURN_RECORDED_AFTER_CANCELLATION`, `REALLOCATED_PRODUCTION_COMPLETED`.
- `_group_history_rows` funde, antes da paginação, eventos com mesma proposta, origem, tipo, autor, status novo e `request_id` (sem `request_id`, mesmo segundo). A frase do grupo vem de `ACTIVITY_GROUP_TEMPLATES` ("definiu o fluxo de producao de 8 itens"); tipos fora da tabela usam a frase singular com o total no fim.
- Sem migration; mudança aditiva no contrato.

### Desktop (`app/`)

- `_api_history_to_legacy` (`app/services/api_proposal_storage.py`) repassa `titulo`, `detalhe`, `quantidade` e `status_real_novo`; `status_novo` não mudou (as abas Fluxo e Fiscal/Entrega ainda o usam).
- `HistoricoTab` (`app/ui/process_detail/historico_tab.py`) reescrita: colunas `Quando | Área | O que aconteceu | Status | Detalhe` (o usuário já está na frase); selo `anterior → [novo]` só com mudança real de status; datas amigáveis via `friendly_when` ("Hoje 19:17", "Ontem 08:05", "14/09 14:05") com data completa no tooltip; filtro por área quando há mais de uma.

## Garantias

1. Nenhuma tela do Histórico exibe código de evento nem metadata crua.
2. Todo `event_type` emitido por `_record_*event` tem frase em `ACTIVITY_TEMPLATES`; o teste de cobertura falha se surgir um sem frase.
3. A auditoria não é alterada: `observation`, `event_type`, `request_id` e os eventos persistidos permanecem como estavam.
4. Um lote (mesmo autor, tipo e requisição) aparece em uma única linha, com o total em `count`.
5. O selo de status só aparece quando `to_status` é um status real, nunca um `event_type`.
6. `HistoricoTab.load` continua devolvendo o histórico completo e sem filtro, para as demais abas.

## Validação

```
python -m pytest api/tests -q
python -m pytest tests -q
python -m compileall -q app api/app
```

- API: 805 passed, 350 skipped.
- Desktop: 1899 passed, 21 skipped.
- `compileall`: sem erros.
- Testes novos: `HistoryReadabilityTests` em `api/tests/test_proposal_activity_feed.py` (cobertura de templates, agrupamento, frase de remanejamento) e `tests/test_historico_tab.py` (datas, frase sem código de evento, seta de status, filtro por área).
- As suítes completas rodaram nesta sessão, logo antes do fechamento; o código não mudou depois.
- Conferência visual feita pelo usuário contra a API de dev (8001).

## Pendência

- A linha agrupada mostra só o total. Expandir a lista de itens exige o número do item na metadata de `PRODUCTION_ITEM_FLOW_UPDATED`, que hoje guarda apenas `item_id`.
