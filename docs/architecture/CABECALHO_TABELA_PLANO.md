# Cabeçalho da tabela padrão — análise e plano (13/10/2026)

Escopo: **somente o cabeçalho** da tabela operacional (`ModernTable` + `BatchSelectionHeader`, usada em Controle Geral, Produção, Galvanização, Expedição, Parciais etc.). O modelo isolado `prototipos/cabecalho_tabela/preview.py` mostra "como é hoje" e "proposto" lado a lado com os mesmos dados.

> **Status (13/10/2026): implementado** em `app/ui/components/modern_header.py` (`ModernHeaderView`). `BatchSelectionHeader` agora é um alias dele (mesmo contrato do modo lote); `ModernTable` já nasce com o cabeçalho novo (altura 34 → 38, sombra ao rolar e canto direito sem degrau). Testes em `tests/test_modern_header.py`. Diferenças em relação ao modelo: a coluna 0 (ícone) nunca ordena e por isso não mostra barra de destaque; tabelas de diálogo (`QTableWidget`) seguem com o cabeçalho antigo.

```text
python prototipos/cabecalho_tabela/preview.py
python prototipos/cabecalho_tabela/preview.py --tema escuro
```

Botões da janela: *Modo de seleção* (mostra a caixa do cabeçalho), *Rolar tabela* (mostra a sombra) e *Tema*. Passe o mouse, clique nos títulos e arraste a borda entre colunas.

## 1. O que está ruim hoje

Origem: `QHeaderView::section` plano em `app/ui/styles.py` + `BatchSelectionHeader` (`app/ui/components/batch_selection.py`) + `TABLE_HEADER_HEIGHT = 34`.

| # | Falha | Onde se vê |
|---|---|---|
| 1 | A **seta de ordenação nativa** é minúscula e fica **em cima do primeiro título/da caixa de seleção** (a coluna 0 vem ordenada por padrão e nunca deveria ordenar). | Chevron solto acima da caixa, na captura do Henrique. |
| 2 | **Nenhuma resposta ao mouse**: não dá para saber quais colunas ordenam, nem onde arrastar para redimensionar. | Passar o mouse não muda nada. |
| 3 | **Colunas de ícone sem nome** (status, chat): faixa em branco no cabeçalho, sem dica. | Duas colunas vazias antes de "Proposta". |
| 4 | **Caixa de seleção nativa** desenhada por `drawControl`, diferente da caixa das linhas (tamanho, cor, borda). | Quadrado branco no cabeçalho × caixa azul nas linhas. |
| 5 | **Sem separação entre colunas** e a linha de baixo é fina; o cabeçalho "gruda" no corpo. | Títulos sem divisórias. |
| 6 | **Coluna ordenada não se destaca** (a seta nativa é a única pista, quando aparece). | Ordenar por Prazo não muda a aparência do título. |
| 7 | Rolagem não dá nenhuma profundidade entre cabeçalho e linhas. | Linhas passam "por baixo" sem sombra. |
| 8 | A seta nativa **desloca o título** quando aparece (reserva de espaço só quando ordenada). | Título "pula". |

## 2. O que o modelo propõe (mantém a identidade: azul-claro, negrito, centralizado)

1. **Seta própria**, só na coluna ordenada: ↑/↓ na cor de destaque ao lado do título; nas outras colunas ordenáveis aparece um "sobe/desce" fantasma **só no hover**. O espaço da seta é sempre reservado: o título não pula.
2. **Barra de destaque** de 2 px (cor de destaque) na base da coluna ordenada, crescendo do centro (240 ms, curva padrão do sistema); título em cor de destaque.
3. **Hover** (140 ms): fundo um tom mais forte, título tende ao destaque, cursor de mão — só em colunas ordenáveis e na caixa de seleção (modo lote).
4. **Separadores curtos** (16 px) entre colunas, que somem ao lado da coluna em hover; **pega de redimensionar** (traço de 2 px) aparece na borda da coluna sob o mouse.
5. **Colunas de ícone** mostram o próprio ícone (círculo de status, balão de chat) com dica "Situação rápida da proposta" / "Conversa da proposta".
6. **Caixa de seleção** igual à das linhas (16 px, raio 4, tokens), com os três estados (vazia, marcada, traço de "parcial"). Fora do modo lote, a coluna fica limpa e **não ordena**.
7. **Linha de baixo** mais firme (token `border`) e **sombra de 7 px** sob o cabeçalho quando a tabela está rolada.
8. Altura 38 px (hoje 34; linhas continuam com 40), título 13 px bold como hoje; tudo por token (claro e escuro), sem hexadecimal.

Regras de movimento: ação dispara antes da animação; só opacidade/cor/escala pintada; respeita "reduzir movimento" (duração zero), como `animate_value()`.

## 3. Como entra no sistema (quando o Henrique aprovar o modelo)

Mudança contida em três pontos, sem tocar em modelos nem na API:

1. **Novo componente** `app/ui/components/modern_header.py` (`ModernHeaderView`, herda `QHeaderView`; o `BatchSelectionHeader` passa a ser uma configuração dele, mantendo `set_batch_state`, `toggle_visible_requested` e `check_state` para os testes atuais).
2. **`ModernTable.__init__`** e `ProcessPage` passam a criar o cabeçalho novo; `TABLE_HEADER_HEIGHT` 34 → 38 (o esqueleto `SkeletonRows(top_offset=...)` usa a mesma constante).
3. **`styles.py`**: o bloco `QHeaderView::section` fica só como reserva (fundo/borda), já que a pintura passa a ser do componente.

Colunas ordenáveis e ícone/dica de cada coluna vêm de um metadado por coluna (`header_icon`, `header_tooltip`, `sortable`) no modelo Qt; o padrão é "ordenável quando tem título".

**Riscos:** (a) tabelas que não são `ModernTable` (QTableWidget de diálogos) seguem com o cabeçalho antigo até serem migradas; (b) testes que leem `batch_header` precisam do mesmo contrato (cobrir com os testes existentes de modo lote); (c) pintura própria precisa respeitar escala de tela (DPI) — conferir em 125%/150%.

**Fases sugeridas:** C0 aprovar o modelo (ajustes visuais); C1 componente + testes de pintura/estado; C2 trocar em `ModernTable`/`ProcessPage`; C3 conferir as demais páginas (Galvanização, Expedição, Parciais, Fiscal) e capturas claro/escuro; C4 documentar e remover o estilo antigo.

## 4. Fora do escopo

Linhas, selos, filtros e paginação; tabelas de diálogo (`QTableWidget`/`QTreeWidget`); o cabeçalho das telas ("Produção", filtros).
