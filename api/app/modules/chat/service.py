from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError, PermissionDeniedError
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.dependencies import user_has_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import CHAT_ADMIN, CHAT_SEND, CHAT_VIEW, CHAT_VIEW_FINALIZED
from api.app.modules.auth.service import effective_permissions
from api.app.modules.auth.tokens import utcnow
from api.app.modules.chat.attachment_storage import (
    ALLOWED_EXTENSIONS_BY_CATEGORY,
    AttachmentValidationError,
    ChatAttachmentCategory,
    ChatAttachmentStorage,
    classify_extension,
    content_disposition_attachment,
    sanitize_original_filename,
    write_upload_to_temp,
)
from api.app.modules.chat.models import ChatAttachment, ChatConversation, ChatMessage, ChatMessageRead, ChatNotification
from api.app.modules.chat.ws_manager import manager as ws_manager
from api.app.modules.chat.schemas import (
    ChatAttachmentOut,
    ConversationOut,
    ConversationList,
    ConversationReadState,
    ConversationUnread,
    MentionableUserList,
    MentionableUserOut,
    MessageCreate,
    MessageList,
    MessageOut,
    NotificationList,
    NotificationOut,
    SharedContentItem,
    SharedContentList,
    TimelineEntry,
    TimelineList,
    UnreadSummary,
)
from api.app.modules.proposals import service as proposals_service
from api.app.modules.proposals.models import Proposal


logger = logging.getLogger(__name__)
attachment_logger = logging.getLogger("api.chat.attachments")


GENERAL_CHAT_KIND = "GERAL"
PROPOSAL_CHAT_KIND = "PROPOSTA"

NOTIFICATION_PRIORITIES = {
    "MENSAGEM": "normal",
    "MENCAO": "atencao",
    "RESPOSTA": "atencao",
    "NOTA_DIRECIONADA": "atencao",
    "NOTA_IMPORTANTE": "atencao",
    "PERGUNTA_ATRIBUIDA": "acao_obrigatoria",
    "PERGUNTA_RESPONDIDA": "atencao",
    "PERGUNTA_ATRASADA": "atrasada",
}


@dataclass(frozen=True)
class AttachmentContent:
    path: Path
    filename: str
    mime_type: str
    headers: dict[str, str]


@dataclass(frozen=True)
class AttachmentIntegrityIssue:
    status: str
    attachment_id: int | None = None
    storage_path: str | None = None
    detail: str | None = None


async def get_or_create_general_chat(session: AsyncSession) -> ChatConversation:
    conversation = (
        await session.execute(select(ChatConversation).where(ChatConversation.kind == GENERAL_CHAT_KIND))
    ).scalars().first()
    if conversation is None:
        conversation = ChatConversation(kind=GENERAL_CHAT_KIND, proposal_id=None, status="ATIVA")
        session.add(conversation)
        await session.flush()
    return conversation


async def get_or_create_proposal_chat(session: AsyncSession, proposal_id: int) -> ChatConversation:
    await proposals_service.get_proposal(session, proposal_id)
    conversation = (
        await session.execute(select(ChatConversation).where(ChatConversation.proposal_id == proposal_id))
    ).scalars().first()
    if conversation is None:
        conversation = ChatConversation(kind=PROPOSAL_CHAT_KIND, proposal_id=proposal_id, status="ATIVA")
        session.add(conversation)
        await session.flush()
    return conversation


async def get_conversation(session: AsyncSession, conversation_id: int) -> ChatConversation:
    conversation = await session.get(ChatConversation, conversation_id)
    if conversation is None:
        raise ApiError(error_codes.CHAT_CONVERSATION_NOT_FOUND, "Conversa nao encontrada.", status_code=404)
    return conversation


def actor_can_view_finalized(actor: User) -> bool:
    return actor.is_superuser or CHAT_VIEW_FINALIZED in effective_permissions(actor)


def _conversation_visible_in_listings(actor: User, conversation: ChatConversation) -> bool:
    """Conversas FINALIZADA para quem nao tem CHAT_VIEW_FINALIZED nao podem
    nem aparecer nas listagens/soma de nao lidas — quem nao pode ver o
    conteudo tambem nao pode ficar com um contador que nunca consegue
    zerar (mark_read exige a mesma permissao, via _ensure_can_view_conversation)."""
    return conversation.status != "FINALIZADA" or actor_can_view_finalized(actor)


def _ensure_can_view_conversation(actor: User, conversation: ChatConversation) -> None:
    """Mesma politica aplicada ao filtro de listagem (status=FINALIZADA), mas
    verificada contra o status real da conversa — evita que quem nao pode ver
    conversas finalizadas leia o conteudo acessando o ID diretamente."""
    if conversation.status != "FINALIZADA":
        return
    if not actor_can_view_finalized(actor):
        raise PermissionDeniedError("Seu usuario nao pode visualizar conversas finalizadas.")


async def _users_by_id(session: AsyncSession, ids: set[int | None]) -> dict[int, User]:
    wanted = {user_id for user_id in ids if user_id}
    if not wanted:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(wanted)))).scalars().all()
    return {user.id: user for user in rows}


def _effective_question_status(raw_status: str | None, due_at: datetime | None, *, now: datetime | None = None) -> str | None:
    """AGUARDANDO_RESPOSTA some com o tempo e vira ATRASADA quando o prazo
    vence — mas isso nunca e gravado no banco (evita depender de um
    scheduler): e calculado aqui, de forma pura e deterministica, toda vez
    que a mensagem e exibida. RESPONDIDA/CANCELADA nunca viram ATRASADA,
    mesmo com prazo vencido — a transicao so existe a partir de
    AGUARDANDO_RESPOSTA (ver PDF 4.2)."""
    if raw_status != "AGUARDANDO_RESPOSTA" or due_at is None:
        return raw_status
    reference = now or datetime.now(due_at.tzinfo)
    return "ATRASADA" if due_at < reference else raw_status


def _attachment_out(attachment: ChatAttachment) -> ChatAttachmentOut:
    return ChatAttachmentOut(
        id=attachment.id,
        message_id=attachment.message_id,
        client_attachment_id=attachment.client_attachment_id,
        original_filename=attachment.original_filename,
        mime_type=attachment.mime_type,
        category=classify_extension(attachment.file_extension).value,
        file_size=attachment.file_size,
        sha256=attachment.sha256,
        uploaded_by=attachment.uploaded_by,
        created_at=attachment.created_at,
        thumbnail_available=bool(attachment.thumbnail_path),
        deleted_at=attachment.deleted_at,
        deleted_by=attachment.deleted_by,
        delete_reason=attachment.delete_reason,
        purged_at=attachment.purged_at,
    )


def _message_attachments(message: ChatMessage) -> list[ChatAttachmentOut]:
    return [_attachment_out(attachment) for attachment in getattr(message, "attachments", [])]


def _message_out(message: ChatMessage, users_by_id: dict[int, User], seen_by_count: int = 0) -> MessageOut:
    author = users_by_id.get(message.author_user_id) if message.author_user_id else None
    mentioned = users_by_id.get(message.mentioned_user_id) if message.mentioned_user_id else None
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        client_message_id=message.client_message_id,
        author_user_id=message.author_user_id,
        author_name=author.display_name if author else None,
        author_avatar_available=bool(author and author.avatar_bytes),
        message_type=message.message_type,
        body=message.body,
        mentioned_user_id=message.mentioned_user_id,
        mentioned_user_name=mentioned.display_name if mentioned else None,
        question_status=_effective_question_status(message.question_status, message.due_at),
        answered_message_id=message.answered_message_id,
        area=message.area,
        due_at=message.due_at,
        viewed_at=message.viewed_at,
        cancelled_at=message.cancelled_at,
        cancellation_reason=message.cancellation_reason,
        is_important=message.is_important,
        created_at=message.created_at,
        seen_by_count=seen_by_count,
        attachments=_message_attachments(message),
    )


async def _seen_counts(session: AsyncSession, messages: list[ChatMessage]) -> dict[int, int]:
    """Para cada mensagem, quantos outros usuarios (nao o proprio autor) ja
    leram ate ela ou alem — calculado em uma unica consulta agregada em vez
    de um laco Python O(mensagens x leituras)."""
    if not messages:
        return {}
    message_ids = [message.id for message in messages]
    stmt = (
        select(ChatMessage.id, func.count(ChatMessageRead.id))
        .select_from(ChatMessage)
        .join(
            ChatMessageRead,
            and_(
                ChatMessageRead.conversation_id == ChatMessage.conversation_id,
                func.coalesce(ChatMessageRead.last_read_message_id, 0) >= ChatMessage.id,
                ChatMessageRead.user_id.is_distinct_from(ChatMessage.author_user_id),
            ),
        )
        .where(ChatMessage.id.in_(message_ids))
        .group_by(ChatMessage.id)
    )
    rows = (await session.execute(stmt)).all()
    # sempre uma entrada por mensagem (mesmo com 0 leituras), igual o
    # contrato original garantia.
    result = {message_id: 0 for message_id in message_ids}
    result.update({int(message_id): int(count) for message_id, count in rows})
    return result


async def _create_message(
    session: AsyncSession,
    conversation: ChatConversation,
    actor: User,
    *,
    body: str,
    message_type: str,
    mentioned_user_id: int | None = None,
    answered_message_id: int | None = None,
    area: str | None = None,
    due_at: datetime | None = None,
    is_important: bool = False,
    client_message_id: str | None = None,
) -> tuple[ChatMessage, set[int]]:
    message = ChatMessage(
        conversation_id=conversation.id,
        author_user_id=actor.id,
        message_type=message_type,
        body=body,
        client_message_id=client_message_id,
        mentioned_user_id=mentioned_user_id,
        question_status="AGUARDANDO_RESPOSTA" if message_type == "PERGUNTA" else None,
        answered_message_id=answered_message_id,
        area=area,
        due_at=due_at if message_type == "PERGUNTA" else None,
        is_important=is_important if message_type == "NOTA_INTERNA" else False,
    )
    session.add(message)
    conversation.last_activity_at = func.now()
    await session.flush()
    recipient_ids = await _create_notifications(session, conversation, message, actor)
    return message, recipient_ids


async def _insert_notification(session: AsyncSession, *, user_id: int, conversation_id: int, message_id: int, notification_type: str) -> None:
    """Insercao idempotente: a constraint unica (user_id, message_id,
    notification_type) garante que a mesma notificacao nunca e duplicada,
    mesmo sob reconexao/poll concorrente ou nova chamada da varredura de
    atraso (ver _ensure_overdue_notifications)."""
    stmt = (
        pg_insert(ChatNotification)
        .values(user_id=user_id, conversation_id=conversation_id, message_id=message_id, notification_type=notification_type)
        .on_conflict_do_nothing(index_elements=["user_id", "message_id", "notification_type"])
    )
    await session.execute(stmt)
    await _mirror_notification_to_generic(
        session, user_id=user_id, conversation_id=conversation_id, message_id=message_id, notification_type=notification_type
    )


# Ponte para a camada generica de notificacoes (api/app/modules/notifications).
# Nesta fase o chat continua escrevendo em `chat_notifications` normalmente e
# apenas ESPELHA cada aviso para `notifications`, para o novo agente de bandeja
# e a futura Central unificada terem uma unica fonte. Mapeamento
# notification_type -> (category, severity):
_GENERIC_NOTIFICATION_MAP: dict[str, tuple[str, str]] = {
    "MENSAGEM": ("CHAT_MENSAGEM", "info"),
    "MENCAO": ("CHAT_MENCAO", "normal"),
    "RESPOSTA": ("CHAT_RESPOSTA", "normal"),
    "PERGUNTA_ATRIBUIDA": ("CHAT_PERGUNTA", "alta"),
    "PERGUNTA_ATRASADA": ("CHAT_PERGUNTA_ATRASADA", "critica"),
    "PERGUNTA_RESPONDIDA": ("CHAT_RESPOSTA", "normal"),
    "NOTA_DIRECIONADA": ("CHAT_NOTA", "normal"),
    "NOTA_IMPORTANTE": ("CHAT_NOTA", "alta"),
}

_GENERIC_NOTIFICATION_VERB = {
    "MENSAGEM": "enviou uma mensagem",
    "MENCAO": "mencionou voce",
    "RESPOSTA": "respondeu sua mensagem",
    "PERGUNTA_ATRIBUIDA": "atribuiu uma pergunta a voce",
    "PERGUNTA_ATRASADA": "tem uma pergunta atribuida a voce em atraso",
    "PERGUNTA_RESPONDIDA": "respondeu sua pergunta",
    "NOTA_DIRECIONADA": "registrou uma nota interna para voce",
    "NOTA_IMPORTANTE": "registrou uma nota interna importante",
}


async def _mirror_notification_to_generic(
    session: AsyncSession, *, user_id: int, conversation_id: int, message_id: int, notification_type: str
) -> None:
    mapping = _GENERIC_NOTIFICATION_MAP.get(notification_type)
    if mapping is None:
        return
    from api.app.modules.notifications import service as notifications_service

    category, severity = mapping
    row = (
        await session.execute(
            select(ChatMessage.body, ChatMessage.author_user_id, ChatConversation.proposal_id)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .where(ChatMessage.id == message_id)
        )
    ).first()
    if row is None:
        return
    body, author_user_id, proposal_id = row
    author = await session.get(User, author_user_id) if author_user_id else None
    who = author.display_name if author else "Alguem"
    if proposal_id:
        deep_link = f"proposal/{proposal_id}?message={message_id}"
    else:
        deep_link = f"chat/{conversation_id}?message={message_id}"
    snippet = (body or "").strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:157] + "..."
    try:
        await notifications_service.emit(
            session,
            user_ids=[user_id],
            category=category,
            severity=severity,
            title=f"{who} {_GENERIC_NOTIFICATION_VERB.get(notification_type, 'gerou uma notificacao')}",
            body=snippet,
            deep_link=deep_link,
            actor_user_id=author_user_id,
            dedup_key=f"chat:{message_id}:{notification_type}",
        )
    except Exception:  # pragma: no cover - espelho best-effort, nunca derruba o chat
        logger.warning("chat_notification_mirror_falhou | message_id=%s tipo=%s", message_id, notification_type, exc_info=True)


async def _prior_participants(session: AsyncSession, conversation_id: int, *, exclude_user_id: int, exclude_message_id: int) -> set[int]:
    """Quem ja mandou alguma mensagem nesta conversa antes (mesmo conceito de
    "participantes" que o desktop usa em ChatConversationPanel.participants()),
    com conta ainda ativa — nao ha tabela de membros, entao "participante" e
    definido pelo historico real da conversa."""
    rows = (
        await session.execute(
            select(ChatMessage.author_user_id)
            .join(User, User.id == ChatMessage.author_user_id)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.author_user_id.is_not(None),
                ChatMessage.author_user_id != exclude_user_id,
                ChatMessage.id != exclude_message_id,
                User.active.is_(True),
            )
            .distinct()
        )
    ).scalars().all()
    return set(rows)


async def _create_notifications(session: AsyncSession, conversation: ChatConversation, message: ChatMessage, actor: User) -> set[int]:
    """Gera notificacao (o "sino") para: mencao, resposta, pergunta
    atribuida/respondida, nota interna direcionada — e, desde a ETAPA 3,
    tambem para toda mensagem comum, notificando quem ja participou da
    conversa antes (exceto quem ja recebe um tipo mais especifico acima
    para esta mesma mensagem, via setdefault — nunca duas notificacoes
    pelo mesmo evento). Nota importante SEM destinatario continua sem
    notificar ninguem individualmente: o projeto nao tem um mapeamento
    usuario->area para rotear isso com seguranca, e notificar todo mundo
    indiscriminadamente e proibido pelo escopo (PDF secao 8)."""
    if conversation.kind == GENERAL_CHAT_KIND:
        return set()

    notifications: dict[int, str] = {}
    if message.mentioned_user_id and message.mentioned_user_id != actor.id:
        if message.message_type == "PERGUNTA":
            notifications[message.mentioned_user_id] = "PERGUNTA_ATRIBUIDA"
        elif message.message_type == "NOTA_INTERNA":
            notifications[message.mentioned_user_id] = "NOTA_DIRECIONADA"
        else:
            notifications[message.mentioned_user_id] = "MENCAO"

    if message.answered_message_id:
        original = await session.get(ChatMessage, message.answered_message_id)
        if original and original.author_user_id and original.author_user_id != actor.id:
            notification_type = "PERGUNTA_RESPONDIDA" if original.message_type == "PERGUNTA" else "RESPOSTA"
            notifications.setdefault(original.author_user_id, notification_type)

    participant_ids = await _prior_participants(session, conversation.id, exclude_user_id=actor.id, exclude_message_id=message.id)
    for user_id in participant_ids:
        notifications.setdefault(user_id, "MENSAGEM")

    for user_id, notification_type in notifications.items():
        await _insert_notification(session, user_id=user_id, conversation_id=conversation.id, message_id=message.id, notification_type=notification_type)
    return set(notifications.keys())


async def _conversation_participant_ids(session: AsyncSession, conversation_id: int) -> set[int]:
    rows = (
        await session.execute(
            select(ChatMessage.author_user_id).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.author_user_id.is_not(None),
            )
        )
    ).scalars().all()
    return {user_id for user_id in rows if user_id}


def _realtime_envelope(event_type: str, data: dict) -> dict:
    """Envelope padronizado (ETAPA 7) pra todo evento realtime: event_id
    unico (dedup/diagnostico no cliente), version simples (evolucao futura
    do contrato sem quebrar clientes antigos — tipo desconhecido e
    ignorado, nao derruba o RealtimeClient), occurred_at, e o payload de
    dominio em `data`."""
    return {
        "version": 1,
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "occurred_at": utcnow().isoformat(),
        "data": data,
    }


async def _conversation_broadcast_targets(session: AsyncSession, conversation: ChatConversation, notified_ids: set[int], actor: User) -> set[int]:
    """Quem deve receber eventos realtime desta conversa. GERAL nao tem
    controle de acesso proprio, entao vai pra todo mundo online (que so
    conseguiu conectar por ja ter CHAT_VIEW — ver /chat/ws). Conversa de
    proposta vai so pra quem ja participou dela, quem foi notificado agora,
    e o proprio autor — nunca um broadcast global pra conversa privada."""
    if conversation.kind == GENERAL_CHAT_KIND:
        return ws_manager.online_user_ids()
    return await _conversation_participant_ids(session, conversation.id) | set(notified_ids) | {actor.id}


async def _publish_conversation_event(
    session: AsyncSession, conversation: ChatConversation, notified_ids: set[int], actor: User, event_type: str, data: dict
) -> None:
    """Avisa clientes conectados por websocket que algo mudou nesta
    conversa — chamado sempre DEPOIS do commit, pra nunca empurrar algo que
    ainda poderia ser desfeito. Payload minimo de proposito (ETAPA 7,
    Estrategia B): o cliente ja tem um refresh() bem testado via REST,
    entao o evento so precisa dizer "o que" mudou e "onde", nao carregar a
    mensagem inteira por um segundo canal que poderia divergir do banco."""
    targets = await _conversation_broadcast_targets(session, conversation, notified_ids, actor)
    await ws_manager.broadcast(targets, _realtime_envelope(event_type, data))


async def _publish_user_event(user_id: int, event_type: str, data: dict) -> None:
    """ETAPA 10: variante de _publish_conversation_event pra eventos que sao
    sempre estritamente individuais (notification.created/read/read_all) --
    vao direto pro dono da notificacao, nunca pros outros participantes da
    conversa (ninguem mais precisa saber que fulano recebeu uma notificacao).
    Mesma regra de sempre: so chamar depois do commit."""
    await ws_manager.broadcast({user_id}, _realtime_envelope(event_type, data))


async def post_message(session: AsyncSession, conversation_id: int, actor: User, payload: MessageCreate) -> MessageOut:
    conversation = await get_conversation(session, conversation_id)
    if conversation.status == "FINALIZADA":
        raise ApiError(error_codes.CHAT_CONVERSATION_FINALIZED, "Esta conversa esta finalizada e nao aceita novas mensagens.", status_code=409)
    body = payload.body.strip()
    if not body:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "A mensagem nao pode ser vazia.", status_code=422)

    if payload.message_type == "PERGUNTA" and not payload.mentioned_user_id:
        raise ApiError(error_codes.CHAT_MENTION_REQUIRED, "Selecione o destinatario da pergunta.", status_code=422)

    client_message_id = payload.client_message_id.strip() if payload.client_message_id else None
    if client_message_id:
        existing = (
            await session.execute(
                select(ChatMessage)
                .options(selectinload(ChatMessage.attachments))
                .where(ChatMessage.conversation_id == conversation.id, ChatMessage.client_message_id == client_message_id)
            )
        ).scalars().first()
        if existing is not None:
            users_by_id = await _users_by_id(session, {existing.author_user_id, existing.mentioned_user_id})
            seen_by_message = await _seen_counts(session, [existing])
            return _message_out(existing, users_by_id, seen_by_message.get(existing.id, 0))

    mentioned_user_id: int | None = payload.mentioned_user_id
    if mentioned_user_id:
        mentioned_user = await session.get(User, mentioned_user_id)
        # o responsavel de uma Pergunta precisa poder responde-la (CHAT_SEND);
        # uma mencao comum so precisa poder ver a mensagem (CHAT_VIEW).
        required_permission = CHAT_SEND if payload.message_type == "PERGUNTA" else CHAT_VIEW
        if mentioned_user is None or not mentioned_user.active or not user_has_permission(mentioned_user, required_permission):
            raise ApiError(error_codes.CHAT_MENTIONED_USER_INVALID, "Usuario mencionado invalido.", status_code=422)

    answered_message_id: int | None = None
    if payload.reply_to_message_id:
        original = await session.get(ChatMessage, payload.reply_to_message_id)
        if original is None or original.conversation_id != conversation.id:
            raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Mensagem citada nao encontrada nesta conversa.", status_code=404)
        answered_message_id = original.id

    message, notified_ids = await _create_message(
        session,
        conversation,
        actor,
        body=body,
        message_type=payload.message_type,
        mentioned_user_id=mentioned_user_id,
        answered_message_id=answered_message_id,
        area=payload.area if payload.message_type == "NOTA_INTERNA" else None,
        due_at=payload.due_at,
        is_important=payload.is_important,
        client_message_id=client_message_id,
    )
    await session.commit()
    await session.refresh(message)
    await _publish_conversation_event(
        session,
        conversation,
        notified_ids,
        actor,
        "message.created",
        {
            "conversation_id": conversation.id,
            "message_id": message.id,
            "client_message_id": message.client_message_id,
            "proposal_id": conversation.proposal_id,
            "sender_user_id": message.author_user_id,
        },
    )
    # ETAPA 10: cada usuario notificado ganha o proprio evento individual,
    # distinto do message.created acima -- o cliente precisa de um tipo
    # proprio pra saber que e a Central de Notificacoes/sino que mudou, sem
    # ter que reinterpretar um evento de conversa como "talvez seja uma
    # notificacao pra mim".
    for notified_user_id in notified_ids:
        await _publish_user_event(notified_user_id, "notification.created", {"conversation_id": conversation.id})
    if message.message_type == "PERGUNTA":
        # uma Pergunta nova e as duas coisas ao mesmo tempo: uma mensagem
        # (message.created, acima) e uma pendencia nova pro responsavel
        # (mesmo par de eventos que reassign_question ja emite ao trocar
        # de responsavel).
        await _publish_conversation_event(
            session,
            conversation,
            notified_ids,
            actor,
            "action_required.created",
            {
                "conversation_id": conversation.id,
                "message_id": message.id,
                "proposal_id": conversation.proposal_id,
                "assigned_to_user_id": message.mentioned_user_id,
            },
        )
    users_by_id = await _users_by_id(session, {message.author_user_id, message.mentioned_user_id})
    return _message_out(message, users_by_id)


async def answer_question(session: AsyncSession, question_message_id: int, actor: User, body: str) -> MessageOut:
    question = await session.get(ChatMessage, question_message_id)
    if question is None or question.message_type != "PERGUNTA":
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Pergunta nao encontrada.", status_code=404)
    if question.question_status == "RESPONDIDA":
        raise ApiError(error_codes.CHAT_QUESTION_ALREADY_ANSWERED, "Esta pergunta ja foi respondida.", status_code=409)
    if question.question_status == "CANCELADA":
        raise ApiError(error_codes.CHAT_QUESTION_CANCELLED, "Esta pergunta foi cancelada e nao aceita mais respostas.", status_code=409)
    if question.mentioned_user_id != actor.id and not user_has_permission(actor, CHAT_ADMIN):
        raise PermissionDeniedError("Somente o responsavel pela pergunta ou um administrador do chat pode responde-la.")
    conversation = await get_conversation(session, question.conversation_id)
    if conversation.status == "FINALIZADA":
        raise ApiError(error_codes.CHAT_CONVERSATION_FINALIZED, "Esta conversa esta finalizada e nao aceita novas mensagens.", status_code=409)
    stripped = (body or "").strip()
    if not stripped:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "A resposta nao pode ser vazia.", status_code=422)

    # Transicao atomica: so avanca se a pergunta ainda estiver aberta no banco
    # neste exato instante — fecha a corrida entre respostas/cancelamentos
    # concorrentes (a checagem acima nao basta sozinha sob READ COMMITTED,
    # duas requisicoes podem passar por ela antes de qualquer uma comitar).
    # So cria a mensagem de resposta depois de garantir a posse da transicao,
    # pra nunca deixar uma resposta orfa se a transicao falhar.
    claimed = await session.execute(
        update(ChatMessage)
        .where(ChatMessage.id == question.id, ChatMessage.question_status == "AGUARDANDO_RESPOSTA")
        .values(question_status="RESPONDIDA")
    )
    if claimed.rowcount == 0:
        await session.rollback()
        raise ApiError(error_codes.CHAT_QUESTION_ALREADY_ANSWERED, "Esta pergunta ja foi respondida ou cancelada.", status_code=409)

    answer, notified_ids = await _create_message(
        session, conversation, actor, body=stripped, message_type="MENSAGEM", answered_message_id=question.id
    )
    await session.commit()
    await session.refresh(answer)
    # dois eventos de dominio distintos pelo mesmo commit: a resposta e uma
    # mensagem nova, e a pergunta original mudou de estado — um cliente que
    # so cuida de mensagens e outro que so cuida de pendencias reagem cada
    # um ao seu, sem precisar interpretar um evento generico.
    await _publish_conversation_event(
        session,
        conversation,
        notified_ids,
        actor,
        "message.created",
        {
            "conversation_id": conversation.id,
            "message_id": answer.id,
            "proposal_id": conversation.proposal_id,
            "sender_user_id": answer.author_user_id,
        },
    )
    await _publish_conversation_event(
        session,
        conversation,
        notified_ids,
        actor,
        "action_required.resolved",
        {"conversation_id": conversation.id, "message_id": question.id, "proposal_id": conversation.proposal_id},
    )
    for notified_user_id in notified_ids:
        await _publish_user_event(notified_user_id, "notification.created", {"conversation_id": conversation.id})
    users_by_id = await _users_by_id(session, {answer.author_user_id, answer.mentioned_user_id})
    return _message_out(answer, users_by_id)


async def _get_question(session: AsyncSession, message_id: int) -> ChatMessage:
    question = await session.get(ChatMessage, message_id)
    if question is None or question.message_type != "PERGUNTA":
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Pergunta nao encontrada.", status_code=404)
    return question


async def mark_question_viewed(session: AsyncSession, message_id: int, actor: User) -> MessageOut:
    """So o proprio responsavel marca a visualizacao, e so uma vez — abrir de
    novo nao atualiza o horario (PDF: 'mostrar quem visualizou e quando, sem
    alterar o status'). Chamado automaticamente pelo desktop ao renderizar o
    card da pergunta pro responsavel, sem exigir uma acao extra dele."""
    question = await _get_question(session, message_id)
    if question.mentioned_user_id == actor.id and question.viewed_at is None:
        question.viewed_at = func.now()
        await session.commit()
        await session.refresh(question)
    users_by_id = await _users_by_id(session, {question.author_user_id, question.mentioned_user_id})
    return _message_out(question, users_by_id)


async def cancel_question(session: AsyncSession, message_id: int, actor: User, reason: str) -> MessageOut:
    question = await _get_question(session, message_id)
    if question.question_status == "RESPONDIDA":
        raise ApiError(error_codes.CHAT_QUESTION_ALREADY_ANSWERED, "Esta pergunta ja foi respondida e nao pode ser cancelada.", status_code=409)
    if question.question_status == "CANCELADA":
        raise ApiError(error_codes.CHAT_QUESTION_NOT_CANCELLABLE, "Esta pergunta ja esta cancelada.", status_code=409)
    is_author = question.author_user_id == actor.id
    is_admin = user_has_permission(actor, CHAT_ADMIN)
    if not is_author and not is_admin:
        raise PermissionDeniedError("Somente o autor da pergunta ou um administrador do chat pode cancela-la.")

    # Mesma transicao atomica de answer_question: garante que resolver e
    # cancelar concorrentes nao pisem um no outro silenciosamente.
    claimed = await session.execute(
        update(ChatMessage)
        .where(ChatMessage.id == question.id, ChatMessage.question_status == "AGUARDANDO_RESPOSTA")
        .values(
            question_status="CANCELADA",
            cancelled_at=func.now(),
            cancelled_by_user_id=actor.id,
            cancellation_reason=reason.strip(),
        )
    )
    if claimed.rowcount == 0:
        await session.rollback()
        raise ApiError(error_codes.CHAT_QUESTION_ALREADY_ANSWERED, "Esta pergunta ja foi respondida ou cancelada.", status_code=409)
    await session.refresh(question)
    await auth_repository.create_security_event(
        session,
        "CHAT_QUESTION_CANCELLED",
        actor_user_id=actor.id,
        target_user_id=question.mentioned_user_id,
        details={"message_id": question.id, "reason": question.cancellation_reason, "by_admin": is_admin and not is_author},
    )
    await session.commit()
    await session.refresh(question)
    conversation = await get_conversation(session, question.conversation_id)
    await _publish_conversation_event(
        session,
        conversation,
        {question.mentioned_user_id} if question.mentioned_user_id else set(),
        actor,
        "action_required.cancelled",
        {"conversation_id": conversation.id, "message_id": question.id, "proposal_id": conversation.proposal_id},
    )
    users_by_id = await _users_by_id(session, {question.author_user_id, question.mentioned_user_id})
    return _message_out(question, users_by_id)


async def reassign_question(session: AsyncSession, message_id: int, actor: User, assignee_user_id: int, reason: str) -> MessageOut:
    """So administrador do chat (ou superusuario) reatribui, e so com
    justificativa — trocar o responsavel sem isso e proibido mesmo que o
    desktop esconda o botao (o backend continua sendo a autoridade, PDF 16)."""
    if not user_has_permission(actor, CHAT_ADMIN):
        raise PermissionDeniedError("Somente um administrador do chat pode reatribuir uma pergunta.")
    question = await _get_question(session, message_id)
    if question.question_status in ("RESPONDIDA", "CANCELADA"):
        raise ApiError(error_codes.CHAT_QUESTION_REASSIGN_DENIED, "Esta pergunta ja foi finalizada e nao pode ser reatribuida.", status_code=409)

    new_assignee = await session.get(User, assignee_user_id)
    if new_assignee is None or not new_assignee.active or not user_has_permission(new_assignee, CHAT_SEND):
        raise ApiError(error_codes.CHAT_MENTIONED_USER_INVALID, "Novo responsavel invalido.", status_code=422)

    previous_assignee_id = question.mentioned_user_id
    question.mentioned_user_id = assignee_user_id
    question.viewed_at = None
    await auth_repository.create_security_event(
        session,
        "CHAT_QUESTION_REASSIGNED",
        actor_user_id=actor.id,
        target_user_id=assignee_user_id,
        details={"message_id": question.id, "previous_assignee_id": previous_assignee_id, "reason": reason.strip()},
    )
    await session.flush()
    await _insert_notification(session, user_id=assignee_user_id, conversation_id=question.conversation_id, message_id=question.id, notification_type="PERGUNTA_ATRIBUIDA")
    await session.commit()
    await session.refresh(question)
    conversation = await get_conversation(session, question.conversation_id)
    await _publish_conversation_event(
        session,
        conversation,
        {assignee_user_id},
        actor,
        "action_required.created",
        {
            "conversation_id": conversation.id,
            "message_id": question.id,
            "proposal_id": conversation.proposal_id,
            "assigned_to_user_id": assignee_user_id,
        },
    )
    await _publish_user_event(assignee_user_id, "notification.created", {"conversation_id": conversation.id})
    users_by_id = await _users_by_id(session, {question.author_user_id, question.mentioned_user_id})
    return _message_out(question, users_by_id)


async def mark_notification_read(session: AsyncSession, notification_id: int, actor: User) -> None:
    notification = await session.get(ChatNotification, notification_id)
    if notification is None or notification.user_id != actor.id:
        raise ApiError(error_codes.CHAT_NOTIFICATION_NOT_FOUND, "Notificacao nao encontrada.", status_code=404)
    if notification.read_at is None:
        notification.read_at = func.now()
        await session.commit()
        # ETAPA 10: avisa as OUTRAS conexoes do mesmo usuario (dois
        # computadores, por exemplo) que esta notificacao especifica virou
        # lida -- mesmo padrao do conversation.read da ETAPA 9.
        await _publish_user_event(actor.id, "notification.read", {"notification_id": notification_id})


async def _ensure_overdue_notifications(session: AsyncSession, actor: User) -> None:
    """Varredura preguicosa: em vez de um job agendado, cada consulta de
    notificacoes/resumo do proprio usuario verifica se alguma pergunta
    atribuida a ele venceu o prazo e ainda nao tem o aviso de atraso — a
    constraint unica torna isso idempotente mesmo chamando varias vezes."""
    overdue_ids = (
        await session.execute(
            select(ChatMessage.id, ChatMessage.conversation_id).where(
                ChatMessage.message_type == "PERGUNTA",
                ChatMessage.mentioned_user_id == actor.id,
                ChatMessage.question_status == "AGUARDANDO_RESPOSTA",
                ChatMessage.due_at.is_not(None),
                ChatMessage.due_at < func.now(),
            )
        )
    ).all()
    if not overdue_ids:
        return
    for message_id, conversation_id in overdue_ids:
        await _insert_notification(session, user_id=actor.id, conversation_id=conversation_id, message_id=message_id, notification_type="PERGUNTA_ATRASADA")
    await session.commit()


async def list_messages(session: AsyncSession, conversation_id: int, actor: User, limit: int = 200, offset: int = 0) -> MessageList:
    conversation = await get_conversation(session, conversation_id)
    _ensure_can_view_conversation(actor, conversation)
    total = int(
        (await session.execute(select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conversation.id))).scalar_one()
    )
    rows = (
        await session.execute(
            select(ChatMessage)
            .options(selectinload(ChatMessage.attachments))
            .where(ChatMessage.conversation_id == conversation.id)
            # ETAPA 9: id como desempate -- created_at sozinho nao e garantia
            # de ordem deterministica sob mensagens com timestamp igual/muito
            # proximo, e o cursor de leitura (last_read_message_id) compara
            # por id. As duas ordenacoes tem que concordar sempre.
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    ids: set[int | None] = set()
    for row in rows:
        ids.add(row.author_user_id)
        ids.add(row.mentioned_user_id)
    users_by_id = await _users_by_id(session, ids)
    seen_by_message = await _seen_counts(session, rows)
    return MessageList(
        items=[_message_out(row, users_by_id, seen_by_message.get(row.id, 0)) for row in rows],
        total=total,
        has_more=(offset + len(rows)) < total,
    )


_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
_MEDIA_EXTENSIONS = {ext for cat in (ChatAttachmentCategory.IMAGE, ChatAttachmentCategory.VIDEO) for ext in ALLOWED_EXTENSIONS_BY_CATEGORY[cat]}


def extract_links(body: str) -> list[str]:
    """So http(s):// (nada de esquemas exoticos) -- evita tratar texto quebrado
    como URL e nunca interpreta/renderiza o HTML da mensagem."""
    if not body:
        return []
    return _URL_PATTERN.findall(body)


async def _list_shared_links(session: AsyncSession, conversation: ChatConversation, search: str, limit: int, offset: int) -> SharedContentList:
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id, ChatMessage.body.ilike("%http%"))
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        )
    ).scalars().all()

    all_items: list[tuple[ChatMessage, str]] = []
    for message in rows:
        for url in extract_links(message.body):
            if search and search.lower() not in url.lower() and search.lower() not in (message.body or "").lower():
                continue
            all_items.append((message, url))

    page = all_items[offset : offset + limit + 1]
    has_more = len(page) > limit
    page = page[:limit]

    ids: set[int | None] = {message.author_user_id for message, _url in page}
    users_by_id = await _users_by_id(session, ids)

    items = [
        SharedContentItem(
            kind="link",
            message_id=message.id,
            attachment_id=None,
            name=url,
            created_at=message.created_at,
            sender_name=users_by_id[message.author_user_id].display_name if message.author_user_id in users_by_id else None,
            snippet=(message.body or "")[:240],
        )
        for message, url in page
    ]
    return SharedContentList(items=items, has_more=has_more)


async def list_shared_content(
    session: AsyncSession,
    conversation_id: int,
    actor: User,
    *,
    kind: str,
    q: str | None = None,
    limit: int = 40,
    offset: int = 0,
) -> SharedContentList:
    """Fase 7 - "Midia e arquivos": deriva midia/documentos/links do historico
    real da conversa. NAO duplica anexos/mensagens -- so referencia
    message_id/attachment_id, reutilizados pelo download (Fase 5) e pelo
    "ir para mensagem" ja existente no desktop."""
    if kind not in {"media", "document", "link"}:
        raise ApiError(error_codes.VALIDATION_ERROR, "Filtro invalido.", status_code=422)
    conversation = await get_conversation(session, conversation_id)
    _ensure_can_view_conversation(actor, conversation)
    search = (q or "").strip()

    if kind == "link":
        return await _list_shared_links(session, conversation, search, limit, offset)

    media_condition = or_(
        func.lower(ChatAttachment.mime_type).like("image/%"),
        func.lower(ChatAttachment.mime_type).like("video/%"),
        func.lower(ChatAttachment.file_extension).in_(_MEDIA_EXTENSIONS),
    )
    query = (
        select(ChatAttachment, ChatMessage)
        .join(ChatMessage, ChatAttachment.message_id == ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation.id, ChatAttachment.deleted_at.is_(None))
    )
    query = query.where(media_condition) if kind == "media" else query.where(~media_condition)
    if search:
        query = query.where(ChatAttachment.original_filename.ilike(f"%{search}%"))
    query = query.order_by(ChatAttachment.created_at.desc(), ChatAttachment.id.desc()).offset(offset).limit(limit + 1)
    rows = (await session.execute(query)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    ids: set[int | None] = {message.author_user_id for _attachment, message in rows}
    users_by_id = await _users_by_id(session, ids)

    items = []
    for attachment, message in rows:
        is_video = str(attachment.mime_type or "").lower().startswith("video/") or classify_extension(attachment.file_extension) == ChatAttachmentCategory.VIDEO
        item_kind = "video" if is_video else ("image" if kind == "media" else "document")
        sender = users_by_id.get(message.author_user_id)
        items.append(
            SharedContentItem(
                kind=item_kind,
                message_id=message.id,
                attachment_id=attachment.id,
                name=attachment.original_filename,
                mime_type=attachment.mime_type,
                size=attachment.file_size,
                sha256=attachment.sha256,
                created_at=attachment.created_at,
                sender_name=sender.display_name if sender else None,
            )
        )
    return SharedContentList(items=items, has_more=has_more)


async def upload_attachment(
    session: AsyncSession,
    message_id: int,
    actor: User,
    upload_file,
    storage: ChatAttachmentStorage | None = None,
    client_attachment_id: str | None = None,
) -> ChatAttachmentOut:
    if not user_has_permission(actor, CHAT_VIEW):
        raise PermissionDeniedError("Seu usuario nao pode acessar esta conversa.")
    storage = storage or ChatAttachmentStorage()
    message = await session.get(ChatMessage, message_id, options=[selectinload(ChatMessage.conversation)])
    if message is None:
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Mensagem nao encontrada.", status_code=404)
    conversation = message.conversation or await get_conversation(session, message.conversation_id)
    _ensure_can_view_conversation(actor, conversation)
    if conversation.status == "FINALIZADA":
        raise ApiError(error_codes.CHAT_CONVERSATION_FINALIZED, "Esta conversa esta finalizada e nao aceita anexos.", status_code=409)
    settings = get_settings()
    active_attachment_rows = (
        await session.execute(
            select(ChatAttachment.file_size).where(ChatAttachment.message_id == message.id, ChatAttachment.deleted_at.is_(None))
        )
    ).scalars().all()
    if len(active_attachment_rows) >= settings.chat_max_attachments_per_message:
        raise ApiError(error_codes.CHAT_ATTACHMENT_LIMIT_EXCEEDED, "Limite de anexos por mensagem atingido.", status_code=413)
    client_attachment_id = client_attachment_id.strip() if client_attachment_id else None
    if client_attachment_id:
        existing = (
            await session.execute(
                select(ChatAttachment)
                .where(ChatAttachment.message_id == message.id, ChatAttachment.client_attachment_id == client_attachment_id)
            )
        ).scalars().first()
        if existing is not None and existing.deleted_at is None:
            return _attachment_out(existing)
        if existing is not None and existing.deleted_at is not None:
            raise ApiError(error_codes.CHAT_ATTACHMENT_NOT_FOUND, "Anexo ja removido.", status_code=410)

    original_filename = sanitize_original_filename(getattr(upload_file, "filename", "") or "arquivo")
    first_chunk = await upload_file.read(1024 * 1024)
    if not first_chunk:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "Arquivo vazio nao pode ser anexado.", status_code=422)

    temp_path: Path | None = None
    final_path: Path | None = None
    attachment: ChatAttachment | None = None
    result: ChatAttachmentOut | None = None
    try:
        storage.ensure_min_free_space()
        type_info = storage.validate_type(original_filename, getattr(upload_file, "content_type", None), first_chunk)
        temp_path, file_size, digest = await write_upload_to_temp(upload_file, storage, type_info, first_chunk)
        total_after_upload = sum(int(size or 0) for size in active_attachment_rows) + file_size
        if total_after_upload > settings.chat_max_total_attachment_mb * 1024 * 1024:
            raise AttachmentValidationError("Limite total de anexos por mensagem excedido.")
        stored_filename = storage.generate_storage_name(original_filename)
        relative_path, final_path = storage.prepare_final_path(stored_filename)
        storage.move_temp_to_final(temp_path, final_path)
        temp_path = None

        attachment = ChatAttachment(
            message_id=message.id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            mime_type=type_info.mime_type,
            file_extension=type_info.extension,
            file_size=file_size,
            storage_path=relative_path,
            sha256=digest,
            client_attachment_id=client_attachment_id,
            uploaded_by=actor.id,
        )
        session.add(attachment)
        await auth_repository.create_security_event(
            session,
            "CHAT_ATTACHMENT_UPLOAD",
            actor_user_id=actor.id,
            details={
                "message_id": message.id,
                "conversation_id": conversation.id,
                "file_size": file_size,
                "mime_type": type_info.mime_type,
                "sha256": digest,
            },
        )
        await session.commit()
        await session.refresh(attachment)
        attachment_logger.info(
            "chat_attachment_uploaded attachment_id=%s message_id=%s user_id=%s file_size=%s mime_type=%s sha256=%s",
            attachment.id,
            message.id,
            actor.id,
            file_size,
            type_info.mime_type,
            digest,
        )
        result = _attachment_out(attachment)
    except AttachmentValidationError as exc:
        await session.rollback()
        storage.remove_file(temp_path)
        storage.remove_file(final_path)
        text = str(exc).lower()
        if "limite" in text:
            raise ApiError(error_codes.CHAT_ATTACHMENT_TOO_LARGE, "Arquivo acima do limite permitido.", status_code=413) from exc
        raise ApiError(error_codes.CHAT_ATTACHMENT_TYPE_NOT_ALLOWED, "Tipo de arquivo nao permitido.", status_code=415) from exc
    except OSError as exc:
        await session.rollback()
        storage.remove_file(temp_path)
        storage.remove_file(final_path)
        attachment_logger.exception("chat_attachment_storage_failed message_id=%s user_id=%s", message_id, actor.id)
        raise ApiError(error_codes.CHAT_ATTACHMENT_STORAGE_ERROR, "Nao foi possivel armazenar o anexo.", status_code=507) from exc
    except Exception:
        await session.rollback()
        storage.remove_file(temp_path)
        storage.remove_file(final_path)
        attachment_logger.exception("chat_attachment_upload_failed message_id=%s user_id=%s", message_id, actor.id)
        raise
    assert attachment is not None and result is not None
    await _publish_conversation_event(
        session,
        conversation,
        set(),
        actor,
        "attachment.created",
        {
            "conversation_id": conversation.id,
            "message_id": message.id,
            "client_message_id": message.client_message_id,
            "attachment": result.model_dump(mode="json"),
        },
    )
    return result


async def _get_attachment_for_actor(session: AsyncSession, attachment_id: int, actor: User, *, include_deleted: bool = False) -> ChatAttachment:
    attachment = (
        await session.execute(
            select(ChatAttachment)
            .options(selectinload(ChatAttachment.message).selectinload(ChatMessage.conversation))
            .where(ChatAttachment.id == attachment_id)
        )
    ).scalars().first()
    if attachment is None:
        raise ApiError(error_codes.CHAT_ATTACHMENT_NOT_FOUND, "Anexo nao encontrado.", status_code=404)
    conversation = attachment.message.conversation if attachment.message else None
    if conversation is None:
        raise ApiError(error_codes.CHAT_ATTACHMENT_NOT_FOUND, "Anexo nao encontrado.", status_code=404)
    _ensure_can_view_conversation(actor, conversation)
    if attachment.deleted_at is not None and not include_deleted:
        raise ApiError(error_codes.CHAT_ATTACHMENT_NOT_FOUND, "Anexo nao esta mais disponivel.", status_code=410)
    return attachment


async def get_attachment_metadata(session: AsyncSession, attachment_id: int, actor: User) -> ChatAttachmentOut:
    attachment = await _get_attachment_for_actor(session, attachment_id, actor)
    return _attachment_out(attachment)


def _ensure_can_delete_attachment(actor: User, attachment: ChatAttachment) -> None:
    message = attachment.message
    if actor.is_superuser or user_has_permission(actor, CHAT_ADMIN):
        return
    if attachment.uploaded_by is not None and attachment.uploaded_by == actor.id:
        return
    if message is not None and message.author_user_id is not None and message.author_user_id == actor.id:
        return
    raise ApiError(error_codes.PERMISSION_DENIED, "Usuario nao possui permissao para remover este anexo.", status_code=403)


async def delete_attachment(session: AsyncSession, attachment_id: int, actor: User, reason: str) -> ChatAttachmentOut:
    attachment = await _get_attachment_for_actor(session, attachment_id, actor, include_deleted=True)
    if attachment.deleted_at is not None:
        return _attachment_out(attachment)
    _ensure_can_delete_attachment(actor, attachment)
    message = attachment.message
    conversation = message.conversation if message else None
    if conversation is None:
        raise ApiError(error_codes.CHAT_ATTACHMENT_NOT_FOUND, "Anexo nao encontrado.", status_code=404)
    reason = str(reason or "").strip()
    if len(reason) < 3:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "Informe uma justificativa para remover o anexo.", status_code=422)
    attachment.deleted_at = utcnow()
    attachment.deleted_by = actor.id
    attachment.delete_reason = reason[:500]
    await auth_repository.create_security_event(
        session,
        "CHAT_ATTACHMENT_DELETED",
        actor_user_id=actor.id,
        details={
            "attachment_id": attachment.id,
            "message_id": attachment.message_id,
            "conversation_id": conversation.id,
            "file_size": attachment.file_size,
            "sha256": attachment.sha256,
            "reason": attachment.delete_reason,
        },
    )
    await session.commit()
    await session.refresh(attachment)
    result = _attachment_out(attachment)
    await _publish_conversation_event(
        session,
        conversation,
        set(),
        actor,
        "attachment.deleted",
        {"conversation_id": conversation.id, "message_id": attachment.message_id, "attachment": result.model_dump(mode="json")},
    )
    return result


async def purge_deleted_attachments(session: AsyncSession, actor: User, storage: ChatAttachmentStorage | None = None, *, now: datetime | None = None) -> int:
    if not (actor.is_superuser or user_has_permission(actor, CHAT_ADMIN)):
        raise ApiError(error_codes.PERMISSION_DENIED, "Usuario nao possui permissao para expurgar anexos.", status_code=403)
    storage = storage or ChatAttachmentStorage()
    settings = get_settings()
    cutoff = (now or utcnow()) - timedelta(days=settings.chat_attachment_deleted_retention_days)
    attachments = (
        await session.execute(
            select(ChatAttachment).where(
                ChatAttachment.deleted_at.is_not(None),
                ChatAttachment.purged_at.is_(None),
                ChatAttachment.deleted_at < cutoff,
            )
        )
    ).scalars().all()
    purged = 0
    for attachment in attachments:
        try:
            path = storage.resolve_path(attachment.storage_path)
        except ValueError:
            path = None
        if path is not None:
            ChatAttachmentStorage.remove_file(path)
        attachment.purged_at = now or utcnow()
        await auth_repository.create_security_event(
            session,
            "CHAT_ATTACHMENT_PURGED",
            actor_user_id=actor.id,
            details={
                "attachment_id": attachment.id,
                "message_id": attachment.message_id,
                "storage_path": attachment.storage_path,
                "sha256": attachment.sha256,
                "deleted_at": attachment.deleted_at.isoformat() if attachment.deleted_at else None,
                "deleted_by": attachment.deleted_by,
                "purged_at": attachment.purged_at.isoformat() if attachment.purged_at else None,
            },
        )
        purged += 1
    if purged:
        await session.commit()
    return purged


async def attachment_integrity_report(
    session: AsyncSession,
    actor: User,
    storage: ChatAttachmentStorage | None = None,
    *,
    include_orphans: bool = True,
    orphan_grace_hours: int = 24,
) -> list[AttachmentIntegrityIssue]:
    if not (actor.is_superuser or user_has_permission(actor, CHAT_ADMIN)):
        raise ApiError(error_codes.PERMISSION_DENIED, "Usuario nao possui permissao para diagnosticar anexos.", status_code=403)
    storage = storage or ChatAttachmentStorage()
    attachments = (await session.execute(select(ChatAttachment))).scalars().all()
    known_paths = {attachment.storage_path for attachment in attachments}
    issues: list[AttachmentIntegrityIssue] = []
    for attachment in attachments:
        if attachment.purged_at is not None:
            continue
        try:
            path = storage.resolve_path(attachment.storage_path)
        except ValueError:
            issues.append(AttachmentIntegrityIssue("INVALID_PATH", attachment.id, attachment.storage_path))
            continue
        if not path.exists() or not path.is_file():
            issues.append(AttachmentIntegrityIssue("MISSING_FILE", attachment.id, attachment.storage_path))
            continue
        if attachment.deleted_at is None:
            try:
                digest = storage.sha256_file(path)
            except OSError as exc:
                issues.append(AttachmentIntegrityIssue("MISSING_FILE", attachment.id, attachment.storage_path, str(exc)))
                continue
            if digest != attachment.sha256:
                issues.append(AttachmentIntegrityIssue("HASH_MISMATCH", attachment.id, attachment.storage_path, digest))
    if include_orphans:
        root = storage.root / "chat"
        cutoff = (utcnow() - timedelta(hours=max(1, orphan_grace_hours))).timestamp()
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file() or ".tmp" in path.parts:
                    continue
                try:
                    relative = path.relative_to(storage.root).as_posix()
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if relative not in known_paths and mtime < cutoff:
                    issues.append(AttachmentIntegrityIssue("ORPHAN_FILE", None, relative))
    return issues


async def get_attachment_content(session: AsyncSession, attachment_id: int, actor: User, storage: ChatAttachmentStorage | None = None) -> AttachmentContent:
    storage = storage or ChatAttachmentStorage()
    attachment = await _get_attachment_for_actor(session, attachment_id, actor)
    try:
        path = storage.resolve_path(attachment.storage_path)
    except ValueError as exc:
        raise ApiError(error_codes.CHAT_ATTACHMENT_STORAGE_ERROR, "Caminho interno do anexo esta invalido.", status_code=500) from exc
    if not path.exists() or not path.is_file():
        attachment_logger.error("chat_attachment_file_missing attachment_id=%s path=%s", attachment_id, attachment.storage_path)
        await auth_repository.create_security_event(
            session,
            "CHAT_ATTACHMENT_FILE_MISSING",
            actor_user_id=actor.id,
            details={"attachment_id": attachment.id, "message_id": attachment.message_id, "storage_path": attachment.storage_path},
        )
        await session.commit()
        raise ApiError(error_codes.CHAT_ATTACHMENT_STORAGE_ERROR, "Arquivo do anexo nao esta disponivel.", status_code=500)
    try:
        digest = storage.sha256_file(path)
    except OSError as exc:
        raise ApiError(error_codes.CHAT_ATTACHMENT_STORAGE_ERROR, "Arquivo do anexo nao esta disponivel.", status_code=500) from exc
    if digest != attachment.sha256:
        attachment_logger.critical("chat_attachment_hash_mismatch attachment_id=%s expected=%s actual=%s", attachment.id, attachment.sha256, digest)
        await auth_repository.create_security_event(
            session,
            "CHAT_ATTACHMENT_HASH_MISMATCH",
            actor_user_id=actor.id,
            details={"attachment_id": attachment.id, "message_id": attachment.message_id, "expected_sha256": attachment.sha256, "actual_sha256": digest},
        )
        await session.commit()
        raise ApiError(error_codes.CHAT_ATTACHMENT_INTEGRITY_ERROR, "Integridade do anexo nao confere.", status_code=409)
    await auth_repository.create_security_event(
        session,
        "CHAT_ATTACHMENT_DOWNLOAD",
        actor_user_id=actor.id,
        details={"attachment_id": attachment.id, "message_id": attachment.message_id, "file_size": attachment.file_size, "sha256": attachment.sha256},
    )
    await session.commit()
    headers = {
        "Cache-Control": "private",
        "ETag": f'"{attachment.sha256}"',
        "Content-Disposition": content_disposition_attachment(attachment.original_filename),
    }
    return AttachmentContent(path=path, filename=attachment.original_filename, mime_type=attachment.mime_type, headers=headers)


async def get_proposal_timeline(
    session: AsyncSession, proposal_id: int, actor: User, *, before: datetime | None = None, limit: int = 200
) -> TimelineList:
    # GET com efeito colateral deliberado: garante que toda proposta consultada
    # tenha um chat proprio, sem precisar alterar o fluxo de criacao de proposta.
    conversation = await get_or_create_proposal_chat(session, proposal_id)
    await session.commit()
    _ensure_can_view_conversation(actor, conversation)

    # limite de seguranca (mesmo teto usado abaixo para list_proposal_history)
    # para nunca carregar um numero irrestrito de mensagens de uma unica vez.
    messages = list(
        reversed(
            (
                await session.execute(
                    select(ChatMessage)
                    .options(selectinload(ChatMessage.attachments))
                    .where(ChatMessage.conversation_id == conversation.id)
                    # ETAPA 9: id como desempate, mesma razao de list_messages.
                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                    .limit(5000)
                )
            )
            .scalars()
            .all()
        )
    )
    ids: set[int | None] = set()
    for message in messages:
        ids.add(message.author_user_id)
        ids.add(message.mentioned_user_id)
    users_by_id = await _users_by_id(session, ids)
    seen_by_message = await _seen_counts(session, messages)

    entries: list[TimelineEntry] = []
    for message in messages:
        try:
            author = users_by_id.get(message.author_user_id) if message.author_user_id else None
            mentioned = users_by_id.get(message.mentioned_user_id) if message.mentioned_user_id else None
            entries.append(
                TimelineEntry(
                    id=message.id,
                    source="chat",
                    entry_kind=message.message_type,
                    author_user_id=message.author_user_id,
                    author_name=author.display_name if author else None,
                    mentioned_user_id=message.mentioned_user_id,
                    mentioned_user_name=mentioned.display_name if mentioned else None,
                    question_status=_effective_question_status(message.question_status, message.due_at),
                    answered_message_id=message.answered_message_id,
                    body=message.body,
                    area=message.area,
                    due_at=message.due_at,
                    viewed_at=message.viewed_at,
                    cancelled_at=message.cancelled_at,
                    cancellation_reason=message.cancellation_reason,
                    is_important=message.is_important,
                    created_at=message.created_at,
                    seen_by_count=seen_by_message.get(message.id, 0),
                    attachments=_message_attachments(message),
                )
            )
        except Exception:
            logger.exception("Mensagem invalida no timeline: message_id=%r conversation_id=%r", message.id, conversation.id)

    # Atividade operacional da proposta (producao/galvanizacao/expedicao/
    # fiscal) NAO entra mais aqui — o chat so mostra comunicacao humana
    # (mensagens, perguntas/respostas, notas internas). Ver
    # proposals_service.list_proposal_activities para o feed operacional.
    entries.sort(key=lambda entry: (entry.created_at, entry.id))
    if before is not None:
        entries = [entry for entry in entries if entry.created_at < before]
    has_more = len(entries) > limit
    if has_more:
        entries = entries[-limit:]
    return TimelineList(conversation_id=conversation.id, items=entries, has_more=has_more)


async def _unread_counts(session: AsyncSession, actor: User, conversation_ids: list[int]) -> dict[int, int]:
    """Uma unica consulta agregada (LEFT JOIN + GROUP BY) para todas as
    conversas, em vez de uma consulta de contagem por conversa."""
    if not conversation_ids:
        return {}
    reads_subq = (
        select(ChatMessageRead.conversation_id, ChatMessageRead.last_read_message_id)
        .where(ChatMessageRead.user_id == actor.id, ChatMessageRead.conversation_id.in_(conversation_ids))
        .subquery()
    )
    stmt = (
        select(ChatMessage.conversation_id, func.count())
        .select_from(ChatMessage)
        .outerjoin(reads_subq, reads_subq.c.conversation_id == ChatMessage.conversation_id)
        .where(
            ChatMessage.conversation_id.in_(conversation_ids),
            ChatMessage.id > func.coalesce(reads_subq.c.last_read_message_id, 0),
            ChatMessage.author_user_id.is_distinct_from(actor.id),
        )
        .group_by(ChatMessage.conversation_id)
    )
    rows = (await session.execute(stmt)).all()
    return {conversation_id: int(count) for conversation_id, count in rows}


async def _last_messages(session: AsyncSession, conversation_ids: list[int]) -> dict[int, ChatMessage]:
    """Busca a ultima mensagem de todas as conversas em uma unica consulta,
    usando ROW_NUMBER() particionado por conversa em vez de uma consulta
    "ORDER BY ... LIMIT 1" por conversa."""
    if not conversation_ids:
        return {}
    ranked = (
        select(
            ChatMessage,
            func.row_number()
            # ETAPA 9: id como desempate, mesma razao de list_messages.
            .over(partition_by=ChatMessage.conversation_id, order_by=(ChatMessage.created_at.desc(), ChatMessage.id.desc()))
            .label("rn"),
        )
        .where(ChatMessage.conversation_id.in_(conversation_ids))
        .subquery()
    )
    ranked_message = aliased(ChatMessage, ranked)
    rows = (await session.execute(select(ranked_message).where(ranked.c.rn == 1))).scalars().all()
    return {message.conversation_id: message for message in rows}


async def list_conversations(
    session: AsyncSession,
    actor: User,
    *,
    status: str | None = None,
    search: str | None = None,
    conversation_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ConversationList:
    await get_or_create_general_chat(session)
    await session.commit()

    stmt = select(ChatConversation, Proposal).select_from(ChatConversation).outerjoin(Proposal, Proposal.id == ChatConversation.proposal_id)
    if status:
        stmt = stmt.where(ChatConversation.status == status)
    if conversation_id:
        stmt = stmt.where(ChatConversation.id == conversation_id)
    rows = (await session.execute(stmt)).all()
    rows = [(conversation, proposal) for conversation, proposal in rows if _conversation_visible_in_listings(actor, conversation)]

    search_normalized = (search or "").strip().lower()
    filtered = []
    for conversation, proposal in rows:
        if search_normalized:
            haystack = " ".join(
                filter(
                    None,
                    [
                        "chat geral" if conversation.kind == GENERAL_CHAT_KIND else "",
                        proposal.proposal_number if proposal else "",
                        proposal.customer_name if proposal else "",
                    ],
                )
            ).lower()
            if search_normalized not in haystack:
                continue
        filtered.append((conversation, proposal))

    conversation_ids = [conversation.id for conversation, _ in filtered]
    unread_by_conversation = await _unread_counts(session, actor, conversation_ids)
    message_counts_by_conversation = await _message_counts(session, conversation_ids)
    filtered.sort(key=lambda pair: (pair[0].kind != GENERAL_CHAT_KIND, -(pair[0].last_activity_at.timestamp() if pair[0].last_activity_at else 0)))

    total = len(filtered)
    page = filtered[offset : offset + limit]
    page_conversation_ids = [conversation.id for conversation, _ in page]
    last_message_by_conversation = await _last_messages(session, page_conversation_ids)
    author_ids = {message.author_user_id for message in last_message_by_conversation.values() if message.author_user_id}
    authors_by_id = await _users_by_id(session, author_ids)

    items = []
    for conversation, proposal in page:
        # Uma conversa com dado legado/inconsistente nao pode derrubar a
        # listagem inteira — registra qual conversa falhou e segue para as
        # demais (a Central de Conversas nunca pode abrir vazia por causa de
        # um unico registro ruim).
        try:
            last_message = last_message_by_conversation.get(conversation.id)
            last_author = authors_by_id.get(last_message.author_user_id) if last_message and last_message.author_user_id else None
            items.append(
                ConversationOut(
                    id=conversation.id,
                    kind=conversation.kind,
                    proposal_id=conversation.proposal_id,
                    proposal_number=proposal.proposal_number if proposal else None,
                    customer_name=proposal.customer_name if proposal else None,
                    proposal_area=proposal.current_area if proposal else None,
                    proposal_status=proposal.current_status if proposal else None,
                    status=conversation.status,
                    last_activity_at=conversation.last_activity_at,
                    created_at=conversation.created_at,
                    unread_count=unread_by_conversation.get(conversation.id, 0),
                    message_count=message_counts_by_conversation.get(conversation.id, 0),
                    last_message_preview=last_message.body if last_message else None,
                    last_message_author=last_author.display_name if last_author else None,
                    last_message_author_user_id=last_message.author_user_id if last_message else None,
                )
            )
        except Exception:
            logger.exception("Conversa invalida na listagem: conversation_id=%r", conversation.id)
    return ConversationList(items=items, total=total)


async def _message_counts(session: AsyncSession, conversation_ids: list[int]) -> dict[int, int]:
    if not conversation_ids:
        return {}
    rows = (
        await session.execute(
            select(ChatMessage.conversation_id, func.count())
            .where(ChatMessage.conversation_id.in_(conversation_ids))
            .group_by(ChatMessage.conversation_id)
        )
    ).all()
    return {conversation_id: int(count) for conversation_id, count in rows}


async def mark_read(session: AsyncSession, conversation_id: int, actor: User, last_read_message_id: int) -> ConversationReadState:
    conversation = await get_conversation(session, conversation_id)
    _ensure_can_view_conversation(actor, conversation)
    message = await session.get(ChatMessage, last_read_message_id)
    if message is None or message.conversation_id != conversation.id:
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Mensagem informada nao pertence a esta conversa.", status_code=404)

    # ETAPA 9: upsert atomico no banco -- nunca SELECT + compara em Python +
    # UPDATE, que sob concorrencia real (duas conexoes lendo o mesmo cursor
    # antigo antes de qualquer uma commitar) deixa o cursor regredir se a
    # requisicao com o valor MENOR commitar por ultimo. O ON CONFLICT ...
    # DO UPDATE ... WHERE inteiro roda dentro do Postgres: sob colisao real
    # a segunda espera o lock da primeira liberar e so aplica se o valor
    # dela ainda for maior que o que acabou de ser commitado -- convergencia
    # pro maior cursor garantida independente da ordem de chegada/commit.
    upsert = (
        pg_insert(ChatMessageRead)
        .values(conversation_id=conversation.id, user_id=actor.id, last_read_message_id=last_read_message_id, updated_at=func.now())
        .on_conflict_do_update(
            index_elements=["conversation_id", "user_id"],
            set_={"last_read_message_id": last_read_message_id, "updated_at": func.now()},
            where=or_(
                ChatMessageRead.last_read_message_id.is_(None),
                ChatMessageRead.last_read_message_id < last_read_message_id,
            ),
        )
        .returning(ChatMessageRead.last_read_message_id, ChatMessageRead.updated_at)
    )
    applied = (await session.execute(upsert)).first()
    if applied is not None:
        final_cursor, final_read_at = applied
    else:
        # O WHERE do DO UPDATE nao bateu: o request chegou com um cursor
        # igual ou mais antigo que o que ja estava persistido (replay
        # idempotente ou resposta atrasada de outro dispositivo). Nao
        # aplicamos nada, mas a resposta precisa contar a verdade -- busca
        # o que realmente esta salvo, nunca ecoa de volta o valor pedido.
        final_cursor, final_read_at = (
            await session.execute(
                select(ChatMessageRead.last_read_message_id, ChatMessageRead.updated_at).where(
                    ChatMessageRead.conversation_id == conversation.id, ChatMessageRead.user_id == actor.id
                )
            )
        ).one()

    # Sincroniza a notificacao (ChatNotification.read_at) ate o cursor FINAL
    # persistido (nao o valor pedido, que pode estar atrasado) — para TODOS
    # os tipos, ver a mensagem ja e suficiente pra marcar a notificacao dela
    # como visualizada. Isso nunca toca em ChatMessage.question_status:
    # notification e a pendencia (ETAPA 5) sao campos completamente
    # separados, entao marcar a notificacao ACTION_REQUIRED como lida aqui
    # NAO resolve/cancela a pergunta correspondente — ela so muda via
    # answer_question/cancel_question, explicitamente. A clausula
    # read_at IS NULL garante que isso nunca "deslê" nada nem depende de o
    # cursor ter avancado nesta chamada (idempotente e seguro mesmo com um
    # last_read_message_id antigo, que so vai casar com 0 linhas).
    notifications_changed = False
    if final_cursor is not None:
        notification_update = await session.execute(
            update(ChatNotification)
            .where(
                ChatNotification.user_id == actor.id,
                ChatNotification.conversation_id == conversation.id,
                ChatNotification.read_at.is_(None),
                ChatNotification.message_id <= final_cursor,
            )
            .values(read_at=func.now())
        )
        notifications_changed = bool((getattr(notification_update, "rowcount", 0) or 0) > 0)
    await session.commit()

    # ETAPA 7: avisa as OUTRAS conexoes do mesmo usuario (ex.: dois
    # computadores) que o cursor avancou — ninguem mais precisa disso, ler
    # nao muda o que outros participantes veem, so o proprio ator. Sempre
    # com o cursor FINAL persistido, nunca com o valor pedido (que pode
    # estar atrasado e nao ter mudado nada).
    if applied is not None or notifications_changed:
        await ws_manager.broadcast(
            {actor.id},
            _realtime_envelope(
                "conversation.read",
                {"conversation_id": conversation.id, "last_read_message_id": final_cursor},
            ),
        )
    return ConversationReadState(conversation_id=conversation.id, last_read_message_id=final_cursor, last_read_at=final_read_at)


async def _pending_question_count(session: AsyncSession, actor: User) -> int:
    count = (
        await session.execute(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.message_type == "PERGUNTA",
                ChatMessage.mentioned_user_id == actor.id,
                ChatMessage.question_status == "AGUARDANDO_RESPOSTA",
            )
        )
    ).scalar_one()
    return int(count)


async def unread_summary(session: AsyncSession, actor: User) -> UnreadSummary:
    await _ensure_overdue_notifications(session, actor)
    conversations = (await session.execute(select(ChatConversation))).scalars().all()
    conversations = [conversation for conversation in conversations if _conversation_visible_in_listings(actor, conversation)]
    conversation_ids = [conversation.id for conversation in conversations]
    unread_by_conversation = await _unread_counts(session, actor, conversation_ids)

    proposal_ids = {conversation.proposal_id for conversation in conversations if conversation.proposal_id}
    proposals_by_id: dict[int, Proposal] = {}
    if proposal_ids:
        rows = (await session.execute(select(Proposal).where(Proposal.id.in_(proposal_ids)))).scalars().all()
        proposals_by_id = {row.id: row for row in rows}

    entries: list[ConversationUnread] = []
    total = 0
    for conversation in conversations:
        unread = unread_by_conversation.get(conversation.id, 0)
        if unread <= 0:
            continue
        total += unread
        proposal = proposals_by_id.get(conversation.proposal_id) if conversation.proposal_id else None
        entries.append(
            ConversationUnread(
                conversation_id=conversation.id,
                kind=conversation.kind,
                proposal_id=conversation.proposal_id,
                proposal_number=proposal.proposal_number if proposal else None,
                unread_count=unread,
            )
        )
    entries.sort(key=lambda entry: entry.unread_count, reverse=True)

    pending_questions = await _pending_question_count(session, actor)
    notification_unread_count = await _notification_unread_count(session, actor)
    unread_mentions = await _notification_unread_count(session, actor, notification_type="MENCAO")
    return UnreadSummary(
        total_unread=total,
        conversations=entries,
        pending_questions=pending_questions,
        notification_unread_count=notification_unread_count,
        unread_mentions=unread_mentions,
        # ETAPA 8: carimbo de hora do servidor no snapshot — so
        # diagnostico/evolucao futura, o desktop nunca usa isso pra decidir
        # o que e "novo" (quem manda e o estado absoluto vindo do Postgres).
        server_time=utcnow().isoformat(),
    )


async def _notification_unread_count(session: AsyncSession, actor: User, notification_type: str | None = None) -> int:
    """COUNT agregado (nao uma lista carregada e contada em Python) — mesma
    regra de visibilidade de conversas finalizadas usada no total de chat.
    notification_type opcional filtra por tipo (ex.: so MENCAO, pro resumo
    de mencoes da ETAPA 6) sem duplicar a regra de visibilidade em dois
    lugares diferentes."""
    stmt = (
        select(func.count())
        .select_from(ChatNotification)
        .join(ChatConversation, ChatConversation.id == ChatNotification.conversation_id)
        .where(ChatNotification.user_id == actor.id, ChatNotification.read_at.is_(None))
    )
    if notification_type is not None:
        stmt = stmt.where(ChatNotification.notification_type == notification_type)
    if not actor_can_view_finalized(actor):
        stmt = stmt.where(ChatConversation.status != "FINALIZADA")
    return int((await session.execute(stmt)).scalar_one())


async def list_notifications(
    session: AsyncSession, actor: User, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> NotificationList:
    """ETAPA 10: listagem paginada pra Central de Notificacoes. `status="unread"`
    filtra read_at IS NULL (mesma semantica do filtro "Nao lidas"); qualquer
    outro valor (None/"all") lista tudo. Igual a `_notification_unread_count`/
    `unread_summary`, esconde conversas FINALIZADA de quem nao tem
    CHAT_VIEW_FINALIZED -- sem esse guard, uma Notification antiga continuaria
    vazando corpo de mensagem/autor de uma conversa que o usuario nao pode
    mais ver."""
    await _ensure_overdue_notifications(session, actor)

    count_stmt = (
        select(func.count())
        .select_from(ChatNotification)
        .join(ChatConversation, ChatConversation.id == ChatNotification.conversation_id)
        .where(ChatNotification.user_id == actor.id)
    )
    if status == "unread":
        count_stmt = count_stmt.where(ChatNotification.read_at.is_(None))
    if not actor_can_view_finalized(actor):
        count_stmt = count_stmt.where(ChatConversation.status != "FINALIZADA")
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        select(ChatNotification, ChatMessage, ChatConversation, Proposal)
        .select_from(ChatNotification)
        .join(ChatMessage, ChatMessage.id == ChatNotification.message_id)
        .join(ChatConversation, ChatConversation.id == ChatNotification.conversation_id)
        .outerjoin(Proposal, Proposal.id == ChatConversation.proposal_id)
        .where(ChatNotification.user_id == actor.id)
    )
    if status == "unread":
        stmt = stmt.where(ChatNotification.read_at.is_(None))
    if not actor_can_view_finalized(actor):
        stmt = stmt.where(ChatConversation.status != "FINALIZADA")
    # ETAPA 9-style desempate por id: created_at sozinho nao garante ordem
    # deterministica entre notificacoes com timestamp igual/muito proximo.
    stmt = stmt.order_by(ChatNotification.created_at.desc(), ChatNotification.id.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
    author_ids = {message.author_user_id for _notification, message, _conversation, _proposal in rows if message.author_user_id}
    users_by_id = await _users_by_id(session, author_ids)

    items = []
    for notification, message, conversation, proposal in rows:
        try:
            author = users_by_id.get(message.author_user_id) if message.author_user_id else None
            items.append(
                NotificationOut(
                    id=notification.id,
                    notification_type=notification.notification_type,
                    priority=NOTIFICATION_PRIORITIES.get(notification.notification_type, "normal"),
                    conversation_id=conversation.id,
                    kind=conversation.kind,
                    proposal_id=conversation.proposal_id,
                    proposal_number=proposal.proposal_number if proposal else None,
                    customer_name=proposal.customer_name if proposal else None,
                    message_id=message.id,
                    message_body=message.body,
                    question_status=message.question_status,
                    area=message.area,
                    author_name=author.display_name if author else None,
                    created_at=notification.created_at,
                    read_at=notification.read_at,
                )
            )
        except Exception:
            logger.exception("Notificacao invalida na listagem: notification_id=%r", notification.id)

    has_more = offset + len(rows) < total
    return NotificationList(items=items, total=total, has_more=has_more)


async def mark_all_notifications_read(session: AsyncSession, actor: User) -> int:
    result = await session.execute(
        update(ChatNotification)
        .where(ChatNotification.user_id == actor.id, ChatNotification.read_at.is_(None))
        .values(read_at=func.now())
    )
    await session.commit()
    rowcount = int(result.rowcount or 0)
    if rowcount > 0:
        # ETAPA 10: um evento agregado so -- nao precisa listar centenas de
        # notification_id pras outras conexoes do mesmo usuario, elas so
        # reconciliam buscando o estado atual via REST.
        await _publish_user_event(actor.id, "notification.read_all", {})
    return rowcount


SECTOR_MODULE_LABELS = {
    "production": "Producao",
    "galvanization": "Galvanizacao",
    "expedition": "Expedicao",
    "fiscal": "Fiscal",
}


def _primary_sector(user: User) -> str | None:
    """Nao existe campo de setor no cadastro de usuario — deriva um rotulo
    apenas quando o usuario tem permissao de exatamente uma area operacional
    especifica, pra nao arriscar mostrar um setor errado."""
    modules = {
        permission.module
        for role in user.roles
        for permission in role.permissions
        if permission.module in SECTOR_MODULE_LABELS
    }
    if len(modules) == 1:
        return SECTOR_MODULE_LABELS[next(iter(modules))]
    return None


async def list_mentionable_users(session: AsyncSession, search: str | None = None) -> MentionableUserList:
    rows = (await session.execute(select(User).where(User.active.is_(True)).order_by(User.display_name))).scalars().all()
    # so oferece no autocomplete quem realmente pode ser mencionado — mesma
    # regra que post_message ja valida no envio (CHAT_VIEW), pra nao deixar
    # o usuario escolher alguem que so vai ser rejeitado depois com um 422.
    rows = [user for user in rows if user_has_permission(user, CHAT_VIEW)]
    normalized = (search or "").strip().lower()
    if normalized:
        rows = [user for user in rows if normalized in user.display_name.lower() or normalized in user.username.lower()]
    online_ids = ws_manager.online_user_ids()
    return MentionableUserList(
        items=[
            MentionableUserOut(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                sector=_primary_sector(user),
                is_online=user.id in online_ids,
                avatar_available=bool(user.avatar_bytes),
            )
            for user in rows
        ]
    )
