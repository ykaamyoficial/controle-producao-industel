# Especificação: melhorias na aba Logística (LOG e Carga)

Data: 2026-11-09. Branch de partida: `inspecao-datas`. Só na API de dev (8001). Nada na oficial sem autorização (ver spec-inspecao-logistica.md e spec-entrada-inspecao.md).

## 1. Intenção e porquê

O Henrique opera os LOGs por fora, nos portais da Equatorial, e registra o andamento no sistema. Hoje a Inspeção já tem a janela "Registrar andamento" com data escolhida por ele. A Logística ainda avança etapa em botões soltos, só aceita pedido com inspeção finalizada, não gera relatório e tem pontos visuais a consertar. O objetivo é igualar a Logística à Inspeção e abrir o LOG para pedidos que ainda estão em inspeção.

## 2. Objetivos

1. Janela "Registrar andamento" do LOG, no padrão da Inspeção, com data escolhida.
2. Incluir em um LOG pedido que ainda está na inspeção, em qualquer etapa.
3. Relatório PDF de uma página por LOG, com a logo da Industel.
4. Relatório PDF da Carga (romaneio), no mesmo estilo.
5. Consertar o painel "Dados do LOG" (vazio grande e caminhos quebrados).
6. Parar o contador de dias quando o LOG for entregue.
7. Filtros e exportação na lista de LOGs.

## 3. Não-objetivos

- Não integrar com o portal da Equatorial (D2 continua).
- Não guardar arquivos, só links (D9 continua).
- Não criar alerta de prazo (D7 continua).
- O relatório não leva links de NF, XML, BIM nem de comprovante.
- Não implementar o modo "atualizar atrasado" para o LOG (ele recusou).

## 4. Decisões do Henrique (2026-11-09)

| ID | Tema | Decisão |
|----|------|---------|
| L1 | Regra D5/D15 | Deixa de bloquear a entrada no LOG. O pedido entra em qualquer etapa da inspeção, com aviso e confirmação ("Incluir mesmo assim"). Segue o princípio de que o sistema nunca trava. |
| L2 | Pedido sem DOC BIM | A lista de propostas do LOG mostra a etapa atual da inspeção de cada pedido (ex.: "Inspeção: visita agendada"). O LOG mostra quantos pedidos ainda não têm DOC BIM. |
| L3 | Janela de andamento | Um botão "Registrar andamento" no topo do LOG abre uma janela com todas as etapas: Documentação enviada (links NF, XML e BIM), Aprovada para entrega e Entregue no CD (link do comprovante). Cada uma tem data "Aconteceu em" (Hoje/Ontem) e observação livre. Sai o botão "Entregue no CD em" do topo. "Editar datas" continua separado. |
| L4 | Atualizar atrasado | Fora do escopo do LOG. |
| L5 | Relatório do LOG | PDF de uma página enxuta: logo, código do LOG, estado, etapa, datas (reservada, carregamento, entrega no CD), carga e tabela de propostas com pedido (PD), cliente/obra e situação da inspeção. Sem links. |
| L6 | Relatório da Carga | PDF da carga no mesmo estilo, com os LOGs do caminhão e as propostas de cada um. |
| L7 | Painel "Dados do LOG" | Consertar o vazio e mostrar só o nome do arquivo nos campos NF, XML e BIM, com "Abrir" e o caminho completo na dica. |
| L8 | Contador de dias | Para quando o LOG é entregue. A lista mostra "Entregue" como etapa final. |
| L9 | Lista | Filtros por etapa, estado e carga, e exportação da lista em XLSX (decidido em 2026-11-09). Exige adicionar `openpyxl` ao `requirements` e ao build/instalador do Desktop. |
| L10 | Pedido já no LOG | Se a inspeção for reprovada, ou o PD mudar para um sem DOC BIM, o pedido continua no LOG com aviso na lista e no relatório, mostrando a etapa atual da inspeção. Substitui a regra de `proposal_links.py` que tira a proposta do LOG (decidido em 2026-11-09). |

## 5. Decisões do Claude (ajustáveis)

- **Exportação XLSX:** o Henrique escolheu `.xlsx` (L9). O construtor usa `openpyxl` (versão fixada), com cabeçalho e larguras de coluna, e confere que o build PyInstaller inclui a biblioteca.
- **PDF:** reaproveitar `QPrinter` em formato PDF, que `app/ui/process_page.py` já usa. Sem dependência nova. A logo vem do arquivo de recursos que o Desktop já usa (o construtor confere qual).
- **"Entregue" como etapa:** hoje a entrega é uma data (`delivered_on`), não uma etapa. O construtor decide se vira derivado (etapa exibida = "Entregue" quando `delivered_on` existe) ou se ganha estado novo. Preferir o derivado, que dispensa migration.
- **Aprovar com pedido sem DOC BIM:** só avisa e pede confirmação, nunca bloqueia (consequência de L1).
- **Observação livre:** vai para o histórico do LOG. Se não existir coluna, usar o campo de texto do evento.
- **Data do andamento:** o avanço grava o evento com a data escolhida; as etapas ganham a data real. Validação só de data impossível (31/02). Datas incoerentes só avisam ("Marcar mesmo assim"), como na Fase 16.

## 6. Restrições e premissas

- PySide6 + FastAPI + PostgreSQL. Desktop nunca fala com o banco. Toda regra nova fica na API.
- Visual segue a skill `qt-industrial-ui`: um botão primário por tela, cor só por token, janelas no padrão de "Detalhes da proposta".
- Migration, se houver, exige entrada em `migration_risk_registry.json`.
- Permissão: gerar relatório exige só ver a Logística; registrar andamento e incluir pedido exigem editar.
- Sem dados pessoais novos. O PDF sai no computador de quem pede, sem envio a terceiros.

## 7. Riscos

- A L1 enfraquece a garantia de que todo pedido no LOG tem DOC BIM. Relatórios e a carga devem mostrar a situação da inspeção para ninguém confundir.
- O `proposal_links.py` hoje tira a proposta do LOG quando o PD muda para um sem inspeção finalizada. Pela L10 essa regra deixa de tirar e passa a avisar. Os testes atuais dessa regra precisam ser reescritos.
- `openpyxl` é dependência nova: fixar versão e conferir o build do instalador (como já aconteceu com `tzdata`).
- Carga só aceita LOG aprovado. Com pedidos sem DOC, isso continua valendo, mas é decisão a rever.
- Contador parado depende de `delivered_on`. LOGs antigos sem essa data continuam contando.

## 8. Critérios de aceite

1. Registrar andamento do LOG pede a data, aceita Hoje/Ontem e qualquer data possível, e grava a data no histórico.
2. É possível incluir no LOG um pedido com inspeção em qualquer etapa, após confirmar o aviso, e a lista mostra a etapa dele.
3. O PDF do LOG sai em uma página, com logo, código, pedidos e propostas.
4. O PDF da Carga lista os LOGs e as propostas de cada um.
5. O painel "Dados do LOG" não tem vazio e não quebra o caminho em várias linhas.
6. LOG entregue mostra "Entregue" e o contador de dias para.
7. Filtros por etapa, estado e carga funcionam juntos com a busca. A exportação respeita os filtros.
8. Testes de API e de Desktop novos passam e a suíte oficial não regride.

## 9. Registro de decisões

Ver tabela da seção 4 (L1 a L9). Quem decidiu: Henrique, em 2026-11-09. A seção 5 lista o que é decisão do Claude.

## 10. Dependências e ordem sugerida

1. L1/L2: API deixa de bloquear e devolve a etapa da inspeção; revisar `proposal_links.py`. Base para o resto.
2. L3: janela "Registrar andamento" do LOG (API aceita data real por etapa).
3. L8 e L7: contador e painel (independentes, pequenos).
4. L9: filtros e exportação.
5. L5 e L6: relatórios PDF (dependem de L2 para mostrar a situação da inspeção).

## 11. Perguntas em aberto

| Pergunta | Dono |
|----------|------|
| Onde fica o arquivo da logo para o PDF? | Construtor |
