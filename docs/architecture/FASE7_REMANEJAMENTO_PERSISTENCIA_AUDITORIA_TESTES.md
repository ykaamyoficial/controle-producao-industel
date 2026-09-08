# Fase 7 - Remanejamento: Persistencia Segura, Auditoria e Testes

Setima e ultima fase do plano de 7 fases do novo fluxo de Remanejamento
Compensado. E a primeira fase que de fato grava no banco: revalida tudo
dentro de uma unica transacao (destino, cada origem, cada saldo), trava as
propostas envolvidas, persiste tudo-ou-nada e registra auditoria completa.
A ponte legada (`EarlyRemanagementDeliveryDialog`) que fechava o fluxo desde
a Fase 1 foi removida - o novo fluxo agora e auto-suficiente.

## Nao recalcula com regra paralela (inventario)

- `_load_compensation_snapshots` (Fase 5/6): reaproveitada tambem pela Fase 7,
  agora com um parametro opcional `preloaded_proposals` - quando fornecido
  (Fase 7), destino e itens de origem vem exclusivamente do dicionario de
  propostas ja travadas (`_locked_remanagement_participants`), nunca de uma
  leitura solta e destravada. Sem esse parametro (Fases 5/6, comportamento
  inalterado), continua consultando `get_proposal`/`ProposalItem` normalmente.
  Ganhou tambem um 5º valor de retorno, `items_by_id`, usado pela Fase 7 para
  montar as linhas persistidas sem uma segunda consulta.
- `build_compensation_plan` (Fase 5): mesmo motor puro, chamado com os
  snapshots frescos carregados dentro da transacao - a Fase 7 nao reimplementa
  nenhuma validacao de compatibilidade/conservacao/saldo, so decide o que
  fazer com um plano ja validado.
- `_batch_item_allocation_balances`: reaproveitada para obter o detalhe
  completo de saldo (`source_ready_before/after`,
  `destination_need_before/after`, etc.) necessario para preencher
  `ProposalRemanagementItem`, sem uma consulta por item.
- `apply_remanagement` (fluxo legado, origem unica): a Fase 7 espelha
  exatamente a mesma sequencia de mutacao por linha (criar
  `ProposalRemanagementItem` + `ProductionAllocationTransfer`, atualizar
  `ExpeditionItem` de origem e destino, registrar `ExpeditionEvent`) e a
  mesma logica de recalculo de status ao final - nenhuma regra nova foi
  inventada, apenas generalizada para N origens dentro de uma unica
  transacao.

## Arquitetura: uma operacao, varias linhas `ProposalRemanagement`

O modelo existente `ProposalRemanagement` so suporta uma origem e um destino
por linha (colunas `source_proposal_id`/`destination_proposal_id` unicas).
O novo fluxo permite que o mesmo destino seja atendido por **varias
propostas de origem diferentes** na mesma confirmacao. Em vez de alterar o
modelo (migracao), cada origem distinta vira sua propria linha
`ProposalRemanagement`, e todas as linhas de uma mesma confirmacao
compartilham:

- `correlation_id = operation_id` - campo que **ja existia** no modelo (usado
  no fluxo legado apenas como copia do `idempotency_key`), reaproveitado
  aqui como a chave de agrupamento do lote. **Nenhuma migracao nova.**
- `idempotency_key = f"{operation_id}:{source_proposal_id}"` - unico por
  (operacao, origem), protegendo tambem o caso de uma unica origem dentro de
  um lote maior contra duplicacao.

Todas as linhas do lote sao criadas e commitadas dentro do **mesmo**
`session.commit()` final - qualquer excecao em qualquer ponto (validacao,
origem sem disponibilidade oficial, IntegrityError inesperado) reverte a
transacao inteira, nunca deixando um subconjunto de origens gravado.

## Revalidacao completa dentro da transacao

Nenhum dado das Fases 1-6 (`state.simulation`, saldos exibidos na tela) e
usado como fonte de verdade para a gravacao - `confirm_remanagement_batch`
(`api/app/modules/proposals/service.py`) sempre:

1. Trava destino + todas as origens distintas via
   `_locked_remanagement_participants` (generalizacao de
   `_locked_remanagement_proposals`, mesmo padrao de `.with_for_update()`
   ordenado por id para evitar deadlock entre confirmacoes concorrentes que
   compartilhem alguma proposta).
2. Revalida que cada origem esta ativa e nao cancelada (`_ensure_proposal_not_cancelled`)
   - o motor de compensacao (Fase 5) nunca verificava isso porque so era
   usado para simulacao; a Fase 7, que grava, precisa.
3. Chama `_load_compensation_snapshots(..., preloaded_proposals=...)` +
   `build_compensation_plan(...)` de novo, com saldo lido **agora**, dentro da
   transacao ja travada - se qualquer saldo caiu desde a Fase 6, o motor
   sozinho gera o erro (`ALLOCATION_EXCEEDS_SOURCE_SNAPSHOT`, etc.) e a
   confirmacao e recusada (409) sem gravar nada.
4. So entao persiste.

## Concorrencia

`_locked_remanagement_participants` trava destino e todas as origens
distintas em uma unica consulta `SELECT ... FOR UPDATE ORDER BY id`. Duas
confirmacoes concorrentes que compartilhem qualquer proposta serializam
nessa trava; a segunda, ao ser liberada, sempre le o saldo **ja atualizado**
pela primeira (nao o congelado no momento em que a requisicao chegou) e e
corretamente bloqueada se o que ela pede nao cabe mais - coberto por
`test_remanagement_confirm_concurrency_never_overspends_source_ready_balance`
(mesmo padrao de teste ja usado por
`test_compensated_remanagement_concurrency_never_overspends_source_ready_balance`,
do fluxo legado).

## Idempotencia

Dupla checagem (double-checked locking), mesmo padrao de `apply_remanagement`:
uma consulta por `correlation_id == operation_id` **antes** de travar (fast
path, evita travar propostas para um retry que ja foi aplicado) e outra
**depois** de travar (fecha a janela de corrida entre a checagem inicial e a
trava). Se `IntegrityError` estourar mesmo assim (corrida entre duas
requisicoes com o mesmo `operation_id` chegando quase simultaneamente), o
`except IntegrityError` faz rollback e busca de novo pelo `correlation_id` -
se achou, devolve o resultado ja commitado por quem venceu a corrida em vez
de propagar o erro. Retry de rede e duplo clique (o botao "Confirmar
remanejamento" ja se desabilita no primeiro clique) sempre devolvem o mesmo
resultado, nunca uma segunda gravacao.

## Auditoria

Reaproveita integralmente os mecanismos ja existentes - nenhuma tabela nova:

- `ProposalRemanagement`/`ProposalRemanagementItem`/`ProductionAllocationTransfer`
  guardam quem, quando, motivo, quantidade e o antes/depois de cada saldo por
  linha (colunas ja existentes, mesmo preenchimento de `apply_remanagement`).
- `ExpeditionEvent` (`_record_expedition_event`) por item, em ambos os lados
  (origem e destino), com metadata incluindo `operation_id`.
- `ProposalEvent` (`_record_event`) por proposta afetada (cada origem +
  destino), com estado antes/depois.
- `auth_repository.create_security_event` uma vez para a operacao inteira,
  com `operation_id`, `destination_proposal_id`, todas as `source_proposal_ids`
  e os `remanagement_ids` gerados.

## Um bug pre-existente encontrado e corrigido

Os testes desta fase (que, ao contrario das Fases 5/6, exercitam cobertura
**parcial** de uma origem contra o banco real) encontraram um bug ja
existente em `apply_remanagement` (fluxo legado, nunca coberto antes porque
os testes existentes so remanejavam a origem por completo):
`source_expedition.status = "DISPONIVEL_PARCIAL"` quando a origem ainda tinha
saldo pronto apos o remanejamento - essa string **nao existe** em
`ck_expedition_items_status` (`EM_SEPARACAO, SEPARACAO_INICIADA, SEPARADO,
ENTREGUE_PARCIAL, ENTREGUE, REMANEJADO`), violando o `CHECK CONSTRAINT` do
banco. Corrigido em **ambos** os caminhos (`apply_remanagement` e
`confirm_remanagement_batch`): com saldo restante, o item de origem mantem o
status que ja tinha (continua elegivel para sua propria separacao/entrega);
so vira `REMANEJADO` quando o saldo pronto chega a zero.

## Migracao pre-existente corrigida (bloqueava toda a suite de integracao)

A migracao `20260817_0024_operational_query_indexes.py` tentava recriar o
indice `ix_proposals_parent_proposal_id`, que ja e criado por
`20260814_0021_proposal_partial_hierarchy.py` junto com a propria coluna -
um `DuplicateTableError` deterministico em qualquer banco criado do zero,
que ja vinha bloqueando a suite de integracao (`test_proposals_integration.py`)
desde as Fases 5 e 6 (reportado sem correcao nos dois casos). Como a Fase 7 e
a primeira com escrita real - e por isso a que mais precisa de verificacao
contra Postgres de verdade -, o indice duplicado foi removido da migracao
(upgrade e downgrade). Root cause confirmado antes da correcao (o indice
citado e criado por outra migracao 3 dias antes); os outros 4 indices dessa
migracao nao tinham conflito e foram mantidos.

## Arquivos criados e alterados

**API:**
- `api/app/modules/proposals/service.py` -
  `_locked_remanagement_participants` (nova, generaliza
  `_locked_remanagement_proposals` para N propostas),
  `_load_compensation_snapshots` (parametro `preloaded_proposals` + retorno
  `items_by_id`), `_get_remanagement_batch_by_operation_id`,
  `_confirm_result_from_rows`, `confirm_remanagement_batch` (nova - unico
  ponto de escrita desta fase). Correcao do status invalido em
  `apply_remanagement`.
- `api/app/modules/proposals/schemas.py` - `RemanagementConfirmRequest`,
  `RemanagementConfirmSourceSummary`, `RemanagementConfirmResult`.
- `api/app/modules/proposals/router.py` - `POST /shipping/remanagements/confirm`
  (mesma permissao `EXPEDITION_UPDATE`, `201 Created`).
- `api/alembic/versions/20260817_0024_operational_query_indexes.py` -
  remocao do indice duplicado (ver secao acima).

**Desktop:**
- `app/integrations/api/proposals_client.py`,
  `app/services/api_proposal_storage.py`, `app/services/backend_adapter.py` -
  `remanagement_confirm(...)` encadeado ate a API, mesmo padrao de 3 camadas
  das fases anteriores.
- `app/services/remanagement_flow_state.py` - `RemanagementFlowState.operation_id`
  (gerado uma vez por tentativa via `uuid4()`, regenerado apenas quando o
  destino muda - as demais voltas/edicoes preservam o mesmo id, garantindo
  que um retry de rede ou duplo clique dentro da mesma tentativa reuse a
  idempotencia).
- `app/ui/remanagement_review_dialog.py` - `_confirm_clicked` agora chama
  `service.remanagement_confirm(...)` de fato apos o "Sim" do
  `QMessageBox.question`. Sucesso: fecha com `Accepted`. Erro estruturado
  (saldo mudou, proposta nao esta mais ativa, etc.): mostra a mensagem e
  **revalida automaticamente** (reaproveita `_load_review`/`_render_result`,
  o mesmo mecanismo do botao "Revalidar") em vez de simplesmente fechar com
  erro - a tela volta a mostrar o estado atual, com o item afetado destacado
  em vermelho pelo mecanismo de erros por produto ja existente desde a Fase
  6. Se a propria revalidacao falhar (ex.: destino sumiu), o dialogo volta
  para a Etapa 4 (`RESULT_BACK`) em vez de deixar a tela em um estado
  inconsistente.
- `app/ui/process_page.py` - o estagio `"legacy_bridge"` foi **removido**;
  `stage == "review"` aceito agora encerra o fluxo direto (a gravacao ja
  aconteceu dentro do proprio dialogo da Etapa 6). Import morto de
  `EarlyRemanagementDeliveryDialog` removido (a classe continua existindo e
  testada isoladamente, apenas nao e mais instanciada por este fluxo).

## Nenhuma entrega, nenhuma nota fiscal

`confirm_remanagement_batch` nunca importa nada de entrega/fiscal, nunca
marca `delivered`/emite NF - move apenas `available_quantity` (material
pronto) e cria a obrigacao de producao equivalente, exatamente como o fluxo
legado sempre fez.

## Testes

- **`api/tests/test_remanagement_compensation.py` + `test_compensated_remanagement.py`**
  (26, puro Python): continuam 100% verdes apos o refactor de
  `_load_compensation_snapshots` (parametro novo, retorno novo) - confirma
  zero mudanca de comportamento para quem nao usa `preloaded_proposals`.
- **`api/tests/test_proposals_integration.py`** (6 novos, contra Postgres
  real, **executados e verdes** - a primeira vez que uma fase deste fluxo
  consegue rodar sua suite de integracao, apos a correcao da migracao):
  origem unica persiste e reproduz os mesmos efeitos colaterais de
  `apply_remanagement`; duas origens diferentes para o mesmo item destino
  geram duas linhas `ProposalRemanagement` compartilhando `correlation_id`,
  sem duplicar o `ExpeditionItem` do destino; retry com o mesmo
  `operation_id` e idempotente (nao duplica); plano incompatível e recusado
  sem persistir nada; auto-referencia e motivo vazio sao bloqueados;
  concorrencia entre duas confirmacoes na mesma origem nunca ultrapassa o
  saldo real (`[201, 409]`, nunca `[201, 201]`).
  **Suite completa: 72/72 passed** (inclui todas as fases anteriores do
  fluxo de remanejamento + o restante da suite de propostas).
- **Suite de dialogos de remanejamento** (`test_remanagement_*.py`, Fases
  1-7): **103 passed** (97 anteriores + 6 novos: chamada ao endpoint de
  confirmacao com o `operation_id` do estado, erro de confirmacao revalida
  em vez de so fechar, erro seguido de revalidacao tambem falha volta para a
  Etapa 4, `operation_id` estavel entre edicoes e regenerado ao trocar de
  destino).
- Regressao ampla (`pytest tests/`): mesma instabilidade pre-existente e nao
  relacionada, ja documentada nas fases anteriores, em arquivos de
  galvanizacao/lote/chat/background - nenhuma delas em arquivo de
  remanejamento ou proposta.

## Resultado final do fluxo de 7 fases

O botao "Remanejamento compensado" em `process_page.py` agora executa um
fluxo completo e auto-suficiente (Destino -> Itens -> Busca -> Alocacao ->
Revisao/Confirmacao/Persistencia), sem depender mais do dialogo legado
`EarlyRemanagementDeliveryDialog` para fechar a operacao. O dialogo legado e
seus endpoints (`POST /shipping/remanagements`, `simulate_remanagement`)
continuam intactos e testados, disponiveis como fallback tecnico, mas nao
sao mais chamados por este botao.
