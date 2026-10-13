---
name: qt-industrial-ui
description: Padrão visual do Desktop PySide6 do Controle de Produção Industel - tokens, botões, tabelas, selos de status, movimento e, principalmente, o padrão das telas que abrem por cima do programa (diálogos). Use ao criar, refinar ou revisar qualquer tela, diálogo ou componente em app/ui/, e ao migrar uma tela existente para o padrão refinado.
---

Padrão visual aprovado pelo usuário em 07/10/2026 a partir de dois protótipos. Vale para todo `app/ui/`.

**Referência viva (rode antes de mexer em tela):**

- `python prototipos/controle_geral/preview.py` - página operacional (tabela, filtros, modo lote).
- `python prototipos/detalhes_proposta/detalhes.py --aba 0..5` - tela que abre por cima do programa.
- Ambos aceitam `--tema escuro`, `--sem-animacao` e `--shot arquivo.png`; o primeiro aceita `--contraste`.

Os protótipos são a fonte da verdade de aparência. Eles não importam `app/`; ao migrar, o visual vai para os componentes reais, não se copia o arquivo do protótipo para dentro de `app/`.

## Regra nº 1: preservar a identidade atual

O usuário rejeitou um visual "web moderno" (cartões brancos soltos, selos em tom pastel) e pediu o visual de hoje, refinado. Portanto **mantenha**:

- moldura azul-clara em volta (barra lateral e topo) e conteúdo com canto superior esquerdo arredondado;
- barra lateral com grupos em maiúsculas, ícones na cor de destaque e item ativo como pílula cheia;
- título de página na cor de destaque, em negrito, com a barra vertical à esquerda da faixa de filtros;
- tabela de ponta a ponta, cabeçalho azul-claro em negrito, linhas zebradas, sem linhas divisórias;
- selos de status **sólidos**, de largura fixa na coluna, texto centralizado;
- ícone de status dentro de um círculo; botão redondo de chat no canto.

**Refine por cima** (é isto que muda): hierarquia de botões, filtro de status segmentado com contagem, aviso de prazo, estados de carregamento/vazio, anel de foco, acentuação correta, contraste medido e movimento.

Em dúvida entre "mais bonito" e "mais parecido com hoje", escolha o parecido com hoje.

## Regras de implementação (Qt)

1. **Cor só vem de token.** Nunca escreva hexadecimal em tela ou componente. Tokens são **derivados** da paleta ativa por `ui_tokens()` em `app/ui/theme_tokens.py` (componente pintado usa `active_tokens()`), para funcionar nas paletas `claro` e `escuro` e em qualquer outra que surgir. Tabela em [references/tokens.md](references/tokens.md).
2. **Sem `setStyleSheet` inline novo.** Estilo vai em `app/ui/styles.py` (`app_stylesheet`) por `objectName`, ou é pintado no `paintEvent` do componente. Ao tocar numa tela, remova os inline que encontrar nela.
3. **Estado dinâmico** por propriedade (`setProperty` + `style().unpolish/polish`) ou por pintura, nunca trocando stylesheet em tempo de execução.
4. **Componentes pintados** (botão, selo, abas, trilha) animam com `QVariantAnimation` sobre um atributo e chamam `update()`. Não anime `geometry` nem `minimumWidth` de widget dentro de layout.
5. **Não empilhe `QGraphicsEffect`**: um widget com efeito dentro de outro com efeito renderiza errado. Fade de entrada usa `QGraphicsOpacityEffect` temporário, removido no `finished`.
6. **Nunca bloqueie a thread de UI**: carga de dados continua em `start_worker`; enquanto carrega, mostre esqueleto, não "Carregando...".
7. **Convenções do projeto que o refinamento não pode quebrar** (ver CLAUDE.md): contador/badge pintado em `paintEvent` (testes leem `_badge_count`), contrato do Action Center (`ActionDescriptor`, ordem destructive > warning > primary > normal), e `QMessageBox` mockado no módulo que importa. **Não troque `QMessageBox` por diálogo próprio** nesta migração - só estilize.
8. **Textos com acentuação correta** ("Produção", "Ações", "Histórico"). Não altere chaves internas (`"PRODUCAO"`, `status_producao`), só o texto exibido; confira testes que comparam rótulos.

## Componentes

Já existem em `app/ui/components/` (confira com `python scripts/ui_gallery.py`, que mostra todos nos dois temas sem precisar logar; `--moldura` mostra a página Controle Geral real, `--moldura --detalhes N` abre Detalhes da proposta por cima, `--painel geral|executivo|relatorios` mostra os painéis e `--chat` as mensagens do chat; `--altura N` mostra a página inteira):

- `ModernButton(texto, icone, accent=..., variant="primary|secondary|ghost|danger")`.
- `SegmentedControl`, `CountTabs`, `SkeletonRows`, `EmptyState(..., action=botao)`.
- `ModernTable` (tabela operacional: linha de 40 px, hover/seleção na linha inteira, selo, aviso de prazo via `deadline_alert()`).
- `StatusBadge(texto, fundo, texto_cor)`, `area_badge(texto, cor)`, `neutral_badge(texto, palette)`; em `QTableWidget`, `BadgeColumnDelegate` + `set_status_badge(item, status, palette)`.
- `detail_widgets.py`: `make_panel()`, `kv_grid()`, `block_grid()`, `stat_block()`, `note_box()`, `ThinProgressBar`, `IconChip`, `FlowTrail`, `CountTabWidget` (abas + páginas com a API do `QTabWidget`).
- `dialog_shell.py`: `dialog_header(titulo, subtitulo, status=[...], actions=[...])`, `dialog_footer(left=[...], right=[...])`, `StepIndicator(passo, total)`, `set_notice_kind()`, `set_validation_state()`, `standardize_tables()`. **Todo diálogo novo monta o topo com `dialog_header` e o rodapé com `dialog_footer`**; `dialog_header` aceita o `QLabel` que a tela já tinha, então atributos que testes consultam continuam existindo.
- `page_header.py`: `page_header(titulo, subtitulo, side=[...], actions=[...])` / `setup_page_header(frame, ...)` - faixa de topo das páginas de painel e relatório (título na cor de destaque, ações à direita, `frame.body_layout` para os filtros). Painel de conteúdo: `make_panel()`; painel interno suave: objectName `SoftPanel`.
- `style_state.py`: `set_style_state(widget, active=True, ...)` troca estado por propriedade e reaplica o estilo (nunca reescreva stylesheet em tempo de execução); `StatusDot(cor)` é o ponto de cor pintado. `status_badge.py` tem também `StageChip` (etapa de linha do tempo) e `StatusBadge.colors()`; `avatar.py` tem `AvatarLabel`.
- Chat: balões, cartões, anexos e composição são estilizados em `styles.py` por nome de objeto e propriedade (`tone`, `mentionsMe`, `dropActive`, `active`, `card`); o visualizador de mídia usa os tokens fixos `media_*`/`overlay*`. Galeria: `python scripts/ui_gallery.py --chat`.
- Casca e véu de diálogo (`window_shell.py`, `dialog_scrim.py`, `install_dialog_shell`), ligados sozinhos por `style_dialog_from_parent()`: sem moldura nativa, fundo transparente com a moldura pintada (canto liso de 24 px, borda com volume, duas sombras), mola ao abrir e encolher ao fechar, tabelas padronizadas. Tela de inicialização (sem janela principal por trás) usa `standalone=True` e precisa de fechamento próprio (`window_title_row()` ou botão Fechar). Popup usa `install_popup_shell()`; menu e lista de combo são tratados por `floating_chrome.py`; `QMessageBox`/`QInputDialog` por `message_boxes.py`. Não chame `apply_frameless_rounded_dialog` à mão. Padrão aprovado em 13/10/2026 (`prototipos/acoes_proposta/acoes.py`); plano e andamento em `docs/architecture/PADRAO_JANELAS_PLANO_MIGRACAO.md`.
- Animação de atributo pintado: `animate_value()` em `app/ui/animations.py`.

Tela de referência no código real: `app/ui/process_detail_dialog.py` e `app/ui/process_detail/`.

Painel de conteúdo usa `objectName` `DetailPanel` (ou `make_panel()`), não `Panel`: `Panel` muda de cor no hover, o que só faz sentido para cartão clicável.

| Componente | Regra |
|---|---|
| Botão primário | Fundo na cor de destaque. **Um por tela/diálogo** - a ação que o usuário mais provavelmente quer. |
| Botão secundário | Fundo azul-claro (`surface_alt`), texto normal, ícone na cor de destaque. Para as demais ações. |
| Botão fantasma | Sem fundo, ícone na cor de destaque. Para Limpar, Cancelar, Fechar, paginação. |
| Botão destrutivo | Só em confirmação de ação irreversível; cor `danger`. |
| Campo | Altura 34, raio 10, borda `input_border` (>= 3:1); foco = borda de 2 px na cor `ring`. |
| Filtro de status | Controle segmentado quando há até 4 status (o marcador desliza); combo acima disso. A contagem por opção só entra onde a tela tem o total de cada status - a lista paginada do Controle Geral não tem, então lá o segmentado fica sem número. O `QComboBox` continua sendo a fonte da verdade e o segmentado só o espelha (ver `ProcessPage._sync_status_segments`). |
| Tabela | Linha 40, cabeçalho 34, zebra, hover, linha selecionada com barra de 4 px à esquerda. Texto de célula e título de coluna **centralizados** nas tabelas operacionais (`ModernTable`; decisão do usuário em 08/10/2026, vale também para números; prazo + aviso formam um bloco centralizado). Tabelas de diálogo seguem à esquerda. Descrição longa **quebra em várias linhas** (a linha cresce), como hoje - o protótipo de Detalhes corta com "..." na aba Itens e nesse ponto não deve ser seguido. |
| Filtros de página | Sem rótulo ao lado do campo; o placeholder e as opções explicam o filtro. Cada campo tem nome acessível (`setAccessibleName`). |
| Selo de status | Sólido, raio 11, altura 22, texto `status_text`, largura fixa da coluna. Fora de tabela, largura do texto + 28. |
| Prazo | Data + aviso: "vencido há X d" (`danger`, com ícone) ou "em X d" (`warning`) quando faltam até 7 dias. Nada se a proposta está encerrada. |
| Valor vazio | Travessão "—" em cor `subtle`, nunca "-" em negrito. |
| Estado vazio | Ícone em círculo, título, texto e botão "Limpar filtros". |
| Carregando | Esqueleto com brilho no lugar do conteúdo. |

Altura de controle 34, raios 10 (campo/botão), 14 (painel) nas páginas. Janela sobreposta: 24, com painel 18, cartão 16 e campo 12 dentro dela; popup 16; menu 12. Espaçamento em múltiplos de 4. Alvo de clique >= 32 px.

## Movimento

- Só opacidade, cor e escala pintada. Entrada 180-240 ms, saída 120-180 ms, curva `cubic-bezier(.23, 1, .32, 1)`.
- Janelas são a exceção, no estilo macOS/iOS: nascem em 88% e saltam para o lugar com mola (`spring`, ~550 ms até assentar, parece no lugar em ~200 ms); saem encolhendo até 94% em 180 ms; curva fora da mola `cubic-bezier(.25, .1, .25, 1)` (`animations.ease`). Use `transition()` de `app/ui/animations.py`; animação de janela fica desligada na plataforma `offscreen` e com Reduzir animações (`window_motion_enabled()`).
- Botão: hover 140 ms, clique encolhe 3% em 80 ms. Marcadores (segmentado, abas) deslizam em 240 ms.
- A ação dispara **antes** da animação; nada espera animação terminar.
- Uma única animação contínua por tela, no máximo (o pulso da etapa atual).
- Tudo respeita a opção de reduzir movimento: com ela ligada, duração zero.

## Telas que abrem por cima do programa

Toda janela sobreposta (detalhes, formulário, assistente, confirmação) segue **um** padrão. Especificação completa, tamanhos e regras de fechamento em [references/janelas-sobrepostas.md](references/janelas-sobrepostas.md). Resumo:

1. **Véu** escurece a tela de trás; a janela aparece com fade.
2. **Janela** com fundo `bg`, canto liso de 24 px, borda com volume (aro, filete de luz, sombreado) e sombra própria, sem barra de título do Windows.
3. **Cabeçalho-cartão**: título 18 px em negrito, subtítulo, linha de situação (selo + prazo) e, à direita, as ações - secundárias, **uma** primária e "Fechar" sempre por último.
4. **Abas** (quando houver) com contagem e traço que desliza.
5. **Corpo** em painéis brancos de raio 14; tabelas em moldura arredondada.
6. **Rodapé de ações** só em formulário/assistente: Cancelar (fantasma), Voltar (secundário), confirmar (primário), alinhados à direita.

## Checklist antes de dar uma tela por pronta

- [ ] Nenhum hexadecimal nem `setStyleSheet` inline novo.
- [ ] Um único botão primário; "Fechar"/"Cancelar" é fantasma.
- [ ] Contraste: texto >= 4.5:1, borda de campo e ícone >= 3:1, nas duas pontas (tema claro e escuro) e nas demais paletas.
- [ ] Foco visível navegando só com Tab; ordem de tabulação lógica; Esc fecha diálogo.
- [ ] Status nunca depende só de cor (tem texto ou ícone).
- [ ] Estados: carregando, vazio, erro.
- [ ] Cabe em 1366x768 sem cortar ação.
- [ ] Captura de tela antes/depois (`QWidget.grab()`), claro e escuro.
- [ ] `python -m pytest tests api/tests -q` passa; se travar, agente `test-doctor`.
- [ ] Área de Action Center: agente `action-center-reviewer`. Área Nomus/fiscal: agente `nomus-integration-guide`.

Plano de migração tela a tela: `docs/architecture/REFINAMENTO_VISUAL_PLANO_MIGRACAO.md`.
