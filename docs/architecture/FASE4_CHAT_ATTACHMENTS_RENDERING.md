# Fase 4 - Exibicao de anexos no chat

## Objetivo

Renderizar anexos dentro das mensagens do chat sem alterar a arquitetura de mensagens, conversa, websocket ou composicao.

## Implementado

- Cards de anexo dentro das bolhas/cards de mensagens.
- Classificacao centralizada por categoria (`image`, `video`, `document`, `spreadsheet`, `archive`, `cad`, `other`).
- Cards especificos por tipo visual: imagem/video com area de preview, documentos/planilhas/CAD/compactados como cards de arquivo.
- Acoes por anexo:
  - abrir;
  - baixar/salvar como;
  - copiar nome pelo menu.
- Visualizador interno simples para imagens com:
  - ajustar a janela;
  - tamanho real;
  - zoom;
  - anterior/proxima para imagens da mesma mensagem ja disponiveis em cache.
- Download assincrono em `QThread`, sem travar a interface.
- Escrita atomica com `.part` antes de renomear para o destino final.
- Cache local controlado em `ControleProducaoIndustel/cache/chat/attachments`, com chave baseada em `attachment_id + sha256 + nome`.
- Limite de cache configuravel por `CHAT_ATTACHMENT_CACHE_MB`.
- Atualizacao otimista da mensagem apos sucesso do upload, para o anexo aparecer antes do refresh completo.

## Observacoes

- O backend atual ainda nao expoe endpoint de thumbnail nem streaming/range para videos. Por isso a UI nao baixa imagem/video automaticamente ao renderizar a conversa.
- O arquivo original so e baixado quando o usuario clica em visualizar, abrir ou baixar.
- Caminhos internos de storage do servidor nao sao exibidos na interface.
