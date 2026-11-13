# Especificação: imprimir relatório de LOG/carga com peso (Logística)

Data: 2026-11-10 · Status: **aguardando aprovação do Henrique** · Branch de trabalho: `logistica-melhorias`

## Intenção e porquê
Na Logística, o menu do botão direito e a Central de Ações (feitos hoje, `row_actions.py`) ainda não deixam emitir o relatório. Hoje o relatório só sai por dentro do detalhe do LOG/carga ("Gerar relatório") e não traz peso. O Henrique quer emitir direto da lista e saber quanto pesa cada pedido e o total.

## Objetivos
1. Ação **"Imprimir relatório"** no menu suspenso e na Central de Ações de **LOG** (aba LOGs) e de **Carga** (aba Cargas de entrega).
2. Relatório com **peso de cada proposta** e **peso total no final**.
3. Relatório com visual mais profissional.
4. Aviso para informar o peso quando faltar.

## Não-objetivos
- Sem impressão direta na impressora do Windows: continua PDF (salvar e abrir), de onde se imprime (D3).
- Sem campo novo de "peso total da proposta" no banco (D2).
- Sem mudança de migration. Só dev; nada na API oficial sem autorização.

## Decisões (Henrique)
| ID | Tema | Decisão |
|----|------|---------|
| D1 | Qual peso | Peso **total da proposta inteira** (soma dos itens: peso unitário × quantidade), igual ao do Controle Geral. |
| D2 | Peso faltando | Ao gerar, se houver proposta sem peso, abre **aviso** listando-as. Informar usa a **janela existente** `ItemWeightDialog` ("Informar pesos dos itens"), que grava com origem MANUAL. Sem campo novo de peso por proposta. |
| D3 | "Imprimir" | Faz o mesmo que "Gerar relatório" hoje: caixa "Salvar como", grava PDF e abre. Um só relatório para manter. |
| D4 | Seguir sem peso | O aviso oferece **"Informar peso"** e **"Gerar assim mesmo"**. Gerando assim mesmo: linha sem peso mostra "—" e o total diz quantas propostas ficaram sem peso (ex.: "12.340 kg · 2 de 5 propostas sem peso"). Nunca inventa número. Sem permissão de edição, só aparece "Gerar assim mesmo". |
| D5 | Melhorias do relatório | (a) visual profissional: logo, tabela com zebra, números à direita, rodapé com página X de Y; (b) resumo no topo (nº de propostas, peso total, datas, etapa); (c) no relatório de carga, subtotal de peso por LOG e total geral da carga; (d) rodapé "Emitido por <usuário> em <data e hora>". |

## Decisões do Claude (revisáveis)
- **C1, de onde vem o peso:** o desktop busca os itens de cada proposta do LOG pelos serviços que já existem (`service.proposal_items`) e soma, sem mudar a API de Logística. Trade-off: uma consulta por proposta ao gerar. Alternativa (mais rápida, mexe na API): devolver `total_weight` e contagem de itens sem peso nos itens do LOG. Recomendo começar pelo desktop; migrar se ficar lento.
- **C2:** "Imprimir relatório" reaproveita `report_actions.save_log_report` / `save_load_report`; o botão "Gerar relatório" do detalhe passa a usar o mesmo caminho (mesmo aviso de peso).
- **C3:** formato do peso: kg, vírgula decimal pt-BR, 2 casas ("1.234,56 kg").
- **C4:** a ação aparece para todo usuário que vê a lista (relatório é leitura); só o "Informar peso" depende de permissão de edição de itens (a mesma da Produção).
- **C5:** `Imprimir relatório` fica depois de "Detalhes" e fora das ações destrutivas; não vira ação primária.

## Restrições
Padrão `qt-industrial-ui` (identidade preservada, cor por token). PDF gerado por `QTextDocument`/`QPrinter` como hoje (`app/services/log_report.py`); rodapé com página X de Y exige tratar paginação nesse mecanismo.

## Premissas e riscos
- **Peso pode estar incompleto** em propostas antigas: coberto por D4.
- **Rodapé "página X de Y"** não é nativo do `QTextDocument.print_`; pode exigir desenhar o rodapé à parte (risco médio, resolver no plano).
- **Muitas propostas na carga** = muitas consultas de itens (C1). Medir com uma carga real de dev.
- O aviso não pode travar quando o usuário fecha a janela de pesos sem salvar: nesse caso volta ao aviso (ou cancela).
- Sem dado real de peso na dev, testar com dados de teste.

## Critérios de aceite
1. Clique direito e ícone, em LOG e em Carga, mostram "Imprimir relatório"; ele gera o PDF.
2. PDF do LOG mostra peso por proposta e total no final; PDF da carga mostra peso por proposta, subtotal por LOG e total da carga.
3. Resumo no topo e rodapé com emitente, data/hora e página X de Y.
4. Proposta sem peso: aviso aparece; "Informar peso" abre a janela de itens e, ao salvar, o relatório usa o peso novo; "Gerar assim mesmo" mostra "—" e a contagem de sem-peso no total.
5. Usuário sem edição: só "Gerar assim mesmo".
6. Testes novos cobrem soma de peso, peso faltando, subtotal por LOG, menu com a ação nas 2 abas; suíte sem regressão (a falha de tempo do `test_nomus_phase6_performance` é conhecida e fora de escopo).

## Dependências e ordem
1. Cálculo de peso (função pura, testável) → 2. HTML/PDF do relatório (LOG e carga) → 3. aviso de peso faltando + integração com `ItemWeightDialog` → 4. ação nos menus/Central → 5. "Gerar relatório" do detalhe no mesmo caminho → 6. testes, auditoria, doc da Fase 17.

## Perguntas em aberto
- Nenhuma bloqueante. Aprovar C1 (cálculo no desktop) ou preferir já na API? — Henrique.
