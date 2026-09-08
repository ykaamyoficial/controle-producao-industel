"""Camada publica do sistema de icones.

`make_icon(name, color, size)` e mantida com a mesma assinatura de sempre e
continua sendo o jeito que a maioria das telas pede um icone - por baixo dos
panos ela agora resolve para Lucide (cache + tema) sempre que `name` for uma
chave semantica conhecida (`AppIcons`), e so cai nos caminhos antigos (PNG
legado, depois desenho procedural) quando o nome nao e reconhecido - o que
hoje so acontece com nomes dinamicos vindos de dados (ex.: status de tabela).

Codigo novo deve preferir a API explicita: `AppIcons`, `IconSize`,
`IconColorRole`, os componentes `AppIcon`/`AppIconButton`
(app/ui/components/app_icon_widget.py, app_icon_button.py) e as helpers de
`icon_motion`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from . import icon_cache, icon_motion, icon_provider
from ._procedural_fallback import ICON_SYMBOLS, draw_procedural_icon
from .icon_registry import ICON_REGISTRY, LUCIDE_DIR
from .icon_tokens import IconColorRole, IconMotion, IconState, IconSize, resolve_color
from .semantic_icons import AppIcons
from .status_icons import (
    STATUS_ICON_REGISTRY,
    STATUS_TO_ICON,
    AppStatusIcon,
    StatusColorRole,
    status_icon,
    status_icon_role,
    status_icon_tooltip,
)

log = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[3]
APP_ICON_DIR = ROOT_DIR / "app" / "assets" / "icons"
PREMIUM_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

# Mapa legado nome -> PNG em app/assets/icons/. Mantido para os poucos nomes
# dinamicos (ex.: status de linha de tabela) que nao passam por AppIcons, e
# como ultimo fallback caso um SVG Lucide venha a faltar em disco.
ICON_FILES = {
    "dashboard": "area_painel.png",
    "control": "area_controle_geral.png",
    "production": "area_producao.png",
    "galvanization": "area_galvanizacao.png",
    "expedition": "area_expedicao.png",
    "stock": "area_almoxarifado.png",
    "fiscal": "sistema_fiscal.png",
    "partial": "status_parcial.png",
    "history": "sistema_historico.png",
    "audit": "sistema_auditoria.png",
    "reports": "sistema_relatorios.png",
    "settings": "sistema_configuracoes.png",
    "users": "sistema_usuarios.png",
    "backup": "sistema_backup.png",
    "restore": "sistema_restaurar.png",
    "database": "sistema_banco_postgresql.png",
    "search": "acao_pesquisar.png",
    "clear": "acao_limpar.png",
    "new": "acao_novo.png",
    "edit": "acao_editar.png",
    "status": "acao_salvar.png",
    "batch": "acao_lote.png",
    "load": "acao_cargas.png",
    "next": "acao_proximo.png",
    "previous": "acao_anterior.png",
    "save": "acao_salvar.png",
    "remove": "acao_remover.png",
    "refresh": "acao_atualizar.png",
    "pdf": "acao_pdf.png",
    "excel": "acao_excel.png",
    "fiscal_pending": "status_pendente.png",
    "fiscal_partial": "status_parcial.png",
    "fiscal_done": "status_finalizado.png",
    "fiscal_critical": "status_pendente.png",
    "fiscal_blocked": "status_cancelado.png",
}

_UNKNOWN_LOGGED: set[str] = set()


def _legacy_png_icon(name: str) -> QIcon | None:
    icon_file = ICON_FILES.get(name)
    if not icon_file and name:
        status_file = f"status_{name.lower()}.png"
        if (APP_ICON_DIR / status_file).exists():
            icon_file = status_file
    if not icon_file:
        return None
    icon = QIcon()
    loaded = False
    for icon_size in PREMIUM_ICON_SIZES:
        path = APP_ICON_DIR / "premium" / str(icon_size) / icon_file
        if path.exists():
            icon.addFile(str(path), QSize(icon_size, icon_size))
            loaded = True
    path = APP_ICON_DIR / icon_file
    if path.exists():
        icon.addFile(str(path), QSize(512, 512))
        loaded = True
    return icon if loaded else None


def make_icon(name: str, color: str = "#2563eb", size: int = 20) -> QIcon:
    try:
        semantic = AppIcons(name)
    except ValueError:
        semantic = None

    if semantic is not None:
        lucide_icon = icon_provider.get_icon(semantic, size, color)
        if lucide_icon is not None:
            return lucide_icon

    legacy_icon = _legacy_png_icon(name)
    if legacy_icon is not None:
        return legacy_icon

    if name not in _UNKNOWN_LOGGED:
        log.warning("Icone '%s' nao encontrado em AppIcons/ICON_FILES; usando fallback procedural.", name)
        _UNKNOWN_LOGGED.add(name)
    return draw_procedural_icon(name, color, size)


__all__ = [
    "make_icon",
    "ICON_FILES",
    "ICON_SYMBOLS",
    "ICON_REGISTRY",
    "PREMIUM_ICON_SIZES",
    "LUCIDE_DIR",
    "AppIcons",
    "IconSize",
    "IconColorRole",
    "IconState",
    "IconMotion",
    "resolve_color",
    "AppStatusIcon",
    "StatusColorRole",
    "STATUS_ICON_REGISTRY",
    "STATUS_TO_ICON",
    "status_icon",
    "status_icon_role",
    "status_icon_tooltip",
    "icon_provider",
    "icon_cache",
    "icon_motion",
]
