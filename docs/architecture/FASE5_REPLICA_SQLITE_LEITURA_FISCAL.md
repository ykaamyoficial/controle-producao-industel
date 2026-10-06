# Fase 5 — Réplica local SQLite: Fiscal lendo da réplica

## Objetivo

Segunda área a ler do SQLite local: lista de registros fiscais e indicadores
fiscais. Reaproveita o padrão da Fase 4 (visão local + `ReplicaReadGate` +
recuo para a API) e vale sob a mesma flag
(`"local_replica": {"enabled": true, "read": true}`).

## Implementação

- `app/replica/fiscal_view.py` — `list_fiscal_records` (busca, `status`,
  `situation_filter`, paginação) e `fiscal_indicators`: espelho de
  `list_fiscal_records`, `_fiscal_record_summary`, `_fiscal_actions`,
  `_fiscal_situation` e `fiscal_indicators` da API. Devolve o mesmo JSON de
  `GET /fiscal/records` e `GET /fiscal/indicators`.
- `app/replica/view_common.py` — peças comuns às visões locais: decimais em 4
  casas, proposta não cancelada, busca por trecho e data/hora no formato da API
  (`Z` em vez de `+00:00`). `expedition_view.py` passou a usá-las.
- `app/services/api_proposal_storage.py` — `_read_from_replica` (tentativa
  genérica com recuo); `fiscal_rows_page` e `fiscal_indicators` leem da réplica
  quando a porta está aberta. A conversão para o formato das telas
  (`_api_fiscal_record_to_legacy`, `_filter_fiscal_rows`) é a mesma nos dois
  caminhos.
- Testes: `tests/test_replica_fiscal_view.py`; casos de Fiscal em
  `api/tests/test_replica_views_parity.py`.

## Garantias

1. Lista e indicadores locais são idênticos aos da API para os mesmos dados; o
   teste de paridade falha se a regra mudar em um lado só.
2. Mesmo universo da API: registro fiscal ativo, proposta não cancelada, e
   filha só depois de chegar à Expedição.
3. Valem as garantias de leitura da Fase 4: sem dado antigo depois de gravar,
   recuo para a API com réplica fechada, incompleta, sem permissão ou com erro.
4. Detalhe do registro fiscal, itens, emissões, movimentos, relatórios e todas
   as gravações continuam na API.

## Validação

```
python -m compileall -q app api/app
python -m pytest tests/test_replica_fiscal_view.py -q
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

- `compileall`: sem erros.
- `tests/test_replica_fiscal_view.py`: `16 passed`.
- Suíte da API (PostgreSQL 17 descartável): `3 failed, 1002 passed, 2 skipped`
  — inclui 4 testes de paridade (Expedição e Fiscal; 17 combinações de filtro
  do Fiscal mais indicadores, com pesos diferentes de zero, antes e depois de
  emissão de NF e de retirada).
- Desktop, arquivo por arquivo (`tests/test_*.py`): `1600 passed, 21 skipped,
  1 failed`; 3 arquivos não concluíram (ver pendências).

Homologação (`controle_producao_industel_dev`, cópia dos dados de produção, 267
registros fiscais), pelo caminho real do app, mediana de 7 chamadas:

| Leitura | API | Réplica | Resultado |
|---|---:|---:|---|
| Lista Fiscal, 50 linhas | 359 ms | 24 ms | idêntico |
| Lista Fiscal, 200 linhas | 818 ms | 38 ms | idêntico |
| Lista com busca (167 linhas) | 829 ms | 34 ms | idêntico |
| Lista por situação (47 linhas) | 299 ms | 21 ms | idêntico |
| Indicadores | 20 ms | 32 ms | idêntico |

`fiscal_view` direto contra a API, 17 combinações de status, situação, busca e
paginação: todas idênticas.

No programa real (Fase 4), 4 aberturas da Expedição não chamaram
`/shipping/proposals`; cada atualização ainda levou 560–700 ms por causa de
`/chat/conversations` e `/chat/unread-summary`, chamados a cada refresh da
página de processos.

## Pendência encontrada

- **Indicadores não ficam mais rápidos nesta máquina** (API local responde em
  20 ms). O ganho é uma chamada de rede a menos, relevante só nas estações que
  acessam o servidor pela rede.
- **Chamadas de chat a cada refresh** dominam agora o tempo das telas migradas;
  é o próximo ganho barato, válido para todas as telas.
- **Tela do Fiscal não aberta no programa real** nesta fase: medição feita pelo
  caminho de serviço do app.
- **Suíte do Desktop:** `python -m pytest tests -q` segue caindo por falha de
  segmentação. Arquivo por arquivo, não concluem
  `test_compatibility_gate_dialog.py`, `test_galvanization_load_details_dialog.py`
  e `test_update_dialog.py` (22 dos 1 644 testes; nenhum usa a réplica; já falhavam antes
  desta fase). Falha fixa: campo `email` no payload de usuário.
- **3 falhas da API já registradas** e dois arquivos de build Docker não
  executados.
- **Regra de leitura duplicada** (API e Desktop), protegida só pelo teste de
  paridade.
- **Ainda na API:** Propostas, Produção, Galvanização, Almoxarifado, Parciais e
  todos os detalhes.
