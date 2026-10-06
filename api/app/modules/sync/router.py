from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import get_current_active_user, get_current_user_ws
from api.app.modules.auth.models import User
from api.app.modules.sync import service
from api.app.modules.sync.notifier import notifier
from api.app.modules.sync.schemas import SyncChangesResponse, SyncHead, SyncSnapshotResponse

router = APIRouter(tags=["sync"])

WS_LIVENESS_CHECK_SECONDS = 60


@router.get("/sync/head", response_model=SyncHead)
async def sync_head(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_head(session, actor)


@router.get("/sync/changes", response_model=SyncChangesResponse)
async def sync_changes(
    since: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_changes(session, actor, since=since, limit=limit)


@router.get("/sync/snapshot", response_model=SyncSnapshotResponse)
async def sync_snapshot(
    entity: str = Query(min_length=1, max_length=60),
    after_id: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_snapshot(session, actor, entity=entity, after_id=after_id, limit=limit)


@router.websocket("/sync/ws")
async def sync_websocket(websocket: WebSocket, session: AsyncSession = Depends(get_db_session)):
    """Aviso em tempo real de que o `seq` avancou; nenhum dado trafega aqui.

    Mesmo desenho de `/chat/ws`: autentica so no handshake e fecha com 4401
    quando o access token vence -- o Desktop reconecta com token novo. Ao
    conectar manda o `seq` atual, para o cliente saber na hora se esta
    atrasado."""
    auth = await get_current_user_ws(websocket, session)
    if auth is None:
        await websocket.close(code=4401)
        return
    actor, expires_at = auth
    head = await service.get_head(session, actor)
    # A conexao dura muito mais que uma requisicao: nao segurar conexao do pool.
    await session.close()
    await websocket.accept()
    notifier.register(websocket)
    try:
        await websocket.send_json({"type": "sync.head", "seq": head.seq})
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=WS_LIVENESS_CHECK_SECONDS)
            except asyncio.TimeoutError:
                if time.time() >= expires_at:
                    await websocket.close(code=4401)
                    break
    except WebSocketDisconnect:
        pass
    finally:
        notifier.unregister(websocket)
