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


class ConversationList(BaseModel):
    items: list[ConversationOut]
    total: int


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    message_type: str = Field(default="MENSAGEM", pattern=r"^(MENSAGEM|PERGUNTA)$")
    mentioned_user_id: int | None = None


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    author_user_id: int | None = None
    author_name: str | None = None
    message_type: str
    body: str
    mentioned_user_id: int | None = None
    mentioned_user_name: str | None = None
    question_status: str | None = None
    answered_message_id: int | None = None
    created_at: datetime
    seen_by_count: int = 0


class MessageList(BaseModel):
    items: list[MessageOut]
    total: int


class TimelineEntry(BaseModel):
    id: int
    source: str
    entry_kind: str
    author_user_id: int | None = None
    author_name: str | None = None
    mentioned_user_id: int | None = None
    mentioned_user_name: str | None = None
    question_status: str | None = None
    body: str | None = None
    area: str | None = None
    event_type: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    created_at: datetime
    seen_by_count: int = 0


class TimelineList(BaseModel):
    conversation_id: int
    items: list[TimelineEntry]


class MarkReadRequest(BaseModel):
    last_read_message_id: int


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
    new_observations: int = 0


class NotificationOut(BaseModel):
    id: int
    notification_type: str
    conversation_id: int
    kind: str
    proposal_id: int | None = None
    proposal_number: str | None = None
    message_id: int | None = None
    message_body: str
    area: str | None = None
    author_name: str | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    total: int


class MentionableUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    sector: str | None = None


class MentionableUserList(BaseModel):
    items: list[MentionableUserOut]
