# Registro de produção em uma única janela

Data: 13/10/2026. Substitui a sequência de telas do "Registrar produção" (central de ações → mesa de itens → revisão → aviso de sucesso, e, quando faltava fluxo, mais a pergunta e a tela de definição de fluxo) por **uma janela só**, do mesmo tamanho do assistente de remanejamento (94% x 94% da janela principal, mínimo 1180 x 690), que troca de página conforme o usuário avança. A API e a regra de gravação **não mudaram**: continua `update_status(proposta, "PRODUCAO", FINALIZADO | FINALIZADO_PARCIAL, observação, item_ids=…)` e `update_item_flow`.

## O que o usuário vê

| Passo | Página | O que decide |
|---|---|---|
| 1. Itens | `ItemsPage` | Quais itens foram produzidos (agrupados por proposta, com busca, "Selecionar todos" e "Limpar seleção"). Quando a janela abre a partir de itens já marcados na tela de Itens da produção, eles chegam marcados. |
| 2. Fluxo | `FlowPage` | **Só aparece quando** algum item marcado está sem fluxo. Uma linha por item, com o fluxo (Produzir + galvanizar, Produzir sem galvanizar, Não produzir…) e o motivo quando for "não produzir"; "Aplicar a todos". Salva ao avançar (mesma regra da tela de definição de fluxo). |
| 3. Revisão | `ReviewPage` | O que será registrado por proposta (TOTAL/PARCIAL, peso), observação e **Confirmar produção**. Revalida contra a API antes de gravar. |
| 4. Concluído | `DonePage` | Resultado na própria janela (propostas, itens, kg). Botão "Fechar". |

Cabeçalho "Passo N de M — instrução", trilha `WizardStepper` (a trilha passa de 3 para 4 passos quando o fluxo entra), rodapé com resumo à esquerda e Cancelar / Voltar / primário à direita. Fechar no meio pede confirmação (nada foi gravado).

## Regras

- **Itens elegíveis** (igual à mesa antiga): não produzido, `produzir_internamente` ≠ "não" e sem bloqueio de fluxo.
- **Fluxo indefinido**: falta `produzir_internamente` ou `precisa_galvanizacao` (mesma leitura de `route_from_flags`). A página de fluxo reaproveita `flow_review_state` (`build_proposal`/`build_payload`) e o seletor de motivo da tela de fluxo.
- **Depois de salvar o fluxo**, os itens são relidos: o que virou "não produzir" sai da seleção e o usuário é avisado; se nada sobrar, volta ao passo 1.
- **Falha parcial** na gravação da produção: as propostas já registradas saem da seleção, o erro aparece na própria página e repetir é seguro.
- **Central de ações**: ao escolher "Registrar produção" ela some (fica escondida) enquanto o assistente está aberto; ao terminar fecha com ou sem mudança. A tela de Itens da produção já fechava a central antes de abrir o registro. Entradas: `RegisterProductionHandler` (central da proposta), `BatchProposalActionCenter._open_register_production`, `BatchStatusDialog` e `ProductionItemsPage.register_selected` (a trava de "defina o fluxo antes" saiu: o passo de fluxo cobre).

## Código

`app/ui/production_wizard/` — `dialog.py` (`ProductionWizardDialog`, `.registered` diz se algo foi gravado), `state.py`, `items_page.py`, `flow_page.py`, `review_page.py`, `done_page.py`. Reaproveita `WizardPage` e o `WizardStepper` do remanejamento. Removidos `app/ui/production_registration_dialog.py` (mesa + revisão) e o seu teste; testes novos em `tests/test_production_wizard.py` e ajustes em `tests/test_action_center.py` e `tests/test_batch_action_center.py`.

## Fora do escopo

"Montar carga" continua registrando a produção automaticamente (`complete_production_items`) sem passar por este assistente.
