# Registro de retirada pelo cliente em uma única janela

Data: 13/10/2026. Segue o mesmo padrão do registro de produção (`REGISTRO_PRODUCAO_ASSISTENTE_UNICO.md`) e do remanejamento: **uma janela só**, no tamanho do assistente de remanejamento (94% x 94% da janela principal, mínimo 1180 x 690), que troca de página. Antes: central de ações → seleção de itens (uma janela por proposta, em lote) → pergunta de confirmação → mensagem de sucesso. A regra e a API **não mudaram**: `update_status(proposta, "EXPEDICAO", ENTREGUE | ENTREGUE_PARCIAL, observação, item_ids)`.

| Passo | Página | O que decide |
|---|---|---|
| 1. Itens | `ItemsPage` | Quais itens o cliente retirou (agrupados por proposta; busca, "Selecionar todos", "Limpar seleção"). Proposta sem item pendente aparece como "Sem itens pendentes" e vira entrega direta. |
| 2. Revisão | `ReviewPage` | O que será gravado por proposta (TOTAL, PARCIAL ou ENTREGA DIRETA, peso), observação e **Confirmar retirada**. Revalida contra a API antes de gravar. |
| 3. Concluído | `DonePage` | Resultado na própria janela (entregue / entrega parcial, itens, kg). |

Regras: ENTREGUE quando todos os itens pendentes da proposta foram marcados (ou não há pendentes); ENTREGUE_PARCIAL nos demais. Falha parcial em lote: as propostas já gravadas saem da lista e a tentativa seguinte reenvia só as que faltam. A central de ações some enquanto o assistente está aberto (entradas: `RegisterDeliveryHandler`, `BatchProposalActionCenter._open_register_delivery` e `BatchStatusDialog`). Removido `ItemSelectionDialog` (sem outros usos).

Código: `app/ui/delivery_wizard/` (`dialog.py`, `state.py`, `items_page.py`, `review_page.py`, `done_page.py`). Testes: `tests/test_delivery_wizard.py` e ajustes em `tests/test_action_center.py` e `tests/test_batch_action_center.py`.
