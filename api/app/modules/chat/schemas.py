from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationOut(BaseModel):
    id: int
    kind: str
    proposal_id: int | None = None
    proposal_number: str | None = None
    customer_name: str | None = None
    proposal_area: str | None = None
    proposal_status: str | None = None
    status: str
    last_activity_at: datetime
    created_at: datetime
    unread_count: int = 0
    message_count: int = 0
    last_message_preview: str | None = None
    last_message_author: str | None = None
    last_message_author_user_id: int | None = None


class ConversationList(BaseModel):
    items: list[ConversationOut]
    total: int


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=64)
    message_type: str = Field(default="MENSAGEM", pattern=r"^(MENSAGEM|PERGUNTA|NOTA_INTERNA)$")
    mentioned_user_id: int | None = None
    reply_to_message_id: int | None = None
    area: str | None = Field(default=None, max_length=40)
    due_at: datetime | None = None
    is_important: bool = False


class ChatAttachmentMetadata(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    stored_filename: str = Field(min_length=1, max_length=120)
    mime_type: str = Field(min_length=1, max_length=120)
    file_extension: str = Field(min_length=1, max_length=20)
    file_size: int = Field(ge=0)
    storage_path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(min_length=64, max_length=64)
    thumbnail_path: str | None = Field(default=None, max_length=500)


class ChatAttachmentRead(ChatAttachmentMetadata):
    id: int
    message_id: int
    uploaded_by: int | None = None
    created_at: datetime
    deleted_at: datetime | None = None
    deleted_by: int | None = None


class ChatAttachmentOut(BaseModel):
    id: int
    message_id: int
    client_attachment_id: str | None = None
    original_filename: str
    mime_type: str
    category: str
    file_size: int
    sha256: str
    uploaded_by: int | None = None
    created_at: datetime
    thumbnail_available: bool = False
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    delete_reason: str | None = None
    purged_at: datetime | None = None


class AttachmentDeleteRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    client_message_id: str | None = None
    author_user_id: int | None = None
    author_name: str | None = None
    author_avatar_available: bool = False
    message_type: str
    body: str
    mentioned_user_id: int | None = None
    mentioned_user_name: str | None = None
    question_status: str | None = None
    answered_message_id: int | None = None
    area: str | None = None
    due_at: datetime | None = None
    viewed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    is_important: bool = False
    created_at: datetime
    seen_by_count: int = 0
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)


class MessageList(BaseModel):
    items: list[MessageOut]
    total: int
    has_more: bool = False


class TimelineEntry(BaseModel):
    id: int
    source: str
    entry_kind: str
    client_message_id: str | None = None
    author_user_id: int | None = None
    author_name: str | None = None
    author_avatar_available: bool = False
    mentioned_user_id: int | None = None
    mentioned_user_name: str | None = None
    question_status: str | None = None
    answered_message_id: int | None = None
    body: str | None = None
    area: str | None = None
    due_at: datetime | None = None
    viewed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    is_important: bool = False
    created_at: datetime
    seen_by_count: int = 0
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)


class TimelineList(BaseModel):
    conversation_id: int
    items: list[TimelineEntry]
    has_more: bool = False


class SharedContentItem(BaseModel):
    """Fase 7 - item da area "Midia e arquivos": nunca duplica o anexo/mensagem,
    apenas referencia message_id/attachment_id para reutilizar a infraestrutura
    de download e o "ir para mensagem" ja existentes."""

    kind: str
    message_id: int
    attachment_id: int | None = None
    name: str
    mime_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    created_at: datetime
    sender_name: str | None = None
    snippet: str | None = None


class SharedContentList(BaseModel):
    items: list[SharedContentItem]
    has_more: bool = False


class MarkReadRequest(BaseModel):
    last_read_message_id: int


class ConversationReadState(BaseModel):
    """ETAPA 9: estado FINAL realmente persistido do cursor de leitura —
    a resposta do mark-read devolve isso em vez de um 204 mudo, pra nunca
    "mentir" quando o request recebido era mais antigo que o cursor ja
    salvo (o cliente que mandou um valor atrasado fica sabendo na hora
    qual e o valor oficial, sem precisar de uma segunda chamada)."""

    conversation_id: int
    last_read_message_id: int | None
    last_read_at: datetime


class CancelQuestionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReassignQuestionRequest(BaseModel):
    assignee_user_id: int
    reason: str = Field(min_length=3, max_length=500)


class ConversationUnread(BaseModel):
    conversation_id: int
    kind: str
    proposal_id: int | None = None
    proposal_number: str | None = None
    unread_count: int


class UnreadSummary(BaseModel):
    total_unread: int
    conversations: list[ConversationUnread]
    pending_questions: int = 0
    notification_unread_count: int = 0
    unread_mentions: int = 0
    server_time: str | None = None


class NotificationOut(BaseModel):
    id: int
    notification_type: str
    priority: str = "normal"
    conversation_id: int
    kind: str
    proposal_id: int | None = None
    proposal_number: str | None = None
    customer_name: str | None = None
    message_id: int | None = None
    message_body: str
    question_status: str | None = None
    area: str | None = None
    author_name: str | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    total: int
    has_more: bool = False


class MentionableUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    sector: str | None = None
    is_online: bool = False
    avatar_available: bool = False


class MentionableUserList(BaseModel):
    items: list[MentionableUserOut]
