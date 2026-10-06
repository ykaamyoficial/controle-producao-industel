# Fase 4 — Réplica local SQLite: lista de Expedição lendo da réplica

## Objetivo

Primeira tela a ler do SQLite local em vez de chamar a API: a lista de
Expedição. Serve de piloto do padrão de leitura (visão local + proteção contra
dado antigo + recuo para a API) antes de migrar as demais telas. Continua
opcional: só vale com `"local_replica": {"enabled": true, "read": true}`.

## Implementação

- `app/replica/expedition_view.py` — `list_expedition_proposals(database,
  search, limit, offset)`: espelho de `list_expedition_proposals`,
  `_expedition_summary` e `_expedition_actions` da API. Devolve o mesmo JSON de
  `GET /shipping/proposals` (filtro de saldo pendente, propostas canceladas
  fora, busca, ordenação por status/atualização/id, paginação, totais em 4
  casas, origens e ações).
- `app/replica/read_gate.py` — `ReplicaReadGate`: a réplica só é lida quando
  está em dia com tudo que este Desktop gravou. Toda escrita pela API fecha a
  porta (ao enviar e ao receber a resposta) e pede um sync; ela reabre quando
  termina um sync iniciado depois da resposta. Escritas de chat, notificações e
  autenticação não contam.
- `app/services/api_proposal_storage.py` — `_BorrowedApiClient.request` avisa a
  porta em cada escrita; `list_expedition_proposals_page` tenta a réplica e, se
  a porta estiver fechada ou a leitura local falhar, usa a API como antes.
- `app/replica/sync_agent.py` — sinal `sync_requested`, para um worker thread
  pedir sync com segurança.
- `app/replica/factory.py` — `replica_read_enabled` (flag `read`).
- `app/ui/main_window.py` — cria a porta, envolve o sync com
  `begin_sync`/`complete_sync` e a entrega ao storage só quando `read` está
  ligado; remove no logout e no fechamento.
- Testes: `tests/test_replica_expedition_view.py`,
  `tests/test_replica_read_gate.py` e, na API,
  `api/tests/test_replica_views_parity.py`.

## Garantias

1. A resposta local é idêntica à da API para os mesmos dados; o teste de
   paridade falha se a regra mudar em um lado só.
2. Depois de gravar pela API, este Desktop não lê da réplica até ela ter
   recebido essa gravação: o usuário nunca salva e vê o dado antigo.
3. Um sync iniciado antes de a resposta da escrita chegar não reabre a leitura
   local.
4. Réplica vazia, ainda não sincronizada nesta sessão, sem a entidade exigida
   (usuário sem permissão) ou com erro de leitura: a tela usa a API.
5. Nenhuma regra de negócio de escrita foi movida para o Desktop; só leitura.
6. Com `read` desligado (padrão) o comportamento é o da Fase 3.

## Validação

```
python -m compileall -q app api/app
python -m pytest tests/test_replica_expedition_view.py tests/test_replica_read_gate.py -q
python -m pytest api/tests -q --ignore=api/tests/test_docker_release_integration.py --ignore=api/tests/test_deployment_rollback_integration.py
```

- `compileall`: sem erros.
- Testes novos do Desktop: `24 passed`.
- Suíte da API (PostgreSQL 17 descartável): `3 failed, 1000 passed, 2 skipped`
  — inclui `test_replica_views_parity.py` (2 testes, 10 combinações de filtro
  cada, antes e depois de mudanças incrementais).

Homologação (`controle_producao_industel_dev`, cópia dos dados de produção),
pelo caminho real do app (`OfficialProposalApiStorage`), mediana de 7 chamadas:

| Leitura | API | Réplica | Resultado |
|---|---:|---:|---|
| Lista de Expedição, 200 linhas (86 propostas) | 813 ms | 40 ms | idêntico |
| Lista com busca | 257 ms | 28 ms | idêntico |
| Após uma escrita (porta fechada) | volta à API | — | idêntico |

`expedition_view` direto contra `GET /shipping/proposals`, 10 combinações de
filtro e paginação: todas idênticas; ~20 ms local contra 25–500 ms da API.

## Pendência encontrada

- **Suíte do Desktop não roda mais de uma vez só nesta máquina.**
  `python -m pytest tests -q` caiu por falha de segmentação em todas as
  tentativas, com e sem as mudanças desta fase. Rodando arquivo por arquivo
  (163 arquivos, 1 628 testes): 1 570 passed, 21 skipped, 1 failed, e 4
  arquivos (36 testes) não concluíram:
  - `test_api_diagnostic_dialog.py` (5) — falha de segmentação intermitente;
  - `test_compatibility_gate_dialog.py` (8) — os testes passam e o processo
    cai ao encerrar, de forma intermitente;
  - `test_galvanization_load_details_dialog.py` — processo cai;
  - `test_update_dialog.py` — timeout em
    `test_coordinator_exception_does_not_crash_dialog` (diálogo real bloqueando
    em `update_dialog._update_failed`).
  Os dois últimos falham igual no commit anterior a esta fase; nenhum deles usa
  a réplica. A falha fixa é a já conhecida do campo `email`.
- **3 falhas da API já registradas** (dois 503 de inicialização, um de auditoria
  de atualização) e dois arquivos de build Docker não executados.
- **Regra de leitura duplicada:** a lógica da lista de Expedição existe na API e
  no Desktop. A proteção é o teste de paridade; não há geração automática.
- **Só a lista de Expedição foi migrada.** Detalhe da Expedição, Fiscal,
  Propostas, Galvanização e Produção continuam na API.
- **Não validado na interface real** nesta fase: medição feita pelo caminho de
  serviço do app, sem abrir a janela.
- **Leitura da réplica carrega todas as linhas de `expedition_items`** a cada
  chamada (1 085 linhas, ~20 ms). Suficiente hoje; com volume muito maior,
  filtrar no SQL.
