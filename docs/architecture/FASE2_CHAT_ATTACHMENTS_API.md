# Fase 2 - API de anexos do chat

## Escopo entregue

A API passa a oferecer a infraestrutura tecnica para anexos do chat:

- `POST /api/v1/chat/messages/{message_id}/attachments`
- `GET /api/v1/chat/attachments/{attachment_id}`
- `GET /api/v1/chat/attachments/{attachment_id}/content`

O storage continua privado. Nenhum endpoint publica `storage_path` ou caminho absoluto; clientes devem trabalhar por `attachment_id`.

## Fluxo de upload

1. Autentica usuario com `chat.send`.
2. Carrega a mensagem e sua conversa.
3. Aplica a mesma regra de visibilidade da conversa usada no chat.
4. Bloqueia conversa finalizada.
5. Sanitiza o nome original apenas para metadado/exibicao.
6. Valida extensao efetiva, extensoes executaveis, tamanho maximo e coerencia MIME/conteudo.
7. Lê o upload em chunks, calculando SHA-256 durante a escrita.
8. Escreve primeiro em `storage/chat/.tmp/*.tmp`.
9. Move atomicamente para `storage/chat/YYYY/MM/DD/{uuid}.{ext}`.
10. Persiste metadados em `chat_attachments`.
11. Se o commit falhar, remove o arquivo fisico criado.

## Download

O download revalida:

```text
attachment -> message -> conversation -> permissao
```

Arquivos com `deleted_at` recebem resposta de indisponibilidade. Arquivo fisico ausente gera erro controlado com log tecnico.

Headers:

- `Cache-Control: private`
- `ETag` baseado no SHA-256
- `Content-Disposition` sanitizado

## Backup

A partir desta fase, backup completo do sistema deve considerar:

- PostgreSQL
- `CHAT_STORAGE_ROOT` (por padrao `data/storage`)

O banco guarda apenas metadados e caminhos relativos.

## Preparacao futura

A implementacao concentra acesso a filesystem em `ChatAttachmentStorage`, mantendo os endpoints livres de `open("C:\\...")` espalhado. Isso permite trocar storage local por NAS/MinIO/S3 em fase futura.
