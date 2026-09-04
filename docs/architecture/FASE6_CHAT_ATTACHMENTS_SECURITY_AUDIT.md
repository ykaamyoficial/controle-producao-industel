# Fase 6 - Seguranca, auditoria e exclusao de anexos

## Objetivo

Endurecer os anexos do chat para uso operacional real, mantendo o servidor como autoridade para permissao, integridade e retencao.

## Implementado

- Exclusao logica de anexo por `DELETE /api/v1/chat/attachments/{id}`.
- Justificativa obrigatoria para remover anexo.
- Regra explicita de autorizacao:
  - usuario que enviou o anexo;
  - autor da mensagem;
  - superusuario ou usuario com `chat.admin`.
- Anexo removido preserva o registro historico:
  - `deleted_at`;
  - `deleted_by`;
  - `delete_reason`;
  - `purged_at`.
- Migration `20260820_0027_chat_attachment_security_controls.py`.
- Auditoria para:
  - upload;
  - download;
  - arquivo ausente;
  - hash divergente;
  - exclusao logica;
  - purge fisico.
- Evento realtime `attachment.deleted`, sem bytes no websocket.
- Desktop aplica merge por `attachment_id` e mostra `Anexo removido` sem abrir/baixar.
- Download valida SHA-256 antes de liberar o arquivo.
- Upload verifica:
  - limite de anexos por mensagem;
  - limite total por mensagem;
  - espaco livre minimo configuravel;
  - whitelist/extensao/MIME/magic bytes ja centralizados.
- Rotina administrativa `attachment_integrity_report` para diagnosticar:
  - `MISSING_FILE`;
  - `HASH_MISMATCH`;
  - `ORPHAN_FILE`;
  - `INVALID_PATH`.
- Rotina administrativa `purge_deleted_attachments` para remover fisicamente anexos apos retencao, com auditoria.

## Configuracoes

- `CHAT_MAX_ATTACHMENTS_PER_MESSAGE`, padrao `10`.
- `CHAT_MAX_TOTAL_ATTACHMENT_MB`, padrao `300`.
- `CHAT_STORAGE_MIN_FREE_MB`, padrao `0`.
- `CHAT_ATTACHMENT_DELETED_RETENTION_DAYS`, padrao `30`.

## Preservado

- Nenhum caminho interno de storage e retornado ao Desktop.
- O ID do anexo nunca e autorizacao por si so.
- O fluxo continua passando por `Attachment -> Message -> Conversation -> Permission`.
- Exclusao logica nao apaga texto da mensagem nem outros anexos.
- Purge fisico e separado da exclusao logica.
