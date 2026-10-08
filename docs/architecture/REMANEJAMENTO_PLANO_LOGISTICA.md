# Remanejamento — plano de logística (proposta de 08/10/2026)

Plano refeito a partir da explicação do Henrique sobre como o remanejamento deve funcionar na fábrica. **Aprovado em 08/10/2026** com as decisões da seção 8. A execução segue por fases (seção 9); a Fase A está em andamento.

## 1. A ideia em uma frase

Remanejar é **trocar o dono das peças**: as peças prontas da proposta que já está na Expedição passam a ser da proposta que precisa entregar primeiro, e as peças que a segunda ainda estava fazendo passam a ser da primeira, **seguindo o caminho em que já estavam**. Nenhuma peça é criada nem some; só muda de dono.

### Exemplo (CP 05507 e CP 05600, quadro 450.400)

| | Antes | Depois de remanejar 4 |
|---|---|---|
| **CP 05507** (cedente) | 10 prontas na Expedição | 6 prontas na Expedição **+ 4 na galvanização** (as que eram da 05600) |
| **CP 05600** (destino) | 10 pedidas: 6 em fabricação, 4 na galvanização | **4 prontas na Expedição** + 6 em fabricação |

- As 4 peças que passam para a 05507 são as **mais adiantadas** da 05600 (as que já estavam na galvanização): seguem o caminho em que estavam (voltar da galvanização → Expedição), só que agora para a 05507. *(Decisão D1 do Henrique: a cedente volta a ter peças prontas mais cedo; a destino fica com as menos adiantadas.)*
- A 05507 **continua na Expedição como parcial**, com as 6 prontas que sobraram. Quando as 4 peças voltarem da galvanização, elas **se juntam** às 6 (mesmo item, sem criar proposta nova) e a 05507 segue o processo normal.
- Se a 05507 cedesse as **10**: ela sai sozinha da lista da Expedição e fica só nos processos (fabricação/galvanização) das peças que vieram da 05600. Ao chegarem, volta à Expedição.

## 2. As peças e seus estágios

Toda peça de um item está, em cada momento, em um destes estágios:

1. **A fabricar** (na produção)
2. **Fabricada, aguardando galvanização** (só itens galvanizados)
3. **Na galvanização** (em uma carga, ainda não voltou)
4. **Pronta na Expedição** (disponível)
5. **Entregue**

Regra de ouro: **o remanejamento nunca muda o total de peças nem o estágio de nenhuma delas.** Só muda quem é o dono. É isso que impede o fluxo de quebrar.

## 3. Como o sistema faz hoje e onde quebra

| Ponto | Hoje | Como deve ficar |
|---|---|---|
| Peças prontas da cedente | Passam para a destino (certo) | Igual |
| Peças em andamento da destino | Viram uma "obrigação de fabricar" da cedente: a cedente volta para a Produção como se fosse fabricar do zero | A cedente recebe **as próprias peças** da destino, no estágio em que estão |
| Item galvanizado | **Proibido** como origem (regra antiga da API, repetida em vários pontos) — por isso nada é encontrado: na base de desenvolvimento as 337 linhas prontas da Expedição são todas de itens galvanizados | Permitido, porque a peça de reposição segue o caminho dela (fabricar → galvanizar) |
| Reposição concluída | Entra **direto na Expedição** (pularia a galvanização) | Segue o estágio seguinte do item: galvanização, se o item for galvanizado |
| Cedente depois de ceder | Fica marcada como "pendente de fabricação" | Fica na Expedição como parcial, ou sai da lista se cedeu tudo |
| Marca de "substituída" | Só no histórico | Selo visível nas listas e nos detalhes (seção 5) |

## 4. Regras do plano

- **R1 — Mesma peça.** Só se remaneja entre itens com mesmo código, unidade e mesmo fluxo (galvanizado com galvanizado, interno com interno). Já é assim.
- **R2 — O que a cedente pode ceder.** Peças **prontas** na Expedição (separadas ou não) que ainda não foram entregues nem cedidas antes. Peça entregue ou retirada pelo cliente não entra.
- **R3 — O que a cedente recebe em troca.** A mesma quantidade de peças em andamento da destino (estágios 1 a 3), **preservando o estágio**. Ordem: as **mais adiantadas** primeiro, ou seja, as que estão na galvanização, depois as fabricadas aguardando galvanização, depois as a fabricar (decisão D1).
- **R4 — Cedeu tudo.** A cedente sai sozinha da lista da Expedição e fica só nos processos das peças que recebeu. Selo **"Substituída"**.
- **R5 — Cedeu parte.** A cedente continua na Expedição como parcial, só com as prontas que sobraram. As peças que recebeu seguem seus processos e, ao chegarem à Expedição, juntam-se às demais do mesmo item. Selo **"Parcialmente substituída"**.
- **R6 — Destino.** Recebe as prontas na Expedição como parcial (se ainda tem peças em andamento) ou como completa (se não falta nada) e continua nos processos pelas peças que manteve. Selo **"Recebeu remanejamento"**.
- **R7 — Sem desfazer.** Um remanejamento já gravado não é apagado; se foi um engano, faz-se outro no sentido contrário. O histórico fica inteiro.
- **R8 — Fiscal não muda.** Cada proposta continua com a mesma quantidade pedida e as mesmas NFs; só mudam as peças físicas que atendem cada uma. (A conferir na implementação: peça já faturada e retirada não pode ser cedida — R2.)

## 5. Como saber que uma proposta foi substituída

- **Selo nas listas** (Controle Geral, Produção, Galvanização, Expedição, Itens em expedição): "Substituída", "Parcialmente substituída" ou "Recebeu remanejamento", com o código do remanejamento (RM-000123) no balão de dica.
- **Detalhes da proposta → aba "Remanejamentos"**: de quem, para quem, quantas peças, **em que estágio estavam as peças trocadas**, motivo, quem fez e quando.
- **Linha do tempo** com a entrada "Cedeu 4 un do quadro 450.400 para a CP 05600 (RM-000123)".
- **Itens em expedição**: o item mostra "4 cedidas" / "4 recebidas" e dá para filtrar só as remanejadas.

## 6. O que muda no sistema (a detalhar depois da aprovação)

1. **Controle de peças por estágio** (API): leitura que, para cada item, diz quantas peças estão em cada estágio, usando o que já existe (produzido, cargas de galvanização, Expedição). Primeiro só leitura, sem mudar nenhum comportamento.
2. **Troca de dono por estágio** (API): hoje só existe a transferência de "obrigação de fabricar". Passa a existir transferência para os estágios 2 e 3 (peças fabricadas aguardando e peças dentro de carga de galvanização), registrada no mesmo remanejamento.
3. **Produção e galvanização respeitam a troca** (API): a reposição concluída segue para a galvanização quando o item é galvanizado; carga de galvanização enxerga as peças trocadas.
4. **Estado das propostas** (API): cedente vira parcial ou sai da Expedição conforme R4/R5; destino conforme R6; nada de "pendente de fabricação" para a cedente.
5. **Selos e aba de remanejamentos** (API + Desktop): campos de resumo na lista (papel: cedente/destino, quantidades) e as telas da seção 5.
6. **Assistente de remanejamento** (Desktop): libera itens galvanizados e, no passo de revisão, mostra "o que acontece" em linguagem simples: *"A CP 05507 entrega 4 peças prontas à CP 05600. 4 peças que estavam em fabricação na CP 05600 passam a ser da CP 05507."*

## 7. Como garantir que não quebra

- **Conservação conferida a cada gravação:** antes de confirmar, a API recalcula, por item e por estágio, o total de peças antes e depois; se qualquer total mudar, a transação é desfeita e nada é gravado.
- **Conciliação na base de desenvolvimento:** rotina que percorre todos os itens e confere a identidade `pedido = entregue + prontas + em andamento (por estágio)`; roda antes de começar e depois de cada fase para provar que nada mudou nos dados existentes.
- **Cenários de teste** (cada um com conferência de totais): só prontas, item não galvanizado; destino com peças a fabricar; destino com peças dentro de carga de galvanização; estágios misturados; cedente cede tudo; cedente cede parte e as peças voltam e se juntam; duas cedentes para uma destino; uma cedente para duas destinos em sequência; cancelamento no meio; entrega ou outro remanejamento ao mesmo tempo (versões e idempotência); repetir o mesmo pedido de confirmação.
- **Sem mexer nos remanejamentos já gravados** (nenhum dado antigo é reescrito; só novos usam a regra nova).

## 8. Decisões tomadas (08/10/2026)

- **D1 — Quais peças em andamento vão para a cedente?** **As mais adiantadas.** (A destino fica com as menos adiantadas e demora mais para completar; foi a escolha do Henrique.)
- **D2 — Peça já separada na Expedição pode ser cedida?** **Sim.** Continua pronta; a separação da cedente é refeita para o que sobrou.
- **D3 — Ordem de execução.** **Por etapas, galvanizados no fim**: o remanejamento atual de itens sem galvanização continua funcionando durante o trabalho.
- **D4 — Onde a cedente aparece.** **Nas duas telas**: na Expedição com as prontas que sobraram e na Galvanização (ou Produção) com as peças que recebeu, até elas voltarem; ao voltarem juntam-se às prontas.
- **D5 — Peça dentro de uma carga que já saiu.** **Pode trocar de dono dentro da carga**: a carga continua a mesma (motorista, dados), passa a listar essas peças no nome da nova proposta, o retorno vale para ela e tudo fica no histórico.
- **D6 — Remanejamentos antigos.** **Ficam como estão**: só os novos seguem a regra nova; nenhum dado já gravado é reescrito.
- **D7 — Fluxos diferentes (09/10/2026).** O remanejamento **acontece mesmo que o fluxo das propostas seja diferente**. As peças que trocam de dono **seguem o caminho que já tinham**, mesmo que a nova dona não fabrique internamente.
- **D8 — Destino sem fluxo definido.** Pode receber o remanejamento: as propostas **trocam as peças** e o destino **continua com o fluxo indefinido**, como estava desde o princípio.
- **D9 — Diferença de galvanização.** **Permitir sempre** (a origem galvanizada pode dar para um destino sem galvanização e vice-versa); a única regra de fluxo é a origem ter fluxo definido.

## 9. Ordem de execução proposta

| Fase | Entrega | Risco |
|---|---|---|
| A | Controle de peças por estágio (só leitura) + conciliação da base de dev | Nenhum (não grava nada) |
| B | Troca de dono por estágio no motor de remanejamento, com conferência de conservação | Médio |
| C | Produção e galvanização respeitando a troca; estado da cedente e do destino (R4–R6) | Alto (mexe em Produção e Galvanização) |
| D | Selos, aba "Remanejamentos" e itens cedidos/recebidos | Baixo |
| E | Assistente: libera galvanizados e mostra "o que acontece" | Baixo |

Tudo desenvolvido e testado na API de desenvolvimento; a API oficial só recebe com tudo definido e com a sua autorização.

## 10. Andamento

### Fase A — controle de peças por estágio (feita em 08/10/2026, só leitura)

- `api/app/modules/proposals/stage_ledger.py`: para cada item, quantas peças estão **a fabricar, aguardando galvanização, na galvanização, prontas e entregues** (mais "cedidas", "recebidas prontas" e "sem fluxo definido" para o item que ainda não tem fluxo). Usa as mesmas contas que a API já tinha (`calculate_item_balance`, disponibilidade da Expedição, cargas de galvanização, remanejamentos); nenhuma fórmula nova de negócio.
- Identidade conferida por item: `pedido = a fabricar + aguardando galvanização + na galvanização + pronta + entregue` (+ sem fluxo definido). Anomalias: estágio negativo, conta que não fecha, entregue + remanejado acima do disponível, Expedição divergente da produção/galvanização, linha de Expedição ausente, remanejado sem registro ou com registro diferente, galvanização em item sem galvanização.
- `GET /shipping/remanagements/stage-ledger?proposal_id=` devolve isso para uma proposta (será a base do "o que acontece" no assistente).
- `python scripts/reconcile_item_stages.py` (banco por `DATABASE_URL`) percorre a base inteira, sem gravar, e sai com código 1 se alguma conta não fechar. É o comando a rodar antes e depois de cada fase.
- Testes: `api/tests/test_stage_ledger.py` (24 casos, sem banco, inclui os dois lados de um remanejamento e o fluxo galvanizado em todos os estágios) e três testes de integração em `test_expedition_fiscal_read_path.py`.

**Resultado na base de desenvolvimento:** 1.216 itens conferidos (805 galvanizados, 310 simples, 101 sem fluxo definido); **1.215 fecham a conta**. Uma única anomalia, e é dado legado: **CP05300 item 2 (26 un)** consta como entregue 26 na Expedição, mas só 25,8582 voltaram da galvanização (a carga 12 enviou e recebeu 25,8582). Não foi corrigida; a Fase B só mexe em itens que fecham a conta.

### Fase B — troca de dono por estágio, com conferência a cada gravação (feita em 08/10/2026)

- `api/app/modules/proposals/stage_swap.py` (sem banco):
  - `plan_stage_swaps` decide quais peças em andamento do destino passam para cada origem, **das mais adiantadas para as menos adiantadas** (D1): na galvanização, depois fabricadas aguardando galvanização, depois a fabricar. A reposição que o destino recebeu de outro remanejamento não pode ser cedida de novo. Se o destino não tem peças em andamento suficientes, é erro (`StageSwapError`).
  - `verify_swap_conservation` compara os estágios de antes e de depois e confere que a gravação fez **só** a troca prevista: a origem perde `q` prontas e ganha `q` em andamento nos estágios do plano, o destino o inverso, entregue não muda, o total por estágio nos itens envolvidos é o mesmo e a conta de cada item continua como estava (diferença antiga de dado legado não é culpa do remanejamento).
- **Na gravação** (`confirm_remanagement_batch`): antes de mexer em qualquer coisa a API monta o plano de troca (sem peças suficientes → 409 `EXPEDITION_REMANAGEMENT_INVALID`, nada gravado); depois de gravar e dar `flush`, relê os estágios do banco, confere, e **qualquer diferença desfaz tudo** (409 `REMANAGEMENT_CONSERVATION_VIOLATION` com a lista do que não fechou).
- **Na revisão** (`/shipping/remanagements/review`): cada origem traz `stage_transfers` — quais peças do destino passam para ela, estágio a estágio (hoje, para itens sem galvanização, sempre "a fabricar"). Será o texto do "o que acontece" no assistente (Fase E). Destino sem peças em andamento suficientes aparece como erro `DESTINATION_IN_FLIGHT_INSUFFICIENT`.
- **O que não mudou:** itens galvanizados continuam bloqueados como origem (liberam na Fase E); o estado da cedente depois de ceder continua o de hoje (muda na Fase C); nenhum dado já gravado foi alterado.
- **Persistência dos estágios 2 e 3** (fabricada aguardando galvanização e dentro de carga): a tabela que registra a troca nesses estágios **fica para a Fase C**, junto com Produção e Galvanização que vão ler essa troca. Criá-la agora deixaria dado sem nenhum consumidor.
- Testes: `api/tests/test_stage_swap.py` (20 casos puros: ordem D1, várias origens, reposição recebida, falta de peças, e cada tipo de violação de conservação) e 4 integrações em `test_proposals_integration.py` (revisão mostra a troca; confirmação troca o dono e o total por estágio se mantém nos dois itens; falha simulada da conferência desfaz tudo e o mesmo pedido depois grava; destino sem peças em andamento é recusado). Os 23 testes de remanejamento que já existiam continuam passando.

### Fase C — desenho (08/10/2026; em andamento)

O sistema já cobre o item **sem galvanização**: a cedente fica na Expedição com as prontas que sobraram, entra na lista de itens de Produção pela reposição recebida (`production_reallocated_in_pending`) e, quando a reposição é concluída, soma ao disponível da Expedição (junta). O que falta é o item **galvanizado**, e por isso a Fase C se concentra nele. Pontos do código que hoje impedem:

1. A reposição concluída entra **direto** na Expedição (`complete_production_items`), pulando a galvanização.
2. As peças já fabricadas que o destino tem (aguardando galvanização ou dentro de carga) não têm como mudar de dono: só existe a transferência da obrigação de **fabricar**.
3. Três pontos usam `item.quantity` como "o que passa pela galvanização": disponível para carga, validação da carga e a conta do retorno (`galvanized`). Com troca de dono essa quantidade muda.

**Solução: quantidade da esteira (`pipeline`).** Para itens galvanizados, "quantas peças este item leva pela galvanização" passa a ser

    esteira = pedido − obrigação cedida + peças já fabricadas recebidas − peças já fabricadas cedidas + reposição concluída recebida

Sem nenhuma troca, a esteira é igual ao pedido, então **nada muda para os itens que nunca foram remanejados**. Com troca, os três pontos acima passam a usar a esteira, e o "junta de novo" sai da conta: o disponível da Expedição do item galvanizado é `retornado + pronto recebido`, menos o que foi cedido.

**Dados.** Tabela nova `remanagement_stage_transfers` (estágio `AWAITING_GALVANIZATION` ou `IN_GALVANIZATION`, quantidade, item de origem e de destino, carga e linhas de carga envolvidas). Para o estágio `IN_GALVANIZATION` a gravação **move as peças entre as linhas da carga** (a do destino diminui o enviado, a da cedente na mesma carga aumenta); linha que zera é desativada, nunca apagada. O estágio `TO_PRODUCE` continua sendo a transferência de obrigação que já existe.

**Etapas da Fase C** (cada uma testada e commitada):

- **C1 — esteira e leitura:** migração e modelo da tabela; conta da esteira; controle de peças por estágio, disponibilidade para carga, validação da carga e retorno usando a esteira; disponível da Expedição do galvanizado com o pronto recebido. Itens sem troca ficam idênticos (provado pelo script de conferência e pelos testes existentes).
- **C2 — gravar a troca no galvanizado:** aplicar as transferências (linhas de carga e tabela), concluir a reposição galvanizada seguindo para a galvanização e ressincronizar o estado das duas propostas. Tudo atrás de uma chave que mantém o galvanizado bloqueado até a Fase E; os testes ligam a chave.
- **C3 — estados da cedente e do destino (R4–R6) e testes de cenário de ponta a ponta:** cedeu tudo, cedeu parte e voltou, duas cedentes, uma cedente para dois destinos, propostas com filhas (por enquanto recusadas com mensagem clara).

#### C1 — esteira e leitura (feita em 08/10/2026)

- **Migração `20261008_0035`** (TRANSITIONAL, tabela nova e vazia com FKs): `remanagement_stage_transfers`. `EXPECTED_DATABASE_REVISION` passou a `20261008_0035`. **Aplicada na base de desenvolvimento** (`docker exec controle_producao_api_dev ... alembic upgrade head`); a API oficial e o banco oficial **não foram tocados** e só recebem esta migração quando a publicação for autorizada.
- **Esteira** (`galvanization_pipeline_quantity`, em `remanagement.py`): `pedido − obrigação cedida + reposição concluída recebida + fabricadas recebidas − fabricadas cedidas`. Três pontos da galvanização passaram a usá-la no lugar de `item.quantity`: disponível para carga, validação da carga e a conta do retorno (`galvanized`). Item que nunca foi remanejado tem esteira igual ao pedido: **comportamento idêntico**.
- **Expedição do galvanizado**: o disponível passa a ser `voltou da galvanização + pronto recebido` (antes só o que voltou), para o destino galvanizado não perder o pronto recebido quando a própria galvanização voltar; origem `REMANEJAMENTO`/`MISTO` quando há pronto recebido.
- **Controle de peças por estágio** usa a esteira (`awaiting = esteira − enviado`) e a reposição galvanizada concluída conta como "aguardando galvanização".
- **Prova de que nada mudou:** a conferência da base de desenvolvimento deu o mesmo resultado de antes (1.216 itens, 1.215 fecham) com as fórmulas novas; as suítes de migração, propostas, leitura da Expedição e paridade passaram (108 testes); 30 casos novos no controle de peças (os dois lados de um remanejamento galvanizado em cada estágio).

#### C2 e C3 — gravar a troca no galvanizado, estados e cenários (feitas em 08/10/2026)

- **Chave de liberação:** `remanagement.GALVANIZED_REMANAGEMENT_ENABLED = False`. Com ela desligada (hoje, e em produção) o galvanizado continua bloqueado como origem na busca e no motor de compensação; os caminhos antigos (`apply_remanagement`, `compatible-items`) ficam sempre bloqueados. Os testes ligam a chave por `patch`. Ela só é ligada de verdade na **Fase E**.
- **Gravação** (`confirm_remanagement_batch`): a parte "a fabricar" do plano vira a obrigação de fabricar de sempre (`ProductionAllocationTransfer`, só se for maior que zero); as peças **aguardando galvanização** viram uma linha em `remanagement_stage_transfers`; as peças **dentro de carga** são tiradas das linhas de carga do destino (da carga mais antiga para a mais nova) e colocadas **na mesma carga em nome da origem** (D5): a linha do destino que zera é desativada (nunca apagada), a carga ganha o evento `GALVANIZATION_ITEM_OWNER_CHANGED` nos dois lados e o peso total da carga é recalculado. Se as peças em carga mudaram entre a revisão e a gravação, o pedido é recusado (409) e nada é gravado.
- **Produção da reposição de item galvanizado:** ao concluir, ela **não** entra mais direto na Expedição: entra na esteira do item (volta a aparecer na fila da galvanização) e só fica pronta quando voltar da carga; aí junta-se às prontas que sobraram.
- **Estado da cedente (R4/R5/D4):** a marca "pendente de fabricação" só é posta se houve obrigação de fabricar de fato; quando a cedente recebeu peças já fabricadas, o estado dela passa a seguir a galvanização (parcial) até as peças voltarem — ela aparece na Galvanização **e** continua na Expedição com as prontas que sobraram; se cedeu tudo, sai sozinha da lista da Expedição e volta quando as peças retornam. O destino (R6) recebe as prontas na Expedição como parcial ou completo.
- **Recusa clara:** troca de peças já fabricadas com proposta que tem **parciais (filhas)** é recusada com mensagem explicando (as parciais seguem outro fluxo de junção); a troca de "a fabricar" não muda.
- **Testes:** `api/tests/test_galvanized_remanagement.py` (8 cenários de ponta a ponta, com a conta de cada item e o total das propostas conferidos a cada passo): chave desligada bloqueia; destino não produzido (a reposição passa pela galvanização e junta); peças dentro de carga trocam de dono na carga e o retorno vale para a origem; as mais adiantadas primeiro entre estágios; a conferência de conservação desfaz a gravação galvanizada; origem cede tudo, sai da Expedição e volta; duas origens para um destino; uma origem para dois destinos em sequência. Regressão: 169 testes (propostas, leitura da Expedição, paridade com o SQLite, estágios, remanejamento) passando.

### Fase E — itens galvanizados liberados no assistente (feita em 08/10/2026, antes da D por escolha do Henrique)

- `GALVANIZED_REMANAGEMENT_ENABLED` passou a `True`: o item galvanizado pronto na Expedição agora **é encontrado** como origem (busca, revisão e confirmação). Na base de desenvolvimento, simulação somente leitura com dados reais: destino CP 05557 (item 450.400, pede 40) passou a ter 7 origens; destino CP 05579 (item 300.8, pede 720) passou a ter 1; revisões válidas, com a troca "a fabricar" prevista. Os caminhos antigos (`apply_remanagement`, `compatible-items`) seguem bloqueados para galvanizado.
- **Assistente (passo 4):** cada origem ganha uma frase em linguagem simples — *"A CP 05507 entrega 4 un prontas à CP 05600. Em troca, passam a ser da CP 05507 (eram da CP 05600): 4 un na galvanização e 2 un ainda a fabricar."* — e a última coluna da tabela passa a mostrar **quais peças passam do destino para a origem, por estágio**, no lugar de "Produção que o destino passa à origem". Resposta antiga da API (sem o detalhe) continua funcionando.
- Testes: a regra "galvanizado como origem é válido" e a regra "inválido com a chave desligada" estão cobertas (`test_remanagement_compensation.py`, `test_galvanized_remanagement.py`); 7 testes novos do assistente (frase, estágios, leitura do detalhe da API, API antiga).
- **Pendente (Fase D, selos):** coluna "Remanejamento" nas listas de Expedição, Produção e Galvanização (Controle Geral fica de fora porque lê do SQLite local); o selo some quando a proposta volta a ficar inteira (decisões do Henrique). A aba "Remanejamentos" nos Detalhes e a marca nos Itens em expedição **não** foram pedidas agora.

### Fase F — fluxos diferentes (feita em 09/10/2026)

Motivo: a busca escondia origens por "fluxo de produção diferente" (origem só galvaniza e destino fabrica e galvaniza, ou destino ainda sem fluxo). Na base de desenvolvimento, de 127 itens destino com necessidade, 63 já achavam origem, **48 só estavam bloqueados pela diferença de fluxo** e 16 não tinham nenhuma peça pronta do mesmo código.

- **Compatibilidade (`items_are_compatible(..., strict_flow=False)`):** no motor novo só importam o **mesmo código e a mesma unidade** e a **origem ter fluxo definido** (a reposição dela segue o fluxo da própria origem). Galvanização, produção interna e fluxo do destino deixam de bloquear. O caminho antigo (`apply_remanagement`) continua com a regra estrita.
- **Estágio novo `UNDEFINED_FLOW`:** peças do destino que ainda não têm caminho. Entram na troca depois das outras (as menos adiantadas) e viram **"a fabricar" na origem**, que fabrica no fluxo dela. O destino fica com as prontas que recebeu, **não muda nenhuma marca de fluxo** e, enquanto sobrar peça sem fluxo, **continua na mesma área** (só ganha a situação "parcial com pendência"). Na conferência de conservação "a fabricar" e "sem fluxo" formam um só total (a peça muda de nome, não some nem aparece).
- **Origem que não galvaniza só recebe peças "a fabricar" (ou sem fluxo):** peças do destino que já estão fabricadas (aguardando galvanização ou em carga) só cabem em origem que passa pela galvanização; senão o pedido é recusado com mensagem clara, sem gravar nada, e o usuário pode escolher outra origem ou outra quantidade.
- **Origem que não fabrica internamente (só galvaniza):** passa a **dever peças a fabricar** depois de ceder prontas. Enquanto não forem feitas, a Produção trata o item dela como item de produção (`_hosts_reallocated_production`): aparece na lista de itens da Produção com a quantidade pendente, deixa iniciar e registrar a produção, e ao concluir as peças seguem o fluxo da própria origem (vão para a galvanização, voltam e juntam-se às prontas).
- **Expedição:** item sem fluxo definido que recebeu prontas mantém a disponibilidade recebida (a conferência periódica não a zera); o controle de peças usa a mesma regra.
- **Assistente:** a frase de "o que acontece" e a tabela mostram *"N un ainda sem fluxo definido (seguem o fluxo da origem)"* quando for o caso.
- **Testes:** `api/tests/test_remanagement_different_flows.py` (5 cenários de ponta a ponta: origem só galvaniza → destino que fabrica e galvaniza, com a reposição aparecendo e sendo feita na Produção; destino sem fluxo recebendo e continuando indefinido; item sem fluxo não serve de origem; peças já fabricadas recusadas para origem que não galvaniza; destino galvanizado não produzido recebendo de origem simples), mais os casos novos de `test_stage_swap.py` e `test_stage_ledger.py`. A conta de cada item e o total das propostas são conferidos a cada passo.
