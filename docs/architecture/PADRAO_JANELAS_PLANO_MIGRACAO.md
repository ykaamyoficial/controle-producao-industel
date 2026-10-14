# Padrão de janelas (canto, volume e movimento) — levantamento e plano de aplicação

Status: **em execução** (13/10/2026, branch `padrao-janelas`). O usuário respondeu as decisões e autorizou seguir todas as ondas, com um commit por onda. Andamento no fim de cada onda, abaixo.

Referência visual aprovada: `prototipos/acoes_proposta/acoes.py` (aprovado em 13/10/2026 com canto de 24 px).
Continuação de: `REFINAMENTO_VISUAL_PLANO_MIGRACAO.md` (as nove ondas do refinamento visual já estão feitas; este plano troca a casca das janelas e o movimento).

## O padrão aprovado

| Item | Valor |
|---|---|
| Canto da janela | 24 px, liso: a moldura é pintada com suavização sobre fundo transparente, sem recorte por máscara |
| Cantos internos | painel 18, cartão 16, campo 12 |
| Borda | aro fino por fora, filete de luz no alto, sombreado na base (5 anéis para dentro) |
| Sombras | uma larga e fraca (até ~30 px, desce 14) e uma curta e escura colada na borda (6 px, desce 2), pintadas numa margem transparente de 48 px |
| Abrir | nasce com 88% do tamanho e salta para 100% com mola (ciclo de 0,40 s, amortecimento 0,68: passa ~5% do ponto); assenta em 550 ms e parece no lugar em ~200 ms; opacidade em 160 ms |
| Fechar | encolhe até 94% e some em 180 ms |
| Véu | escurece em 260 ms e clareia em 180 ms |
| Clique em cartão | afunda 3% em 90 ms e volta com a mesma mola |
| Curva fora da mola | `cubic-bezier(.25, .1, .25, 1)` |
| Reduzir animações | tudo com duração zero |

Os valores exatos são as constantes no topo do protótipo (`ESCALA_ENTRADA`, `MOLA_MS`, `MOLA_RESPOSTA`, `MOLA_AMORTECIMENTO`, `SAIDA_MS`, `VEU_MS`, `SOMBRA`).

## Objetivo

Levar o canto liso, a borda com volume e o abrir/fechar com mola a **todas** as telas do Desktop, sem mudar regra de negócio, contrato com a API nem fluxo de uso. Layout, cores, textos e hierarquia de botões de cada tela ficam como estão.

Fora do escopo: API, banco, novas funcionalidades, redesenho de layout, diálogos do próprio Windows (abrir/salvar arquivo) e o ícone da bandeja.

## Levantamento

Feito sobre o código em 13/10/2026 (branch `atualizador-versionado`), por leitura da árvore de classes de `app/`.

### Números

| Medida | Valor |
|---|---|
| Arquivos Python em `app/ui/` | 174 (cerca de 43,9 mil linhas) |
| Classes de diálogo (`QDialog`) | 60, em 49 arquivos |
| ... que já passam pelo ponto único `style_dialog_from_parent()` | 53 (51 chamam na própria classe; `StatusDialog` herda e `FiscalProposalDetailDialog` recebe de quem abre) |
| ... de tamanho grande (94% x 90% da janela principal) | 31 |
| ... com `done()`, `reject()` ou `closeEvent()` próprios | 16 |
| Diálogos montados na hora (`QDialog(self)` dentro de uma página) | 3 |
| Caixas de mensagem (`QMessageBox`) | 200 chamadas em 42 arquivos (125 aviso, 46 informação, 21 pergunta, 7 erro, 1 montada à mão) |
| Entradas de texto do Qt (`QInputDialog`) | 7 |
| Abrir/salvar arquivo (`QFileDialog`, do Windows) | 9 |
| Menus de contexto (`QMenu`) | 16 em 12 arquivos de `app/ui`, mais 1 no agente de bandeja |
| Popups (`Qt.Popup` / janela `ToolTip`) | 4 classes |
| Aviso rápido (`ToastNotification`) | 91 chamadas em 9 arquivos |
| Páginas da janela principal | 11 entradas na barra lateral, 16 classes de página |
| Arquivos de teste do Desktop | 190; 21 deles chamam `exec`/`accept`/`reject` de diálogo |

Legenda das tabelas: **Tam.** G = grande (94% x 90% da janela principal, mínimo 1100 x 650); M = média; P = pequena (até 500 px). **2º nível** = abre por cima de outro diálogo.

### 1. Centrais de ação e detalhes (13 classes)

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Ações da proposta | `ProposalActionCenter`, `StatusDialog` | `action_center/proposal_action_center.py`, `status_dialog.py` | M (760) | `reject()` próprio; é a tela do protótipo |
| Ações dos itens selecionados | `BatchProposalActionCenter` | `action_center/batch_action_center.py` | M (760) | 12 caixas de mensagem |
| Ações fiscais | `FiscalActionCenter` | `action_center/fiscal_action_center.py` | M (760 x 550) | |
| Ações da carga | `GalvanizationLoadActionCenter` | `action_center/load_action_center.py` | M (760 x 560) | |
| Correção administrativa | `ManualStatusDialog` | `status_dialog.py` | M (720) | 2º nível |
| Pausar produção | `ProductionPauseDialog` | `action_center/handlers/production.py` | P (460) | 2º nível |
| Escolher carga | `_SelectGalvanizationLoadDialog` | `action_center/handlers/galvanization.py` | P (420) | 2º nível; tabela |
| Ações em lote (antiga) | `BatchStatusDialog` | `batch_status_dialog.py` | G | `closeEvent()` próprio; tela legada |
| Propostas selecionadas | `BatchSelectionReviewDialog` | `batch_selection_review_dialog.py` | M (820 x 520) | alça de redimensionar |
| Detalhes da proposta | `ProcessDetailDialog` | `process_detail_dialog.py`, `process_detail/` | G | 6 abas com tabela; fade próprio na troca de aba |
| Detalhes do painel | `DashboardDetailsDialog` | `dashboard_details_dialog.py` | G | |
| Remanejamento da proposta (aviso) | `RemanagementInfoDialog` | `remanagement_info_dialog.py` | P (500) | |

### 2. Produção e galvanização (15 classes)

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Proposta (cadastro e edição) | `ProcessFormDialog` | `process_form_dialog.py` | G | abre "Conferir proposta Nomus" por cima |
| Definir fluxo dos itens | `ItemFlowDialog` | `item_flow_dialog.py` | G | |
| Selecionar itens | `ItemSelectionDialog` | `item_selection_dialog.py` | G | |
| Informar pesos dos itens | `ItemWeightDialog` | `item_weight_dialog.py` | G | |
| Definir fluxo (proposta ou lote) | `FlowReviewDialog` | `flow_review_dialog.py` | G | `reject()` próprio; 22 caixas de mensagem; menu de contexto |
| Registrar produção (assistente) | `ProductionWizardDialog` | `production_wizard/dialog.py` | G | `reject()` próprio (confirma o descarte); troca de passo |
| Remanejamento (assistente) | `RemanagementWizardDialog` | `remanagement_wizard/dialog.py` | G | `reject()` próprio; troca de passo |
| Montar/editar carga | `GalvanizationLoadDialog` | `galvanization_load_dialog.py` | G | `closeEvent()` próprio; abas |
| Alocação de item | `_ItemAllocationDialog` | `galvanization_load_dialog.py` | P (440) | 2º nível |
| Revisão da carga | `_GalvanizationLoadReviewDialog` | `galvanization_load_dialog.py` | P (420) | 2º nível |
| Registrar retorno da galvanização | `GalvanizationReturnDialog` | `galvanization_load_dialog.py` | G | `closeEvent()` próprio; abas |
| Revisão do retorno | `_GalvanizationReturnReviewDialog` | `galvanization_load_dialog.py` | P (440) | 2º nível |
| Cargas de galvanização | `GalvanizationLoadManagerDialog` | `galvanization_load_dialog.py` | G | menu de contexto |
| Detalhes da carga | `GalvanizationLoadDetailsDialog` | `galvanization_load_details_dialog.py` | G | abas; menu de contexto |
| Detalhes da carga (antigo) | `_LegacyGalvanizationLoadDetailsDialog` | `galvanization_load_dialog.py` | G | **nenhuma referência no código**: confirmar e remover à parte |

### 3. Fiscal e Nomus (12 classes)

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Registrar emissão fiscal (simples) | `FiscalEmissionDialog` | `fiscal_emission_dialog.py` | G | `closeEvent()` próprio |
| Registrar emissão fiscal — itens | `FiscalItemSelectionDialog` | `fiscal_item_selection_dialog.py` | G | |
| Registrar emissão fiscal — rascunho | `FiscalEmissionDraftDialog` | `fiscal_emission_draft_dialog.py` | G | |
| Confirmar emissões fiscais | `FiscalEmissionReviewDialog` | `fiscal_emission_review_dialog.py` | G | |
| Detalhes da proposta (Fiscal) | `FiscalProposalDetailDialog` | `fiscal_page.py` | G | a casca é aplicada por quem abre |
| Buscar proposta no Nomus | `NomusApiImportDialog` | `nomus_api_import_dialog.py` | M (560 x 280) | `reject()` próprio |
| Integração Nomus | `NomusApiSettingsDialog` | `nomus_api_settings_dialog.py` | M (820 x 520) | |
| Importar propostas do Nomus | `NomusBatchImportDialog` | `nomus_batch_import_dialog.py` | G | `reject()`, `closeEvent()` e `resizeEvent()` próprios; animação própria |
| Conferir importação do Nomus | `NomusBatchConferenceDialog` | `nomus_batch_conference_dialog.py` | G | `reject()` próprio |
| Importando proposta do Nomus | `NomusImportProgressDialog` | `nomus_import_progress_dialog.py` | M (740 x 460) | não pode fechar durante a importação (`reject()`/`closeEvent()` próprios); 3 animações próprias |
| Conferir proposta Nomus | `ProposalImportDialog` | `proposal_import_dialog.py` | G | 2º nível |
| Consulta de propostas pela API | `ApiProposalsReadonlyDialog` | `api_proposals_readonly_dialog.py` | G (1020 x 680) | |

### 4. Relatórios e sistema (11 classes)

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Registros do relatório | `OperationalRowsDialog` | `operational_reports_page.py` | G | |
| Detalhes da proposta (consulta) | `OperationalProcessReadOnlyDialog` | `operational_reports_page.py` | G | |
| Carga de galvanização (consulta) | `OperationalLoadReadOnlyDialog` | `operational_reports_page.py` | G | |
| Configurações | `SettingsDialog` | `settings_dialog.py`, `settings_page.py` | G | reaplica o tema com a janela aberta (chama o ponto único de novo) |
| Usuários e permissões | `UserManagerDialog` | `user_dialog.py` | G | |
| Novo/Editar usuário | `UserEditorDialog` | `user_dialog.py` | G | 2º nível |
| Meu perfil | `UserProfileDialog` | `user_profile_dialog.py` | M (560) | |
| Sobre | `AboutDialog` | `about_dialog.py` | P (360) | |
| Auditoria de atualizações | `UpdateAuditDialog` | `update_audit_dialog.py` | G (1080 x 700) | |
| Evento (detalhe) | `EventDetailDialog` | `update_audit_dialog.py` | M (560 x 480) | 2º nível |
| Diagnóstico da API | `ApiDiagnosticDialog` | `api_diagnostic_dialog.py` | G | `closeEvent()` e `event()` próprios |

### 5. Chat e mídia (3 classes)

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Chats | `ChatCenterDialog` (hospeda `ChatCenterPage` e `ChatConversationPanel`) | `chat_center_page.py`, `proposal_chat_dialog.py` | G (94% x 94%) | `done()` próprio (encerra as threads); **vídeo embutido** (`QVideoWidget`) nos cartões da conversa; sombra por `QGraphicsDropShadowEffect` no cabeçalho |
| Registrar nota interna | `InternalNoteDialog` | `proposal_chat_dialog.py` | P (380) | sem casca hoje; 2º nível |
| Visualizador de mídia | `MediaViewerDialog` | `components/chat_message_attachments.py` | G (980 x 700) | sem casca hoje; **`QVideoWidget`**; teclado e `closeEvent()` próprios |

### 6. Inicialização (5 classes) — abrem sem a janela principal por trás

| Tela | Classe | Arquivo | Tam. | Atenção |
|---|---|---|---|---|
| Login | `LoginDialog` | `login_dialog.py` | P (420) | sem casca; a janela principal ainda está invisível |
| Conexão com o servidor (primeiro acesso) | `FirstAccessDialog` | `first_access_dialog.py` | P (460) | chama o ponto único, mas sem dono fica com a barra do Windows |
| Verificando compatibilidade | `CompatibilityGateDialog` | `compatibility_gate_dialog.py` | P (420) | sem casca |
| Sistema em manutenção | `MaintenanceModeDialog` | `maintenance_mode_dialog.py` | P (460) | sem casca; `closeEvent()` próprio |
| Nova versão disponível | `UpdateDialog` | `update_dialog.py` | M (640 x 520) | sem casca; estilo próprio; abre na inicialização (`main.py`) e com o programa aberto (`main_window.py`) |

Sobra uma classe sem uso: `ModernDialog` (`components/modern_dialog.py`) não é instanciada em lugar nenhum. Remover à parte.

### 7. Diálogos montados na hora (3)

| Tela | Onde | Situação |
|---|---|---|
| Distribuição por proposta (Produção) | `production_items_page.py:280` | `QDialog(self)` de 680 x 380, **sem casca** |
| Distribuição por proposta (Expedição) | `expedition_items_page.py:333` | `QDialog(self)` de 760 x 400, **sem casca** |
| Lista de detalhe do Fiscal | `fiscal_page.py:897` | grande, já passa pelo ponto único |

### 8. Caixas de mensagem e diálogos do Qt

| Tipo | Quantidade | Situação |
|---|---|---|
| `QMessageBox` | 200 chamadas em 42 arquivos | moldura do Windows; os testes fazem patch nelas no módulo que importa, então a classe **não pode ser trocada** |
| `QInputDialog` (texto, texto longo, lista) | 7 | moldura do Windows |
| `QFileDialog` | 9 | janela do próprio Windows: fica como é |

### 9. Popups, menus e avisos

| Tela | Classe | Arquivo | Como é hoje |
|---|---|---|---|
| Central de notificações | `NotificationCenterPanel` (`Qt.Popup`) | `components/notification_center_panel.py` | raio 16 só pela folha de estilo; fade de 140 ms ao abrir; some de uma vez |
| Menu do usuário | `UserProfilePopover` (`Qt.Popup`) | `components/user_profile_popover.py` | idem |
| Emojis | `_EmojiPopup` (`Qt.Popup`) | `components/mention_compose_bar.py` | sem animação |
| Menções (@) | `_MentionPopup` (janela `ToolTip`, sem foco) | `components/mention_compose_bar.py` | sem animação |
| Menus de contexto | `QMenu` (16) | 12 arquivos de `app/ui` | raio 9 pela folha de estilo |
| Listas de combo | popup do `QComboBox` | `styles.py` | sem raio |
| Dicas | `QToolTip` | `styles.py` | raio 7 |
| Aviso rápido (verde/vermelho) | `ToastNotification` (91 chamadas) | `components/toast_notification.py` | aparece e some de uma vez, após 2,6 s |
| Aviso de notificação | `InAppToast` | `components/toast_manager.py` | fade de 200 ms ao entrar; some de uma vez |

### 10. Páginas e janela principal

| Entrada na barra lateral | Classe | Arquivo |
|---|---|---|
| Painel geral | `DashboardPage` | `dashboard_page.py` |
| Dashboard Executivo | `ExecutiveDashboardPage` | `executive_dashboard_page.py` |
| Controle Geral, Almoxarifado, Parciais | `ProcessPage` | `process_page.py` |
| Produção | `ProductionAreaPage` (com `ProductionItemsPage`) | `production_items_page.py` |
| Galvanização | `GalvanizationAreaPage` (com `GalvanizationItemsPage`, `GalvanizationLoadsPage`) | `galvanization_items_page.py` |
| Expedição | `ExpeditionAreaPage` (com `ExpeditionItemsPage`) | `expedition_items_page.py` |
| Fiscal | `FiscalPage` | `fiscal_page.py` |
| Relatórios Operacionais | `OperationalReportsPage` | `operational_reports_page.py` |
| Histórico (e Auditoria, Relatórios) | `DataPage` | `data_page.py` |

- Troca de página hoje: `fade_in(page)` de 180 ms, com `QGraphicsOpacityEffect` sobre a página inteira (`main_window.py:503` e `:564`).
- Janela principal: `MainWindow` mantém a moldura nativa do Windows com barra de título própria (`components/native_frameless.py`), para o Windows continuar cuidando de redimensionar, encaixar nas bordas e maximizar. O canto externo é o do sistema: reto no Windows 10, arredondado pelo próprio Windows no 11.
- Fora do programa principal: o agente de bandeja (`app/services/notifier_agent.py`) tem só ícone e menu do Windows.

## Como o padrão se traduz em cada tipo de tela

| Tipo de tela | O que recebe |
|---|---|
| Janela sobreposta (os 60 diálogos e os 3 montados na hora) | Casca completa: canto 24 px liso, borda com volume, duas sombras, mola ao abrir, encolher ao fechar, véu com fade |
| Janela de inicialização (login, primeiro acesso, compatibilidade, manutenção, atualização) | Mesma casca, sem véu. Perdem a barra do Windows e ganham botão de fechar próprio no cabeçalho |
| Caixa de mensagem e entrada de texto do Qt | Mesma casca, aplicada por um gancho global, sem trocar a classe (ver "Decisões em aberto") |
| Popup e menu (notificações, usuário, emoji, menção, menus de contexto, lista de combo) | Casca leve: canto liso (16 px em popup, 12 em menu), volume e sombra menores, abre crescendo a partir do botão que o chamou (94% para 100%, ~200 ms), some com fade de 120 ms |
| Dica (`QToolTip`) | Canto liso de 8 px e fade; sem volume |
| Aviso (os dois tipos) | Sobe com a mola e some descendo, como o aviso do protótipo |
| Página (troca pela barra lateral) | A página nova aparece com fade curto e leve aproximação; a técnica de foto substitui o efeito gráfico sobre a página inteira |
| Conteúdo que troca dentro da tela (abas, passos de assistente, esqueleto para conteúdo) | Mesma curva e mesma técnica; os fades atuais passam a usar o helper novo |
| Janela principal | Fica com a moldura do Windows (ver "Decisões em aberto") |
| Abrir/salvar arquivo e bandeja | São do Windows: não mudam |

## Como entra no código

### Ponto único

53 dos 60 diálogos já passam por `style_dialog_from_parent()` (`app/ui/dialog_utils.py`), que chama `install_dialog_shell()` (`app/ui/components/dialog_shell.py`). A casca nova entra ali e vale para todos de uma vez; nenhum diálogo precisa trocar de classe-base.

| Peça | Arquivo | O que faz |
|---|---|---|
| Casca de janela | novo `app/ui/components/window_shell.py` | pinta a moldura (canto, volume, sombras) por filtro de eventos; cria a margem de sombra e compensa a geometria; cortina de abrir/fechar; gancho no `done()` |
| Mola e curva | `app/ui/animations.py` | `spring()`, curva padrão e transição com aviso de fim. Nada de animar `pos` ou `geometry`: há teste que proíbe (`test_animations_module_has_no_pos_or_geometry_animation`) |
| Véu | `app/ui/components/dialog_scrim.py` | passa a clarear com fade, pinta uma foto da janela de trás durante o fade e respeita o canto arredondado quando a dona também tem casca |
| Ponto único | `dialog_utils.py`, `dialog_shell.py` | escolhe a casca: nova, recorte antigo ou nenhuma |
| Recorte antigo | `app/ui/components/frameless_dialog.py` | vira o plano B para tela onde o fundo transparente não servir |
| Tokens | `app/ui/theme_tokens.py` | cores do aro, do filete de luz e das sombras derivadas da paleta (nada de hexadecimal na casca) |
| Raios internos | `app/ui/styles.py` | painel 18, cartão 16, campo 12 dentro de janela sobreposta |
| Galeria | `scripts/ui_gallery.py` | opção `--casca`: pequena, média, grande com tabela, 2º nível, câmera lenta |

### Prova feita em 13/10/2026

Um `QDialog` comum (layout direto no diálogo, `QTableWidget`, `done()` e `reject()` próprios, aberto por `exec()`) recebeu a casca **de fora**, sem alterar a classe, e foi capturado na tela real (Windows 10, PySide6 6.11):

- moldura com volume, canto de 24 px e sombra pintados pelo filtro de eventos; a tabela desenhou normalmente sobre o fundo transparente;
- Esc chamou o `reject()` da classe, o gancho segurou o `done()` pelos 180 ms da saída e depois chamou o `done()` da classe; `exec()` voltou 202 ms depois do Esc com o resultado certo;
- a animação roda a um quadro a cada 16 ms, com cerca de 1,3 ms de pintura por quadro, e a janela aceita clique e teclado desde o primeiro quadro.

### Regras que saíram das medições

1. **O véu pinta uma foto da janela de trás enquanto escurece ou clareia.** Repintar a página inteira a cada quadro custava ~50 ms no protótipo e a janela perdia quadros. Parado, o véu volta a ser transparente.
2. **O relógio da animação só parte depois do primeiro quadro pintado.** Partindo antes, o tempo de o Windows criar a janela comia o começo do salto.
3. **Fechamento vindo de fora não espera a saída** (Alt+F4, programa encerrando). Senão o `QDialog` vê a janela ainda visível, recusa o fechamento e cancela até o encerramento do programa.
4. **A cortina se declara opaca e apaga o que está embaixo**, para o Qt não redesenhar tabela e área de rolagem a cada quadro.
5. **Sem animação em teste.** Com a plataforma `offscreen` (toda a suíte e o CI) e com "Reduzir animações", a duração é zero e `done()` fecha na hora; os testes que chamam `accept()`/`reject()` continuam valendo.
6. **Fechar com animação segura quem chamou `exec()` por 180 ms.** É o custo aceito do padrão.

### Compensação de geometria

A sombra precisa de 48 px de margem transparente em volta da janela. A casca soma essa margem na primeira exibição: margens do layout, tamanho mínimo e máximo, tamanho atual e posição. Pontos a tratar na fundação:

- `apply_large_dialog_geometry()` (chamada em 25 arquivos) liga a alça de redimensionar, que ficaria na faixa da sombra: reposicionar ou desligar;
- arrastar pelo topo (hoje os primeiros 64 px) passa a descontar a margem;
- diálogo de largura fixa (`setFixedWidth`) precisa ter mínimo e máximo ajustados juntos;
- em 1366 x 768 a janela grande com margem passa alguns pixels da tela; é só sombra transparente.

### Chave de ativação

A casca nova entra atrás de uma chave de configuração, desligada por padrão. Cada onda liga a chave na máquina de desenvolvimento, confere o seu grupo de telas e corrige. Quando todos os grupos passarem, a chave vira padrão e depois é removida. Enquanto existir, voltar ao recorte atual é trocar um valor.

## Ondas

Tamanho: P (até ~300 linhas tocadas), M (até ~1.000), G (acima disso ou alto risco).

Como a casca liga para todos os diálogos de uma vez, as ondas B a E são de **conferência e correção tela a tela**, não de reescrita.

### Onda A — Fundação e pilotos (G)

| Entrega | Onde |
|---|---|
| Casca de janela, cortina, mola, compensação de geometria, gancho no `done()` | novo `window_shell.py`, `animations.py` |
| Véu com fade de saída, foto e recorte arredondado | `dialog_scrim.py` |
| Ponto único escolhendo a casca; chave de ativação | `dialog_utils.py`, `dialog_shell.py`, configuração |
| Tokens da casca nas paletas `claro` e `escuro`; contraste conferido | `theme_tokens.py`, `scripts/check_contrast.py` |
| Raios internos dentro de janela sobreposta | `styles.py` |
| Galeria `--casca` e script de medição de quadros | `scripts/` |
| Testes da casca (lista em "Testes") | `tests/test_window_shell.py`, ajustes em `test_dialog_shell.py` e `test_visual_foundation.py` |
| Pilotos conferidos: Ações da proposta e Detalhes da proposta | sem mudança nas telas |

Aceite: os dois pilotos iguais ao protótipo nos dois temas; suíte verde; entrada a um quadro a cada ~16 ms, sem buracos, medida na tela real; Esc, Alt+F4 e sair do programa com a janela aberta funcionando.

**Andamento (13/10/2026, branch `padrao-janelas`):**

| Entrega | Situação |
|---|---|
| Casca de janela (moldura pintada, margem de sombra, cortina, gancho no `done()`, alça de redimensionar no canto visível, arrasto pelo topo) | Feito - `app/ui/components/window_shell.py` |
| Mola, curva padrão e transição com aviso de fim; animação de janela desligada em `offscreen` e com "Reduzir animações" | Feito - `app/ui/animations.py` (`spring`, `ease`, `transition`, `window_motion_enabled`) |
| Véu: escurece com o salto, clareia com a saída, foto da janela de trás, recorte arredondado sobre janela com casca | Feito - `dialog_scrim.py`. A foto vem do que a janela já pintou (cópia do *backing store*, ~3 ms); repintar custava 76 ms |
| Ponto único escolhendo a casca; chave de ativação | Feito - `dialog_shell.install_dialog_shell()`; chave `INDUSTEL_WINDOW_SHELL=1` (variável de ambiente) ou `set_window_shell_enabled()`, desligada por padrão |
| Tokens da casca | Feito - `shell_ink` e `shell_light` em `theme_tokens.py`: exceção fixa (luz e sombra iguais nos dois temas), como os tokens de mídia |
| Raios internos dentro de janela com casca (painel 18, campo 12) | Feito - regras `QDialog[windowShell="true"]` em `styles.py` |
| Galeria | Feito - `python scripts/ui_gallery.py --casca` liga a casca em qualquer modo (`--moldura --detalhes N`, `--remanejamento N`...) |
| Testes da casca | Feito - `tests/test_window_shell.py` (17 testes). Os testes antigos da moldura e do véu não precisaram mudar |
| Pilotos | Detalhes da proposta conferido na tela real pela galeria, claro e escuro, com a aba de tabela: 35 quadros na entrada a ~16 ms, até 5 ms de pintura por quadro. Ações da proposta entra na onda B |
| Miolo da janela | **Mudou em relação ao protótipo:** o degradê do corpo virou cor chapada, porque área de rolagem e painel com o mesmo fundo apareceriam como retângulos. O volume ficou só na borda; o protótipo foi ajustado para ficar igual |
| Vídeo dentro de janela transparente | Testado antes da onda F: `QVideoWidget` tocando um vídeo de teste aparece normalmente dentro de diálogo com a casca nova (Windows 10, PySide6 6.11) |

Suíte ao fim da onda: 2754 passaram e 382 pulados com a casca desligada (Desktop + API). Com a chave ligada os 1949 testes do Desktop também passaram, mas essa rodada prova pouco: nos testes a maioria dos diálogos nasce sem janela dona e, sem dona, não recebe a casca. A rodada com a casca forçada em todos está no andamento das ondas B a E.

### Onda B — Centrais de ação e detalhes (M)

As 13 classes do grupo 1. Atenção ao 2º nível (Correção administrativa, Pausar produção, Escolher carga): a janela de baixo fica com o véu recortado no canto dela. Revisar com o agente `action-center-reviewer`.

### Onda C — Produção e galvanização (G)

As 15 classes do grupo 2 e os 2 diálogos montados na hora (passam a chamar o ponto único). Atenção: assistentes com `reject()` que pede confirmação (a saída só anima depois de o usuário confirmar o descarte), diálogos com `closeEvent()` próprio e as tabelas grandes.

### Onda D — Fiscal e Nomus (M)

As 12 classes do grupo 3. Atenção: o diálogo de progresso do Nomus não pode fechar durante a importação e tem animações próprias; a importação em lote redimensiona sozinha. Conferir contra `NOMUS_FISCAL_INTEGRATION_CONTRACT.md` com o agente `nomus-integration-guide` (só aparência).

### Onda E — Relatórios e sistema (M)

As 11 classes do grupo 4. Atenção: Configurações troca de tema com a janela aberta (a moldura precisa ser repintada com a paleta nova).

### Onda F — Chat e mídia (G, risco alto)

As 3 classes do grupo 5. É onde o fundo transparente pode não servir: `QVideoWidget` cria uma janela nativa filha, que em geral não compõe dentro de janela com transparência. Sequência: testar vídeo tocando com a casca nova; se falhar, essas telas ficam com o recorte antigo (canto de 24 px por máscara, abrir e fechar só com fade pela opacidade da janela, sem o salto) até decidir a troca do player (ver "Decisões em aberto"). Trocar também a sombra por `QGraphicsDropShadowEffect` do cabeçalho do chat por sombra pintada.

### Onda G — Inicialização (M)

As 5 classes do grupo 6. Sem janela principal não há véu. Cada tela ganha botão de fechar próprio no cabeçalho antes de perder a barra do Windows. A de atualização precisa funcionar nos dois momentos (inicialização e programa aberto); validar com a skill `desktop-update-doctor`.

### Onda H — Popups, menus e avisos (M)

Os itens do grupo 9. `ToastNotification` muda num arquivo só e vale para as 91 chamadas. Menus e listas de combo recebem a casca leve por um gancho global na exibição.

### Onda I — Páginas e conteúdo interno (M)

Troca de página pela técnica de foto no lugar do efeito gráfico; abas, passos de assistente e a passagem de esqueleto para conteúdo usando o mesmo helper.

### Onda J — Caixas de mensagem (M, depende de decisão)

Casca aplicada às 200 `QMessageBox` e às 7 `QInputDialog` por gancho global, sem trocar a classe nem tocar nas chamadas. Os testes continuam fazendo patch no mesmo lugar.

### Onda K — Fechamento (P)

Chave vira padrão e é removida; atualizar a skill `qt-industrial-ui` e `references/janelas-sobrepostas.md`; remover as duas classes sem uso; gerar o instalador e conferir numa máquina limpa; documento de fechamento pela skill `fase-report`.

## Andamento das ondas B a K (13/10/2026)

| Onda | O que foi feito | Como foi conferido |
|---|---|---|
| B a E — diálogos | Folga mínima de 8 px para conteúdo de ponta a ponta (central de chats); importação em lote do Nomus decide o rodapé pela largura do conteúdo; os dois "Distribuição por proposta" passam pelo ponto único com cabeçalho e rodapé; cartão de ação com canto de 16 px | Ferramenta de conferência (plugin de pytest, fora do repositório) que força a casca em todo diálogo e fotografa cada um com os dados de exemplo dos testes: 93 fotos de 35 classes. Suíte com a casca forçada: 1942 passaram, 8 falhas esperadas (3 testes que afirmam o comportamento sem a casca, 1 que mede a janela com a margem, 4 do Nomus por configuração local ausente no diretório de conferência) |
| F — chat e mídia | Nota interna e visualizador de mídia passam pelo ponto único | **O risco do vídeo não se confirmou:** vídeo tocando aparece dentro de janela transparente. Conferido na tela real com `QVideoWidget`, com o cartão de vídeo do chat e com o visualizador aberto. O chat ficou com a casca completa |
| G — inicialização | `style_dialog_from_parent(..., standalone=True)`: as cinco telas perdem a barra do Windows, recebem o tema da configuração e, onde não havia botão de fechar (login, primeiro acesso, compatibilidade), uma linha de título com X (`window_title_row`) | Fotos das cinco telas; testes de inicialização |
| H — popups, menus, avisos | Casca leve (16 px, sombra menor, entrada a partir do botão, saída por fantasma) na central de notificações, menu do usuário e emojis; menus de contexto e listas de combo com canto liso e fade por um filtro ligado uma vez na aplicação (`floating_chrome.py`); popup de menção com canto liso; aviso rápido pintado, com mola; aviso de notificação some com fade | Tela real: popups, menu, combo e avisos com canto liso. A animação dos popups não pôde ser medida direito na galeria, porque o serviço de exemplo trava a tela ao buscar notificações |
| I — páginas | Transição cruzada na troca de página (foto da página antiga por baixo da nova); passos dos assistentes com fade | Tela real: no meio da troca a página antiga aparece por baixo. O efeito gráfico da página que entra foi mantido (trocá-lo custaria o mesmo) |
| J — caixas de mensagem | Funções estáticas de `QMessageBox` e `QInputDialog` trocadas no início do programa por versões que montam a mesma caixa com a casca (`message_boxes.py`); título pintado no alto da caixa. Corrigido o véu que escurecia duas vezes quando um diálogo abria logo depois de outro fechar | Tela real: aviso, pergunta e entrada de texto; `tests/test_message_boxes.py`. A abordagem por filtro de eventos, prevista no plano, deixava a caixa invisível e foi descartada |
| K — fechamento | A casca nova virou o padrão. A chave não foi removida: `INDUSTEL_WINDOW_SHELL=0` volta ao recorte antigo, como saída de emergência. Skill `qt-industrial-ui` atualizada | Suíte oficial completa |

### O que não foi conferido

- **Nenhuma tela foi vista com dados reais, logado na API.** A conferência foi pela galeria, por montagens de teste na tela real e pelas fotos com os dados de exemplo dos testes.
- 25 diálogos não foram fotografados, porque os testes não os constroem: `AboutDialog`, `FiscalActionCenter`, `_SelectGalvanizationLoadDialog`, `GalvanizationLoadActionCenter`, `ApiProposalsReadonlyDialog`, `DashboardDetailsDialog`, `FiscalEmissionDialog`, `FiscalProposalDetailDialog`, `GalvanizationLoadDialog`, `_ItemAllocationDialog`, `_GalvanizationLoadReviewDialog`, `_GalvanizationReturnReviewDialog`, `ItemFlowDialog`, `ItemSelectionDialog`, `ItemWeightDialog`, `OperationalRowsDialog`, `OperationalProcessReadOnlyDialog`, `OperationalLoadReadOnlyDialog`, `InternalNoteDialog`, `EventDetailDialog`, `UpdateAuditDialog`, `UserEditorDialog`, `UserProfileDialog`, `MediaViewerDialog` (visto na tela real, sem mídia) e `ProposalActionCenter` (coberto pela subclasse). Recebem a mesma casca pelo mesmo ponto único.
- Dica (`QToolTip`) ficou como era.
- Botões das caixas de mensagem: traduzidos depois, a pedido do usuário ("Sim", "Não", "Cancelar"...), em `message_boxes.py`. Com a chave de emergência desligada voltam a sair em inglês, porque aí a caixa é a original do Qt.
- As duas classes sem uso (`ModernDialog`, `_LegacyGalvanizationLoadDetailsDialog`) não foram removidas.
- O instalador não foi gerado.

## Ordem e dependências

```
Onda A ──► Onda B ──► Onda C ──► Onda D ──► Onda E ──► Onda K
   │
   ├──► Onda F (chat e mídia)
   ├──► Onda G (inicialização)
   ├──► Onda H (popups, menus, avisos)
   ├──► Onda I (páginas)
   └──► Onda J (caixas de mensagem)
```

F a J dependem só da fundação e podem entrar em qualquer ordem.

## Receita de conferência por tela

1. Abrir com dados reais, nos temas claro e escuro.
2. Canto e sombra inteiros nos quatro lados; nada do conteúdo encosta na curva.
3. Abrir e fechar por botão, Esc e Alt+F4; fechar no meio da abertura.
4. Tabela rolando, campo de texto digitando, combo abrindo, menu de contexto abrindo.
5. Abrir o que ela abre por cima (2º nível e caixas de mensagem) e voltar.
6. Arrastar pelo topo; conferir em 1366 x 768.
7. Com "Reduzir animações" ligado: abre e fecha na hora.
8. Capturar antes e depois.

## Testes

Novos, em `tests/test_window_shell.py`:

- instalar duas vezes não muda nada; sem dono não instala a casca completa;
- a margem de sombra é somada uma vez só, inclusive em diálogo de tamanho fixo;
- com animação desligada (padrão dos testes), `accept()`/`reject()` fecham na hora;
- com animação ligada à força, `done()` só chega depois da saída e `exec()` devolve o resultado certo;
- `done()` e `reject()` próprios da classe continuam sendo chamados, uma vez;
- fechamento de fora fecha na hora; sair do programa com diálogo aberto não fica preso;
- o véu é liberado em todas as formas de fechar e na destruição do diálogo;
- a cortina some depois da entrada e não sobra filha no diálogo.

A ajustar: `tests/test_dialog_shell.py` (3 testes sobre a moldura) e `tests/test_visual_foundation.py` (4 testes do véu).

Suíte oficial ao fim de cada onda: `python -m pytest tests api/tests -q` (travou: agente `test-doctor`).

## Riscos

| Risco | Como tratar |
|---|---|
| Fundo transparente quebrar a repintura de alguma tela (o comentário antigo em `frameless_dialog.py` relata isso com tabelas) | A prova com `QTableWidget` passou; conferir tela a tela nas ondas B a E; plano B por tela (recorte antigo) e chave de ativação |
| Vídeo não aparecer dentro de janela transparente | Onda F isolada; plano B imediato para as duas telas |
| `done()` adiado mudar a ordem de algum fluxo que fecha um diálogo e abre outro em seguida | Teste dedicado; conferir os fluxos de 2º nível; animação desligada é sempre o caminho antigo |
| Véu preso na tela se um diálogo morrer no meio da saída | Liberação no `destroyed`, como hoje, e teste dedicado |
| Custo de fotografar a janela principal real (no protótipo, ~50 ms) atrasar a abertura | Medir na onda A com a tela real; se pesar, buscar forma mais barata de obter a imagem (reaproveitar o que a janela já pintou em vez de repintar) |
| Margem de sombra desalinhar tamanho ou posição de algum diálogo | Compensação central com teste; conferência em 1366 x 768 |
| Gancho no `done()` por instância depender de comportamento do PySide | Provado no PySide6 6.11; teste trava a regressão ao atualizar a biblioteca; alternativa é uma classe-base comum |
| Popups e menus com transparência perderem a sombra ou o fechamento ao clicar fora | Onda H separada, com conferência de cada popup |
| Diálogo real abrir em teste e travar a suíte | Sem animação em `offscreen`; `timeout=25` já denuncia; agente `test-doctor` |

## O que muda na skill `qt-industrial-ui`

- Raio da janela sobreposta: 16 passa a 24; painel 18, cartão 16, campo 12 dentro dela.
- Movimento: entrada com mola (550 ms até assentar) e saída de 180 ms no lugar de "entrada 180-240 ms, saída 120-180 ms"; a curva fora da mola passa a ser `cubic-bezier(.25, .1, .25, 1)` nas janelas.
- Borda com volume e duas sombras entram como parte da casca; "não empilhe `QGraphicsEffect`" continua valendo (a casca não usa nenhum).
- "Não use `WA_TranslucentBackground` no diálogo" sai de `references/janelas-sobrepostas.md`: passa a ser a regra, com o recorte como exceção documentada.
- Protótipo de referência das janelas sobrepostas passa a ser `prototipos/acoes_proposta/acoes.py`.

## Decisões já tomadas pelo usuário (13/10/2026)

- Canto da janela de 24 px, liso.
- Borda com um pouco de efeito 3D.
- Animação no estilo da Apple: salto com mola ao abrir, encolher ao fechar.
- Sem cascata nos cartões: a janela entra inteira.
- Aplicar a todas as telas do sistema.

## Decisões respondidas pelo usuário (13/10/2026)

| # | Decisão | Resposta |
|---|---|---|
| 1 | Caixas de mensagem (200) e entradas de texto (7) recebem a casca? | Sim, por último (onda J), por gancho global, sem trocar a classe |
| 2 | Páginas: volume e raio maior nos painéis? | Não. Só o que flutua (janelas, popups, avisos); as páginas ganham a transição animada |
| 3 | Janela principal no Windows 10 | Mantém o canto do Windows |
| 4 | Chat com vídeo, se a transparência falhar | Aceitar o recorte antigo nessas duas telas |
| 5 | Telas de inicialização perdem a barra do Windows? | Sim, com botão de fechar próprio |
| 6 | Como seguir | Todas as ondas, na ordem do plano, um commit por onda, sem parar para perguntar |
