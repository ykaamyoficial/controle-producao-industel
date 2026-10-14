# Refinamento visual do Desktop — plano de migração

Status: **planejamento** (07/10/2026). Nenhuma tela de `app/ui/` foi alterada ainda.

Padrão a aplicar: skill `qt-industrial-ui` (`.claude/skills/qt-industrial-ui/`).
Referência visual aprovada: `prototipos/controle_geral/preview.py` e `prototipos/detalhes_proposta/detalhes.py`.

## Objetivo

Levar todas as telas do Desktop ao padrão aprovado nos protótipos **sem mudar regra de negócio, contrato com a API nem fluxo de uso**. A identidade atual é mantida (moldura azul, selos sólidos, tabela zebrada); muda a qualidade de construção: hierarquia de botões, estados, foco, contraste, movimento e um padrão único para as telas que abrem por cima do programa.

Fora do escopo: API, banco, novas funcionalidades, troca de biblioteca de interface.

## Tamanho do trabalho

| Medida | Valor |
|---|---|
| Arquivos Python em `app/ui/` | 152 |
| Linhas em `app/ui/` | cerca de 40 mil |
| Páginas principais | 11 entradas na barra lateral, 8 classes de página |
| Diálogos | 44 arquivos `*_dialog.py`, mais 4 centrais de ação |
| Chamadas `setStyleSheet` fora de `styles.py` | 317 |

Onde os estilos inline se concentram: `chat_message_attachments.py` (45), `timeline_entries.py` (33), `chat_shared_content.py` (15), `executive_dashboard_page.py` (15), `nomus_import_progress_dialog.py` (13), `proposal_chat_dialog.py` (12), `mention_compose_bar.py` (10), `remanagement_review_dialog.py` (9).

## Estratégia

1. **Fundação primeiro.** Tokens, folha de estilo e componentes-base mudam uma vez e já melhoram todas as telas que os usam.
2. **Dois pontos centrais para os diálogos.** Todo diálogo passa por `style_dialog_from_parent()` e `apply_frameless_rounded_dialog()`; o véu, a borda e o raio entram ali e valem para todos os diálogos de uma vez. Depois cada diálogo só ganha o cabeçalho-cartão e a hierarquia de botões.
3. **Uma onda = um subsistema**, pequena o bastante para revisar e reverter.
4. **A suíte é a rede de segurança.** Cada onda fecha com `python -m pytest tests api/tests -q` e comparação de capturas de tela.

### Receita por tela

1. Capturar a tela como está (claro e escuro) com `QWidget.grab()`.
2. Trocar botões pela hierarquia: um primário, demais secundários, Fechar/Cancelar/Limpar fantasma.
3. Trocar cores literais e `setStyleSheet` inline por tokens e `objectName`.
4. Aplicar componentes-base (tabela, selo, campo, estado vazio, esqueleto).
5. Corrigir acentuação dos textos exibidos (sem tocar em chaves internas).
6. Conferir foco por Tab, Esc e 1366x768.
7. Ajustar testes que comparavam texto/estilo; rodar a suíte.
8. Capturar de novo e comparar.

## Ondas

Tamanho: P (até ~300 linhas tocadas), M (até ~1.000), G (acima disso ou alto risco de teste).

### Onda 0 — Fundação (G)

Nada muda de lugar; as telas existentes ficam mais consistentes.

| Entrega | Onde |
|---|---|
| Tokens derivados da paleta ativa (`surface_hover`, `zebra`, `subtle`, `input_border`, `ring`, `status_text`, `accent_soft`) para **todas** as paletas | `app/ui/theme_tokens.py` |
| Cores de status do tema claro ajustadas (verde, amarelo, laranja) | `STATUS_BADGE_COLORS` em `app/ui/styles.py` |
| `scripts/check_contrast.py` rodando sobre todas as paletas | novo |
| Fonte Inter embutida e registrada na inicialização; empacotada no instalador | `app/assets/fonts/`, inicialização, build |
| Folha de estilo: campos, foco, cabeçalho de tabela, zebra, barras de rolagem, tooltip | `app/ui/styles.py` |
| Botão com três variantes (primário, secundário, fantasma) + hover/clique animados | `components/modern_button.py`, `components/app_icon_button.py` |
| Selo sólido, tabela, estado vazio, esqueleto de carregamento | `components/status_badge.py`, `modern_table.py`, `empty_state.py`, novo `skeleton.py` |
| Controle segmentado com contagem; abas com contagem | novos componentes |
| Movimento: curva única, helpers, opção "reduzir animações" | `app/ui/animations.py`, Configurações |
| Casca de janela sobreposta: véu, cabeçalho-cartão, rodapé de ações | `dialog_utils.py`, `frameless_dialog.py`, novos componentes |
| Capturas de referência de todas as telas (antes) | script de captura |

**Andamento (07/10/2026, branch `refinamento-visual-onda-0`, ainda sem commit):**

| Entrega | Situação |
|---|---|
| Tokens derivados (`ui_tokens`, `active_tokens`) | Feito - `app/ui/theme_tokens.py` |
| Cores de status do tema claro + texto do selo escolhido por contraste | Feito - `app/ui/styles.py`; corrigiu também o vermelho do tema escuro (texto branco a 2.7:1) |
| `scripts/check_contrast.py` | Feito - 96 pares, 0 falhas nas paletas `claro` e `escuro` (as únicas oficiais) |
| Fonte Inter embutida | Feito - `app/assets/fonts/`, `app/ui/fonts.py`, registrada em `app/main.py`; `app/assets` já é empacotado pelos `.spec` |
| Folha de estilo: campos, foco de 2 px, cabeçalho de tabela, zebra, seleção, rolagem | Feito |
| Botão com variantes e hover/clique animados | Feito - `ModernButton`; quem não é `accent` passou a ser "secundário" (fundo azul-claro) |
| Controle segmentado, abas com contagem, esqueleto | Feito - componentes novos, ainda sem uso nas telas |
| Curva única, `animate_value`, "reduzir animações" | Feito no código (chave `reduce_motion` da configuração); **falta o botão em Configurações** (Onda 8) |
| Véu das telas sobrepostas + raio 16 | Feito - `dialog_scrim.py`, ligado em `style_dialog_from_parent()` |
| Galeria de conferência | Feito - `python scripts/ui_gallery.py` |
| Selo sólido como componente (`StatusBadge` ainda usa estilo inline) | Movido para a Onda 3 |
| Tabela com linha de 40 px e hover de linha inteira | Movido para a Onda 2 (junto com `process_page.py`, que fixa a altura do cabeçalho) |
| Estado vazio refinado | Movido para a Onda 2 |
| Cabeçalho-cartão e rodapé de ações reutilizáveis | Movido para as Ondas 3 e 4, quando houver uso real |
| Capturas "antes" de todas as telas reais | **Não feito** - exige sessão logada na API; a galeria cobre só os componentes |
| Conferir PDF/Excel exportados com as cores novas de status | **Não feito** |

Risco principal: `ModernButton(accent=True)` é usado em quase toda tela e hoje várias ações por tela são "accent". A variante nova precisa manter `accent=True` funcionando (vira primário) para nada quebrar; a redução para **um** primário é feita tela a tela nas ondas seguintes.

### Onda 1 — Moldura do programa (M)

`main_window.py`, `components/title_bar.py`, `sidebar.py`, `components/top_tabs.py`, `notification_bell.py`, `notification_center_panel.py`, `toast_manager.py`, `toast_notification.py`, `floating_chat_button.py`, `user_profile_popover.py`, `login_summary_banner.py`.

Cuidado: contadores da barra lateral e do sino são pintados em `paintEvent` e os testes leem `_badge_count`.

**Andamento (07/10/2026, mesmo branch, ainda sem commit):**

| Entrega | Situação |
|---|---|
| Barra lateral: rótulos e grupos acentuados, item de 40 px, hover claro sem borda | Feito - `sidebar.py`, `styles.py` |
| Item ativo com ícone visível (antes o ícone azul sumia dentro da pílula azul) | Feito |
| Contador da barra lateral como pílula pintada (antes entrava no texto do botão) | Feito - `NavButton`; hoje nenhuma tela chama `set_nav_badge` |
| Barra superior: textos acentuados, separador pela folha de estilo | Feito - `title_bar.py` |
| Botão flutuante de chat pintado, contador em bolha, hover e foco | Feito - `floating_chat_button.py` |
| Aviso interno, resumo de login, popover do usuário e central de notificações sem estilo inline, acentuados e com um único botão primário | Feito |
| Prévia sem login | Feito - `python scripts/ui_gallery.py --moldura` |
| `main_window.py` (recorte do canto, animação de troca de página) | Sem mudança - já estava no padrão |
| `top_tabs.py` (abas por área) | Sem mudança - testes dependem do estilo por área; fica para a Onda 2 |
| "Controle de Producao Industel" na barra de título | **Não alterado** - vem de `APP_NAME` (`app/version.py`), usado também fora da interface; decidir à parte |

### Onda 2 — Páginas operacionais (G)

| Tela | Arquivo | Tam. |
|---|---|---|
| Controle Geral, Produção, Galvanização, Expedição, Almoxarifado, Parciais (mesma classe) | `process_page.py` | G |
| Itens de produção | `production_items_page.py` | M |
| Itens de galvanização | `galvanization_items_page.py` | M |
| Fiscal | `fiscal_page.py` | G |
| Histórico / Relatórios (tabela simples) | `data_page.py` | P |

`process_page.py` é o protótipo aprovado: filtros, segmentado de status com contagem, tabela, modo lote, paginação. É a tela mais coberta por testes (ordem de colunas, lote, refresh).

**Andamento (07/10/2026, branch `refinamento-visual-onda-0`; Ondas 0 e 1 commitadas, Onda 2 ainda sem commit):**

| Entrega | Situação |
|---|---|
| `process_page.py`: título e ações na mesma linha, filtros sem rótulo na linha de baixo, um único botão primário ("Novo processo" no Controle Geral, "Ações" nas demais áreas e no modo lote) | Feito |
| Filtro de status segmentado quando a área tem até 4 status; combo nas demais | Feito - **sem contagem**: o Controle Geral é paginado pela API e o total por status não vem na resposta; contar exigiria mudar a API |
| Tabela (`modern_table.py`): linha de 40 px, cabeçalho de 34 px, hover e seleção na linha inteira, ícone de status em círculo, selo de 22 px, proposta em negrito | Feito - vale para toda tela que usa `ModernTable` |
| Aviso de prazo ao lado da data ("vencido há X d", "em X d") | Feito - `deadline_alert()`; só apresentação, sem aviso para proposta cancelada ou entregue |
| Esqueleto na primeira carga; estado vazio com ícone em círculo e "Limpar filtros" quando há filtro ativo | Feito |
| Filtro de prazo com rótulos legíveis ("Vencidos", "Próximos 7 dias") | Feito - o valor enviado à API não mudou |
| Itens de produção, itens e cargas de galvanização, Fiscal, Histórico/Auditoria: hierarquia de botões, acentuação e altura de cabeçalho | Feito - **layout dos filtros não foi refeito** nessas telas (continuam com rótulo ao lado do campo) |
| Títulos de página acentuados ("Expedição", "Parciais e pendências", "Histórico") | Feito - `main_window.py` usa os rótulos da barra lateral |
| Mensagens de `QMessageBox` e de erro do Fiscal/Produção | **Não alteradas** - continuam sem acento; ficam para as Ondas 4 e 5, junto com os diálogos dessas áreas |
| Abas por área (`top_tabs.py`) | Sem mudança |
| Prévia sem login | `python scripts/ui_gallery.py --moldura --estado normal|lote|vazio|carregando` |

### Onda 3 — Detalhes e centrais de ação (G)

| Tela | Arquivo |
|---|---|
| Detalhes da proposta + 6 abas | `process_detail_dialog.py`, `process_detail/*.py` |
| Central de ações da proposta | `status_dialog.py`, `action_center/proposal_action_center.py` |
| Central de ações em lote | `action_center/batch_action_center.py`, `batch_status_dialog.py`, `batch_selection_review_dialog.py` |
| Central de ações de carga e fiscal | `action_center/load_action_center.py`, `action_center/fiscal_action_center.py` |
| Cartão de ação | `components/action_card_button.py` |
| Detalhes do painel | `dashboard_details_dialog.py` |

Detalhes da proposta é o segundo protótipo aprovado. Central de ações: a ordem e as categorias (destructive > warning > primary > normal) não mudam; revisar com o agente `action-center-reviewer`.

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Peças reutilizáveis das telas sobrepostas: painel, grades chave/valor e em blocos, número de resumo, nota, barra de progresso, trilha do fluxo, abas com contagem | Feito - `components/detail_widgets.py` |
| Selo de status pintado (`StatusBadge`), com `area_badge()` e `neutral_badge()`; selo em coluna de tabela | Feito - `components/status_badge.py`, `components/badge_delegate.py` |
| Detalhes da proposta: cabeçalho-cartão com selo e aviso de prazo, abas com contagem, esqueleto na primeira carga, erro com "Tentar de novo" (antes a janela fechava em silêncio) | Feito - `process_detail_dialog.py` |
| Abas Resumo (trilha do fluxo, barra de peso, atalhos "Ver itens"/"Ver cargas"), Itens, Fluxo (um painel por área, em duas colunas), Cargas, Fiscal/Entrega, Histórico | Feito - `process_detail/*.py` |
| Descrição longa de item quebra linha, com altura mínima de 40 px | Feito, conforme decidido |
| Rótulos de status acentuados na origem ("Em produção", "Liberado para produção", "Aguardando separação"...) | Feito - `STATUS_LABELS`, `AREA_STATUS_LABEL_OVERRIDES`, `LOAD_STATUS_LABELS`, `PERMISSION_AREAS` em `backend_adapter.py` e `FISCAL_STATUS_LABELS`; só os rótulos exibidos, as chaves não mudaram |
| "Não informado" para peso ausente | Feito - `format_weight_or_missing()` |
| Centrais de ação (proposta, lote, carga, fiscal), correção administrativa, ações em lote antigas, detalhes do painel e revisão de seleção: selos sólidos, títulos pela folha de estilo, Fechar/Cancelar fantasma, textos acentuados | Feito - cartões de ação (`action_card_button.py`) não mudaram, já seguiam a hierarquia |
| Cabeçalho-cartão e rodapé de ações como componentes próprios | Não criado - o cabeçalho de Detalhes é montado no próprio diálogo; extrair quando a Onda 4 precisar do segundo uso |
| Prévia sem login | `python scripts/ui_gallery.py --moldura --detalhes 0..5` |

### Onda 4 — Formulários e assistentes de produção (G)

`process_form_dialog.py`, `item_flow_dialog.py`, `item_selection_dialog.py`, `item_weight_dialog.py`, `production_registration_dialog.py`, `flow_review_dialog.py`, `galvanization_load_dialog.py` (1.904 linhas), `galvanization_load_details_dialog.py`. O remanejamento (a tela legada `early_remanagement_dialog.py` e os cinco passos `remanagement_*_dialog.py`) deixou de ser uma sequência de diálogos: virou **um assistente de 4 passos em uma janela** (`app/ui/remanagement_wizard/`, ver `REMANEJAMENTO_ASSISTENTE_UNICO.md`), já no padrão novo, com trilha de passos, rodapé de ações e caixa de aviso azul-clara.

Aqui entra o rodapé de ações (Cancelar, Voltar, confirmar) e o indicador de passo nos assistentes. Clique fora **não** fecha.

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Os 14 diálogos: textos exibidos acentuados (títulos, rótulos, colunas, dicas, avisos, mensagens de `QMessageBox`) | Feito |
| Cancelar/Fechar/Limpar como botão fantasma; títulos e destaques pela folha de estilo em vez de estilo inline | Feito |
| Um único botão primário por diálogo | Feito - só dois tinham dois ("Adicionar item" no cadastro de proposta e "Aplicar" na lista de cargas viraram secundários) |
| Véu, cantos e botões animados | Já vinham da Onda 0 |
| Layout dos diálogos (cabeçalho-cartão, rodapé de ações, indicador de passo) | Feito em 07/10/2026, na fase de layout - ver o bloco "Layout dos diálogos" abaixo |
| Estilos inline restantes nesses arquivos | Não removidos (cores de alerta e destaques específicos) |

A passada foi mecânica (ferramenta que só toca texto exibido, nunca chaves ou códigos) e conferida pela suíte: 6 testes que comparavam os textos antigos foram atualizados.

### Onda 5 — Fiscal e Nomus (G)

`fiscal_emission_dialog.py`, `fiscal_emission_draft_dialog.py`, `fiscal_emission_review_dialog.py`, `fiscal_item_selection_dialog.py`, `nomus_api_import_dialog.py`, `nomus_api_settings_dialog.py`, `nomus_batch_import_dialog.py`, `nomus_batch_conference_dialog.py`, `nomus_import_progress_dialog.py`, `proposal_import_dialog.py`, `api_proposals_readonly_dialog.py`.

Só aparência; conferir contra `NOMUS_FISCAL_INTEGRATION_CONTRACT.md` com o agente `nomus-integration-guide`.

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Os 11 diálogos fiscais e do Nomus: textos exibidos acentuados, Cancelar/Fechar/Limpar como botão fantasma, títulos pela folha de estilo | Feito |
| Mensagens e avisos que tinham ficado para trás nas páginas (Fiscal, itens de Produção e de Galvanização) | Feito |
| Revisão contra o contrato Nomus/fiscal pelo agente `nomus-integration-guide` | Feita - nenhuma violação; apontou um teste que tinha ficado sem efeito, já corrigido |
| Guarda contra acento em valor interno | Feito - `tests/test_visual_text_guards.py` |
| Layout dos diálogos | Feito - ver o bloco "Layout dos diálogos" |
| Mensagens vindas dos serviços `app/services/nomus_*` | Não alteradas - são texto da camada de serviço e parte delas é comparada em testes |

**Erro encontrado e corrigido nesta onda:** a ferramenta de acentuação transformou o valor interno do filtro de status fiscal (`situacao:CP_EM_PROCESSAMENTO` e outros três) em `situação:...`, o que quebraria o filtro. Foi revertido antes de qualquer commit, a regra da ferramenta foi endurecida (literal sem espaço e com separador nunca é tocado) e todo o código já alterado foi varrido atrás do mesmo padrão, sem outras ocorrências.

### Onda 6 — Painéis e relatórios (M)

`dashboard_page.py`, `executive_dashboard_page.py`, `operational_reports_page.py` e os componentes `kpi_card.py`, `card_indicador.py`, `grafico_status.py`, `header_dashboard.py`, `tabela_prazos.py`, `barra_progresso_area.py`.

O redesenho seguiu o que o usuário aprovou nos dois protótipos (manter a identidade de hoje, só refinar), sem protótipo próprio para painéis: a conferência visual foi feita na galeria (`python scripts/ui_gallery.py --moldura --painel geral|executivo|relatorios`, com `--tema escuro` e `--altura` para ver a página inteira).

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Painel geral, Dashboard Executivo, Relatórios Operacionais e seus componentes: textos exibidos acentuados, Limpar/Fechar como botão fantasma, títulos pela folha de estilo | Feito |
| Filtro "Confiabilidade" do Dashboard Executivo | Corrigido - enviava o texto da opção em minúsculas como valor; passou a usar um valor interno (`itemData`), senão "Média" com acento deixaria de filtrar |
| Redesenho do Painel geral | Feito: cabeçalho em degradê vira a faixa padrão de página (`page_header.py`) com hora da última atualização e botão Atualizar (único primário, ícone gira durante a consulta); cartões de indicador sem sombra, com hover e anel de foco pela folha de estilo e Enter/Espaço abrindo as propostas; barras de área animadas; legenda do gráfico com a linha inteira clicável; selos de prazo pintados, neutros quando a contagem é zero; os cartões antigos ficam na tela até os novos chegarem |
| Redesenho do Dashboard Executivo | Feito: faixa padrão e filtros sem rótulo lateral (placeholder e nome acessível); grupos de indicadores em painel suave; ícone na cor do significado (atraso e pendência crítica em perigo, vencendo e falta emitir em atenção, emitida em sucesso) em vez de cor por posição; barras animadas; selo de severidade sólido nos alertas, com a lista do tamanho do conteúdo; gargalo atual com selo de área; números no padrão brasileiro (21.400 kg) |
| Redesenho dos Relatórios Operacionais | Feito: faixa padrão com Gerar relatório como único primário e Exportar CSV como secundário; filtros sem rótulo lateral; cartões ocupando a largura; os três diálogos de consulta (registros, proposta, carga) com cabeçalho-cartão e rodapé padrão; rótulos de coluna e de relatório acentuados, o que vale também para o cabeçalho do CSV exportado |
| Estilos inline e sombras dos painéis | Zerados nas três páginas e nos componentes (`kpi_card`, `card_indicador`, `grafico_status`, `header_dashboard`, `tabela_prazos`, `barra_progresso_area`, `badge_status`) |

### Onda 7 — Chat (G)

`chat_center_page.py`, `proposal_chat_dialog.py` (1.897 linhas) e os componentes `chat_message_attachments.py` (2.218 linhas, 45 estilos inline), `timeline_entries.py`, `chat_shared_content.py`, `chat_pending_attachments.py`, `mention_compose_bar.py`, `proposal_activity_panel.py`.

Era a área com mais estilo inline e mais pintura própria. Como nos painéis, o redesenho manteve a identidade de hoje; galeria: `python scripts/ui_gallery.py --chat [--tema escuro] [--altura 1300]`.

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Central de chat, chat da proposta e componentes (anexos, linha do tempo, conteúdo compartilhado, barra de menção, painel de atividade): textos exibidos acentuados e títulos pela folha de estilo | Feito |
| Handlers da central de ações (cancelar proposta, galvanização, produção): textos acentuados e Cancelar como botão fantasma | Feito |
| Balões e cartões da linha do tempo | Feito: balão próprio, dos outros (com a mensagem que menciona você marcada por propriedade), separador de dia, nota interna, pergunta dirigida e resposta citada saem do estilo escrito no código e passam à folha de estilo; texto sobe de 9-12 px para 11-13 px; selos de status (Aguardando, Respondida, IMPORTANTE) sólidos como no resto do programa; botão "mais ações" com ícone no lugar do caractere "⋮", que a fonte não tem |
| Largura e alinhamento dos balões | Corrigidos: o corpo do balão tem a largura natural do texto (até 420 px), em vez da largura proporcional do `QLabel`, que deixava a mensagem curta estreita e alta; a coluna do avatar tem largura fixa, então a mensagem agrupada alinha com a primeira e a linha deixa de esticar na vertical quando há poucas mensagens |
| Anexos e visualizador de mídia | Feito: cartão de arquivo, vídeo, áudio, galeria, barra de transferência, anexo pendente e visualizador usam a folha de estilo; o fundo escuro do visualizador e as sobreposições vêm de tokens fixos (`media_bg`, `media_text`, `overlay`...), a única exceção aos tokens derivados da paleta, porque a mídia é escura nos dois temas; os ícones da barra do visualizador usavam um cinza claro fixo que sumia sobre o fundo claro do diálogo |
| Barra de composição, conversas e aba Mídia e arquivos | Feito: área de soltar arquivo, prévia de resposta, ponto de presença, abas da conversa, destaque temporário de mensagem e selo de situação passam a estado por propriedade (`set_style_state`), sem reescrever stylesheet em tempo de execução; ponto de status e avatar pintados; contagem de não lidas na cor de perigo com o texto de maior contraste |

### Onda 8 — Sistema e acesso (M)

`login_dialog.py`, `first_access_dialog.py`, `settings_page.py`, `settings_dialog.py`, `notification_preferences_widget.py`, `user_dialog.py`, `user_profile_dialog.py`, `about_dialog.py`, `update_dialog.py`, `update_audit_dialog.py`, `maintenance_mode_dialog.py`, `compatibility_gate_dialog.py`, `api_diagnostic_dialog.py`.

Login, atualização e manutenção abrem **sem** janela principal por trás: não há véu; a janela usa o mesmo cabeçalho-cartão e botões.

**Andamento (07/10/2026):**

| Entrega | Situação |
|---|---|
| Os 13 diálogos e páginas de sistema: textos exibidos acentuados, Cancelar/Fechar como botão fantasma, títulos pela folha de estilo | Feito |
| Botão "Reduzir animações" em Configurações | Feito em Aparência: caixa "Reduzir animações" aplicada na hora (`set_reduced_motion`) e gravada em `reduce_motion`; vale para qualquer usuário, sem depender da permissão de editar configurações. Os textos exibidos da página (menu e títulos) também ganharam acento |
| Layout dessas telas | Feito para os diálogos de janela (usuários, perfil, Sobre, Configurações, Nomus); login, primeiro acesso, atualização, manutenção e compatibilidade **não** mudaram: abrem sem janela principal e ficam com a barra de título nativa |
| Vários botões primários em Configurações | Mantidos - cada um é a ação principal de uma seção diferente da página |

## Layout dos diálogos (07/10/2026)

Peças novas em `app/ui/components/dialog_shell.py`: `dialog_header()` (cabeçalho-cartão), `dialog_footer()` (rodapé de ações com resumo à esquerda), `StepIndicator` ("Passo N de M"), `set_notice_kind()` / `set_validation_state()` (aviso e erro de campo por propriedade, sem estilo inline) e `standardize_tables()`.

**Casca central.** `style_dialog_from_parent()` agora instala em todo diálogo, de uma vez: sem moldura do Windows com cantos de 16 px (só quando existe janela principal por trás; sem ela a barra de título nativa fica, porque é a única forma garantida de fechar), véu atrás e tabelas padronizadas (sem grade, zebra, título à esquerda, linha de pelo menos 40 px). Regras de estilo corrigidas junto: o fundo de todo `QWidget` dentro de diálogo deixou de ser pintado (criava faixas cinzas dentro dos painéis) e só cartão clicável muda de cor no hover.

**Diálogos com layout refeito (cabeçalho-cartão e rodapé):** cadastro de proposta; fluxo, seleção e peso de itens; registro e revisão de produção; revisão de fluxo (passos 1 e 2); remanejamento (passos 1 a 5 e a tela única); montar/editar carga, alocação, revisões, retorno, gerenciador e detalhes da carga; emissão fiscal (passos 1 a 3 e a simples); importar do Nomus (busca, lote, conferência) e conferência de PDF; consulta pela API; centrais de ação (proposta, lote, carga, fiscal); correção administrativa; propostas selecionadas; detalhes do painel; usuários (editor e gerenciador); meu perfil; Sobre; Configurações.

**Abas** de `QTabWidget` trocadas por `CountTabWidget` nos diálogos de carga (montar, retorno, detalhes) e na conferência do Nomus.

**Não refeitos:** diálogo de progresso do Nomus (visual próprio, com cerca de 13 estilos inline dependentes do tema), diagnóstico da API (linha de botões muito larga, pede redesenho), diálogo antigo de ações em lote (`batch_status_dialog`, picker legado) e os de inicialização citados acima.

## Painéis, chat e estilos inline (07/10/2026)

Peças novas: `app/ui/components/page_header.py` (faixa de topo de página: título na cor de destaque, subtítulo, informações de apoio e ações, com área para filtros), `style_state.py` (`set_style_state` muda propriedade de estado e reaplica o estilo; `StatusDot` é o ponto de cor pintado), `StageChip` e `StatusBadge.colors()` em `status_badge.py`, `AvatarLabel` em `avatar.py` e os tokens `media_*` / `overlay*` / `on_overlay` em `ui_tokens()`.

Regras de estilo novas em `styles.py`: cartão de indicador, legenda, linha de alerta e painel suave (painéis); balões, cartões, anexos, vídeo, áudio, composição, conversas, abas e visualizador de mídia (chat); avisos de sucesso, toast, cabeçalho de coluna e o diálogo de progresso do Nomus. `check_contrast.py` passou a conferir também os pares do chat (hora na bolha, texto do visualizador, contagem não lida...).

**Diálogo de progresso do Nomus** refeito sobre a casca padrão: cabeçalho-cartão no lugar do degradê, painel de progresso e rodapé padrão; os 13 estilos inline (cópia dupla da folha de estilo, com degradê) viraram regras na folha de estilo do app.

**Estilos inline** em `app/ui`: 317 no início, 12 agora. O que sobra é intencional: aplicação do tema (`main_window`, `dialog_utils`, `frameless_dialog`), identidade de área (`area_identity`, `top_tabs`, cujos testes conferem a cor no stylesheet), variantes do cartão da central de ações (`action_card_button`, contrato do Action Center) e o diálogo de atualização, que abre sem janela principal.

**Filtros sem rótulo lateral** também em Fiscal (e nos relatórios fiscais), itens de Produção, itens de Galvanização e cargas: placeholder e primeira opção autoexplicativa ("Todos os status fiscais", "Todas as situações"), nome acessível em cada campo.

**Exportações.** PDF e CSV de seleção (`ProcessPage._export_pdf/_export_csv`) e o CSV dos relatórios escrevem texto puro vindo de `display_cell`: não usam as cores de status, então a mudança de cor não os afeta. O texto de status agora sai acentuado e o CSV já é gravado em UTF-8 com BOM, que o Excel lê certo.

**Instalador.** Os `.spec` oficiais incluem `app/assets` inteiro e as seis fontes Inter estão versionadas. Conferido gerando o pacote de verdade (`python -m PyInstaller ControleProducao.spec`, em pasta temporária): `ControleProducao.exe` + `_internal/app/assets/fonts` com as seis fontes e a licença, no mesmo caminho relativo que `app/ui/fonts.py` usa. Obs.: o build em um caminho longo estoura o limite de 260 caracteres do Windows (arquivo de licença do numpy); gere o pacote em pasta curta. O instalador do Inno Setup não foi gerado.

**Contagem por status no Controle Geral** (filtro segmentado): **não feita**. A lista é paginada e a API não devolve o total de cada status; mostrar número ali seria mentir. Depende de um endpoint de totais por status em `api/app/modules/proposals/` (mais testes da API e entrada na documentação do contrato); fica fora do refinamento visual.

## Situação geral (07/10/2026)

As nove ondas foram refeitas no padrão: fundação, moldura, páginas operacionais, Detalhes da proposta, centrais de ação, layout de todos os diálogos, painéis e relatórios, chat e a página de Configurações. Suíte completa (Desktop + API) ao fim: 2446 testes passando, 340 pulados; estilos inline em `app/ui`: 317 no início, 12 agora.

O que continua em aberto, em ordem de valor:

1. **Conferir no sistema real, logado, nos dois temas.** Até aqui a conferência visual foi feita na galeria (`scripts/ui_gallery.py`, com `--moldura`, `--painel` e `--chat`) e pelos testes; nenhuma tela foi vista com dados reais. É o passo que mais pode revelar ajuste fino (larguras com dado real, textos longos, 1366x768).
2. **Contagem por status no filtro segmentado do Controle Geral**: precisa de endpoint de totais na API (ver o bloco acima).
3. Diálogos que ficaram de fora do layout novo: diagnóstico da API, ações em lote antigo (`batch_status_dialog`) e os de inicialização (login, primeiro acesso, atualização, manutenção, compatibilidade, que abrem sem janela principal).

## Ordem e dependências

```
Onda 0 ──► Onda 1 ──► Onda 2 ──► Onda 3 ──► Onda 4 ──► Onda 5
                                   │
                                   └──► Ondas 6, 7 e 8 (independentes entre si, em qualquer ordem)
```

As ondas 6 e 7 precisam de protótipo aprovado antes de começar.

## Fechamento de cada onda

- Suíte verde: `python -m pytest tests api/tests -q` (travou: agente `test-doctor`).
- `scripts/check_contrast.py` sem falha.
- Capturas antes/depois das telas da onda, claro e escuro.
- Documento de fechamento pela skill `fase-report`.
- Commits separados por subsistema pela skill `commit-by-subsystem`.

## Riscos

| Risco | Como tratar |
|---|---|
| Estilo inline sobrescreve a folha global e a tela "não pega" o tema novo | Remover os inline da tela na própria onda |
| Fonte e alturas novas estouram layouts de largura fixa | Conferir cada tela em 1366x768 |
| Testes que comparam texto de botão/rótulo quebram com a acentuação | Ajustar o teste junto, na mesma onda |
| Mexer em diálogo deixa um `QMessageBox` real abrir em teste e trava a suíte | Não trocar `QMessageBox`; `timeout=25` já denuncia; agente `test-doctor` |
| Véu fica na tela se um diálogo fechar por exceção | Esconder o véu no `finished` do diálogo e num `try/finally` do ponto central |
| Diálogos abertos sem janela principal (login, atualização) | Ponto central só cria véu quando há janela principal visível |
| Cores de status mudam em relatórios/exportações que reutilizam `status_color` | Conferir PDF/Excel exportados na Onda 0 |
| Uma paleta nova reprova no contraste com os tokens derivados | `check_contrast.py` roda em todas as oficiais; ajustar a derivação, não a paleta |

## Decisões já tomadas pelo usuário

- Manter o azul atual e a identidade visual de hoje.
- Embutir a fonte Inter.
- Movimento "mais vivo" (hover/clique animados, marcadores que deslizam, pulso na etapa atual).
- Selos sólidos; verde, amarelo e laranja do tema claro escurecidos para o texto branco ficar legível.
- Telas sobrepostas seguem o padrão de "Detalhes da proposta".
- A pasta `prototipos/` é versionada no repositório como referência visual.
- Cabeçalho de tabela alinhado à esquerda (números à direita). **Revisto em 08/10/2026:** nas tabelas operacionais (`ModernTable`) título e texto de todas as colunas ficam centralizados, e a coluna Proposta ficou mais estreita (112 px); tabelas de diálogo continuam à esquerda.
- Filtros das páginas sem rótulo ao lado do campo.
- Descrição longa de item **quebra em várias linhas**, como hoje. O protótipo de Detalhes corta com "..." na aba Itens; nesse ponto vale o comportamento atual (`configure_wrapping_table`), não o protótipo.

## Pendências

1. Abrir o sistema real, logado, e conferir as telas nos dois temas.
2. Gerar o instalador (Inno Setup) com a versão final e instalar numa máquina limpa: a conferência do pacote já foi feita (fontes presentes no `.exe` do PyInstaller), falta só o instalador completo.
