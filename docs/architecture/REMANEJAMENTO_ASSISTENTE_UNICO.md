# Remanejamento em uma única janela (assistente de 4 passos)

Data: 08/10/2026. Substitui a sequência de cinco diálogos das Fases 1 a 6 (destino, itens, busca, alocação, revisão) por **uma janela só**, do tamanho da central de chats (94% x 94% da janela principal), que troca de página conforme o usuário avança. A API e o motor de compensação não mudaram; mudou a tela e a regra de quais propostas podem receber material.

## O que o usuário vê

| Passo | Página | O que decide |
|---|---|---|
| 1. Proposta destino | `DestinationPage` | Qual proposta vai **receber** o material. Só aparecem propostas em **Produção** ou **Galvanização**. |
| 2. Itens | `ItemsPage` | Quais itens da proposta destino adiantar e quanto de cada. "Selecionar todos" marca todos os itens listados que podem receber remanejamento. |
| 3. Origem do material | `SourcesPage` | De qual proposta da Expedição o material sai. Ao avançar do passo 2 o sistema busca o que está pronto; o usuário **escolhe a proposta de origem**. |
| 4. Revisão | `ReviewPage` | Simulação antes/depois, motivo (obrigatório) e confirmação. |

Cabeçalho com "Passo N de 4 — instrução", trilha de passos (`WizardStepper`; passos já feitos são clicáveis para voltar), rodapé com resumo do passo à esquerda e Cancelar / Voltar / Avançar à direita (um primário por tela). O texto do primário diz o que acontece: "Escolher itens", "Buscar material pronto", "Revisar remanejamento", "Confirmar remanejamento".

### Passo 3 — escolher a origem (o desenho)

Três colunas, da esquerda para a direita:

1. **Propostas com material pronto** — lista ordenada por quantos itens do pedido cada proposta cobre (depois por saldo). Colunas: Proposta, Cliente, *Cobre* ("3 de 5") e *Retirando* ("2 itens · 30 un").
2. **Itens que a proposta escolhida pode fornecer** — só os itens do pedido que ela tem pronto: Pedido, Disponível aqui e **Retirar** (digitável, em negrito/azul). Botões "Retirar o máximo desta proposta" e "Limpar esta proposta".
3. **Cobertura do pedido** — um cartão por item pedido com barra, "800 de 1000 kg · falta 200 kg" e selo Completo / Parcial / Sem origem escolhida / Sem material pronto. Botões "Sugerir origens" (usa `suggest_allocation`: maior saldo primeiro) e "Limpar tudo".

Nada é preenchido sozinho: o usuário define de qual proposta vem cada item; "Sugerir origens" é opcional. A quantidade digitada é cortada no saldo da origem **e** no que ainda falta do pedido (somando as outras origens). "Atualizar disponibilidade" refaz a busca; o que passou do saldo é ajustado e o usuário é avisado (antes o diálogo marcava a linha como inválida).

## Regra nova: quem pode receber

`BackendService.early_delivery_destination_candidates` (`app/services/backend_adapter.py`) passou a consultar `GET /proposals?current_area=PRODUCAO` e `...=GALVANIZACAO` (a lista já aceitava o filtro, no Desktop e na réplica), descarta canceladas e concluídas e devolve a união sem repetir, ordenada pelo número. Ficam de fora quem já está na **Expedição**, no Fiscal, entregue ou finalizado.

A página filtra o texto de busca localmente (a lista é pequena), sem chamar a API a cada tecla. Ao avançar, a lista é buscada de novo: se outra pessoa moveu a proposta para a Expedição nesse meio-tempo, o usuário é avisado e fica no passo 1.

> **Limite conhecido:** a regra vale na **listagem do Desktop**. A API (`remanagement_destination_items`, `review`, `confirm`) continua aceitando qualquer proposta ativa como destino, porque os testes e a compensação da Fase 5-7 foram escritos assim. Se outro cliente (ou uma chamada direta) precisar ser barrado, o próximo passo é validar `current_area in (PRODUCAO, GALVANIZACAO)` em `_load_compensation_snapshots`/`confirm_remanagement_batch` com um código de erro próprio.

## Fluxo de dados

Todas as páginas compartilham um único `RemanagementFlowState` (`app/services/remanagement_flow_state.py`), então Voltar preserva o que já foi escolhido.

- Avançar chama `page.commit()` (grava no estado) e depois `next_page.enter()` (carrega). Voltar **não** recarrega, para não perder o que foi digitado.
- Avançar do passo 2 sem mexer na seleção **não** apaga a busca e as origens já escolhidas (`set_item_selections` só é chamado se a seleção mudou).
- Trocar o destino descarta itens, origens e simulação (e gera novo `operation_id`).
- A confirmação é a mesma de antes: pergunta final, `remanagement_confirm(operation_id, ...)` transacional e idempotente; se o backend recusar, a página mostra o motivo e revalida.
- Fechar (X, Esc, Cancelar) com itens ou origens já escolhidos pede confirmação ("As escolhas feitas até aqui serão descartadas. Nada foi gravado.").

## Arquivos

- `app/ui/remanagement_wizard/` — `dialog.py` (`RemanagementWizardDialog`), `base.py` (`WizardPage`), `destination_page.py`, `items_page.py`, `sources_page.py`, `review_page.py`, `widgets.py` (selos de cobertura).
- `app/ui/components/wizard_stepper.py` — trilha de passos pintada; `app/ui/components/dialog_shell.py::info_notice` — caixa azul-clara de aviso (QSS `InfoNotice` em `styles.py`).
- `app/ui/process_page.py::open_early_remanagement_delivery` — agora só abre o assistente, atualiza a lista e mostra o toast.
- Removidos: `early_remanagement_dialog.py` (tela legada, sem uso desde a Fase 7) e os cinco `remanagement_*_dialog.py`, com seus testes.
- Prévia sem login: `python scripts/ui_gallery.py --remanejamento 1..4 [--shot arquivo.png]`.

## Testes

`tests/test_remanagement_wizard.py` (92 casos): cada página isolada (listagem, busca, seleção, "selecionar todos", cortes de quantidade, ordenação das origens, sugestão, cobertura, reentrada com saldo menor, erros de carga, confirmação, falha de confirmação), o assistente inteiro (navegação, voltar preserva, trocar destino descarta, fluxo completo até aceitar, fechar com confirmação, tamanho 94%) e a trilha. `tests/test_remanagement_destination_eligibility.py` (5 casos): a regra de quem pode receber, no adaptador. `tests/test_remanagement_allocation.py` (algoritmo de sugestão) e os testes da API continuam como estavam.
