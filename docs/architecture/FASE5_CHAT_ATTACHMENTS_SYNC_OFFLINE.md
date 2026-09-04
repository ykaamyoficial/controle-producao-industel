# Fase 5 - Sincronizacao, realtime e offline dos anexos

## Objetivo

Consolidar o comportamento de anexos do chat em uso simultaneo por varios computadores, mantendo o servidor como fonte oficial da verdade.

## Implementado

- Idempotencia de mensagem por `client_message_id`.
- Idempotencia de anexo por `client_attachment_id`.
- Migration `20260820_0026_chat_attachment_sync_idempotency.py` com colunas nullable e constraints compostas:
  - `chat_messages(conversation_id, client_message_id)`;
  - `chat_attachments(message_id, client_attachment_id)`.
- O Desktop gera `client_message_id` por envio e usa o `local_id` do anexo como `client_attachment_id`.
- O backend retorna o registro ja existente quando recebe novamente a mesma chave idempotente.
- Evento realtime `attachment.created` passou a ser conhecido pelo cliente.
- Payload realtime de anexo inclui metadados completos em `data.attachment`, nunca bytes.
- Painel do chat faz merge de anexos por `attachment_id`, sem duplicar.
- `message.created` inclui `client_message_id` no payload para reconciliacao.
- Cache de anexo centralizado em `AttachmentCacheManager`.
- Cache validado por `attachment_id + sha256`; cache corrompido e removido e baixado novamente.
- Cache continua em `AppData/Local/ControleProducaoIndustel/cache/chat/attachments`, fora da instalacao do executavel.

## Estrategia offline/reconexao

- O WebSocket existente ja usa backoff e reconecta automaticamente.
- Ao reconectar, a janela principal chama o `SessionSyncService`/poll oficial para reconciliar badges e conversas.
- A timeline aberta continua usando `refresh()` como fallback oficial ao receber evento de conversa.
- Arquivos completos nao sao baixados automaticamente apos login/reconexao; somente metadados entram na timeline.
- Se o arquivo estiver em cache e o SHA-256 conferir, ele pode ser aberto mesmo sem novo download.
- Se o cache estiver ausente e a rede falhar, o download falha sem afetar a mensagem nem apagar metadados oficiais.

## Limites mantidos

- Sem bytes/base64 no WebSocket.
- Sem download automatico de imagens, PDFs ou videos originais ao abrir conversa.
- Sem retry automatico infinito de upload. Retry continua explicito pelo usuario, agora protegido por idempotencia.
