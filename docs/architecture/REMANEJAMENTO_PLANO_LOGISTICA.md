# Remanejamento — plano de logística (proposta de 08/10/2026)

Plano refeito a partir da explicação do Henrique sobre como o remanejamento deve funcionar na fábrica. **Ainda não foi implementado nada deste plano**; ele precisa de aprovação (decisões na seção 8).

## 1. A ideia em uma frase

Remanejar é **trocar o dono das peças**: as peças prontas da proposta que já está na Expedição passam a ser da proposta que precisa entregar primeiro, e as peças que a segunda ainda estava fazendo passam a ser da primeira, **seguindo o caminho em que já estavam**. Nenhuma peça é criada nem some; só muda de dono.

### Exemplo (CP 05507 e CP 05600, quadro 450.400)

| | Antes | Depois de remanejar 4 |
|---|---|---|
| **CP 05507** (cedente) | 10 prontas na Expedição | 6 prontas na Expedição **+ 4 em fabricação** (as que eram da 05600) |
| **CP 05600** (destino) | 10 pedidas: 6 em fabricação, 4 na galvanização | **4 prontas na Expedição** + 2 em fabricação + 4 na galvanização |

- As 4 peças que passam para a 05507 são as **menos adiantadas** da 05600 (as que estavam em fabricação): seguem fabricar → galvanizar → Expedição, só que agora para a 05507. A 05600 fica com as mais adiantadas, para entregar mais cedo.
- A 05507 **continua na Expedição como parcial**, com as 6 prontas que sobraram. Quando as 4 peças novas chegarem à Expedição, elas **se juntam** às 6 (mesmo item, sem criar proposta nova) e a 05507 segue o processo normal.
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
- **R3 — O que a cedente recebe em troca.** A mesma quantidade de peças em andamento da destino (estágios 1 a 3), **preservando o estágio**. Ordem padrão: as **menos adiantadas** primeiro (decisão D1).
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

## 8. Decisões que preciso de você

- **D1 — Quais peças em andamento vão para a cedente?** Recomendo **as menos adiantadas** (a destino fica com as mais adiantadas e entrega mais cedo). A alternativa é as mais adiantadas.
- **D2 — Peça já separada na Expedição pode ser cedida?** Recomendo **sim** (continua pronta; a separação da cedente é refeita para o que sobrou).
- **D3 — Ordem de entrega das fases.** Recomendo começar pelas fases 1 e 2 (só leitura e troca de dono, sem mudar telas), depois 3 e 4, e só no fim liberar os galvanizados no assistente. Assim o remanejamento atual de itens sem galvanização continua funcionando durante o trabalho.

## 9. Ordem de execução proposta

| Fase | Entrega | Risco |
|---|---|---|
| A | Controle de peças por estágio (só leitura) + conciliação da base de dev | Nenhum (não grava nada) |
| B | Troca de dono por estágio no motor de remanejamento, com conferência de conservação | Médio |
| C | Produção e galvanização respeitando a troca; estado da cedente e do destino (R4–R6) | Alto (mexe em Produção e Galvanização) |
| D | Selos, aba "Remanejamentos" e itens cedidos/recebidos | Baixo |
| E | Assistente: libera galvanizados e mostra "o que acontece" | Baixo |

Tudo desenvolvido e testado na API de desenvolvimento; a API oficial só recebe com tudo definido e com a sua autorização.
