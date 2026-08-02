from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.core.config import API_STAGE, API_VERSION, SERVICE_NAME, get_settings
from api.app.core.exceptions import install_exception_handlers
from api.app.core.logging import AccessLogMiddleware, configure_logging
from api.app.database.session import dispose_engine
from api.app.modules.auth.router import router as auth_router
from api.app.modules.chat.router import router as chat_router
from api.app.modules.roles.router import router as roles_router
from api.app.modules.nomus_integration.router import router as nomus_integration_router
from api.app.modules.proposal_import.router import router as proposal_import_router
from api.app.modules.proposals.router import router as proposals_router
from api.app.modules.provisioning.router import router as provisioning_router
from api.app.modules.security_events.router import router as security_events_router
from api.app.modules.system.router import router as system_router
from api.app.modules.users.router import router as users_router
from api.app.shared.request_context import RequestIdMiddleware
from api.app.modules.auth.bootstrap import ensure_default_admin

def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        logging.getLogger("api.lifecycle").info(
            "api_started service=%s version=%s stage=%s env=%s",
            SERVICE_NAME,
            API_VERSION,
            API_STAGE,
            settings.app_env,
        )
        await ensure_default_admin()
        yield
        await dispose_engine()
        logging.getLogger("api.lifecycle").info("api_stopped service=%s", SERVICE_NAME)

    application = FastAPI(
        title="Controle de Producao API",
        version=API_VERSION,
        description="Fundacao da API do Sistema de Controle de Producao.",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(RequestIdMiddleware)
    install_exception_handlers(application)
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")
    application.include_router(roles_router, prefix="/api/v1")
    application.include_router(security_events_router, prefix="/api/v1")
    application.include_router(proposals_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(proposal_import_router, prefix="/api/v1")
    application.include_router(nomus_integration_router, prefix="/api/v1")
    application.include_router(provisioning_router, prefix="/api/v1")

    return application


app = create_app()
