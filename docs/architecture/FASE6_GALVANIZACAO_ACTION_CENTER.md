# Fase 6 — Padronização da Galvanização na Central de Ações

Data: 2026-08-12
Escopo: padronização de entrada + separação de contextos (proposta vs.
carga) + navegação. Nenhuma regra operacional, status, permissão ou
migration foi alterada.

## 1. Diagnóstico (antes de alterar código)

### 1.1 Estado real encontrado

- `ProcessPage(area="GALVANIZACAO")` já abria `StatusDialog` para a ação
  individual da proposta, exatamente como Produção/Controle Geral/
  Almoxarifado/Expedição (`app/ui/process_page.py:538-547`).
- `StatusDialog` **já era** uma subclasse de `ProposalActionCenter`
  (`app/ui/status_dialog.py`), isto é, a Galvanização de proposta **já
  usava a Central de Ações oficial** antes desta fase — não existia uma
  tela paralela. O que faltava era migrar seus dois action ids para fora
  do `LegacyActionHandler` e resolver a lacuna de navegação
  proposta→carga.
- `BackendAdapter.process_actions(process_id, "GALVANIZACAO")`
  (`app/services/backend_adapter.py:1352-1369`) retornava:
  - `MANAGE_LOAD` ("Adicionar a uma carga") quando o status é
    `AGUARDANDO_ENVIO` ou `DISPONIVEL_PARCIAL`;
  - `REGISTER_GALVANIZATION_RETURN` ("Registrar retorno da galvanizacao")
    quando o status é `ENVIADO_GALVANIZACAO` ou `RETORNOU_PARCIAL` **e**
    existe carga ativa (`process_loads()` filtrado por
    `LIBERADA_PARA_ENVIO`/`RETORNO_PARCIAL`).
  - Para o status `EM_CARGA` (proposta já dentro de uma carga ainda não
    liberada) e para `RETORNOU_GALVANIZACAO` (carga já encerrada), a
    função **não retornava nenhuma ação** — a Central mostrava só a
    mensagem genérica "Esta movimentacao e controlada pela tela Cargas."
    Esta era exatamente a lacuna que a navegação desta fase preenche.
- Ambos os action ids já eram roteados via `LegacyActionHandler`
  (`app/ui/status_dialog.py`, funções module-level `_manage_load` e
  `_register_galvanization_return`), abrindo respectivamente
  `GalvanizationLoadManagerDialog` e `GalvanizationReturnDialog`/
  `GalvanizationLoadManagerDialog` (quando há mais de uma carga ativa).
- `BackendActionProvider` (`app/ui/action_center/provider.py`) já era
  genérico o bastante — não continha nenhuma ramificação por área — e
  já cobria `MANAGE_LOAD`/`REGISTER_GALVANIZATION_RETURN` sem alteração.
- `GalvanizationLoadDetailsDialog` (`app/ui/galvanization_load_details_dialog.py`)
  já concentra **todas** as ações exclusivas da carga: `Editar carga`,
  `Liberar carga` e `Registrar retorno`, resolvidas via
  `service.galvanization_load_actions(load)` e um menu próprio
  (`_rebuild_actions_menu`, linhas 685-740). Nenhuma dessas ações jamais
  vazou para o `StatusDialog`/`ProposalActionCenter` da proposta — a
  separação de contexto pedida pelas seções 26-29 já existia na prática.
- `GalvanizationLoadManagerDialog` (`app/ui/galvanization_load_dialog.py:1119`)
  é a listagem/gestão de cargas (filtros, criação, edição em lote);
  `GalvanizationLoadDetailsDialog` é o "centro operacional" de uma carga
  específica (`load_id`).

### 1.2 Cardinalidade proposta ↔ carga

- `GalvanizationLoadItem` (`api/app/modules/proposals/models.py:187-218`)
  tem `proposal_id` **e** `load_id` como FKs indexadas
  (`ix_galvanization_load_items_proposal`, `ix_galvanization_load_items_load`).
  Uma proposta pode ter itens em **mais de uma carga ao longo do tempo**
  (ex.: carga antiga já `RETORNADA_GALVANIZACAO` + itens remanejados para
  uma carga nova) — **Cenário B** do prompt técnico, na dimensão
  histórica.
- Operacionalmente, porém, o mapeamento `status_galvanizacao` da proposta
  é 1:1 com o status da carga corrente
  (`load_status_to_area_status = {'AGUARDANDO_LIBERACAO': 'EM_CARGA',
  'LIBERADA_PARA_ENVIO': 'ENVIADO_GALVANIZACAO', 'RETORNO_PARCIAL':
  'RETORNOU_PARCIAL'}`, `backend_adapter.py:562`), então **na prática**
  uma proposta normalmente tem no máximo uma carga *ativa* por vez —
  **Cenário A** para o subconjunto "ativa". A distinção importa porque a
  navegação desta fase só deveria considerar cargas ativas (ver 1.3);
  cargas fechadas são histórico, não "a carga atual".
- Conclusão: implementado suporte a múltiplas cargas ativas (seção 19,
  navegação intermediária) mesmo que o fluxo normal do sistema hoje não
  produza esse caso, porque o modelo de dados não impede duas cargas
  simultaneamente ativas para a mesma proposta (ex.: itens diferentes da
  mesma proposta em duas cargas separadas). Não foi necessária nenhuma
  migration para responder esta pergunta — a resposta já estava no
  schema existente.

### 1.3 Ponto de leitura reutilizado

- `BackendAdapter.process_loads(process_id)` (`backend_adapter.py:1010-1023`)
  já existia e já era usado por `_register_galvanization_return` para
  achar cargas ativas da proposta. Reutilizado (não recriado) para a
  navegação. **Limitação conhecida, pré-existente e fora do escopo desta
  fase**: a implementação atual busca todas as cargas e depois os itens
  de cada uma (`galvanization_load_items(load_id)` por carga) — um
  padrão N+1 interno ao próprio método, não introduzido por esta fase.
  Como `GalvanizationLoadItem.proposal_id` já é indexado na API
  (seção 1.2), uma versão futura de `process_loads()` poderia trocar isso
  por uma única consulta filtrada por `proposal_id` — mas isso exigiria
  tocar `official_proposal_storage.py`/API, fora do escopo de UX +
  roteamento desta fase (seção 60 do prompt: não criar endpoint novo sem
  necessidade comprovada). Documentado aqui para uma fase futura.
- Confirmado por teste (`test_process_loads_called_once_per_action_center_open_not_per_card`):
  abrir a Central faz **uma única chamada** a `process_loads()`, não uma
  por card exibido.

## 2. Arquitetura

### 2.1 Arquivos criados

- `app/ui/action_center/handlers/galvanization.py`:
  - `ManageGalvanizationLoadHandler` — novo handler dedicado para
    `MANAGE_LOAD` (antes `LegacyActionHandler` + função module-level em
    `status_dialog.py`).
  - `OpenRelatedGalvanizationLoadHandler` — novo handler para o novo
    action id `OPEN_RELATED_GALVANIZATION_LOAD` (navegação, não status).
  - `_SelectGalvanizationLoadDialog` — diálogo mínimo de escolha quando
    há mais de uma carga ativa (seção 19).
  - `register_galvanization_return_legacy()` — a mesma função que antes
    vivia em `status_dialog.py` como `_register_galvanization_return`,
    **relocada sem nenhuma alteração de lógica**, continua envolvida por
    `LegacyActionHandler`.
  - `relevant_galvanization_loads(service, proposal_id)` — helper
    compartilhado entre provider e handler para resolver cargas ativas.
- `tests/test_galvanization_action_center.py` — 25 testes novos (seção 4).
- `docs/architecture/FASE6_GALVANIZACAO_ACTION_CENTER.md` — este documento.

### 2.2 Arquivos alterados

- `app/ui/action_center/provider.py`: adicionado `GalvanizationActionProvider`,
  que **envolve** `BackendActionProvider` (composição, não substituição —
  seção 7 do prompt: reusar antes de criar) e, somente quando
  `context.area == "GALVANIZACAO"`, acrescenta o descriptor de navegação
  `OPEN_RELATED_GALVANIZATION_LOAD` com base em `process_loads()`. Para
  qualquer outra área o comportamento é idêntico ao `BackendActionProvider`
  puro (coberto por `test_non_galvanization_area_is_untouched_by_the_wrapper`).
- `app/ui/status_dialog.py`: `StatusDialog` passa a construir
  `GalvanizationActionProvider(service)` em vez de `BackendActionProvider(service)`
  diretamente (continua sendo o único provider usado por todas as áreas —
  ele delega para o genérico fora de Galvanização); registry passa a
  registrar `ManageGalvanizationLoadHandler()` para `MANAGE_LOAD` e
  `OpenRelatedGalvanizationLoadHandler()` (escopado a
  `area="GALVANIZACAO"`) para o novo action id. As duas funções
  module-level específicas de Galvanização foram removidas daqui (foram
  para `handlers/galvanization.py`).

### 2.3 Uso do `LegacyActionHandler` antes/depois

| Action ID | Antes | Depois |
|---|---|---|
| `MANAGE_LOAD` | `LegacyActionHandler(_manage_load)` | `ManageGalvanizationLoadHandler()` |
| `REGISTER_GALVANIZATION_RETURN` | `LegacyActionHandler(_register_galvanization_return)` | **inalterado** — `LegacyActionHandler(register_galvanization_return_legacy)`, por decisão explícita (seção 3 abaixo) |
| `OPEN_RELATED_GALVANIZATION_LOAD` | não existia | `OpenRelatedGalvanizationLoadHandler()` (novo, nunca foi legacy) |

## 3. MANAGE_LOAD

- Fluxo anterior: `StatusDialog` → `LegacyActionHandler` → função
  module-level `_manage_load` → `GalvanizationLoadManagerDialog`.
- Fluxo novo: `ProposalActionCenter` → `ActionRegistry.resolve("MANAGE_LOAD")`
  → `ManageGalvanizationLoadHandler.execute()` → `GalvanizationLoadManagerDialog`
  (mesmo service, mesmo `proposal_id`, mesma checagem `exec() or changed`).
- Service reutilizado: `GalvanizationLoadManagerDialog`/API de cargas —
  nenhum service novo.
- Dialog reutilizado: `GalvanizationLoadManagerDialog` (inalterado).
- Comportamento parcial: elegibilidade de item/saldo continua
  inteiramente dentro do gerenciador oficial; o handler não filtra nem
  decide nada sobre itens (seções 10-12), só abre o diálogo com o
  `proposal_id` certo e reage ao resultado.

## 4. Navegação para carga (`OPEN_RELATED_GALVANIZATION_LOAD`)

- Não é um status: nunca é enviado a `update_status()`, nunca aparece em
  `process_actions()` do backend — é montado inteiramente no
  `GalvanizationActionProvider` (UI), coerente com a seção 15.
- Resolução: `relevant_galvanization_loads(service, proposal_id)` chama
  `service.process_loads(proposal_id)` e filtra por status ativo
  (`AGUARDANDO_LIBERACAO`, `LIBERADA_PARA_ENVIO`, `RETORNO_PARCIAL`).
- Zero cargas relevantes: nenhuma ação de navegação é oferecida (não
  aparece o card).
- Uma carga relevante: card "Abrir carga #N" → abre
  `GalvanizationLoadDetailsDialog(service, load_id, parent)` diretamente.
- Múltiplas cargas relevantes: card "Ver cargas da proposta" → abre
  `_SelectGalvanizationLoadDialog` (lista simples, usuário escolhe) →
  então `GalvanizationLoadDetailsDialog` da carga escolhida. Nunca abre a
  primeira carga arbitrariamente (seção 19, testado explicitamente).
- Concorrência (seção 43): o handler **não confia** no snapshot de cargas
  usado para montar o card — ele chama `process_loads()` de novo no
  clique. Se a carga relevante desapareceu nesse intervalo (ex.: outro
  usuário encerrou o retorno), mostra
  "A carga relacionada não está mais disponível. Atualize os dados da
  proposta." e chama `reload_context()` em vez de crashar ou abrir uma
  carga desatualizada (testado em
  `test_load_disappearing_between_open_and_click_shows_controlled_message`).
- Ao fechar `GalvanizationLoadDetailsDialog`: se `details_dialog.changed`
  for `True` (o usuário editou/liberou/registrou retorno de dentro da
  carga), a Central marca `_changed_since_open = True` e chama
  `reload_context()` — permanece aberta, mas already refletindo o novo
  estado; se o usuário fechar a Central em seguida, `reject()` já sabe
  que precisa contar como mudança (mesmo mecanismo que os outros
  handlers "que ficam abertos" já usavam).

## 5. Retorno da galvanização

- Onde permanece a ação: `REGISTER_GALVANIZATION_RETURN` continua
  disponível diretamente na proposta (compatibilidade temporária,
  seções 21-25), **e** agora também alcançável navegando por
  `OPEN_RELATED_GALVANIZATION_LOAD` → `GalvanizationLoadDetailsDialog` →
  "Registrar retorno" (menu já existente da carga, inalterado).
- Retorno parcial/total/múltiplos retornos: nenhuma lógica foi tocada —
  continuam inteiramente em `GalvanizationReturnDialog` e no service
  oficial (`register_galvanization_partial_return`, etc.). A Central da
  proposta não calcula nada disso.
- Decisão sobre o legado: `REGISTER_GALVANIZATION_RETURN` **permanece**
  em `LegacyActionHandler`, sem remoção, conforme mandado pela seção 24 —
  a navegação proposta→carga é nova nesta fase e ainda não tem
  comprovação de uso em produção suficiente para justificar desativar a
  entrada direta. Recomendação: reavaliar a remoção/depreciação em uma
  fase 8 dedicada, após telemetria real de uso da navegação.

## 6. Fiscal

- Nenhum arquivo do módulo Fiscal foi tocado. O retorno da galvanização
  continua acionando o processo Fiscal exatamente como antes — a Central
  de Ações não chama Fiscal em nenhum ponto, direto ou indireto.

## 7. Banco/API

- Nenhuma migration criada.
- Nenhum endpoint novo criado (seção 60) — a navegação reutiliza
  `BackendAdapter.process_loads()`, já existente.
- Nenhum SQL na UI — toda leitura passa por `service.process_loads()`
  (service/API oficial).

## 8. Testes

- Arquivo novo: `tests/test_galvanization_action_center.py` — 25 testes,
  cobrindo: abertura da Central (proposal_id/area/status corretos,
  ausência de ações de carga, estado vazio, não-gravação ao abrir/fechar),
  `MANAGE_LOAD` (handler dedicado, proposal_id correto, cancelamento não
  grava, sucesso sinaliza refresh, indisponível fora do status elegível),
  compatibilidade do retorno legado (continua via `LegacyActionHandler`,
  mensagem controlada sem carga ativa), navegação (zero/uma/múltiplas
  cargas, nunca escolhe a primeira arbitrariamente, concorrência/carga
  sumida, não é N+1, nunca é ação primária) e contrato do provider
  (todo descriptor tem handler registrado; áreas fora de Galvanização
  ficam bit-a-bit idênticas ao `BackendActionProvider` puro).
- Suíte completa (`pytest tests/`): **994 passed, 2 skipped, 2 failed**.
  As 2 falhas (`test_notification_bell.py::...test_badge_text_hides_at_zero_and_caps_at_99_plus`
  e `test_title_bar.py::...test_chat_unread_badge_hidden_when_zero`) são
  **pré-existentes e não relacionadas** a esta fase — confirmado
  reproduzindo-as com as alterações desta fase removidas via
  `git stash` (mesma falha, agora com um `TypeError` anterior ainda mais
  básico em `NotificationBell.__init__`, evidenciando que o problema é
  de outra frente de trabalho em andamento no branch, não desta fase).

## 9. Critérios de aceitação (seção 72 do prompt)

- [x] Galvanização usa `ProposalActionCenter` (já usava via `StatusDialog`
      antes desta fase; confirmado, não recriado).
- [x] Nenhuma Central duplicada foi criada.
- [x] `MANAGE_LOAD` usa handler específico (`ManageGalvanizationLoadHandler`).
- [x] `LegacyActionHandler` deixou de ser usado para `MANAGE_LOAD`. Continua
      em uso, deliberadamente, para `REGISTER_GALVANIZATION_RETURN`.
- [x] Itens elegíveis continuam definidos pelo domínio (nenhuma regra nova
      na Central).
- [x] Proposta parcial (`DISPONIVEL_PARCIAL`) continua funcionando sem
      alteração de regra.
- [x] Nenhuma duplicação de itens em carga (nenhuma validação foi movida
      para a UI).
- [x] Navegação proposta→carga implementada com segurança (concorrência,
      ambiguidade, carga inexistente).
- [x] Ações exclusivas da carga (editar/liberar/histórico/retorno) não
      migraram para a Central da proposta — confirmado que já viviam
      exclusivamente em `GalvanizationLoadDetailsDialog`.
- [x] Retorno continua contexto da carga (`GalvanizationReturnDialog`);
      entrada direta preservada por compatibilidade.
- [x] `reload_context()` atualiza corretamente a Central após navegação.
- [x] Correção administrativa inalterada.
- [x] Permissões reutilizadas (`can_edit`/`can_admin`), nenhum RBAC novo.
- [x] Nenhuma regra operacional alterada.
- [x] Nenhuma migration criada.
- [x] Regressão completa executada; falhas remanescentes são pré-existentes
      e documentadas na seção 8.
