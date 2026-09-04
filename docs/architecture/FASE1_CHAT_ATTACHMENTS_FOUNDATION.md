# Fase 1 - Anexos do Chat: Banco e Storage

## Banco

A migration `20260820_0025_chat_attachments_foundation.py` cria a tabela
`chat_attachments`, relacionada a `chat_messages.id` por `message_id`.
Uma mensagem pode ter zero, um ou varios anexos. Mensagens antigas continuam
sem registros nessa tabela.

A tabela guarda somente metadados: nome original, nome interno, MIME type,
extensao, tamanho, caminho relativo de storage, SHA-256, futura miniatura,
usuario de upload, timestamps e campos de exclusao logica. Nenhuma coluna usa
`BYTEA`, `BLOB` ou Large Object.

## Storage

Arquivos fisicos ficarao fora do PostgreSQL. A classe
`ChatAttachmentStorage` centraliza a geracao de nomes internos, paths relativos
e resolucao contra a raiz configurada. A organizacao preparada e:

```text
chat/YYYY/MM/DD/stored_filename
```

Diretorios serao criados sob demanda nas fases de upload/download.

## Configuracao

Novas variaveis da API:

```text
CHAT_STORAGE_ROOT=data/storage
CHAT_MAX_IMAGE_MB=20
CHAT_MAX_DOCUMENT_MB=50
CHAT_MAX_VIDEO_MB=200
```

Os limites ficam centralizados para as proximas fases, ainda sem bloquear
upload nesta fase.

## Seguranca

O nome original e tratado apenas como metadado. O nome fisico e sempre gerado
pela API com UUID e extensao normalizada. Caminhos salvos no banco devem ser
relativos e validados para impedir caminhos absolutos e path traversal.

## Evolucao

A Fase 2 podera usar esta infraestrutura para endpoints FastAPI de
upload/download, controle de acesso, streaming e validacoes de conteudo sem
acoplar o desktop ao filesystem.
