# Fase 7 - Refinamento final da experiencia de anexos no chat

## Objetivo

Refinar a experiencia diaria de anexos sem reescrever a arquitetura criada nas fases anteriores.

## Entregue

- Drag-and-drop de arquivos na conversa e no compositor.
- Feedback visual temporario ao arrastar arquivos para o chat.
- Drop adiciona arquivos apenas como anexos pendentes, sem upload automatico.
- Rejeicao explicita de pastas arrastadas.
- Ctrl+V com imagem ou screenshot cria um PNG temporario amigavel (`captura_YYYY-MM-DD_HH-MM-SS_mmm.png`).
- Ctrl+V com texto continua colando texto normalmente no editor.
- Ctrl+V com arquivos locais adiciona os arquivos a fila pendente quando o Qt fornece URLs locais.
- Limpeza dos screenshots temporarios ao remover, limpar ou concluir envio.
- Foco retorna ao campo de mensagem apos anexar por dialogo, drop ou clipboard.
- Menu de anexos padronizado com acao principal visivel e acoes secundarias no menu.
- Opcao "Copiar imagem" para imagens ja disponiveis no cache local, sem expor caminho interno.
- Visualizador de imagem com salvar, copiar, atalhos de teclado, zoom ate 800%, ajuste a tela e duplo clique para alternar zoom.

## Fora desta etapa

- Player de video embutido: mantido em abrir/reproduzir pelo sistema operacional para evitar dependencia pesada nesta fase.
- Compressao/otimizacao de imagens: nao aplicada para preservar documentos tecnicos e evitar transformacao silenciosa.
- Preview avancado de PDF: mantido como abrir/salvar por nao haver suporte leve existente no projeto.
