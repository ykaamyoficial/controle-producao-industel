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

