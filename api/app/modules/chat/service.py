from __future__ import annotations

from sqlalchemy import and_, func, literal, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.app.core import error_codes
from api.app.core.exceptions import ApiError, PermissionDeniedError
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import CHAT_VIEW_FINALIZED
from api.app.modules.auth.service import effective_permissions
from api.app.modules.chat.models import ChatConversation, ChatMessage, ChatMessageRead, ChatNotification
from api.app.modules.chat.schemas import (
    ConversationOut,
    ConversationList,
    ConversationUnread,
    MentionableUserList,
    MentionableUserOut,
    MessageCreate,
    MessageList,
    MessageOut,
    NotificationList,
    NotificationOut,
    TimelineEntry,
    TimelineList,
    UnreadSummary,
)
from api.app.modules.proposals import service as proposals_service
from api.app.modules.proposals.models import (
    ExpeditionEvent,
    FiscalEvent,
    FiscalRecord,
    GalvanizationLoadEvent,
    Proposal,
    ProposalEvent,
)
from api.app.modules.proposals.service import _history_observation


HISTORY_ITEMS_PER_PROPOSAL_LIMIT = 200


GENERAL_CHAT_KIND = "GERAL"
PROPOSAL_CHAT_KIND = "PROPOSTA"


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


def _message_out(message: ChatMessage, users_by_id: dict[int, User], seen_by_count: int = 0) -> MessageOut:
    author = users_by_id.get(message.author_user_id) if message.author_user_id else None
    mentioned = users_by_id.get(message.mentioned_user_id) if message.mentioned_user_id else None
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        author_user_id=message.author_user_id,
        author_name=author.display_name if author else None,
        message_type=message.message_type,
        body=message.body,
        mentioned_user_id=message.mentioned_user_id,
        mentioned_user_name=mentioned.display_name if mentioned else None,
        question_status=message.question_status,
        answered_message_id=message.answered_message_id,
        created_at=message.created_at,
        seen_by_count=seen_by_count,
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
) -> ChatMessage:
    message = ChatMessage(
        conversation_id=conversation.id,
        author_user_id=actor.id,
        message_type=message_type,
        body=body,
        mentioned_user_id=mentioned_user_id,
        question_status="AGUARDANDO_RESPOSTA" if message_type == "PERGUNTA" else None,
        answered_message_id=answered_message_id,
    )
    session.add(message)
    conversation.last_activity_at = func.now()
    await session.flush()
    await _create_notifications(session, conversation, message, actor)
    return message


async def _create_notifications(session: AsyncSession, conversation: ChatConversation, message: ChatMessage, actor: User) -> None:
    if conversation.kind == GENERAL_CHAT_KIND:
        return
    if message.message_type == "PERGUNTA":
        recipient_ids = {message.mentioned_user_id} if message.mentioned_user_id else set()
        notification_type = "MENCAO"
    else:
        participant_ids = set(
            (
                await session.execute(
                    select(ChatMessage.author_user_id).where(
                        ChatMessage.conversation_id == conversation.id,
                        ChatMessage.author_user_id.is_not(None),
                    )
                )
            ).scalars().all()
        )
        recipient_ids = participant_ids - {actor.id}
        notification_type = "MENSAGEM"
    for user_id in recipient_ids:
        if not user_id:
            continue
        session.add(
            ChatNotification(
                user_id=user_id,
                conversation_id=conversation.id,
                message_id=message.id,
                notification_type=notification_type,
            )
        )


async def post_message(session: AsyncSession, conversation_id: int, actor: User, payload: MessageCreate) -> MessageOut:
    conversation = await get_conversation(session, conversation_id)
    if conversation.status == "FINALIZADA":
        raise ApiError(error_codes.CHAT_CONVERSATION_FINALIZED, "Esta conversa esta finalizada e nao aceita novas mensagens.", status_code=409)
    body = payload.body.strip()
    if not body:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "A mensagem nao pode ser vazia.", status_code=422)

    mentioned_user_id: int | None = None
    if payload.message_type == "PERGUNTA":
        mentioned_user_id = payload.mentioned_user_id
        if not mentioned_user_id:
            raise ApiError(error_codes.CHAT_MENTION_REQUIRED, "Selecione o destinatario da pergunta.", status_code=422)
        mentioned_user = await session.get(User, mentioned_user_id)
        if mentioned_user is None or not mentioned_user.active:
            raise ApiError(error_codes.CHAT_MENTIONED_USER_INVALID, "Usuario mencionado invalido.", status_code=422)

    message = await _create_message(session, conversation, actor, body=body, message_type=payload.message_type, mentioned_user_id=mentioned_user_id)
    await session.commit()
    await session.refresh(message)
    users_by_id = await _users_by_id(session, {message.author_user_id, message.mentioned_user_id})
    return _message_out(message, users_by_id)


async def answer_question(session: AsyncSession, question_message_id: int, actor: User, body: str) -> MessageOut:
    question = await session.get(ChatMessage, question_message_id)
    if question is None or question.message_type != "PERGUNTA":
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Pergunta nao encontrada.", status_code=404)
    if question.question_status == "RESPONDIDA":
        raise ApiError(error_codes.CHAT_QUESTION_ALREADY_ANSWERED, "Esta pergunta ja foi respondida.", status_code=409)
    conversation = await get_conversation(session, question.conversation_id)
    if conversation.status == "FINALIZADA":
        raise ApiError(error_codes.CHAT_CONVERSATION_FINALIZED, "Esta conversa esta finalizada e nao aceita novas mensagens.", status_code=409)
    stripped = (body or "").strip()
    if not stripped:
        raise ApiError(error_codes.CHAT_MESSAGE_INVALID, "A resposta nao pode ser vazia.", status_code=422)

    answer = await _create_message(session, conversation, actor, body=stripped, message_type="MENSAGEM", answered_message_id=question.id)
    question.question_status = "RESPONDIDA"
    await session.commit()
    await session.refresh(answer)
    users_by_id = await _users_by_id(session, {answer.author_user_id, answer.mentioned_user_id})
    return _message_out(answer, users_by_id)


async def list_messages(session: AsyncSession, conversation_id: int, actor: User, limit: int = 200, offset: int = 0) -> MessageList:
    conversation = await get_conversation(session, conversation_id)
    _ensure_can_view_conversation(actor, conversation)
    total = int(
        (await session.execute(select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conversation.id))).scalar_one()
    )
    rows = (
        await session.execute(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at).limit(limit).offset(offset)
        )
    ).scalars().all()
    ids: set[int | None] = set()
    for row in rows:
        ids.add(row.author_user_id)
        ids.add(row.mentioned_user_id)
    users_by_id = await _users_by_id(session, ids)
    seen_by_message = await _seen_counts(session, rows)
    return MessageList(items=[_message_out(row, users_by_id, seen_by_message.get(row.id, 0)) for row in rows], total=total)


async def get_proposal_timeline(session: AsyncSession, proposal_id: int, actor: User) -> TimelineList:
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
                    .where(ChatMessage.conversation_id == conversation.id)
                    .order_by(ChatMessage.created_at.desc())
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
                question_status=message.question_status,
                body=message.body,
                created_at=message.created_at,
                seen_by_count=seen_by_message.get(message.id, 0),
            )
        )

    history = await proposals_service.list_proposal_history(session, proposal_id=proposal_id, limit=5000, offset=0)
    for item in history:
        entries.append(
            TimelineEntry(
                id=item.id,
                source=item.source,
                entry_kind="OBSERVACAO" if item.observation else "EVENTO_SISTEMA",
                author_user_id=item.actor_user_id,
                author_name=item.actor_name,
                body=item.observation,
                area=item.area,
                event_type=item.event_type,
                from_status=item.from_status,
                to_status=item.to_status,
                created_at=item.created_at,
            )
        )

    entries.sort(key=lambda entry: entry.created_at)
    return TimelineList(conversation_id=conversation.id, items=entries)


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
            .over(partition_by=ChatMessage.conversation_id, order_by=ChatMessage.created_at.desc())
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
    limit: int = 50,
    offset: int = 0,
) -> ConversationList:
    await get_or_create_general_chat(session)
    await session.commit()

    stmt = select(ChatConversation, Proposal).select_from(ChatConversation).outerjoin(Proposal, Proposal.id == ChatConversation.proposal_id)
    if status:
        stmt = stmt.where(ChatConversation.status == status)
    rows = (await session.execute(stmt)).all()

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
    filtered.sort(key=lambda pair: (pair[0].kind != GENERAL_CHAT_KIND, -pair[0].last_activity_at.timestamp()))

    total = len(filtered)
    page = filtered[offset : offset + limit]
    page_conversation_ids = [conversation.id for conversation, _ in page]
    last_message_by_conversation = await _last_messages(session, page_conversation_ids)
    author_ids = {message.author_user_id for message in last_message_by_conversation.values() if message.author_user_id}
    authors_by_id = await _users_by_id(session, author_ids)

    items = []
    for conversation, proposal in page:
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
            )
        )
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


async def mark_read(session: AsyncSession, conversation_id: int, actor: User, last_read_message_id: int) -> None:
    conversation = await get_conversation(session, conversation_id)
    message = await session.get(ChatMessage, last_read_message_id)
    if message is None or message.conversation_id != conversation.id:
        raise ApiError(error_codes.CHAT_MESSAGE_NOT_FOUND, "Mensagem informada nao pertence a esta conversa.", status_code=404)

    read = (
        await session.execute(
            select(ChatMessageRead).where(ChatMessageRead.conversation_id == conversation.id, ChatMessageRead.user_id == actor.id)
        )
    ).scalars().first()
    if read is None:
        session.add(ChatMessageRead(conversation_id=conversation.id, user_id=actor.id, last_read_message_id=last_read_message_id))
    elif (read.last_read_message_id or 0) < last_read_message_id:
        read.last_read_message_id = last_read_message_id
        read.updated_at = func.now()
    await session.commit()


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


async def _recent_history_by_proposal(session: AsyncSession, proposal_ids: list[int], *, per_proposal_limit: int = HISTORY_ITEMS_PER_PROPOSAL_LIMIT):
    """Busca, em consultas fixas (uma por tabela de evento, nunca uma por
    proposta), os `per_proposal_limit` eventos mais recentes de CADA
    proposta — os mesmos 4 tipos de evento e o mesmo criterio de ordenacao
    e corte que proposals_service.list_proposal_history usa para uma unica
    proposta, so que aplicados a todas de uma vez via UNION ALL + ROW_NUMBER
    particionado por proposal_id. Retorna um dict proposal_id -> lista de
    linhas (id, proposal_id, source, created_at, metadata_, actor_user_id,
    area), da mais recente para a mais antiga."""
    if not proposal_ids:
        return {}

    proposal_q = select(
        ProposalEvent.id.label("id"),
        ProposalEvent.proposal_id.label("proposal_id"),
        literal("proposal").label("source"),
        ProposalEvent.created_at.label("created_at"),
        ProposalEvent.metadata_.label("metadata_"),
        ProposalEvent.actor_user_id.label("actor_user_id"),
        func.coalesce(ProposalEvent.to_area, ProposalEvent.from_area).label("area"),
    ).where(ProposalEvent.proposal_id.in_(proposal_ids))

    expedition_q = select(
        ExpeditionEvent.id.label("id"),
        ExpeditionEvent.proposal_id.label("proposal_id"),
        literal("expedition").label("source"),
        ExpeditionEvent.created_at.label("created_at"),
        ExpeditionEvent.metadata_.label("metadata_"),
        ExpeditionEvent.actor_user_id.label("actor_user_id"),
        literal("EXPEDICAO").label("area"),
    ).where(ExpeditionEvent.proposal_id.in_(proposal_ids))

    galvanization_q = select(
        GalvanizationLoadEvent.id.label("id"),
        GalvanizationLoadEvent.proposal_id.label("proposal_id"),
        literal("galvanization").label("source"),
        GalvanizationLoadEvent.created_at.label("created_at"),
        GalvanizationLoadEvent.metadata_.label("metadata_"),
        GalvanizationLoadEvent.actor_user_id.label("actor_user_id"),
        literal("GALVANIZACAO").label("area"),
    ).where(GalvanizationLoadEvent.proposal_id.in_(proposal_ids))

    # join com fiscal_records (nao um indice novo em fiscal_events) para
    # reaproveitar os indices ja existentes em uq_fiscal_records_proposal e
    # ix_fiscal_events_record_created, igual list_proposal_history ja faz.
    fiscal_q = (
        select(
            FiscalEvent.id.label("id"),
            FiscalRecord.proposal_id.label("proposal_id"),
            literal("fiscal").label("source"),
            FiscalEvent.created_at.label("created_at"),
            FiscalEvent.metadata_.label("metadata_"),
            FiscalEvent.actor_user_id.label("actor_user_id"),
            literal("FISCAL").label("area"),
        )
        .select_from(FiscalEvent)
        .join(FiscalRecord, FiscalRecord.id == FiscalEvent.fiscal_record_id)
        .where(FiscalRecord.proposal_id.in_(proposal_ids))
    )

    combined = union_all(proposal_q, expedition_q, galvanization_q, fiscal_q).subquery("combined_history")
    ranked = select(
        combined,
        func.row_number()
        .over(
            partition_by=combined.c.proposal_id,
            order_by=(combined.c.created_at.desc(), combined.c.source.desc(), combined.c.id.desc()),
        )
        .label("rn"),
    ).subquery("ranked_history")

    rows = (
        await session.execute(
            select(ranked).where(ranked.c.rn <= per_proposal_limit).order_by(ranked.c.proposal_id, ranked.c.created_at.desc())
        )
    ).all()

    result: dict[int, list] = {}
    for row in rows:
        result.setdefault(row.proposal_id, []).append(row)
    return result


async def _new_observation_entries(session: AsyncSession, actor: User, conversations: list[ChatConversation]) -> list[dict]:
    """Observacoes de area publicadas depois da ultima vez que o usuario abriu
    aquela conversa. Nao existe uma tabela propria para isso: reaproveita o
    mesmo conjunto de eventos que a Timeline usa (_recent_history_by_proposal,
    equivalente em lote a proposals_service.list_proposal_history) e a mesma
    regra de extracao de observacao (_history_observation), comparando contra
    o cursor de leitura (ChatMessageRead.updated_at) que ja existe."""
    proposal_conversations = [c for c in conversations if c.kind == PROPOSAL_CHAT_KIND and c.proposal_id]
    if not proposal_conversations:
        return []
    conversation_by_proposal = {c.proposal_id: c for c in proposal_conversations}
    conversation_ids = [c.id for c in proposal_conversations]
    reads = (
        await session.execute(
            select(ChatMessageRead).where(ChatMessageRead.user_id == actor.id, ChatMessageRead.conversation_id.in_(conversation_ids))
        )
    ).scalars().all()
    last_seen_by_conversation = {read.conversation_id: read.updated_at for read in reads}

    # so proposta cujo chat o usuario ja abriu pelo menos uma vez entra na
    # busca (sem isso nao ha "ultima vez visto" pra comparar).
    relevant_proposal_ids = [
        proposal_id
        for proposal_id, conversation in conversation_by_proposal.items()
        if last_seen_by_conversation.get(conversation.id) is not None
    ]
    if not relevant_proposal_ids:
        return []

    history_by_proposal = await _recent_history_by_proposal(session, relevant_proposal_ids)

    actor_ids = {row.actor_user_id for rows in history_by_proposal.values() for row in rows if row.actor_user_id}
    users_by_id = await _users_by_id(session, actor_ids)

    entries: list[dict] = []
    for proposal_id in relevant_proposal_ids:
        conversation = conversation_by_proposal[proposal_id]
        last_seen_at = last_seen_by_conversation[conversation.id]
        for item in history_by_proposal.get(proposal_id, []):
            metadata = item.metadata_ if isinstance(item.metadata_, dict) else {}
            observation = _history_observation(metadata)
            if not observation or item.created_at <= last_seen_at:
                continue
            actor_row = users_by_id.get(item.actor_user_id) if item.actor_user_id else None
            entries.append(
                {
                    "notification_type": "OBSERVACAO",
                    "conversation_id": conversation.id,
                    "kind": conversation.kind,
                    "proposal_id": proposal_id,
                    "message_id": None,
                    "message_body": observation,
                    "area": item.area,
                    "author_name": actor_row.display_name if actor_row else None,
                    "created_at": item.created_at,
                    "read_at": None,
                }
            )
    return entries


async def unread_summary(session: AsyncSession, actor: User) -> UnreadSummary:
    conversations = (await session.execute(select(ChatConversation))).scalars().all()
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
    new_observations = len(await _new_observation_entries(session, actor, conversations))
    return UnreadSummary(total_unread=total, conversations=entries, pending_questions=pending_questions, new_observations=new_observations)


async def list_notifications(session: AsyncSession, actor: User, *, limit: int = 50, offset: int = 0) -> NotificationList:
    stmt = (
        select(ChatNotification, ChatMessage, ChatConversation, Proposal)
        .select_from(ChatNotification)
        .join(ChatMessage, ChatMessage.id == ChatNotification.message_id)
        .join(ChatConversation, ChatConversation.id == ChatNotification.conversation_id)
        .outerjoin(Proposal, Proposal.id == ChatConversation.proposal_id)
        .where(ChatNotification.user_id == actor.id)
        .order_by(ChatNotification.created_at.desc())
        .limit(max(limit, 200))
    )
    rows = (await session.execute(stmt)).all()
    author_ids = {message.author_user_id for _notification, message, _conversation, _proposal in rows if message.author_user_id}
    users_by_id = await _users_by_id(session, author_ids)

    real_items = []
    for notification, message, conversation, proposal in rows:
        author = users_by_id.get(message.author_user_id) if message.author_user_id else None
        real_items.append(
            NotificationOut(
                id=notification.id,
                notification_type=notification.notification_type,
                conversation_id=conversation.id,
                kind=conversation.kind,
                proposal_id=conversation.proposal_id,
                proposal_number=proposal.proposal_number if proposal else None,
                message_id=message.id,
                message_body=message.body,
                author_name=author.display_name if author else None,
                created_at=notification.created_at,
                read_at=notification.read_at,
            )
        )

    all_conversations = (await session.execute(select(ChatConversation))).scalars().all()
    observation_entries = await _new_observation_entries(session, actor, all_conversations)
    proposal_ids = {entry["proposal_id"] for entry in observation_entries if entry.get("proposal_id")}
    proposals_by_id: dict[int, Proposal] = {}
    if proposal_ids:
        proposal_rows = (await session.execute(select(Proposal).where(Proposal.id.in_(proposal_ids)))).scalars().all()
        proposals_by_id = {row.id: row for row in proposal_rows}
    observation_items = [
        NotificationOut(
            id=-(index + 1),
            notification_type=entry["notification_type"],
            conversation_id=entry["conversation_id"],
            kind=entry["kind"],
            proposal_id=entry["proposal_id"],
            proposal_number=(proposals_by_id.get(entry["proposal_id"]).proposal_number if entry.get("proposal_id") in proposals_by_id else None),
            message_id=entry["message_id"],
            message_body=entry["message_body"],
            area=entry["area"],
            author_name=entry["author_name"],
            created_at=entry["created_at"],
            read_at=entry["read_at"],
        )
        for index, entry in enumerate(observation_entries)
    ]

    merged = sorted(real_items + observation_items, key=lambda item: item.created_at, reverse=True)
    total = len(merged)
    page = merged[offset : offset + limit]
    return NotificationList(items=page, total=total)


async def mark_all_notifications_read(session: AsyncSession, actor: User) -> int:
    result = await session.execute(
        update(ChatNotification)
        .where(ChatNotification.user_id == actor.id, ChatNotification.read_at.is_(None))
        .values(read_at=func.now())
    )
    await session.commit()
    return int(result.rowcount or 0)


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
    normalized = (search or "").strip().lower()
    if normalized:
        rows = [user for user in rows if normalized in user.display_name.lower() or normalized in user.username.lower()]
    return MentionableUserList(
        items=[
            MentionableUserOut(id=user.id, username=user.username, display_name=user.display_name, sector=_primary_sector(user))
            for user in rows
        ]
    )
