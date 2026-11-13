# Plano: relatório de LOG/carga com peso

Especificação aprovada: `docs/spec-logistica-relatorio-peso.md` (D1-D5, C1-C5).
Objetivo: "Imprimir relatório" nos menus de LOG e Carga; relatório com peso por proposta, subtotal por LOG, total, resumo, rodapé; aviso de peso faltando.
Arquitetura: função pura de peso (`app/services/log_weight.py`) alimenta `log_report.py`; `report_actions.py` orquestra aviso + PDF; menus chamam `report_actions`.
Tecnologia: PySide6 `QTextDocument`/`QPrinter` (como hoje), unittest/pytest. Só desktop e dev, sem API nem migration.
Restrições: skill `qt-industrial-ui`; patch de `QMessageBox`/diálogos no módulo onde são importados; commit local por subsistema, sem push.

## Fatos conferidos no código
- Itens do LOG (`LogItemOut`) trazem `proposal_id`, `proposal_number`, `status` e `removed_at`; não trazem peso. Só itens ativos entram no relatório.
- Peso mora nos itens da proposta: `service.proposal_items(proposal_id)` devolve dicts com `id`, `quantidade`, `peso` (lido por `ItemWeightDialog`). **T1 confirma se `peso` é unitário ou total** antes de somar.
- `ItemWeightDialog(service, proposal_id, parent)` grava via `service.update_item_weights`; `saved_count` > 0 indica que salvou.
- Menus: `RowAction(label, icon, enabled, callback, description, primary=, destructive=)` em `logistics_page.py:463-479`.
- Usuário logado: `service.user_name()`.

## Tarefas

### T1. Cálculo de peso (função pura)
Arquivos: criar `app/services/log_weight.py`, `tests/test_log_weight.py`.
Interface:
- `proposal_weight(items: list[dict]) -> tuple[float | None, int]`: retorna (peso total conhecido ou `None` se nenhum item tem peso, quantidade de itens sem peso). Regra: item sem peso (0/vazio) conta como sem peso, nunca como 0.
- `fmt_kg(value: float | None) -> str`: "1.234,56 kg" ou "—".
Passos: ler `proposal_items` real/fake para fixar se `peso` é unitário (então total = `peso × quantidade`); teste falha → implementar → teste passa → commit.
Pronto: casos todos-com-peso, parcial, nenhum, lista vazia, quantidade fracionada.

### T2. Coleta de pesos de um LOG/carga
Arquivos: `app/services/log_weight.py`.
Interface: `collect_weights(service, logs: list[dict]) -> dict[int, tuple[float | None, int]]` por `proposal_id` (itens ativos; proposta repetida em 2 LOGs consulta uma vez). Erro de API em uma proposta vira "sem peso" com aviso, não derruba o relatório.
Pronto: teste com `FakeService` completo (sem abrir diálogo real).

### T3. Relatório (visual + peso + resumo + rodapé)
Arquivos: `app/services/log_report.py`, `tests/test_log_report*.py` (ajustar existentes).
- `log_report_html(log, weights, issued_by, issued_at)` e `load_report_html(...)`: cabeçalho com logo; quadro-resumo (nº de propostas, peso total, datas, etapa); tabela com zebra e coluna **Peso** à direita; linha **Total**; texto "N de M propostas sem peso" quando houver; na carga, subtotal por LOG e **Total da carga**; cores por token da marca.
- Rodapé "Emitido por X em dd/mm/aaaa hh:mm · página X de Y": `QTextDocument.print_` não faz sozinho; desenhar com `QPainter` por página (loop de `QPrinter.newPage`) ou, se ficar frágil, rodapé estático "Emitido por … em …" sem numeração (registrar como `shortcut:` no código).
Pronto: testes de HTML (peso, total, "—", subtotal) e geração de PDF não vazio.

### T4. Aviso de peso faltando e orquestração
Arquivos: `app/ui/report_actions.py`, novo `app/ui/missing_weight_dialog.py`, testes.
- Em `save_log_report/save_load_report`: calcula pesos; se há proposta sem peso, abre `MissingWeightDialog` listando-as, com **Informar peso** (só `can_edit`; abre `ItemWeightDialog` da proposta escolhida, recalcula ao voltar) e **Gerar assim mesmo**; fechar/cancelar cancela a emissão.
- Depois do aviso: caixa "Salvar como", PDF, abrir.
Pronto: testes com patch de `QMessageBox`/diálogos em `app.ui.report_actions`; casos: tudo com peso (sem aviso), sem peso + gerar assim mesmo, informar peso e recalcular, sem permissão (só "Gerar assim mesmo"), cancelar.

### T5. Ação "Imprimir relatório" nos menus
Arquivos: `app/ui/logistics_page.py`, `tests/test_row_actions_desktop.py`.
- Nova `RowAction("Imprimir relatório", "reports", True, ...)` logo após "Detalhes", para LOG e Carga, visível para todos (C4). Chama `report_actions` com os dados da linha.
- Os botões "Gerar relatório" dos detalhes (`logistics_dialogs.py:685`, `:1056`) já chamam `report_actions`; ficam no mesmo caminho sem mudança extra.
Pronto: testes de menu nas 2 abas; ação não é primária nem destrutiva.

### T6. Verificação e fechamento
- Suíte completa (`python -m pytest tests api/tests -q`); falha conhecida de tempo em `test_nomus_phase6_performance` fica fora de escopo.
- Auditoria independente: revisão de código; gerar PDF de teste de LOG e de carga (dados fake) e conferir o conteúdo extraindo o texto; conferir aderência a `qt-industrial-ui`.
- Doc: atualizar `docs/architecture/FASE17_LOGISTICA_MELHORIAS.md`; commits por subsistema (serviço de peso, relatório, aviso, menus, testes, doc), com a spec e o plano num commit de docs.

## Foco de revisão (falhas que nenhum teste da spec cobre)
1. `peso` unitário vs total somado errado (resultado plausível porém falso).
2. Proposta repetida em dois LOGs da mesma carga contada em dobro no total geral.
3. Itens removidos do LOG entrando no relatório ou no peso.
4. Falha de rede ao buscar itens de uma proposta durante a emissão.
5. Cancelar a janela de pesos sem salvar deixando o aviso num estado incoerente.

## Autorrevisão
Toda decisão D1-D5 tem tarefa (D1 T1, D2/D4 T4, D3 T5, D5 T3). Nomes consistentes: `log_weight`, `proposal_weight`, `collect_weights`, `MissingWeightDialog`. Rodapé com página X de Y é o risco técnico principal, com recuo definido.

## Como executar
Recomendo o agente `maestro` (equipe por papel), com auditorias da T6 feitas por agentes separados dos implementadores. Aguardo seu ok antes de implementar.
