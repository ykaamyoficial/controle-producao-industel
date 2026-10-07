# Tokens

Valores de referência dos protótipos. No sistema os tokens novos **não são constantes**: `ui_tokens(palette)` em `app/ui/theme_tokens.py` os calcula a partir da paleta ativa, então os hexadecimais reais diferem um pouco dos da tabela (o tema escuro oficial, por exemplo, usa fundo `#1b2740`, não o do protótipo).

Como usar no código:

- Em QSS: `app_stylesheet()` já expõe `zebra`, `table_header`, `selected`, `subtle`, `input_border` e `ring`.
- Em componente pintado à mão: `active_tokens()` (paleta registrada por `app_stylesheet()`).
- Em delegate/tela que tem `service`: `ui_tokens(service.palette)`.
- Paletas oficiais: `claro` e `escuro` (`OFFICIAL_COLOR_PALETTES` em `app/services/backend_adapter.py`).
- Nome no código do token "header" da tabela abaixo: `table_header`. `chrome` continua vindo de `chrome_bg_color()`; `status_text` é `_contrast_text(cor)` em `app/ui/styles.py`.

## Cores

| Token | Já existe em `service.palette`? | Claro | Escuro | Uso |
|---|---|---|---|---|
| `chrome` | via `chrome_bg_color()` | `#CBD8EF` | `#0A1020` | moldura: barra lateral e topo |
| `bg` | sim | `#F5F7FB` | `#0F172A` | fundo do conteúdo e das janelas sobrepostas |
| `surface` | sim | `#FFFFFF` | `#172033` | painéis, campos, faixa de filtros |
| `surface_alt` | sim | `#E8F1FF` | `#22304A` | botão secundário, painel de destaque, trilho do segmentado |
| `surface_hover` | novo | `#DCE9FB` | `#2A3B59` | hover de linha e de botão secundário |
| `zebra` | novo | `#EEF4FE` | `#1C2740` | linhas ímpares da tabela |
| `header` | `tree_heading` | `#DBEAFE` | `#24324A` | cabeçalho de tabela |
| `selected` | `tree_selected` | `#BFDBFE` | `#0E5E78` | linha selecionada/marcada |
| `text` | sim | `#0F172A` | `#F8FAFC` | texto |
| `muted` | sim | `#475569` | `#CBD5E1` | rótulos, subtítulos |
| `subtle` | novo | `#5B6B82` | `#9FB0C6` | placeholder, valor vazio |
| `border` | sim | `#DCE3EE` | `#2C3B56` | borda de painel (decorativa) |
| `input_border` | novo | `#8391A6` | `#6B7C95` | borda de campo e caixa de marcação (>= 3:1) |
| `accent` | sim | `#006FC9` | `#38BDF8` | destaque, botão primário, título |
| `accent_hover` | sim | `#005AA3` | `#7DD3FC` | hover do primário |
| `accent_text` | sim | `#FFFFFF` | `#0F172A` | texto sobre `accent` |
| `accent_soft` | novo | `#E3F0FB` | `#17364F` | pílula de contagem ativa |
| `ring` | novo (= `accent`) | `#006FC9` | `#38BDF8` | anel de foco |
| `danger` | sim | `#B91C1C` | `#FB7185` | prazo vencido, ação destrutiva |
| `warning` | ajustado | `#A2500A` | `#FACC15` | prazo próximo |
| `success` | sim | `#047857` | `#34D399` | confirmação |
| `status_text` | novo | `#FFFFFF` | `#0F172A` | texto dentro do selo sólido |

## Cores de status (selo sólido)

Mesmas categorias de `STATUS_BADGE_COLORS` em `app/ui/styles.py`. No tema claro, três cores ficaram mais escuras para o texto branco do selo passar de 4.5:1 - **decisão do usuário, aprovada nos protótipos**:

| Categoria | Claro hoje | Claro refinado | Escuro |
|---|---|---|---|
| neutral | `#64748B` | igual | `#CBD5E1` |
| waiting | `#2563EB` | igual | `#60A5FA` |
| progress | `#EA580C` | `#C2410C` | `#FB923C` |
| attention / warning | `#CA8A04` | `#A16207` | `#FACC15` |
| done | `#16A34A` | `#15803D` | `#4ADE80` |
| final_done | `#0F766E` | igual | `#2DD4BF` |
| danger / blocked | `#DC2626` | igual | `#FB7185` |
| location_production | `#047857` | igual | `#34D399` |
| location_galvanization | `#7C3AED` | igual | `#A78BFA` |
| location_expedition | `#C2410C` | igual | `#FB923C` |
| location_grouped | `#0369A1` | igual | `#38BDF8` |

`location_grouped` não apareceu nos protótipos; confira o contraste ao migrar.

## Contraste

Mínimos: texto 4.5:1; borda de campo, ícone e anel de foco 3:1. `python scripts/check_contrast.py` confere os pares nas paletas oficiais (96 pares, 0 falhas em 07/10/2026) e `tests/test_visual_foundation.py` repete a conferência na suíte. Ao criar um token ou par novo, acrescente-o em `palette_pairs()`.

## Tipografia

Fonte: Inter 4.1 embutida em `app/assets/fonts/` (licença OFL), registrada por `load_app_fonts()` (`app/ui/fonts.py`) na inicialização, com Segoe UI como reserva. Em componente pintado à mão, parta de `QFont(self.font())` para herdar a família.

| Uso | Tamanho | Peso |
|---|---|---|
| Título de janela sobreposta | 18 | 800 |
| Título de página | 18 | 700 |
| Número de resumo | 20 | 700 |
| Título de painel | 14 | 700 |
| Texto, botão, célula | 13 | 400 / 600 |
| Rótulo de campo, legenda, selo | 12 | 400-700 |
| Contagem em pílula, grupo da barra lateral | 11 | 700 |

Números (quantidade, peso, data, código) usam algarismos tabulares.

## Medidas

| Item | Valor |
|---|---|
| Altura de botão/campo | 34 |
| Linha de tabela / cabeçalho de tabela | 40 / 34 |
| Item da barra lateral | 40 |
| Raio: campo e botão / painel / janela sobreposta / moldura de tabela | 10 / 14 / 16 / 12 |
| Selo em tabela | altura 22, raio 11 |
| Base de espaçamento | 4 |
