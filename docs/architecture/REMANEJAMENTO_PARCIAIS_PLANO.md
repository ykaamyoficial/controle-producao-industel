# Remanejamento parcial por itens — análise e plano (09/10/2026)

Pedido do Henrique: quando o remanejamento tira **só uma parte dos itens** de uma proposta, a proposta deve **seguir a lógica de parciais que o sistema já tem** — o que fica na Expedição é a **P1**, o que passa a ocupar o lugar do que foi substituído é a **P2** — em vez de ficar uma proposta só, misturada. **Este documento é só plano: nada foi implementado.** O restante do plano de logística está em `REMANEJAMENTO_PLANO_LOGISTICA.md`.

**Decisões do Henrique (09/10/2026):** D10 — quando sai só parte da quantidade de um item, **o item é dividido em dois**; D11 — o **destino também divide**; D12 — nomes confirmados (P1 = fica na Expedição, P2 = ocupa o lugar do substituído, uma filha por lugar); D13 — os remanejamentos que ele já fez na base de teste são **ajustados só na base de teste**, por script.

## 1. Como o remanejamento funciona hoje

Remanejar é **trocar o dono das peças por estágio** (plano de logística, fases A–F e marca da D, todas feitas): a origem entrega peças prontas ao destino e recebe em troca peças em andamento do destino (as mais adiantadas primeiro), seguindo o caminho que já tinham. Cada gravação passa pela conferência de conservação (nenhuma peça nasce ou some). O que está **certo** e fica como está:

- a conta por item e por estágio (`stage_ledger.py`, `stage_swap.py`, `confirm_remanagement_batch`);
- fluxos diferentes entre as propostas e destino sem fluxo definido;
- a reposição que volta pela galvanização e se junta às prontas;
- a marca vermelha na proposta e a janelinha "para onde foram as peças".

O que **não está como o Henrique espera**: tudo isso acontece **dentro de uma proposta só**, com a linha do item guardando peças em estágios diferentes (ex.: 6 prontas + 4 vindas do destino). O estado da proposta fica misturado.

## 2. Como as parciais funcionam hoje (a lógica que deve ser seguida)

No fluxo oficial só existe **um lugar** que cria parciais: a conclusão da produção (`complete_production_items`, `source = "PARTIAL_PRODUCTION"`). O desenho é:

1. **Parcial = conjunto de itens inteiros.** A filha `CP05378-1` recebe linhas de item (`item.proposal = child`), com o `ExpeditionItem`, as linhas de carga e o `FiscalItem` indo junto. A quantidade da linha não é dividida (a numeração do item é única por proposta e o fiscal é 1 para 1 com o item).
2. **Mãe e filhas.** Enquanto a mãe não tem item próprio pendente, ela vira só referência no Controle Geral (`PARENT_PROPOSAL_OPERATIONAL_DEATH`); cada filha caminha sozinha pela galvanização, Expedição e Fiscal (a filha só entra no Fiscal ao chegar na Expedição; a mãe continua sendo a referência fiscal).
3. **Filhas iguais se juntam.** Filhas com a mesma área, o mesmo status e as mesmas cargas viram uma só (`_merge_equal_status_partial_children`); nas listas aparecem como `CP05378-1,2`.
4. **A mãe renasce.** Quando todas as filhas ativas estão na Expedição com o mesmo status, os itens voltam para a mãe e as filhas se desativam (`_reborn_parent_when_children_converge`, chamada ao registrar retorno de carga e ao separar/entregar na Expedição).
5. **Item com peças em lugares diferentes não se divide** (hoje). Retorno parcial de carga e entrega parcial mantêm a linha do item inteira, com as quantidades em estágios diferentes. **Dividir a linha do item é capacidade nova**, que este plano acrescenta (decisão D10).

O legado (Desktop antigo) tinha a ideia do Henrique: "se só parte do material da origem for usada, a origem fica na Expedição com o resto e um **novo subprocesso de reposição** vai para produção" (`PROPOSAL_STATE_MACHINE_CURRENT_AS_IS.md`). Os campos `origem_remanejamento` e `proposta_reposicao` ainda existem na tela de Resumo e no relatório de Parciais, mas a API nunca os preenche.

## 3. O problema, com a base de desenvolvimento

Leitura feita em 09/10/2026 (somente leitura):

| Proposta | O que aconteceu | Como está hoje | Onde aparece |
|---|---|---|---|
| CP 05493 | cedeu 1 item de 8 (RM-000002) | **uma proposta só**: 7 itens prontos + 1 a fabricar; área "Expedição", produção "Item pendente de fabricação" | Expedição **e** Produção ao mesmo tempo |
| CP 05640 | recebeu 1 item pronto (RM-000002) | área Produção, "Não iniciado", mas com 1 item pronto na Expedição; 7 itens sem fluxo | Expedição **e** Produção ao mesmo tempo |
| CP 05492 | cedeu tudo, 8 de 8 (RM-000001) | 0 peças prontas, 8 a fabricar, mas a **área ainda diz "Expedição"** | só Produção (o Controle Geral mostra Expedição) |
| CP 05643 | recebeu tudo (RM-000001) | completa na Expedição | só Expedição (certo) |

Outros pontos achados na análise:

- A troca de **peças já fabricadas** (aguardando galvanização ou em carga) é **recusada** quando a proposta tem parciais (`_stage_swaps_for_plan`). Como todo remanejamento passará a criar famílias, isso precisa ser resolvido.
- A conferência de conservação relê os itens **pela proposta**; se um item mudar de proposta durante a gravação ela não o encontra. Precisa ler **por item**.
- A marca de remanejamento (fase D) é calculada pelo balanço de peças cedidas/recebidas; no formato novo ela passa a vir da família (seção 7).
- Todos os remanejamentos feitos na dev tiram **itens inteiros** (quantidade pedida = quantidade cedida), o que facilita converter os três casos (seção 9).

## 4. O que o Henrique pediu, em regras

- **R-P1 — Cedeu parte dos itens.** A proposta se divide em **filhas**, como as parciais de hoje: **P1** = o que continua pronto na Expedição; **P2** = o que foi substituído e agora segue o caminho das peças que vieram do destino (produção, galvanização…). A mãe vira referência no Controle Geral. Se as peças que vieram estão em lugares diferentes (uma em produção, outra em carga), vira **uma filha por lugar** (P2, P3…), e as de mesmo lugar se juntam sozinhas.
- **R-P2 — Cedeu tudo.** Não há o que dividir: a proposta inteira volta para o lugar das peças que recebeu (a área passa a refletir isso — corrige o caso CP 05492). Se as peças estão em lugares diferentes, vira uma filha por lugar.
- **R-P3 — Destino.** Mesma lógica: o que recebeu pronto vira filha na Expedição; o restante continua na proposta, no lugar onde estava. Se recebeu tudo, vai inteira para a Expedição (como hoje).
- **R-P4 — Voltar a ser uma só.** Quando as peças da P2 chegam à Expedição, P1 e P2 se juntam e a mãe renasce — o que o sistema já faz com as parciais.
- **R-P5 — Famílias já existentes.** Se a origem (ou o destino) já é filha ou mãe, as novas filhas nascem da **mesma mãe**, com o próximo número (`partial_number = maior + 1`), e a filha que perde todos os itens se desativa como numa fusão.
- **R-P6 — Parte da quantidade (D10).** Se o remanejamento leva 4 de 10 peças de um item, o item é **dividido em duas linhas**: 6 (que ficam) e 4 (que ficam no lugar do que foi substituído); cada linha cai na filha certa. A mesma divisão vale no destino (o item que recebeu 4 de 10 prontas vira uma linha de 4 prontas e outra de 6 em andamento).
- **R-P7 — O pedido não muda.** Somando as linhas de um mesmo item do pedido (mesmo número de item na família), a quantidade pedida é sempre a original; o fiscal continua um `FiscalItem` por linha, acompanhando a linha.

## 5. Arquitetura recomendada: "lotes físicos" (decisão técnica D14, pendente)

Pensando peça a peça, depois do remanejamento cada pedido tem **dois lotes de peças em situações diferentes**: no pedido da origem, as peças que ficaram (prontas) e as que vieram do destino (em andamento); no pedido do destino, as que chegaram prontas e as que ele ainda espera. Cada lote vira **uma linha** com uma situação só. Assim as parciais do sistema funcionam sem nenhuma conta especial.

**Operação por linha de remanejamento** (origem X do pedido S, destino Y do pedido D, `q` peças):
1. `X` perde `q` peças prontas: nasce a linha **Y1** (identidade do pedido D: número do item, descrição, observações; quantidade `q`) levando as `q` peças prontas (a disponibilidade da Expedição é dividida; a separação da origem é refeita, como hoje — D2).
2. `Y` perde `q` peças em andamento, escolhidas **das mais adiantadas** (D1) — uma linha **X2** por estágio (identidade do pedido S, quantidade igual às peças daquele estágio): em carga (as linhas de carga são divididas dentro da mesma carga, D5), aguardando galvanização, a fabricar. O fluxo de cada linha segue o **caminho das peças** (D7–D9): a linha X2 de peças a fabricar nasce marcada como "produzir internamente", mesmo que a linha original da origem não produza.
3. Linha que perderia **todas** as peças é **reaproveitada** (não vira linha vazia): continua com o mesmo número, id e histórico e passa a levar o lote que chegou.
4. **Realinhar as famílias** (seção 4) agrupando as linhas por situação e criando/movendo as filhas.

**Por que isto é mais simples que o motor atual:** as linhas passam a ser "puras" (cada uma com uma situação só), então **não há mais transferências de obrigação de fabricar, nem de estágio, nem a fórmula especial da esteira da galvanização, nem a "produção hospedada"** para os remanejamentos novos. A conservação vira: a soma das peças por produto e por situação nas propostas envolvidas não muda, e a soma da quantidade por item do pedido (R-P7) também não. O motor atual continua só para ler o que já foi gravado (decisão D6).

**Alternativa descartada:** manter o motor de transferências e dividir as linhas depois. A fórmula da esteira da galvanização (`pedido − cedido + reposição concluída + …`) contaria em dobro a linha dividida, e cada passo da vida da peça (produção, carga, retorno) teria de tratar a linha nova como caso especial.

**Mudança de rota que isso significa:** é um motor novo (atrás de uma chave, como foi o galvanizado), não um ajuste. Por isso a **Fase P0 é uma prova de conceito** com o pior caso (galvanizado em carga, parte da quantidade, destino sem fluxo, divisão do fiscal) antes de seguir.

## 6. O que muda no sistema

**API**
1. **Dividir linha** (`split_item_row`): nova linha com a identidade do pedido de destino, peso/quantidade proporcionais, `ExpeditionItem`, linhas de carga e fluxo do lote; limpa `legacy_id` e `source_hash`; eventos nas duas propostas. **Juntar linhas** (`rejoin_item_rows`): soma quantidade, `ExpeditionItem`, linhas de carga e `FiscalItem` (e as notas já lançadas), refaz o peso e aponta de volta as referências (remanejamentos, obrigações antigas, eventos).
2. **Motor por linhas** (`confirm_remanagement_batch` v2, atrás de uma chave): faz as quatro etapas da seção 5 numa transação, com a conferência de conservação nova; recusa se a divisão pedir mais do que já foi faturado numa linha (o `FiscalItem` não pode ficar com total menor que o faturado).
3. **Famílias:** extrair a criação de filha (hoje embutida em `complete_production_items`) para função própria; `realign_family(proposal)` agrupa as linhas por situação (pronto na Expedição / a fabricar / aguardando galvanização / em carga N / sem fluxo) e cria ou move filhas; estado de cada filha recalculado com as funções que já existem.
4. **Fusão e renascimento:** `_merge_equal_status_partial_children` e `_reborn_parent_when_children_converge` passam a **juntar linhas de mesmo número** (hoje só movem linhas, e duas linhas "3" na mesma proposta violam a unicidade); rodam também ao fim do remanejamento e nos pontos em que as peças chegam (retorno de carga, conclusão de produção, separação, entrega).
5. Conferência de conservação **por linha**; liberar a troca de peças fabricadas com parciais (hoje recusada).
6. Resposta de confirmação diz **quais propostas nasceram**; filhas de remanejamento marcadas (`source = "PARTIAL_REMANAGEMENT"`); preencher `origem_remanejamento` e `proposta_reposicao`.
7. **Marca** (fase D): no formato novo a marca vem da família — a proposta fica marcada enquanto for filha (ou mãe) de um remanejamento ainda não reunido; o texto ("Substituída" para a que ocupa o lugar do substituído, "Recebeu remanejamento" para a que recebeu pronto) e a janelinha (mãe, filhas, código RM) se mantêm.

**Desktop**
1. Passo de revisão do assistente explica a divisão: "A CP 05493 vai ser dividida: a **CP 05493-1** (7 itens) continua na Expedição e a **CP 05493-2** (1 item) vai para a Produção no lugar do que foi substituído."
2. Janelinha da marca mostra a mãe e as filhas; listas e página de Parciais já entendem mãe/filhas. Nenhuma tela nova.

## 7. Riscos

1. **Dividir e juntar linhas** é a parte mais delicada: expedição, cargas, fiscal (um `FiscalItem` por linha, com histórico de nota), peso, numeração e as referências antigas. Por isso a prova de conceito primeiro, e testes de ida e volta (dividir e juntar devolve exatamente o original).
2. **Reimportação do Nomus**: se a proposta for reimportada com a quantidade original, pode "desfazer" a divisão (a linha original voltaria a 10). Conferir como a importação trata proposta que já existe e, se preciso, travar a reimportação de proposta com divisão ativa.
3. **Status de Expedição diferentes**: a junção exige o mesmo status; a P1 pode estar "separação iniciada" e a P2 chegar "aguardando separação", e as duas não se juntam. Avaliar se a regra aceita isso para famílias de remanejamento.
4. **Peças da mesma linha em lugares diferentes** (cedido por inteiro, mas parte em produção e parte em carga): resolve-se dividindo por estágio, uma linha por estágio.
5. **Fiscal**: peça com NF emitida e ainda não entregue que seja cedida; o plano recusa quando o faturado não cabe, mas a regra (R2/R8 do plano de logística) precisa ser conferida com o fiscal antes do primeiro uso real.
6. **Várias origens para um destino e vice-versa**: o realinhamento roda uma vez por proposta ao fim do lote; a ordem de travas (`_locked_remanagement_participants`) precisa cobrir as propostas que nascem.
7. **Mais linhas por proposta** e desempenho das listas/réplica: as linhas e filhas novas sincronizam pelo mesmo caminho das parciais de produção; precisa de teste de paridade com a lista de Controle Geral.
8. **Remanejamentos antigos** (os da API oficial): ficam como estão (D6); só os novos usam o motor novo.

## 8. Fases de execução propostas

| Fase | Entrega | Risco |
|---|---|---|
| P0 | **Prova de conceito**: dividir/juntar linha (ida e volta idêntica), uma linha de remanejamento no motor novo com os piores casos, conservação nova — atrás de uma chave, sem mudar o comportamento atual | Alto (decide o resto) |
| P1 | Motor por linhas completo (origem e destino, vários estágios, várias origens), ainda sem criar filhas; conferência por linha; liberar troca fabricada com parciais | Alto |
| P2 | Famílias: extrair criação de filha; `realign_family`; cedeu tudo (área correta); famílias já existentes; mãe vira referência | Médio-alto |
| P3 | Chegada das peças: fusão e renascimento juntando linhas, estados de Expedição diferentes, retorno de carga e entrega | Alto |
| P4 | Assistente explica a divisão; marca nova; janelinha com mãe/filhas; campos de origem na API | Baixo |
| P5 | Ajuste **só na dev**: desfaz as trocas antigas (RM-000001 e RM-000002, só se nada andou depois — as obrigações estão com 0 concluído) e reaplica pelo motor novo; conciliação da base | Médio |
| P6 | Cenários de ponta a ponta, documentação, virar a chave para o motor novo na dev | Baixo |

**Cenários de teste (ponta a ponta, com a conta de cada linha, o total por produto e o total por item do pedido conferidos a cada passo):** itens inteiros; parte da quantidade; peças em produção, em carga e aguardando carga na mesma origem; cedeu tudo; destino com tudo e com parte; duas origens para um destino; uma origem para dois destinos em sequência; origem que já é filha; mãe renascendo e linhas se juntando; retorno de carga; entrega da P1 antes da P2; item com NF parcial; repetir a mesma confirmação; réplica local; dividir e juntar (ida e volta).

Tudo continua sendo desenvolvido e testado só na API de desenvolvimento; a API oficial só recebe com tudo definido e com a autorização do Henrique.

## 9. Decisões

Tomadas pelo Henrique: **D10** dividir o item em dois quando sai parte da quantidade; **D11** o destino também divide; **D12** nomes P1/P2 confirmados (uma filha por lugar); **D13** ajustar os remanejamentos da base de teste, só nela.

Pendente (recomendação nossa): **D14 — motor novo "por linhas"** (seção 5), com a Fase P0 como prova de conceito antes de seguir, em vez de manter o motor de transferências e dividir depois. Recomendação: **sim**.
