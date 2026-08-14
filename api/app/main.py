from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.audit import service as audit_service
from api.app.core.config import API_STAGE, API_VERSION, SERVICE_NAME, get_settings
from api.app.core.client_version_middleware import ClientVersionMiddleware
from api.app.core.exceptions import install_exception_handlers
from api.app.core.logging import AccessLogMiddleware, configure_logging
from api.app.core.versioning import get_api_contract_version, get_database_schema_version
from api.app.database.session import dispose_engine
from api.app.health.checks.database import run_database_and_schema_checks
from api.app.maintenance.middleware import MaintenanceMiddleware
from api.app.maintenance.service import build_default_service as build_default_maintenance_service
from api.app.modules.auth.router import router as auth_router
from api.app.modules.channels.router import router as channels_router
from api.app.modules.chat.router import router as chat_router
from api.app.modules.health.router import router as health_router
from api.app.modules.maintenance.router import router as maintenance_admin_router
from api.app.modules.roles.router import router as roles_router
from api.app.modules.nomus_integration.router import router as nomus_integration_router
from api.app.modules.proposal_import.router import router as proposal_import_router
from api.app.modules.proposals.router import router as proposals_router
from api.app.modules.provisioning.router import router as provisioning_router
from api.app.modules.security_events.router import router as security_events_router
from api.app.modules.system.router import router as system_router
from api.app.modules.update_audit.router import router as update_audit_router
from api.app.modules.users.router import router as users_router
from api.app.shared.request_context import RequestIdMiddleware
from api.app.modules.auth.bootstrap import ensure_default_admin, sync_official_permissions
from api.app.updates import service as update_distribution_service
from api.app.updates.router import router as updates_router

def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        logging.getLogger("api.lifecycle").info(
            "api_started service=%s version=%s stage=%s contract=%s schema=%s env=%s commit=%s build_time=%s",
            SERVICE_NAME,
            API_VERSION,
            API_STAGE,
            get_api_contract_version(),
            get_database_schema_version(),
            settings.app_env,
            settings.build_commit_sha,
            settings.build_time_utc or "unknown",
        )
        # Fase 1 - Servidor e Endereco Oficial da API (Secao 13): registra onde o
        # processo esta de fato escutando, para diferenciar no log um bind local
        # (127.0.0.1, so a propria maquina) de um bind acessivel pela LAN
        # (0.0.0.0, publicado pelo host conforme docker-compose.prod.yml).
        logging.getLogger("api.lifecycle").info(
            "api_listening host=%s port=%s", settings.api_host, settings.api_port,
        )
        try:
            _database_result, _schema_result, raw_check = await run_database_and_schema_checks()
            logging.getLogger("api.lifecycle").info(
                "api_postgresql_status status=%s", raw_check.status,
            )
        except Exception:
            logging.getLogger("api.lifecycle").exception("api_postgresql_status_check_failed")

        await sync_official_permissions()
        await ensure_default_admin()
        recovered = update_distribution_service.recover_incomplete_staging()
        if recovered:
            logging.getLogger("api.updates").warning("release_staging_recovered_on_startup count=%s", len(recovered))
        # Maintenance Mode (Fase 14, Secao 9): carrega o estado persistido no
        # startup -- nunca assume OFF por default. Se o arquivo indicar
        # ACTIVE/RECOVERY, a operacao de negocio continua bloqueada apos o
        # reinicio; se estiver corrompido, MaintenanceService ja aplica o
        # fallback conservador (ACTIVE) e registra MAINTENANCE_STATE_LOAD_FAILED.
        maintenance_state = build_default_maintenance_service().get_state()
        logging.getLogger("api.maintenance").info(
            "MAINTENANCE_STATE_LOADED_ON_STARTUP | state=%s | maintenance_id=%s",
            maintenance_state.state.value, maintenance_state.maintenance_id,
        )

        # Auditoria de atualizacoes (Fase 16, Secao 18): drena o spool local
        # assim que o processo sobe (cobre eventos gravados enquanto a API
        # estava fora do ar/em migration) e continua drenando perto de
        # tempo real por um timer periodico -- nunca perde
        # MAINTENANCE/DEPLOYMENT_FAILED so porque o Postgres estava
        # indisponivel no momento exato do evento.
        audit_log = logging.getLogger("api.audit")
        try:
            drained_on_startup = await audit_service.drain_spool_to_database()
            if drained_on_startup:
                audit_log.info("AUDIT_SPOOL_DRAINED_ON_STARTUP count=%s", drained_on_startup)
        except Exception:
            audit_log.exception("AUDIT_SPOOL_DRAIN_ON_STARTUP_FAILED")

        async def _periodic_drain() -> None:
            interval = settings.audit_drain_interval_seconds
            while True:
                try:
                    await asyncio.sleep(interval)
                    drained = await audit_service.drain_spool_to_database()
                    if drained:
                        audit_log.info("AUDIT_SPOOL_DRAINED count=%s", drained)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    audit_log.exception("AUDIT_SPOOL_PERIODIC_DRAIN_FAILED")

        drain_task = asyncio.create_task(_periodic_drain())

        yield

        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass
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

    # MaintenanceMiddleware/ClientVersionMiddleware ficam DENTRO de
    # AccessLog/RequestId (adicionados primeiro -- Starlette empilha o
    # ULTIMO add_middleware como o mais externo): RequestId ja preencheu
    # request.state.request_id e o AccessLog ainda registra a requisicao
    # mesmo quando bloqueada por manutencao (Fase 14, Secao 15) ou por
    # versao de cliente desatualizada (Fase 6, Secao 10/11).
    application.add_middleware(MaintenanceMiddleware)
    application.add_middleware(ClientVersionMiddleware)
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(RequestIdMiddleware)
    install_exception_handlers(application)
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(maintenance_admin_router, prefix="/api/v1")
    application.include_router(channels_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")
    application.include_router(roles_router, prefix="/api/v1")
    application.include_router(security_events_router, prefix="/api/v1")
    application.include_router(proposals_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(proposal_import_router, prefix="/api/v1")
    application.include_router(nomus_integration_router, prefix="/api/v1")
    application.include_router(provisioning_router, prefix="/api/v1")
    application.include_router(updates_router, prefix="/api/v1")
    application.include_router(update_audit_router, prefix="/api/v1")

    return application


app = create_app()
