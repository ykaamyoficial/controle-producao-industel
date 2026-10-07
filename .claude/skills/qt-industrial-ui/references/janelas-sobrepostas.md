# Telas que abrem por cima do programa

Modelo aprovado: `python prototipos/detalhes_proposta/detalhes.py`. Toda janela sobreposta do sistema deve parecer da mesma família que ela.

## Anatomia

```
tela de trás escurecida (véu)
┌──────────────────────────────────────────────────────────────┐  janela: fundo bg, borda 1 px, raio 16
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ Título 18 px negrito                  [Sec.] [Primária] X│ │  cabeçalho-cartão (painel branco, raio 14)
│ │ subtítulo                                         Fechar │ │
│ │ [SELO SÓLIDO]  Prazo: dd/mm/aaaa  ⚠ em 5 d               │ │
│ └──────────────────────────────────────────────────────────┘ │
│  Aba ativa   Aba (12)   Aba   Aba (2)                        │  abas com contagem (opcional)
│ ─────────────────────────────────────────────────────────── │
│ ┌───────────────────────────┐ ┌───────────────────────────┐ │
│ │ Painel                    │ │ Painel                    │ │  corpo: painéis de raio 14, espaçamento 12
│ └───────────────────────────┘ └───────────────────────────┘ │
│                          [Cancelar] [Voltar] [Confirmar]     │  rodapé (só formulário/assistente)
└──────────────────────────────────────────────────────────────┘
```

Margem interna da janela: 16 nas laterais, 14 em cima e embaixo; espaçamento entre blocos 10-12.

## Partes

**Véu.** Cobre a janela principal inteira. Cor `rgb(8, 15, 30)` com 41% de opacidade no tema claro e 59% no escuro. Aparece em 200 ms. É ele que separa a janela do fundo (o recorte arredondado atual não permite sombra nativa); uma sombra suave pode ser pintada pelo próprio véu em volta do retângulo da janela.

**Janela.** Fundo `bg`, borda de 1 px `border`, raio 16, sem barra de título do Windows. Entra com fade de 220 ms.

**Cabeçalho-cartão.** Painel branco com:

- título (18 px, peso 800) - o que é e de quem: "CP 05672 | Cliente";
- subtítulo em `muted` (obra/site, ou a instrução do passo num assistente);
- linha de situação quando fizer sentido: selo sólido da etapa + prazo com aviso;
- ações à direita, nesta ordem: secundárias, **uma** primária, e "Fechar" (fantasma, ícone X) **sempre por último**.

**Abas.** Use quando o conteúdo tem partes independentes. Contagem ao lado do nome quando a aba é uma lista (Itens 12, Cargas 2). Aba ativa em negrito sobre fundo branco, com traço na cor de destaque que desliza. Setas esquerda/direita trocam de aba.

**Corpo.** Painéis brancos (borda 1 px, raio 14, margem interna 16/14). Título do painel 14 px peso 700. Um painel de destaque por janela pode usar fundo azul-claro com borda azulada (ex.: "Fluxo da proposta").

- Campo e valor lado a lado (chave em `muted` 12 px à esquerda, valor peso 600) para dados cadastrais.
- Blocos (chave em cima, valor embaixo, 3-4 colunas) para grupos de números.
- Resumo de uma lista: números grandes (20 px) com legenda, acima da tabela.
- Tabela dentro de moldura arredondada (raio 12), mesmo padrão de zebra e selos da tabela principal.
- Aviso/observação fixa: caixa azul-clara com ícone de informação, nunca texto solto em cinza.

**Rodapé de ações.** Só em formulário e assistente. Alinhado à direita: Cancelar (fantasma), Voltar (secundário, só em assistente), e a confirmação (primário, com o verbo da ação: "Salvar", "Registrar produção", "Emitir"). Em assistente, à esquerda fica o indicador de passo ("Passo 2 de 4").

## Tamanhos

| Tipo | Quando | Tamanho |
|---|---|---|
| Grande | Detalhes, centrais de ação, conferências, assistentes com tabela | 94% x 90% da janela principal (mínimo 1100 x 650) - o `apply_large_dialog_geometry` atual |
| Média | Formulários de cadastro/edição | 720 a 960 de largura, altura pelo conteúdo |
| Pequena | Confirmação, entrada de um dado só | 420 a 520 de largura |

## Fechar

- **Esc** fecha sempre (comportamento do `QDialog`).
- **Clique fora** (no véu) fecha **somente** janela de consulta (detalhes). Em formulário, assistente ou qualquer tela com dado digitado, clique fora não faz nada.
- Fechar com alteração não salva pede confirmação.
- Ação irreversível (cancelar proposta, excluir) pede confirmação com botão destrutivo e o texto dizendo o que será perdido.

## Carregamento e erro

- Ao abrir, o cabeçalho já mostra o que se sabe e o corpo mostra o esqueleto até os dados chegarem; então o corpo entra com fade.
- Ações do cabeçalho ficam desabilitadas enquanto carrega.
- Erro de carga: mensagem dentro da janela com "Tentar de novo", em vez de fechar a janela em silêncio.

## Como isso entra no código real

O protótipo desenha a janela como um widget filho. **No sistema continua sendo `QDialog`** (o fluxo `exec()` e os testes dependem disso):

- `style_dialog_from_parent()` (`app/ui/dialog_utils.py`) já é o ponto único por onde passam os diálogos, e `apply_frameless_rounded_dialog()` (`app/ui/components/frameless_dialog.py`) já tira a moldura e arredonda os cantos. O padrão novo entra **nesses dois pontos**, para valer em todos os diálogos de uma vez.
- O véu é um widget filho da janela principal, mostrado quando o diálogo aparece e escondido quando ele fecha (`showEvent`/`finished`), ligado no mesmo ponto central.
- Não use `WA_TranslucentBackground` no diálogo: o comentário em `frameless_dialog.py` registra que isso quebra o repaint de tabelas e áreas de rolagem.
- O cabeçalho-cartão, as abas com contagem e o rodapé de ações viram componentes reutilizáveis em `app/ui/components/`, para nenhum diálogo montá-los à mão.
- `QMessageBox` continua sendo `QMessageBox` (os testes fazem patch nele); só recebe estilo.
