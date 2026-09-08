"""Componentes de aba do dialogo `app.ui.process_detail_dialog.ProcessDetailDialog`.

Cada modulo aqui e um `QWidget` isolado (Resumo/Itens/Fluxo/Cargas/Fiscal-
Entrega/Historico) - nenhum deles fala com a API diretamente: todos recebem
`service` (a mesma instancia de `BackendService`/fake de teste que o
dialogo ja usa) e os dados ja carregados pelo dialogo pai, e so formatam
para exibicao. Nenhuma regra de negocio nova mora aqui.
"""
