from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.app_icon import app_icon, configure_windows_taskbar_icon
from app.services.app_logging import configure_logging, get_logger
from app.services.update_distribution_client import check_for_updates
from app.services.update_state import evaluate_pending_update
from app.versioning import get_desktop_version


log = get_logger("main")


def run_startup_update_check(
    parent=None,
    *,
    checker=check_for_updates,
    dialog_factory=None,
    timeout: int = 6,
) -> tuple[bool, bool]:
    """Checks for updates before the desktop starts the official API runtime.

    Returns (checked, update_launched). `update_launched` is True only when
    the user confirmed the optional update and UpdateCoordinator actually
    handed off to the Updater process (Fase 07: o fluxo opcional agora usa o
    mesmo orchestrator do fluxo obrigatorio) -- nesse caso o chamador nao
    deve abrir a MainWindow, pois o app precisa fechar para o Updater assumir."""
    pending = evaluate_pending_update()
    if pending.get("status") == "failed_or_incomplete":
        log.warning(
            "Atualizacao anterior nao concluida antes da abertura | destino=%s | iniciada=%s",
            pending.get("target_version"),
            pending.get("started_at"),
        )
        if parent is not None:
            QMessageBox.warning(
                parent,
                "Atualizacao nao concluida",
                "A ultima atualizacao foi iniciada, mas esta versao ainda nao mudou.\n\n"
                "O sistema vai continuar funcionando e voce podera tentar atualizar novamente.",
            )

    try:
        result = checker(timeout=timeout)
    except Exception:
        log.exception("Falha inesperada na verificacao inicial de atualizacao")
        return True, False

    if not result:
        return True, False

    if result.get("error"):
        log.warning(
            "Verificacao inicial de atualizacao indisponivel | tipo=%s | detalhe=%s",
            result.get("error_kind"),
            result.get("error"),
        )
        return True, False

    if not result.get("update_available"):
        return True, False

    try:
        if dialog_factory is None:
            from app.ui.update_dialog import UpdateDialog

            dialog_factory = UpdateDialog
        dialog = dialog_factory(result, parent)
        dialog.exec()
        return True, bool(getattr(dialog, "update_launched", False))
    except Exception:
        log.exception("Falha ao exibir dialogo inicial de atualizacao")
    return True, False


def run_startup_bootstrap(parent=None, *, dialog_factory=None, bootstrap_runner=None) -> bool:
    """Fase 3 - Primeiro Acesso Automatico: garante que existe um API_BASE_URL
    valido e alcancavel antes de qualquer outra verificacao de startup (que
    ja pressupoe uma API respondendo). Retorna False quando o usuario opta
    por sair sem configurar o servidor -- o chamador nao deve prosseguir.

    Tenta a conexao silenciosamente primeiro (sem abrir nenhuma janela): no
    caminho feliz -- configuracao ja persistida e servidor respondendo, que e
    o caso em praticamente toda abertura do app -- nao ha nenhum dialogo
    visivel nem atraso extra de UI. So constroi o FirstAccessDialog quando a
    tentativa silenciosa falha de fato, para o usuario poder agir.
    """
    from app.services.bootstrap_service import BootstrapState

    if bootstrap_runner is None:
        from app.integrations.api.config import DesktopApiConfigStore
        from app.services.bootstrap_service import run_bootstrap

        def bootstrap_runner():
            return run_bootstrap(config_store=DesktopApiConfigStore())

    try:
        result = bootstrap_runner()
    except Exception:
        log.exception("Falha inesperada na tentativa silenciosa de bootstrap")
        result = None

    if result is not None and result.state == BootstrapState.READY_FOR_LOGIN:
        return True

    if dialog_factory is None:
        from app.ui.first_access_dialog import FirstAccessDialog

        dialog_factory = FirstAccessDialog

    dialog = dialog_factory(parent)
    dialog.exec()
    return bool(getattr(dialog, "proceed", False))


def run_startup_compatibility_check(
    parent=None,
    *,
    config_store_factory=None,
    client_factory=None,
    check_runner=None,
    dialog_factory=None,
    maintenance_dialog_factory=None,
) -> tuple[bool, str | None]:
    """Verifica compatibilidade Desktop<->API antes de liberar o uso operacional (Fase 03).

    Retorna (proceed, update_available_message):
      - proceed=False bloqueia a inicializacao (o chamador nao deve construir a MainWindow).
      - update_available_message, quando presente, e um aviso nao bloqueante para exibir apos
        o login (versao local dentro do minimo suportado, porem abaixo da recomendada).

    So consulta a API se a integracao estiver habilitada nas configuracoes do desktop
    (settings.enabled); caso contrario, o fluxo de login existente ja trata e informa a API
    desativada com sua propria mensagem, e este check nao duplica esse bloqueio.
    """
    from app.integrations.api.client import DesktopApiClient
    from app.integrations.api.config import DesktopApiConfigStore
    from app.integrations.api.system_client import SystemApiClient
    from app.services.compatibility_check import run_compatibility_check
    from app.versioning.models import CompatibilityStatus

    config_store_factory = config_store_factory or DesktopApiConfigStore
    client_factory = client_factory or DesktopApiClient
    check_runner = check_runner or run_compatibility_check

    settings = config_store_factory().load_settings()
    if not settings.enabled:
        log.info("Verificacao de compatibilidade ignorada | motivo=integracao_api_desativada")
        return True, None

    def perform_check():
        client = client_factory(settings)
        try:
            return check_runner(SystemApiClient(client))
        finally:
            client.close()

    # Tenta a checagem silenciosamente primeiro -- sem abrir nenhum dialogo.
    # No caminho feliz (COMPATIBLE/UPDATE_AVAILABLE/UPDATE_RECOMMENDED, que
    # nunca bloqueiam) o app segue direto pro login sem nenhuma janela extra
    # piscando na tela. So constroi o CompatibilityGateDialog (com retry
    # interativo) quando o resultado realmente exige acao do usuario.
    try:
        check_result = perform_check()
    except Exception:
        log.exception("Falha inesperada na tentativa silenciosa de verificacao de compatibilidade")
        check_result = None

    silent_ok = check_result is not None and check_result.state not in {
        CompatibilityStatus.UPDATE_REQUIRED,
        CompatibilityStatus.INCOMPATIBLE,
        CompatibilityStatus.MAINTENANCE,
        CompatibilityStatus.CHECK_FAILED,
        CompatibilityStatus.SERVER_UPDATE_REQUIRED,
    }

    if silent_ok:
        proceed = True
    else:
        if dialog_factory is None:
            from app.ui.compatibility_gate_dialog import CompatibilityGateDialog

            dialog_factory = CompatibilityGateDialog

        dialog = dialog_factory(perform_check, parent)
        dialog.exec()

        check_result = getattr(dialog, "check_result", None)
        proceed = bool(getattr(dialog, "proceed", False))

    if not proceed and check_result is not None and check_result.state == CompatibilityStatus.MAINTENANCE:
        # Fase 14, Secao 23: tela dedicada de manutencao (com polling
        # periodico) em vez da mensagem estatica generica do gate acima.
        if maintenance_dialog_factory is None:
            from app.ui.maintenance_mode_dialog import MaintenanceModeDialog

            maintenance_dialog_factory = MaintenanceModeDialog
        maintenance_dialog = maintenance_dialog_factory(perform_check, check_result, parent)
        maintenance_dialog.exec()
        check_result = getattr(maintenance_dialog, "check_result", check_result)
        proceed = bool(getattr(maintenance_dialog, "proceed", False))

    if not proceed:
        state = check_result.state.value if check_result else "desconhecido"
        log.warning("Inicializacao interrompida por verificacao de compatibilidade | estado=%s", state)
        return False, None
    if check_result is not None and check_result.state == CompatibilityStatus.UPDATE_AVAILABLE and check_result.dto is not None:
        return True, (
            f"Ha uma nova versao recomendada disponivel ({check_result.dto.recommended_desktop_version}). "
            "Voce pode continuar usando esta versao."
        )
    return True, None


def confirm_post_update_handshake(argv: list[str]) -> None:
    """Fase 10, Secao 24: se o Desktop foi reaberto pelo Updater
    (--post-update <request_id>), confirma localmente que o processo novo
    realmente iniciou -- nenhuma dependencia de rede, so um marcador em
    disco que o Updater espera com timeout. Nao faz nada se a flag nao
    estiver presente (caminho normal, sem Updater envolvido)."""
    if "--post-update" not in argv:
        return
    try:
        request_id = argv[argv.index("--post-update") + 1]
    except IndexError:
        log.warning("Flag --post-update presente sem request_id.")
        return
    try:
        from app.updater.handshake import write_handshake_marker

        write_handshake_marker(request_id)
        log.info("post_update_handshake_confirmed request_id=%s", request_id)
    except Exception:
        log.exception("Falha ao confirmar handshake pos-atualizacao | request_id=%s", request_id)


def main():
    configure_logging()
    log.info("desktop_started version=%s", get_desktop_version())
    confirm_post_update_handshake(sys.argv[1:])

    if "--notifier" in sys.argv[1:]:
        from app.services.notifier_agent import run_notifier_loop

        run_notifier_loop()
        return 0

    def handle_exception(exc_type, exc_value, exc_traceback):
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        log.critical("Erro nao tratado", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception
    configure_windows_taskbar_icon()

    from app.services.notifier_agent import acquire_main_app_mutex

    acquire_main_app_mutex()

    app = QApplication(sys.argv)
    app.setApplicationName("Controle de Producao Industel")
    app.setWindowIcon(app_icon())

    if not run_startup_bootstrap():
        return 0

    compatibility_proceed, update_available_message = run_startup_compatibility_check()
    if not compatibility_proceed:
        return 0

    update_checked, update_launched = run_startup_update_check()
    if update_launched:
        return 0

    from app.ui.main_window import MainWindow

    window = MainWindow(skip_auto_update_check=update_checked, update_available_notice=update_available_message)
    if not window.start():
        return 0
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
