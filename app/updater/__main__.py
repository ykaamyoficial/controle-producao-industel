"""Entry point do Updater (Fase 10) -- componente SEPARADO do Desktop
principal, empacotavel como Updater.exe (ver Updater.spec).

Uso:
    python -m app.updater --request <caminho-para-request.json> [--allow-force-close]

O Desktop escreve o UpdateRequest em um arquivo JSON temporario seguro e
inicia este processo de forma independente (Secao 7/9) -- nenhum outro
argumento solto e aceito alem do caminho do arquivo e das poucas flags de
politica explicitas abaixo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.updater.contract import InvalidUpdateRequestError, UpdateRequest
from app.updater.exceptions import ConcurrentUpdateError, UpdateFailedError, UpdaterError
from app.updater.journal_store import UpdateJournalStore
from app.updater.orchestrator import OrchestratorConfig, UpdaterOrchestrator
from app.updater.paths import backup_dir, download_dir, ensure_updater_dirs, journal_dir, lock_path, staging_dir, updater_logs_dir

LOGGER_NAME = "controle_producao.updater"


def _configure_logging() -> logging.Logger:
    """Log tecnico proprio do Updater (Secao 3), separado do log do Desktop
    para os dois processos nunca disputarem o mesmo arquivo rotacionado."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    ensure_updater_dirs()
    handler = RotatingFileHandler(updater_logs_dir() / "updater.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Updater do Desktop (Fase 10) -- componente separado.")
    parser.add_argument("--request", required=True, help="Caminho do arquivo JSON com o UpdateRequest.")
    parser.add_argument(
        "--allow-force-close", action="store_true",
        help="Permite encerrar o Desktop a forca se ele nao sair dentro do timeout (politica explicita, Secao 18 -- nunca o padrao).",
    )
    parser.add_argument("--app-exit-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--handshake-timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    log = _configure_logging()

    try:
        request = UpdateRequest.load(Path(args.request))
    except (OSError, ValueError, KeyError) as exc:
        log.error("update_request_load_failed | erro=%s", exc)
        print(f"ERRO: nao foi possivel ler o UpdateRequest: {exc}")
        return 1

    store = UpdateJournalStore(journal_dir())
    config = OrchestratorConfig(
        app_exit_timeout_seconds=args.app_exit_timeout_seconds,
        handshake_timeout_seconds=args.handshake_timeout_seconds,
        allow_force_close=args.allow_force_close,
    )
    orchestrator = UpdaterOrchestrator(journal_store=store, lock_path=lock_path(), config=config)

    try:
        recovered = orchestrator.recover_incomplete_update(request=request)
        if recovered is not None:
            log.warning("update_recovery_applied | request_id=%s | resolved_state=%s", recovered.request_id, recovered.state.value)
    except Exception:
        log.exception("update_recovery_unexpected_error")

    try:
        journal = orchestrator.run_update(
            request,
            download_dir=download_dir(request.request_id),
            staging_dir=staging_dir(request.request_id),
            backup_dir=backup_dir(request.request_id),
        )
    except InvalidUpdateRequestError as exc:
        log.error("update_request_invalid | erro=%s", exc)
        print(f"ERRO: request invalido: {exc}")
        return 1
    except ConcurrentUpdateError as exc:
        log.error("update_concurrent_rejected | erro=%s", exc)
        print(f"ERRO: outra atualizacao ja esta em andamento: {exc}")
        return 1
    except UpdateFailedError as exc:
        log.error("update_failed | request_id=%s | state=%s | erro=%s", request.request_id, exc.journal.state.value, exc)
        print(f"FALHA: {exc}")
        print(f"estado_final={exc.journal.state.value}")
        return 1
    except UpdaterError as exc:
        log.exception("update_unexpected_error | request_id=%s", request.request_id)
        print(f"ERRO: {exc}")
        return 1

    print(f"SUCESSO: estado_final={journal.state.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
