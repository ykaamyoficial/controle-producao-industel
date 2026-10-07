# Fase 6 — Réplica local: regras de negócio só na API

## Objetivo

Alinhar a réplica local à diretriz do responsável (07/10/2026): **regra de
negócio fica exclusivamente na API**. O computador guarda dados para carregar
mais rápido; o que é calculado (status exibido, ações habilitadas, situação
fiscal, saldos) continua vindo da API. Onde a lentidão é da API, a correção é
feita na API.

Esta fase substitui o que as Fases 4 e 5 descrevem sobre Expedição e Fiscal.

## Implementação

- **Removido:** `app/replica/expedition_view.py` e `app/replica/fiscal_view.py`
  (cópias no Desktop de `_expedition_summary`, `_expedition_actions`,
  `_fiscal_situation`, `_fiscal_actions`, `fiscal_indicators`), seus testes e os
  casos correspondentes de `api/tests/test_replica_views_parity.py`.
  `list_expedition_proposals_page`, `fiscal_rows_page` e `fiscal_indicators`
  voltaram a ler sempre da API. `app/replica/view_common.py` ficou só com a
  conversão de data/hora.
- **Mantido — Controle Geral lendo da réplica:** `app/replica/proposals_view.py`
  lista, filtra e ordena as propostas mãe com o mesmo JSON de
  `GET /proposals`. Não calcula nada. Ordenação por número da proposta
  (collation do PostgreSQL) e a checagem de duplicidade (`proposal_exists`,
  usada na importação Nomus) continuam indo à API — esta última por
  `_authoritative_reads`, que faz as leituras do thread ignorarem a réplica.
- **Detalhes da proposta, corrigido na API:** `list_partial_proposals` aplica a
  busca (`_proposal_search_clause`) e o novo parâmetro `proposal_id` no SQL,
  antes de carregar as cinco relações. O Desktop
  (`OfficialProposalApiStorage.process_partials`) passa a enviar `proposal_id`
  junto com a busca; APIs anteriores ignoram o parâmetro.
- Testes: `tests/test_replica_proposals_view.py`,
  `api/tests/test_partials_list_filter.py` e o caso do Controle Geral em
  `api/tests/test_replica_views_parity.py`.

## Garantias

1. O Desktop não reproduz regra de negócio: as leituras locais só listam,
   filtram e ordenam colunas já replicadas.
2. A lista local do Controle Geral é idêntica à da API (teste de paridade);
   pedido que a réplica não reproduz com segurança vai à API.
3. Decisão de duplicidade de proposta nunca depende da réplica.
4. `GET /partials/proposals` com `search` e/ou `proposal_id` devolve exatamente
   a lista completa filtrada pelo mesmo critério (mesmas linhas, ordem e total).
5. Seguem valendo as proteções de leitura da Fase 4 (sem dado antigo depois de
   gravar; recuo para a API) e a flag `local_replica.read`, desligada por padrão.

## Validação

```
python -m compileall -q app api/app
python -m pytest tests -q
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

- `compileall`: sem erros.
- Suíte do Desktop: `1623 passed, 21 skipped` (sem falhas).
- Suíte da API (PostgreSQL 17 descartável): `3 failed, 1004 passed, 2 skipped`.
  As 3 falhas são as já registradas nas fases anteriores (dois 503 de
  inicialização e um de auditoria de atualização); os dois arquivos de build
  Docker não foram executados.

Homologação (`controle_producao_industel_dev`, cópia dos dados de produção):

| Leitura | Antes | Depois | Resultado |
|---|---:|---:|---|
| `GET /partials/proposals?search=<número>` (Detalhes) | 1 349 ms | 65 ms | idêntico em 7 buscas |
| Controle Geral, 200 linhas, pelo caminho do app | 758 ms | 19 ms | idêntico |
| Controle Geral filtrado por cliente | 634 ms | 19 ms | idêntico |

`proposals_view` direto contra `GET /proposals`: 27 combinações de filtro,
ordenação e paginação, todas idênticas.

No log da versão instalada em produção, abrir os Detalhes levava 1,6 s
(mediana), dos quais 1,0–1,2 s eram `GET /partials/proposals`; os dados da
proposta com itens e descrições (`GET /proposals/{id}`) respondiam em 80 ms.

## Pendência encontrada

- **Tela de Detalhes não medida no programa** depois da correção; o tempo
  esperado (~0,3 s) é a soma das chamadas medidas isoladamente.
- **Expedição e Fiscal voltam aos tempos da API** (~0,3 s com 50 linhas, ~0,8 s
  com 200), em vez dos 20–40 ms da leitura local removida.
- **Lista de Parciais sem busca** ainda carrega todas as propostas ativas
  (~1,3 s): o filtro por movimento parcial é feito em Python.
- **Produção e Galvanização** (1–1,7 s) têm o mesmo padrão de carregar tudo e
  filtrar em Python; a otimização será feita na API.
- **Controle Geral sem paginação na tela:** mostra as 200 propostas mais
  recentes; a paginação de 200 em 200 ainda não foi implementada.
- **Dados estáticos no computador:** os itens (produto, descrição, observações)
  já estão na réplica, mas nenhuma tela de detalhe os usa; pela medição, o
  ganho possível ali é pequeno (80 ms) perto do que foi corrigido na API.
