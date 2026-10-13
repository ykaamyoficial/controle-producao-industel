from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog


def apply_large_dialog_geometry(
    dialog: QDialog,
    parent=None,
    width_ratio: float = 0.94,
    height_ratio: float = 0.90,
    minimum_width: int = 1100,
    minimum_height: int = 650,
) -> None:
    """Apply the standard geometry for content-heavy dialogs."""
    dialog.setMinimumSize(minimum_width, minimum_height)
    dialog.setSizeGripEnabled(True)

    reference = parent.window() if parent and parent.window() else None
    if reference:
        available_width = reference.width()
        available_height = reference.height()
        center = reference.geometry().center()
    else:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        available_width = available.width() if available else minimum_width
        available_height = available.height() if available else minimum_height
        center = available.center() if available else None

    width = max(minimum_width, int(available_width * width_ratio))
    height = max(minimum_height, int(available_height * height_ratio))
    dialog.resize(width, height)

    if center:
        frame = dialog.frameGeometry()
        frame.moveCenter(center)
        dialog.move(frame.topLeft())


def _startup_palette() -> dict:
    """Paleta gravada na configuracao, lida sem montar o servico (as telas de
    inicializacao abrem antes dele)."""
    from app.services import backend_adapter as backend

    name = None
    try:
        store = backend.get_configuration_service(backend.get_config_path())
        if store.exists():
            name = store.load().get("color_palette")
    except Exception:
        name = None
    return backend.OFFICIAL_COLOR_PALETTES[backend.normalize_palette_name(name)]


def style_dialog_from_parent(dialog: QDialog, parent=None, *, frameless: bool = True, standalone: bool = False) -> None:
    """Ponto unico dos dialogos: aplica a folha de estilo da janela dona, o
    veu que escurece a janela de tras e a casca padrao de tela sobreposta
    (sem moldura do Windows, cantos arredondados, tabelas padronizadas).

    `frameless=False` e para o dialogo que nao tem botao proprio de fechar e
    por isso precisa da barra de titulo nativa.

    `standalone=True` e para a tela de inicializacao (login, primeiro acesso,
    compatibilidade, manutencao, atualizacao), que abre sem janela principal
    por tras: com a casca nova ela tambem perde a barra do Windows, entao
    precisa ter fechamento proprio (`window_title_row()` ou um botao Fechar).
    Sem dona ela recebe a folha de estilo do tema gravado na configuracao."""
    from app.ui.components.window_shell import window_shell_enabled

    owner = parent.window() if parent and parent.window() else None
    own_shell = standalone and window_shell_enabled()
    if owner:
        dialog.setStyleSheet(owner.styleSheet())
        # Ponto unico dos dialogos: e aqui que toda tela sobreposta ganha o
        # veu que escurece a janela de tras.
        from app.ui.components.dialog_scrim import attach_dialog_scrim

        attach_dialog_scrim(dialog, owner)
    elif own_shell and not dialog.styleSheet():
        from app.ui.styles import app_stylesheet

        dialog.setStyleSheet(app_stylesheet(_startup_palette()))
    from app.ui.components.dialog_shell import install_dialog_shell

    # Sem janela dona a barra de titulo nativa e a unica forma garantida de
    # fechar a janela: so some com ela a tela que traz o proprio fechamento.
    install_dialog_shell(dialog, frameless=frameless and (owner is not None or own_shell))
