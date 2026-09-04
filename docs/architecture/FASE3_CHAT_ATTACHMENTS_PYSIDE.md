# Fase 3 - Interface PySide para anexos do chat

## Escopo entregue

A barra de composicao do chat agora permite:

- selecionar multiplos arquivos pelo botao de anexo;
- visualizar anexos pendentes antes do envio;
- remover anexos individualmente;
- enviar texto + anexos;
- enviar somente anexo;
- acompanhar progresso individual;
- cancelar um upload em andamento;
- manter anexos com falha visiveis para nova tentativa.

## Componentes

- `PendingChatAttachment`: modelo local com `local_id`, caminho, tamanho, categoria, progresso e estado.
- `AttachmentsQueueWidget`: fila compacta de anexos pendentes.
- `PendingAttachmentWidget`: linha individual com nome, tamanho, estado, progresso e acoes.
- `ChatAttachmentUploadWorker`: worker em `QThread`, sem manipular widgets diretamente.

## Fluxo

```text
Selecionar arquivos
      ↓
fila local
      ↓
Enviar
      ↓
cria mensagem
      ↓
worker envia anexos para /chat/messages/{message_id}/attachments
      ↓
UI atualiza progresso/erro/sucesso por local_id
```

O upload e sequencial nesta fase para reduzir consumo de rede/RAM e evitar sobrecarga da API local. O worker captura o `message_id` no inicio, entao trocar de conversa durante o envio nao altera o destino.

## Memoria

O cliente HTTP usa um wrapper de arquivo com `read()` e callback de progresso. O caminho selecionado e transmitido como stream pelo `httpx`; a UI nao carrega videos/documentos grandes em bytes antes de enviar.

## Limitacoes deliberadas

A fase nao implementa visualizacao profissional dos anexos ja enviados dentro das bolhas. As mensagens ja recebem metadados (`attachments`) desde a Fase 2, mas a renderizacao historica completa fica para a Fase 4.
