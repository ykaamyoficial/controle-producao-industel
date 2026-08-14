from __future__ import annotations
import json
from typing import Any
from urllib.parse import urlparse, urlunparse
from app.integrations.api.exceptions import ApiBusinessError
from app.services.api_proposal_storage import OfficialProposalApiStorage, api_permission_level, user_message_for_api_error
from app.services.api_reports import ApiExecutiveDashboardService, ApiOperationalReportsService
from app.services.status_sorting import sort_fiscal_rows, sort_process_rows
from app.services.app_paths import ensure_app_data_dirs, get_config_example_path, get_config_path
from app.services.app_logging import get_logger
from app.services.configuration_service import get_configuration_service
log = get_logger('backend')
_UNSET = object()
PERMISSION_LEVEL_NONE = 'NONE'
PERMISSION_LEVEL_VIEW = 'VIEW'
PERMISSION_LEVEL_EDIT = 'EDIT'
PERMISSION_LEVELS = (PERMISSION_LEVEL_NONE, PERMISSION_LEVEL_VIEW, PERMISSION_LEVEL_EDIT)
PERMISSION_LEVEL_LABELS = {PERMISSION_LEVEL_NONE: 'Sem acesso', PERMISSION_LEVEL_VIEW: 'Visualizar', PERMISSION_LEVEL_EDIT: 'Visualizar e alterar'}
OFFICIAL_AREAS = {'CONTROLE GERAL': {'column': 'status_geral'}, 'PRODUCAO': {'column': 'status_producao'}, 'GALVANIZACAO': {'column': 'status_galvanizacao'}, 'EXPEDICAO': {'column': 'status_expedicao'}, 'ALMOXARIFADO': {'column': 'status_almoxarifado'}}
PERMISSION_AREAS = [('dashboard', 'Painel Geral', 'PAINEL GERAL'), ('executive_dashboard', 'Dashboard Executivo', 'DASHBOARD EXECUTIVO'), ('control_general', 'Controle Geral', 'CONTROLE GERAL'), ('production', 'Producao', 'PRODUCAO'), ('galvanization', 'Galvanizacao', 'GALVANIZACAO'), ('expedition', 'Expedicao', 'EXPEDICAO'), ('fiscal', 'Fiscal', 'FISCAL'), ('partials', 'Parciais', 'PARCIAIS'), ('warehouse', 'Almoxarifado', 'ALMOXARIFADO'), ('operational_reports', 'Relatorios Operacionais', 'RELATORIOS OPERACIONAIS'), ('history', 'Historico', 'HISTORICO'), ('settings', 'Configuracoes', 'CONFIGURACOES'), ('users_permissions', 'Usuarios e Permissoes', 'USUARIOS_PERMISSOES'), ('chats', 'Chats', 'CHATS')]
NAV_PERMISSION_KEYS = {nav: key for key, _label, nav in PERMISSION_AREAS}
LEGACY_AREA_PERMISSION_KEYS = {'CONTROLE GERAL': 'control_general', 'PRODUCAO': 'production', 'GALVANIZACAO': 'galvanization', 'EXPEDICAO': 'expedition', 'ALMOXARIFADO': 'warehouse'}
PERMISSION_LEGACY_AREAS = {value: key for key, value in LEGACY_AREA_PERMISSION_KEYS.items()}
STATUS_LABELS = {'': '', 'AGUARDANDO_LIBERACAO': 'Aguardando liberacao', 'NAO_LIBERADO': 'Nao liberado', 'LIBERADO_PRODUCAO': 'Liberado para producao', 'EM_PRODUCAO': 'Em producao', 'EM_GALVANIZACAO': 'Em galvanizacao', 'EM_EXPEDICAO': 'Em expedicao', 'ENTREGUE': 'Entregue', 'CANCELADA': 'Cancelada', 'NAO_INICIADO': 'Aguardando inicio', 'FLUXO_INDEFINIDO': 'Fluxo indefinido', 'ITEM_PENDENTE_FABRICACAO': 'Item pendente de fabricacao', 'INICIADO': 'Em producao', 'FINALIZADO': 'Producao concluida', 'FINALIZADO_PARCIAL': 'Produzido parcialmente', 'PARADO': 'Producao pausada', 'AGUARDANDO_ENVIO': 'Aguardando montagem de carga', 'AGUARDANDO_RETORNO': 'Aguardando retorno', 'DISPONIVEL_PARCIAL': 'Disponivel parcialmente', 'EM_CARGA': 'Em carga', 'ENVIADO_GALVANIZACAO': 'Enviado para galvanizacao', 'RETORNO_PARCIAL': 'Retorno parcial', 'RETORNADO': 'Retornado', 'RETORNOU_GALVANIZACAO': 'Retornou da galvanizacao', 'RETORNOU_PARCIAL': 'Retornou parcialmente', 'EM_SEPARACAO': 'Aguardando separacao', 'AGUARDANDO_SEPARACAO_PARCIAL': 'Aguardando separacao parcial', 'SEPARACAO_INICIADA': 'Em separacao', 'SEPARADO': 'Separado para entrega', 'ENTREGUE_PARCIAL': 'Entregue parcialmente', 'AGUARDANDO_CONFIRMACAO': 'Aguardando confirmacao', 'SEM_PARAFUSOS': 'Sem almoxarifado', 'ALMOXARIFADO_ENTREGUE': 'Almoxarifado entregue', 'ALMOXARIFADO_ENTREGUE_PARCIAL': 'Almoxarifado entregue parcial', 'NAO_DEFINIDO': 'Nao definido', 'SIM': 'Sim', 'NAO': 'Nao', 'PRINCIPAL': 'Principal', 'PARCIAL': 'Parcial'}
AREA_STATUS_LABEL_OVERRIDES = {'ALMOXARIFADO': {'NAO_DEFINIDO': 'Aguardando definicao', '': 'Aguardando definicao', 'AGUARDANDO_CONFIRMACAO': 'Aguardando confirmacao', 'EM_SEPARACAO': 'Em separacao', 'SEM_PARAFUSOS': 'Sem almoxarifado', 'SEPARADO': 'Separado', 'ALMOXARIFADO_ENTREGUE_PARCIAL': 'Entregue parcial', 'ALMOXARIFADO_ENTREGUE': 'Entregue', 'FINALIZADO': 'Entregue'}, 'PRODUCAO': {'FINALIZADO': 'Producao concluida', 'FINALIZADO_PARCIAL': 'Produzido parcialmente'}, 'GALVANIZACAO': {'RETORNOU_GALVANIZACAO': 'Retornou da galvanizacao', 'RETORNOU_PARCIAL': 'Retornou parcialmente', 'DISPONIVEL': 'Disponivel para carga'}, 'EXPEDICAO': {'ENTREGUE': 'Entregue', 'ENTREGUE_PARCIAL': 'Entregue parcial'}}
LOAD_STATUS_LABELS = {'AGUARDANDO_LIBERACAO': 'Aguardando liberacao', 'LIBERADA_PARA_ENVIO': 'Liberada para envio', 'RETORNO_PARCIAL': 'Retorno parcial', 'RETORNADA_GALVANIZACAO': 'Retornada da galvanizacao'}
STATUS_LABELS['SEPARADO_COM_PENDENCIA'] = 'Separado com pendencia'
DEFAULT_REPORT_DEFINITIONS = [{'name': 'Processos em andamento', 'source': 'ANDAMENTO', 'columns': ['proposta', 'cliente', 'obra_site', 'lote', 'peso', 'prazo_entrega', 'status_geral', 'status_producao', 'status_galvanizacao', 'status_expedicao', 'situacao_fluxo']}, {'name': 'Parciais e pendencias', 'source': 'PARCIAIS', 'columns': ['proposta', 'tipo_processo', 'cliente', 'obra_site', 'peso_parcial', 'saldo_pendente', 'status_producao', 'status_galvanizacao', 'status_expedicao', 'situacao_fluxo', 'origem_remanejamento', 'observacao_remanejamento']}, {'name': 'Galvanizacao enviada/retorno', 'source': 'GALVANIZACAO', 'columns': ['proposta', 'cliente', 'obra_site', 'lote', 'peso', 'data_envio_galv', 'data_prevista_retorno_galv', 'data_retorno_galv', 'status_galvanizacao', 'status_expedicao']}, {'name': 'Entregas por cliente', 'source': 'ENTREGAS', 'columns': ['cliente', 'proposta', 'pedido_compra', 'obra_site', 'prazo_entrega', 'data_retirada', 'status_expedicao', 'status_geral']}]
ITEM_NO_PRODUCTION_LABELS = {'pronta_entrega': 'Pronta entrega', 'comprado_terceiro': 'Comprado de terceiro', 'terceirizado': 'Terceirizado', 'outro': 'Outro'}
AREA_FINISHED_STATUS = {'PRODUCAO': {'FINALIZADO'}, 'GALVANIZACAO': {'RETORNOU_GALVANIZACAO'}, 'EXPEDICAO': {'ENTREGUE'}, 'ALMOXARIFADO': {'ALMOXARIFADO_ENTREGUE', 'SEM_PARAFUSOS'}}
STATUS_FLOW_ORDER = {'CONTROLE GERAL': ['AGUARDANDO_LIBERACAO', 'LIBERADO_PRODUCAO', 'EM_PRODUCAO', 'EM_GALVANIZACAO', 'EM_EXPEDICAO', 'ENTREGUE', 'CANCELADA'], 'PRODUCAO': ['NAO_INICIADO', 'INICIADO', 'PARADO', 'FINALIZADO_PARCIAL', 'FINALIZADO', 'ITEM_PENDENTE_FABRICACAO'], 'GALVANIZACAO': ['AGUARDANDO_ENVIO', 'DISPONIVEL_PARCIAL', 'EM_CARGA', 'ENVIADO_GALVANIZACAO', 'RETORNOU_PARCIAL', 'RETORNOU_GALVANIZACAO'], 'EXPEDICAO': ['EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARACAO_INICIADA', 'SEPARADO', 'ENTREGUE_PARCIAL', 'ENTREGUE'], 'ALMOXARIFADO': ['AGUARDANDO_CONFIRMACAO', 'EM_SEPARACAO', 'SEPARADO', 'SEM_PARAFUSOS', 'ALMOXARIFADO_ENTREGUE_PARCIAL', 'ALMOXARIFADO_ENTREGUE']}
STATUS_FLOW_ORDER['EXPEDICAO'].insert(3, 'SEPARADO_COM_PENDENCIA')
COLOR_PALETTES = {'aurora': {'label': 'Aurora profissional', 'bg': '#f5f7fb', 'surface': '#ffffff', 'surface_alt': '#e8f1ff', 'text': '#0f172a', 'muted': '#475569', 'border': '#cbd5e1', 'accent': '#006fc9', 'accent_hover': '#005aa3', 'accent_text': '#ffffff', 'secondary': '#be123c', 'success': '#047857', 'warning': '#b45309', 'danger': '#b91c1c', 'info': '#0369a1', 'disabled': '#94a3b8', 'area_control': '#006fc9', 'area_production': '#047857', 'area_galvanization': '#7c3aed', 'area_expedition': '#c2410c', 'area_stock': '#64748b', 'tree_selected': '#bfdbfe', 'tree_heading': '#dbeafe'}, 'grafite': {'label': 'Grafite alto contraste', 'bg': '#0f172a', 'surface': '#172033', 'surface_alt': '#24324a', 'text': '#f8fafc', 'muted': '#cbd5e1', 'border': '#475569', 'accent': '#38bdf8', 'accent_hover': '#7dd3fc', 'accent_text': '#0f172a', 'secondary': '#fb923c', 'success': '#34d399', 'warning': '#facc15', 'danger': '#fb7185', 'info': '#7dd3fc', 'disabled': '#64748b', 'area_control': '#38bdf8', 'area_production': '#34d399', 'area_galvanization': '#a78bfa', 'area_expedition': '#fb923c', 'area_stock': '#94a3b8', 'tree_selected': '#0e7490', 'tree_heading': '#1e293b'}}

class AppError(Exception):
    pass

class VersionConflictError(AppError):
    """Raised when the API rejects a write because its optimistic-locking `version` is stale."""
    pass

def normalize_status(status: str | None) -> str:
    return str(status or '').strip().upper()

def status_label(status: str) -> str:
    normalized = normalize_status(status)
    return STATUS_LABELS.get(normalized, status or '')

def area_status_label(area: str, status: str) -> str:
    normalized = normalize_status(status)
    return AREA_STATUS_LABEL_OVERRIDES.get(area, {}).get(normalized, status_label(normalized))

def load_status_label(status: str) -> str:
    normalized = normalize_status(status)
    return LOAD_STATUS_LABELS.get(normalized, status_label(normalized))

def normalize_permission_area(area_key: str) -> str:
    text = str(area_key or '').strip()
    if text in LEGACY_AREA_PERMISSION_KEYS:
        return LEGACY_AREA_PERMISSION_KEYS[text]
    upper = text.upper()
    if upper in LEGACY_AREA_PERMISSION_KEYS:
        return LEGACY_AREA_PERMISSION_KEYS[upper]
    if upper in NAV_PERMISSION_KEYS:
        return NAV_PERMISSION_KEYS[upper]
    return text.lower().replace(' ', '_')

def permission_area_options() -> list[dict[str, str]]:
    return [{'key': key, 'label': label, 'nav': nav} for key, label, nav in PERMISSION_AREAS]

def permission_level_label(level: str) -> str:
    return PERMISSION_LEVEL_LABELS.get(level or PERMISSION_LEVEL_NONE, 'Sem acesso')

def user_can_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    return bool(user.get('api_superuser') or user.get('perfil') == 'admin')

def profile_label(profile: str) -> str:
    return 'Administrador' if profile == 'admin' else 'Usuario'

def profile_default_permissions(profile: str) -> dict[str, str]:
    if profile == 'admin':
        return {area['key']: PERMISSION_LEVEL_EDIT for area in permission_area_options()}
    return {area['key']: PERMISSION_LEVEL_NONE for area in permission_area_options()}

def display_cell(_key: str, value: Any) -> str:
    if value is None:
        return ''
    return str(value)

def normalize_stockroom_need(value: Any) -> str:
    text = normalize_status(str(value or 'NAO_DEFINIDO'))
    return text if text in {'SIM', 'NAO', 'NAO_DEFINIDO'} else 'NAO_DEFINIDO'

class _OfficialLegacyNamespace:
    AppError = AppError
    AREAS = OFFICIAL_AREAS
    AREA_FINISHED_STATUS = AREA_FINISHED_STATUS
    COLOR_PALETTES = COLOR_PALETTES
    DEFAULT_REPORT_DEFINITIONS = DEFAULT_REPORT_DEFINITIONS
    ITEM_NO_PRODUCTION_LABELS = ITEM_NO_PRODUCTION_LABELS
    NAV_PERMISSION_KEYS = NAV_PERMISSION_KEYS
    PERMISSION_LEGACY_AREAS = PERMISSION_LEGACY_AREAS
    PERMISSION_LEVEL_NONE = PERMISSION_LEVEL_NONE
    PERMISSION_LEVEL_VIEW = PERMISSION_LEVEL_VIEW
    PERMISSION_LEVEL_EDIT = PERMISSION_LEVEL_EDIT
    PERMISSION_LEVELS = PERMISSION_LEVELS
    PROFILE_OPTIONS = [('admin', 'Administrador'), ('usuario', 'Usuario')]
    PROFILE_DEFAULT_AREAS = {'admin': list(OFFICIAL_AREAS), 'usuario': []}
    STATUS_FLOW_ORDER = STATUS_FLOW_ORDER
    json = json
    area_status_label = staticmethod(area_status_label)
    display_cell = staticmethod(display_cell)
    load_status_label = staticmethod(load_status_label)
    normalize_permission_area = staticmethod(normalize_permission_area)
    normalize_status = staticmethod(normalize_status)
    normalize_stockroom_need = staticmethod(normalize_stockroom_need)
    permission_area_options = staticmethod(permission_area_options)
    permission_level_label = staticmethod(permission_level_label)
    profile_label = staticmethod(profile_label)
    profile_default_permissions = staticmethod(profile_default_permissions)
    status_label = staticmethod(status_label)
    user_can_admin = staticmethod(user_can_admin)
legacy = _OfficialLegacyNamespace()
THEME_ALIASES = {'aurora': 'claro', 'aurora professional': 'claro', 'aurora profissional': 'claro', 'energia': 'claro', 'verde operacional': 'claro', 'grafite': 'escuro', 'grafite alto contraste': 'escuro', 'pulso': 'escuro', 'pulso executivo': 'escuro'}
OFFICIAL_COLOR_PALETTES = {'claro': {**COLOR_PALETTES['aurora'], 'label': 'Claro'}, 'escuro': {**COLOR_PALETTES['grafite'], 'label': 'Escuro', 'bg': '#0f172a', 'surface': '#172033', 'surface_alt': '#24324a', 'text': '#f8fafc', 'muted': '#dbeafe', 'border': '#475569', 'accent': '#38bdf8', 'accent_hover': '#7dd3fc', 'accent_text': '#0f172a'}}

def normalize_palette_name(name: str | None) -> str:
    normalized = (name or 'claro').strip().lower()
    normalized = THEME_ALIASES.get(normalized, normalized)
    return normalized if normalized in OFFICIAL_COLOR_PALETTES else 'claro'

def _load_config_example() -> dict[str, Any]:
    example_path = get_config_example_path()
    if not example_path.exists():
        return {}
    with example_path.open('r', encoding='utf-8') as file:
        return legacy.json.load(file)

def load_app_config() -> dict[str, Any]:
    ensure_app_data_dirs()
    service = get_configuration_service(get_config_path())
    data = service.load() if service.exists() else _load_config_example()
    data.setdefault('company', 'Industel')
    data.setdefault('color_palette', 'claro')
    # Fase 3 - Primeiro Acesso Automatico (Secao 21): nao persistir um servidor
    # "validado" por default -- esse default so serve para exibicao quando
    # nada foi configurado ainda; a gravacao real de um endereco valido e
    # sempre feita pelo bootstrap ou pelo diagnostico via DesktopApiConfigStore.
    data.setdefault('desktop_api', {'enabled': False, 'base_url': 'http://127.0.0.1:8000', 'connect_timeout': 3, 'read_timeout': 10})
    data.setdefault('platform_api', {'enabled': False, 'base_url': 'http://127.0.0.1:8100', 'environment_type': 'production', 'company_code': '', 'company_name': ''})
    data.setdefault('saved_reports', legacy.DEFAULT_REPORT_DEFINITIONS)
    data['color_palette'] = normalize_palette_name(data.get('color_palette'))
    data.pop('postgresql_official_proposals_enabled', None)
    data.pop('db_path', None)
    data.pop('backup_dir', None)
    data.pop('backup_keep', None)
    save_app_config(data)
    return data

def save_app_config(config: dict[str, Any]):
    ensure_app_data_dirs()
    get_configuration_service(get_config_path()).save(config)

def update_app_config(changes: dict[str, Any]) -> dict[str, Any]:
    """Atualizacao parcial atomica de nivel superior: mescla apenas as chaves
    de `changes`, sem sobrescrever o restante da configuracao com um
    snapshot em memoria que possa estar desatualizado."""
    ensure_app_data_dirs()

    def _apply(config: dict[str, Any]) -> None:
        config.update(changes)

    return get_configuration_service(get_config_path()).update(_apply)

def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}

class BackendService:
    """Desktop backend adapter for the official API/PostgreSQL runtime."""

    def __init__(self):
        self.config = load_app_config()
        self.official_proposal_storage = OfficialProposalApiStorage()
        self.user = None
        self._api_access_token: str | None = None
        self._api_refresh_token: str | None = None
        self._avatar_cache: dict[int, bytes | None] = {}
        # Callback opcional, setado pela MainWindow: chamado depois que uma
        # conversa e confirmada como lida no backend, para que o badge global
        # do cabecalho seja atualizado sem o dialog de chat precisar conhecer
        # o widget do header diretamente.
        self.on_conversation_marked_read = None
        log.info('Backend inicializado | banco_operacional=PostgreSQL via API')

    @property
    def palettes(self):
        return OFFICIAL_COLOR_PALETTES

    @property
    def palette_name(self) -> str:
        return normalize_palette_name(self.config.get('color_palette'))

    @property
    def palette(self):
        return self.palettes.get(self.palette_name, self.palettes['claro'])

    @property
    def company(self) -> str:
        return self.config.get('company', 'Industel')

    def _logout_current_api_session_best_effort(self) -> None:
        try:
            self.official_proposal_storage.logout_current_session()
            log.info('Sessao da API encerrada antes da troca de empresa')
        except Exception:
            log.warning('Nao foi possivel encerrar sessao ativa na API antes da troca de empresa')

    def logout(self) -> None:
        self._logout_current_api_session_best_effort()
        self.user = None
        self._api_access_token = None
        self._api_refresh_token = None

    def authenticate(self, login: str, password: str) -> bool:
        try:
            state = self.official_proposal_storage.start_session(login, password)
            api_user = state.authenticated_user
            if not api_user:
                self.user = None
                self._api_access_token = None
                self._api_refresh_token = None
                return False
            self._apply_current_api_user(api_user)
            self._api_access_token = state.access_token
            try:
                self._api_refresh_token = self.official_proposal_storage.token_store.get_refresh_token()
            except Exception:
                self._api_refresh_token = None
            return True
        except Exception as exc:
            log.warning('Falha no login via API | detalhe=%s', user_message_for_api_error(exc))
            self.user = None
            self._api_access_token = None
            self._api_refresh_token = None
            return False

    def user_name(self) -> str:
        if not self.user:
            return '-'
        return self.user['nome'] or self.user['login']

    def user_profile(self) -> str:
        if not self.user:
            return '-'
        return 'Administrador' if legacy.user_can_admin(self.user) else 'Usuario'

    def update_current_user(self, *, username: str | None = None, display_name: str | None = None) -> dict[str, Any]:
        api_user = self.official_proposal_storage.update_current_user(username=username, display_name=display_name)
        self._apply_current_api_user(api_user)
        return dict(self.user or {})

    def change_current_password(self, current_password: str, new_password: str, confirm_password: str) -> None:
        self.official_proposal_storage.change_current_password(current_password, new_password, confirm_password)

    def upload_current_avatar(self, filename: str, content: bytes, mime: str) -> dict[str, Any]:
        api_user = self.official_proposal_storage.upload_current_avatar(filename, content, mime)
        self._apply_current_api_user(api_user)
        self.invalidate_avatar_cache(api_user.id)
        return dict(self.user or {})

    def remove_current_avatar(self) -> dict[str, Any]:
        api_user = self.official_proposal_storage.remove_current_avatar()
        self._apply_current_api_user(api_user)
        self.invalidate_avatar_cache(api_user.id)
        return dict(self.user or {})

    def avatar_bytes_for_user(self, user_id: int) -> bytes | None:
        key = int(user_id)
        if key not in self._avatar_cache:
            self._avatar_cache[key] = self.official_proposal_storage.avatar_bytes_for_user(key)
        return self._avatar_cache[key]

    def invalidate_avatar_cache(self, user_id: int | None = None) -> None:
        if user_id is None:
            self._avatar_cache.clear()
        else:
            self._avatar_cache.pop(int(user_id), None)

    def _apply_current_api_user(self, api_user) -> None:
        permissions = set(api_user.permissions or [])
        self.user = {
            'id': api_user.id, 'nome': api_user.display_name, 'login': api_user.username,
            'perfil': 'admin' if api_user.is_superuser or '*' in permissions else 'usuario',
            'ativo': 1 if api_user.active else 0, 'areas_acesso': ','.join(legacy.AREAS.keys()),
            'api_permissions': permissions, 'api_superuser': bool(api_user.is_superuser or '*' in permissions),
            'password_must_change': api_user.password_must_change,
            'avatar_available': api_user.avatar_available, 'avatar_mime': api_user.avatar_mime,
        }

    def visible_areas(self) -> list[str]:
        if not self.user:
            return []
        return [area for area in OFFICIAL_AREAS if self.can_view(area)]

    def permission_key(self, area: str) -> str:
        return legacy.normalize_permission_area(area)

    def permission_area_options(self) -> list[dict[str, str]]:
        return legacy.permission_area_options()

    def access_level_options(self) -> list[tuple[str, str]]:
        return [(level, legacy.permission_level_label(level)) for level in legacy.PERMISSION_LEVELS]

    def permission_level(self, area_key: str) -> str:
        if not self.user:
            return legacy.PERMISSION_LEVEL_NONE
        normalized = legacy.normalize_permission_area(area_key)
        return api_permission_level(set(self.user.get('api_permissions') or []), normalized, is_admin=bool(self.user.get('api_superuser')))

    def can_view(self, area_key: str) -> bool:
        return self.permission_level(area_key) in {legacy.PERMISSION_LEVEL_VIEW, legacy.PERMISSION_LEVEL_EDIT}

    def can_edit(self, area_key: str) -> bool:
        return self.permission_level(area_key) == legacy.PERMISSION_LEVEL_EDIT

    def can_view_nav(self, nav_key: str) -> bool:
        return self.can_view(self.permission_key(nav_key))

    def can_admin_chat(self) -> bool:
        if not self.user:
            return False
        permissions = set(self.user.get('api_permissions') or [])
        return bool(self.user.get('api_superuser')) or '*' in permissions or 'chat.admin' in permissions

    def can_edit_process(self) -> bool:
        return self.can_edit('control_general')

    def official_proposals_enabled(self) -> bool:
        return True

    def _api_app_error(self, exc: Exception) -> AppError:
        return AppError(user_message_for_api_error(exc))

    def can_admin(self) -> bool:
        return bool(self.user and self.user.get('api_superuser'))

    def can_access_area(self, area: str) -> bool:
        return self.can_view(area)

    def can_edit_area(self, area: str) -> bool:
        return self.can_edit(area)

    def dashboard(self) -> dict[str, Any]:
        rows = self.official_proposal_storage.list_proposals(sort_by='updated_at', sort_dir='desc', limit=200, offset=0)
        production = len(self.official_proposal_storage.list_production_proposals(limit=200, offset=0))
        expedition = len(self.official_proposal_storage.list_expedition_proposals(limit=200, offset=0))
        fiscal = self.official_proposal_storage.fiscal_indicators()
        galvanization = len(self.official_proposal_storage.galvanization_load_candidates('', ''))
        delivered = sum((1 for row in rows if row.get('status_geral') == 'ENTREGUE' or row.get('current_status') == 'ENTREGUE'))
        active = sum((1 for row in rows if row.get('status_geral') not in {'ENTREGUE', 'CANCELADA'} and row.get('current_status') not in {'ENTREGUE', 'CANCELADA'}))
        return {'Ativas': active, 'Vencidos': 0, 'Prox. 7 dias': 0, 'Producao': production, 'Galvanizacao': galvanization, 'Expedicao': expedition, 'Pend. remanej.': 0, 'Entregues': delivered, 'Fiscal': fiscal.get('falta_emitir', 0) + fiscal.get('nf_parcial', 0)}

    def dashboard_charts(self) -> dict[str, Any]:
        data = self.dashboard()
        areas = [{'label': 'Producao', 'total': data.get('Producao', 0)}, {'label': 'Galvanizacao', 'total': data.get('Galvanizacao', 0)}, {'label': 'Expedicao', 'total': data.get('Expedicao', 0)}, {'label': 'Fiscal', 'total': data.get('Fiscal', 0)}]
        status_counts: dict[str, int] = {}
        for row in self.official_proposal_storage.list_proposals(sort_by='updated_at', sort_dir='desc', limit=200, offset=0):
            status = row.get('status_geral') or row.get('current_status') or '-'
            status_counts[status] = status_counts.get(status, 0) + 1
        return {'areas': areas, 'status': [{'label': key, 'total': value} for key, value in status_counts.items()], 'prazos': []}

    def focus_text(self) -> str:
        return 'Operacao oficial conectada ao PostgreSQL via API.'

    def dashboard_metric_rows(self, metric: str) -> list[dict[str, Any]]:
        return self.process_rows('CONTROLE GERAL', {})

    def dashboard_chart_rows(self, chart_key: str, label: str) -> list[dict[str, Any]]:
        return self.process_rows('CONTROLE GERAL', {'text': label if chart_key == 'status' else ''})

    def operational_report(self, area: str, filters: dict[str, Any] | None=None) -> dict[str, Any]:
        try:
            return ApiOperationalReportsService(self.official_proposal_storage).generate(area, filters)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def executive_dashboard_report(self, filters: dict[str, Any] | None=None) -> dict[str, Any]:
        try:
            return ApiExecutiveDashboardService(self).generate(filters)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def list_status(self, area: str | None=None) -> list[str]:
        if area == 'CONTROLE GERAL':
            return ['AGUARDANDO_LIBERACAO', 'LIBERADO_PRODUCAO', 'EM_PRODUCAO', 'EM_GALVANIZACAO', 'EM_EXPEDICAO', 'ENTREGUE', 'CANCELADA']
        if area == 'PRODUCAO':
            return ['NAO_INICIADO', 'INICIADO', 'PARADO', 'FINALIZADO_PARCIAL', 'FINALIZADO', 'ITEM_PENDENTE_FABRICACAO']
        if area == 'GALVANIZACAO':
            return ['AGUARDANDO_ENVIO', 'DISPONIVEL_PARCIAL', 'EM_CARGA', 'ENVIADO_GALVANIZACAO', 'RETORNOU_GALVANIZACAO']
        if area == 'EXPEDICAO':
            return ['EM_SEPARACAO', 'SEPARACAO_INICIADA', 'SEPARADO_COM_PENDENCIA', 'SEPARADO', 'ENTREGUE_PARCIAL', 'ENTREGUE']
        if area == 'PARCIAIS':
            return ['FINALIZADO_PARCIAL', 'ITEM_PENDENTE_FABRICACAO', 'DISPONIVEL_PARCIAL', 'RETORNOU_PARCIAL', 'AGUARDANDO_SEPARACAO_PARCIAL', 'ENTREGUE_PARCIAL', 'NOTA_FISCAL_PARCIAL', 'ALMOXARIFADO_ENTREGUE_PARCIAL']
        if area == 'ALMOXARIFADO':
            return ['NAO_DEFINIDO', 'AGUARDANDO_CONFIRMACAO', 'EM_SEPARACAO', 'SEPARADO', 'SEM_PARAFUSOS', 'ALMOXARIFADO_ENTREGUE', 'ALMOXARIFADO_ENTREGUE_PARCIAL']
        return []

    def status_label(self, status: str) -> str:
        return legacy.status_label(status)

    def area_status_label(self, area: str, status: str) -> str:
        return legacy.area_status_label(area, status)

    def process_rows(self, area: str | None=None, filters: dict[str, str] | None=None) -> list[dict[str, Any]]:
        filters = dict(filters or {})
        if area == 'CONTROLE GERAL':
            try:
                rows = self.official_proposal_storage.list_proposals(customer=filters.get('cliente') or None, current_status=filters.get('status') or None, sort_by='updated_at', sort_dir='desc', limit=200, offset=0)
                rows = [row for row in rows if not row.get('parent_proposal_id')]
                text = (filters.get('text') or '').upper()
                if text:
                    rows = [row for row in rows if text in (row.get('proposta') or '').upper() or text in (row.get('cliente') or '').upper() or text in (row.get('obra_site') or '').upper() or (text in (row.get('lote') or '').upper())]
                return rows
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'PRODUCAO':
            try:
                rows = self.official_proposal_storage.list_production_proposals(search=filters.get('text') or None, status=filters.get('status') or None, limit=200, offset=0)
                return sort_process_rows(area, self._merge_partial_operational_rows(rows, area))
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'EXPEDICAO':
            try:
                rows = self.official_proposal_storage.list_expedition_proposals(search=filters.get('text') or None, limit=200, offset=0)
                status_filter = (filters.get('status') or '').strip().upper()
                if status_filter:
                    rows = [row for row in rows if (row.get('status_expedicao') or row.get('current_status') or '').upper() == status_filter]
                return sort_process_rows(area, rows)
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'GALVANIZACAO':
            try:
                return sort_process_rows(area, self._official_galvanization_rows(filters))
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'PARCIAIS':
            try:
                return sort_process_rows(area, self.official_proposal_storage.partial_rows(filters))
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'ALMOXARIFADO':
            try:
                return sort_process_rows(area, self.official_proposal_storage.warehouse_rows(filters))
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        return []

    def sort_process_rows(self, area: str | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sort_process_rows(area, rows)

    def _merge_partial_operational_rows(self, rows: list[dict[str, Any]], area: str) -> list[dict[str, Any]]:
        """Une filhas somente no mesmo bloco operacional.

        A linha resultante preserva os ids reais em ``proposal_ids`` para que
        uma acao posterior possa atingir exatamente os lotes representados.
        Sem parent_proposal_id, a linha continua com o comportamento antigo.
        """
        status_key = {
            'EXPEDICAO': 'status_expedicao',
            'FISCAL': 'status_fiscal',
            'GALVANIZACAO': 'status_galvanizacao',
        }.get(area, 'status_localizacao')
        groups: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            process_id = int(row.get('id') or row.get('processo_id') or row.get('proposal_id') or 0)
            parent_id = int(row.get('parent_proposal_id') or process_id)
            status = str(row.get(status_key) or row.get('current_status') or '').upper()
            load_key = str(row.get('carga_galvanizacao') or '') if area == 'GALVANIZACAO' else ''
            groups.setdefault((parent_id, status, load_key), []).append(row)
        merged: list[dict[str, Any]] = []
        parent_group_count: dict[int, int] = {}
        for parent_id, _status, _load_key in groups:
            parent_group_count[parent_id] = parent_group_count.get(parent_id, 0) + 1
        for (_parent_id, _status, _load_key), group in groups.items():
            # A mãe é uma linha própria no Fiscal. Separe-a antes de agrupar
            # as filhas; status igual não transforma a mãe em alvo das ações
            # das filhas.
            mother_rows = [row for row in group if not row.get('parent_proposal_id')]
            child_rows = [row for row in group if row.get('parent_proposal_id')]
            merged.extend(mother_rows)
            if len(child_rows) <= 1:
                merged.extend(child_rows)
                continue
            group = sorted(child_rows, key=lambda row: int(row.get('partial_number') or 0))
            base_row = next((row for row in group if not row.get('parent_proposal_id')), group[0])
            ids = [int(row.get('id') or row.get('processo_id') or row.get('proposal_id')) for row in group]
            partials = [int(row.get('partial_number') or 0) for row in group if row.get('partial_number')]
            display = str(base_row.get('proposta') or base_row.get('proposal_number') or '')
            if partials and base_row.get('parent_proposal_id') and parent_group_count.get(_parent_id, 0) > 1:
                root = display.rsplit('-', 1)[0] if '-' in display else display
                display = f"{root}-{','.join(str(value) for value in partials)}"
            elif partials and base_row.get('parent_proposal_id'):
                display = display.rsplit('-', 1)[0] if '-' in display else display
            combined = dict(base_row)
            combined['id'] = ids[0]
            combined['processo_id'] = ids[0]
            combined['proposal_ids'] = ids
            combined['fiscal_processo_ids'] = [
                int(row.get('fiscal_processo_id') or row.get('id') or 0)
                for row in group
                if row.get('fiscal_processo_id') or row.get('id')
            ]
            combined['proposta'] = display
            combined['proposal_number'] = display
            combined['grouped_partial'] = len(ids) > 1
            combined['group_partial_numbers'] = partials
            for numeric_key in ('quantidade_itens', 'item_count', 'itens_pendentes', 'quantidade_disponivel', 'quantidade_separada', 'quantidade_entregue', 'saldo_pendente'):
                values = [row.get(numeric_key) for row in group if row.get(numeric_key) not in (None, '')]
                if values and all(isinstance(value, (int, float)) for value in values):
                    combined[numeric_key] = sum(values)
            merged.append(combined)
        return merged

    def process_visible_in_area(self, process: dict[str, Any] | Any, area: str) -> bool:
        if isinstance(process, dict):
            cancelled = bool(process.get('is_cancelled')) or (process.get('status_geral') or process.get('current_status') or '') == 'CANCELADA'
            if cancelled:
                return area == 'CONTROLE GERAL'
        return True

    def batch_status_candidates(self, area: str, text: str='', exclude_ids: set[int] | None=None) -> list[dict[str, Any]]:
        return [row for row in self.process_rows(area, {'text': text}) if int(row.get('id') or 0) not in (exclude_ids or set())][:300]

    def status_for_area(self, process: dict[str, Any], area: str) -> str:
        if area in legacy.AREAS:
            return process.get(legacy.AREAS[area]['column']) or process.get('status_geral') or ''
        return process.get('status_geral') or ''

    def common_next_statuses(self, area: str, process_ids: list[int]) -> list[str]:
        if area in {'CONTROLE GERAL', 'PRODUCAO', 'EXPEDICAO', 'ALMOXARIFADO'}:
            if not process_ids or not self.can_edit(area):
                return []
            common: set[str] | None = None
            valid_ids = []
            for process_id in process_ids:
                try:
                    options = set(self.next_status_options(area, process_id))
                except Exception:
                    continue
                if not options:
                    continue
                common = options if common is None else common & options
                valid_ids.append(process_id)
            ordered = STATUS_FLOW_ORDER[area]
            return [status for status in ordered if common and status in common and valid_ids]
        return []

    def validate_batch_selection(
        self,
        area: str,
        process_ids: list[int],
        action_id: str = 'STATUS',
    ) -> dict[str, Any]:
        """Revalida no estado oficial atual uma seleção acumulada da interface.

        A função apenas consulta as regras já expostas por ``next_status_options``
        e ``process_actions``; não cria transições ou políticas de lote novas.
        """

        ordered_ids = list(dict.fromkeys(int(value) for value in process_ids if value))
        if not self.can_edit(area):
            return {
                'valid_ids': [],
                'incompatible': [
                    {'id': process_id, 'proposta': '', 'reason': 'sem permissão para alterar esta área'}
                    for process_id in ordered_ids
                ],
                'common_statuses': [],
                'global_reason': '',
            }

        valid_ids: list[int] = []
        incompatible: list[dict[str, Any]] = []
        status_options: dict[int, list[str]] = {}
        rows: list[dict[str, Any]] = []
        for process_id in ordered_ids:
            try:
                process = self.get_process_area_dict(process_id, area)
            except Exception as exc:
                incompatible.append({'id': process_id, 'proposta': '', 'reason': str(exc) or 'não encontrada'})
                continue
            if not process:
                incompatible.append({'id': process_id, 'proposta': '', 'reason': 'não encontrada'})
                continue
            proposal = process.get('proposta') or process.get('proposal_number') or str(process_id)
            if not self.process_visible_in_area(process, area):
                incompatible.append({'id': process_id, 'proposta': proposal, 'reason': 'não está mais disponível nesta área'})
                continue
            try:
                if action_id == 'DEFINE_ITEM_FLOW':
                    allowed = any(
                        action.get('id') == 'DEFINE_ITEM_FLOW'
                        for action in self.process_actions(process_id, area)
                    )
                    options = ['DEFINE_ITEM_FLOW'] if allowed else []
                else:
                    options = self.next_status_options(area, process_id)
            except Exception as exc:
                incompatible.append({'id': process_id, 'proposta': proposal, 'reason': str(exc) or 'estado indisponível'})
                continue
            if not options:
                incompatible.append({'id': process_id, 'proposta': proposal, 'reason': 'não possui ação compatível no estado atual'})
                continue
            valid_ids.append(process_id)
            status_options[process_id] = list(options)
            rows.append(process)

        common_statuses: list[str] = []
        global_reason = ''
        if action_id == 'STATUS' and valid_ids:
            common = set(status_options[valid_ids[0]])
            for process_id in valid_ids[1:]:
                common.intersection_update(status_options[process_id])
            common_statuses = [
                status for status in STATUS_FLOW_ORDER.get(area, []) if status in common
            ]
            if not common_statuses and not incompatible:
                summaries = []
                for process, process_id in zip(rows, valid_ids):
                    proposal = process.get('proposta') or process.get('proposal_number') or process_id
                    labels = ', '.join(self.action_label(area, status) for status in status_options[process_id])
                    summaries.append(f'{proposal}: {labels}')
                global_reason = 'Não existe uma ação comum para todas as propostas.\n' + '\n'.join(summaries[:20])

        return {
            'valid_ids': valid_ids,
            'incompatible': incompatible,
            'common_statuses': common_statuses,
            'global_reason': global_reason,
            'rows': rows,
        }

    def load_status_label(self, status: str) -> str:
        return legacy.load_status_label(status) 

    def can_mount_galvanization_load(self) -> bool:
        return self.can_edit('GALVANIZACAO')

    def _official_galvanization_rows(self, filters: dict[str, str] | None=None) -> list[dict[str, Any]]:
        filters = filters or {}
        text = (filters.get('text') or '').strip().upper()
        status_filter = (filters.get('status') or '').strip().upper()
        # A proposta pode ocupar mais de um bloco operacional ao mesmo tempo:
        # itens ainda aguardando carga e itens que ja pertencem a uma carga.
        # Agrupar apenas pelo processo fazia os itens restantes desaparecerem
        # assim que o primeiro lote era colocado em uma carga.
        grouped: dict[tuple[int, str], dict[str, Any]] = {}
        block_states: dict[tuple[int, str], set[str]] = {}

        def matches(row: dict[str, Any]) -> bool:
            if status_filter and (row.get('status_galvanizacao') or '').upper() != status_filter:
                return False
            if not text:
                return True
            haystack = ' '.join((str(row.get(key) or '') for key in ('proposta', 'cliente', 'obra_site', 'lote', 'carga_galvanizacao'))).upper()
            return text in haystack
        for row in self.official_proposal_storage.galvanization_load_candidates('', ''):
            normalized = dict(row)
            process_id = int(normalized.get('processo_id') or normalized.get('id') or 0)
            if not process_id:
                continue
            normalized.setdefault('status_galvanizacao', 'AGUARDANDO_ENVIO')
            normalized.setdefault('status_geral', 'EM_GALVANIZACAO')
            normalized['localizacao_atual'] = 'GALVANIZACAO'
            normalized['status_localizacao'] = normalized.get('status_galvanizacao') or 'AGUARDANDO_ENVIO'
            normalized['processo_id'] = process_id
            normalized['id'] = process_id
            normalized.pop('carga_galvanizacao', None)
            grouped[(process_id, 'CANDIDATE')] = normalized
        load_status_to_area_status = {'AGUARDANDO_LIBERACAO': 'EM_CARGA', 'LIBERADA_PARA_ENVIO': 'ENVIADO_GALVANIZACAO', 'RETORNO_PARCIAL': 'RETORNOU_PARCIAL'}
        # Quando a carga esta em retorno parcial, o status de CADA proposta
        # reflete o retorno DAQUELA proposta especifica (item['status_retorno'],
        # ja calculado pela API por proposta em _galvanization_load_detail),
        # nao o status agregado da carga inteira - uma proposta sem nenhum
        # item retornado ainda continua "Enviado para galvanizacao", nunca
        # "Retornou parcialmente" so porque outra proposta da mesma carga
        # ja retornou. O status da carga (load_status) permanece intocado.
        return_status_to_area_status = {
            'RETORNADO': 'RETORNOU_GALVANIZACAO',
            'RETORNO_PARCIAL': 'RETORNOU_PARCIAL',
            'AGUARDANDO_RETORNO': 'ENVIADO_GALVANIZACAO',
        }
        for load in self.official_proposal_storage.galvanization_loads():
            load_status = load.get('status') or ''
            area_status = load_status_to_area_status.get(load_status)
            if not area_status:
                continue
            for item in self.official_proposal_storage.galvanization_load_items(int(load['id'])):
                process_id = int(item.get('processo_id') or 0)
                if not process_id:
                    continue
                if load_status == 'RETORNO_PARCIAL':
                    proposal_area_status = return_status_to_area_status.get(item.get('status_retorno') or '', area_status)
                else:
                    proposal_area_status = area_status
                block_key = (process_id, f"LOAD:{int(load['id'])}")
                block_states.setdefault(block_key, set()).add(proposal_area_status)
                row = grouped.setdefault(block_key, {'id': process_id, 'processo_id': process_id, 'proposta': item.get('proposta') or '', 'cliente': item.get('cliente') or '', 'obra_site': item.get('obra_site') or '', 'lote': item.get('lote') or '', 'peso': item.get('peso_pendente') or item.get('peso_enviado') or ''})
                row.update({'status_galvanizacao': proposal_area_status, 'status_geral': 'EM_GALVANIZACAO', 'localizacao_atual': 'GALVANIZACAO', 'status_localizacao': proposal_area_status, 'carga_galvanizacao': int(load['id']), 'data_envio_galv': load.get('data_envio') or '', 'data_prevista_retorno_galv': load.get('data_prevista_retorno') or '', 'data_retorno_galv': load.get('data_retorno') or ''})
        # Um bloco de carga totalmente retornado deixa de aparecer na
        # galvanizacao. Um bloco parcialmente retornado continua visivel.
        for block_key, states in block_states.items():
            if states == {'RETORNOU_GALVANIZACAO'}:
                grouped.pop(block_key, None)
            elif len(states) > 1:
                grouped[block_key]['status_galvanizacao'] = 'RETORNOU_PARCIAL'
                grouped[block_key]['status_localizacao'] = 'RETORNOU_PARCIAL'
        rows = [
            row for row in grouped.values()
            if matches(row)
        ]
        return self._merge_partial_operational_rows(rows, 'GALVANIZACAO')

    def galvanization_load_candidates(self, proposal: str='', client: str='') -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_load_candidates(proposal, client)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def production_items_queue(self, filters: dict[str, Any] | None=None) -> list[dict[str, Any]]:
        filters = filters or {}
        try:
            return self.official_proposal_storage.production_items_queue(search=filters.get('text') or None, pending=filters.get('pending'), limit=500, offset=0)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_items_queue(self, filters: dict[str, Any] | None=None) -> list[dict[str, Any]]:
        filters = filters or {}
        try:
            return self.official_proposal_storage.galvanization_items_queue(search=filters.get('text') or None, situation=filters.get('situation') or None, limit=200, offset=0)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_loads(self) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_loads()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_load_items(self, load_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_load_items(load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_load_all_items(self, load_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_load_all_items(load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_conversations(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        try:
            return self.official_proposal_storage.chat_conversations(
                status=filters.get('status') or None,
                search=filters.get('search') or None,
                limit=filters.get('limit') or 200,
                offset=filters.get('offset') or 0,
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_messages(self, conversation_id: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        try:
            return self.official_proposal_storage.chat_messages(conversation_id, limit=filters.get('limit') or 500, offset=filters.get('offset') or 0)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_send_message(
        self,
        conversation_id: int,
        body: str,
        message_type: str = 'MENSAGEM',
        mentioned_user_id: int | None = None,
        reply_to_message_id: int | None = None,
        area: str | None = None,
        due_at=None,
        is_important: bool = False,
    ) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_send_message(
                conversation_id, body, message_type, mentioned_user_id, reply_to_message_id, area, due_at, is_important
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_answer_question(self, message_id: int, body: str) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_answer_question(message_id, body)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_proposal_timeline(self, proposal_id: int, **filters) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_proposal_timeline(proposal_id, **filters)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_mark_read(self, conversation_id: int, last_read_message_id: int) -> None:
        try:
            self.official_proposal_storage.chat_mark_read(conversation_id, last_read_message_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_unread_summary(self) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_unread_summary()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_mentionable_users(self, search: str | None = None) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.chat_mentionable_users(search=search or None)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.chat_notifications(limit=limit or 50)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_notifications_page(self, *, status: str | None = None, limit: int = 30, offset: int = 0) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_notifications_page(status=status, limit=limit or 30, offset=offset or 0)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_mark_all_notifications_read(self) -> None:
        try:
            self.official_proposal_storage.chat_mark_all_notifications_read()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_mark_notification_read(self, notification_id: int) -> None:
        try:
            self.official_proposal_storage.chat_mark_notification_read(notification_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_mark_question_viewed(self, message_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_mark_question_viewed(message_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_cancel_question(self, message_id: int, reason: str) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_cancel_question(message_id, reason)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def chat_reassign_question(self, message_id: int, assignee_user_id: int, reason: str) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.chat_reassign_question(message_id, assignee_user_id, reason)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def proposal_activities(self, proposal_id: int, area: str | None = None, before: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.proposal_activities(proposal_id, area=area or None, before=before or None, limit=limit or 50)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_available_weight_info(self, process_id: int, load_id: int | None=None) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.galvanization_available_weight_info(process_id, load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_load_proposal_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_load_proposal_items(load_id, process_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_return_proposals(self, load_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_return_proposals(load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_return_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.galvanization_return_items(load_id, process_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def get_galvanization_load_dict(self, load_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.get_galvanization_load_dict(load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_load_details(self, load_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.galvanization_load_details(load_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def galvanization_load_actions(self, load: dict[str, Any]) -> list[str]:
        """Ações que a UI pode oferecer; a API segue como autoridade final."""

        if not self.can_edit("GALVANIZACAO"):
            return []
        status = normalize_status(load.get("status"))
        if status == "AGUARDANDO_LIBERACAO":
            return ["EDIT", "RELEASE"]
        if status in {"LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"}:
            return ["RETURN"]
        return []

    def save_galvanization_load(
        self,
        driver: str,
        max_weight: str,
        expected_return_date: str,
        items: list[dict[str, Any]],
        load_id: int | None = None,
        *,
        load_weight: str | None | object = _UNSET,
        load_weight_source: str | None = "MANUAL",
        expected_version: int | None = None,
    ) -> int:
        if not self.can_edit('GALVANIZACAO'):
            raise AppError('Seu usuario nao pode alterar cargas de galvanizacao.')
        try:
            if load_weight is _UNSET:
                if expected_version is None:
                    return self.official_proposal_storage.save_galvanization_load(driver, max_weight, expected_return_date, items, load_id)
                return self.official_proposal_storage.save_galvanization_load(
                    driver,
                    max_weight,
                    expected_return_date,
                    items,
                    load_id,
                    expected_version=expected_version,
                )
            if expected_version is None:
                return self.official_proposal_storage.save_galvanization_load(
                    driver,
                    max_weight,
                    expected_return_date,
                    items,
                    load_id,
                    load_weight=load_weight,
                    load_weight_source=load_weight_source,
                )
            return self.official_proposal_storage.save_galvanization_load(
                driver,
                max_weight,
                expected_return_date,
                items,
                load_id,
                load_weight=load_weight,
                load_weight_source=load_weight_source,
                expected_version=expected_version,
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def add_items_to_galvanization_load(
        self,
        load_id: int,
        *,
        item_ids: list[int] | None = None,
        proposal_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        if not self.can_edit("GALVANIZACAO"):
            raise AppError("Seu usuario nao pode alterar cargas de galvanizacao.")
        try:
            return self.official_proposal_storage.add_items_to_galvanization_load(
                load_id, item_ids=item_ids, proposal_ids=proposal_ids
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def release_galvanization_load(self, load_id: int):
        if not self.can_edit('GALVANIZACAO'):
            raise AppError('Seu usuario nao pode liberar cargas de galvanizacao.')
        try:
            self.official_proposal_storage.release_galvanization_load(load_id)
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def mark_galvanization_load_returned(self, load_id: int):
        if not self.can_edit('GALVANIZACAO'):
            raise AppError('Seu usuario nao pode registrar retorno de galvanizacao.')
        try:
            proposals = self.official_proposal_storage.galvanization_return_proposals(load_id)
            self.official_proposal_storage.register_galvanization_partial_return(load_id, [{'processo_id': row.get('processo_id'), 'proposal_level': True} for row in proposals], 'Retorno total pelo desktop')
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def register_galvanization_partial_return(self, load_id: int, returned_items: list[dict[str, Any]], observation: str='') -> int:
        if not self.can_edit('GALVANIZACAO'):
            raise AppError('Seu usuario nao pode registrar retorno de galvanizacao.')
        try:
            return self.official_proposal_storage.register_galvanization_partial_return(load_id, returned_items, observation)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_rows(self, filters: dict[str, Any] | None=None) -> list[dict[str, Any]]:
        try:
            rows = self.official_proposal_storage.fiscal_rows(filters)
            return sort_fiscal_rows(self._merge_partial_operational_rows(rows, 'FISCAL'))
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def ensure_global_fiscal_entries(self) -> int:
        self.official_proposal_storage.fiscal_rows({})
        return 0

    def fiscal_items(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.fiscal_items(fiscal_processo_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_indicators(self) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.fiscal_indicators()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_indicator_rows(self, indicator: str) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.fiscal_indicator_rows(indicator)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_report_rows(self, report_type: str, filters: dict[str, Any] | None=None) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.fiscal_report_rows(report_type, filters)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_movements(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.fiscal_movements(fiscal_processo_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_emissions(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.fiscal_emissions(fiscal_processo_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_critical_pending(self, process_id: int) -> bool:
        return any((int(row.get('processo_id') or 0) == int(process_id) for row in self.official_proposal_storage.fiscal_indicator_rows('pendencia_critica')))

    def can_register_fiscal_emission(self) -> bool:
        return self.can_edit('fiscal')

    def can_cancel_fiscal_emission(self) -> bool:
        return self.can_edit('fiscal')

    def register_fiscal_emission(self, fiscal_processo_id: int, emissions: list[dict[str, Any]], numero_controle: str='', observacao: str='') -> int:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_register_fiscal_emission():
            raise legacy.AppError('Seu usuario nao tem permissao para registrar emissao fiscal.')
        try:
            return self.official_proposal_storage.register_fiscal_emission(fiscal_processo_id, emissions, numero_controle, observacao)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def mark_fiscal_invoice_withdrawn(self, fiscal_processo_id: int, observacao: str='') -> int | None:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_register_fiscal_emission():
            raise legacy.AppError('Seu usuario nao tem permissao para registrar retirada fiscal.')
        try:
            return self.official_proposal_storage.mark_fiscal_invoice_withdrawn(fiscal_processo_id, observacao)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def cancel_latest_fiscal_emission(self, fiscal_processo_id: int, reason: str='') -> int:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_cancel_fiscal_emission():
            raise legacy.AppError('Seu usuario nao tem permissao para cancelar emissao fiscal.')
        try:
            return self.official_proposal_storage.cancel_latest_fiscal_emission(fiscal_processo_id, reason)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def fiscal_status_label(self, status: str) -> str:
        labels = {'FALTA_EMITIR_NOTA_FISCAL': 'Falta emitir NF', 'AGUARDANDO_NF': 'CP em processamento', 'CP_EM_PROCESSAMENTO': 'CP em processamento', 'NF_EM_PROCESSAMENTO': 'NF em processamento', 'DISPONIVEL_PARA_EMISSAO': 'Disponivel para emitir NF', 'PENDENCIA_FISCAL_CRITICA': 'Pendencia fiscal critica', 'NOTA_FISCAL_PARCIAL': 'NF parcial', 'NF_PARCIAL': 'NF parcial', 'NOTA_FISCAL_EMITIDA': 'NF emitida', 'NF_EMITIDA': 'NF emitida', 'NF_RETIRADA_CLIENTE': 'NF retirada pelo cliente', 'FISCAL_CANCELADO': 'Fiscal cancelado', 'PENDENTE': 'Pendente', 'PARCIAL': 'Parcial', 'FATURADO': 'Faturado', 'CANCELADO': 'Cancelado'}
        return labels.get(legacy.normalize_status(status or ''), status or '-')

    def early_delivery_destination_candidates(self, search: str='') -> list[dict[str, Any]]:
        try:
            rows = self.official_proposal_storage.list_proposals(sort_by='updated_at', sort_dir='desc', limit=200, offset=0)
            text = search.strip().upper()
            return [row for row in rows if not text or text in (row.get('proposta') or '').upper() or text in (row.get('cliente') or '').upper() or (text in (row.get('obra_site') or '').upper())]
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def remanagement_source_candidates(self, exclude_process_id: int | None=None, search: str='') -> list[dict[str, Any]]:
        try:
            rows = self.official_proposal_storage.list_expedition_proposals(search=search or None, limit=200, offset=0)
            ready_statuses = {'SEPARADO', 'ENTREGUE_PARCIAL'}
            return [row for row in rows if int(row.get('id') or 0) != int(exclude_process_id or 0) and (row.get('status_expedicao') or '').upper() in ready_statuses]
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def deliver_by_material_remanagement(self, destination_id: int, source_id: int, observation: str, item_ids: list[int] | None=None):
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_edit('EXPEDICAO'):
            raise legacy.AppError('Seu usuario nao pode realizar remanejamentos.')
        try:
            self.official_proposal_storage.deliver_by_material_remanagement(destination_id, source_id, observation, item_ids=item_ids)
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def remanagement_compatible_items(self, source_id: int, destination_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.remanagement_compatible_items(source_id, destination_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def preview_material_remanagement(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.preview_material_remanagement(payload)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def apply_material_remanagement(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.user or not self.can_edit('EXPEDICAO'):
            raise legacy.AppError('Seu usuario nao pode realizar remanejamentos.')
        try:
            return self.official_proposal_storage.apply_material_remanagement(payload)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def stockroom_delivery_required(self, process_id: int) -> bool:
        return False

    def history_rows(self) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.history_rows()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def process_history_rows(self, process_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.process_history_rows(process_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def process_partials(self, process_id: int) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.process_partials(process_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def process_loads(self, process_id: int) -> list[dict[str, Any]]:
        loads = []
        try:
            galvanization_loads = self.official_proposal_storage.galvanization_loads()
        except Exception:
            return loads
        for load in galvanization_loads:
            try:
                items = self.official_proposal_storage.galvanization_load_items(int(load['id']))
            except Exception:
                continue
            if any((int(item.get('processo_id') or 0) == int(process_id) for item in items)):
                loads.append(load)
        return loads

    def audit_rows(self) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.audit_rows()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def saved_reports(self) -> list[dict[str, Any]]:
        return list(self.config.get('saved_reports', []))

    def save_palette(self, palette_name: str):
        palette_name = normalize_palette_name(palette_name)
        if palette_name not in self.palettes:
            raise legacy.AppError('Paleta invalida.')
        # Atualizacao parcial atomica em vez de reescrever o self.config inteiro
        # (que pode estar desatualizado em relacao a outras gravacoes feitas por
        # outras telas/threads desde que este BackendService foi inicializado).
        self.config = update_app_config({'color_palette': palette_name})

    def toggle_palette(self) -> str:
        next_palette = 'escuro' if self.palette_name == 'claro' else 'claro'
        self.save_palette(next_palette)
        return next_palette

    def backup_now(self):
        raise AppError('Backup local desativado. No modo oficial, o backup deve ser feito no PostgreSQL do servidor.')

    def choose_database(self, path: str):
        raise AppError('Troca de banco local desativada. O desktop usa somente a API/PostgreSQL oficial.')

    def database_health(self):
        api = self.config.get('desktop_api') or {}
        return {'status': 'ok', 'message': 'Banco operacional: PostgreSQL via API.', 'path': api.get('base_url', '')}

    def restore_backup(self, backup_path: str):
        raise AppError('Restauracao local desativada. Restaure backups diretamente no PostgreSQL do servidor.')

    def user_rows(self) -> list[dict[str, Any]]:
        try:
            return self.official_proposal_storage.user_rows()
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def get_user(self, user_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.get_user(user_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def profile_options(self):
        return list(legacy.PROFILE_OPTIONS)

    def profile_default_areas(self, profile: str) -> list[str]:
        return list(legacy.PROFILE_DEFAULT_AREAS.get(profile, []))

    def profile_default_permissions(self, profile: str) -> dict[str, str]:
        return dict(legacy.profile_default_permissions(profile))

    def user_permissions(self, user_id: int) -> dict[str, str]:
        defaults = {area['key']: legacy.PERMISSION_LEVEL_NONE for area in self.permission_area_options()}
        try:
            row = self.official_proposal_storage.get_user(user_id)
            return {**defaults, **dict(row.get('permissions') or {})}
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def _permission_summary(self, user_id: int) -> str:
        permissions = self.user_permissions(user_id)
        parts = []
        for area in self.permission_area_options():
            level = permissions.get(area['key'], legacy.PERMISSION_LEVEL_NONE)
            if level == legacy.PERMISSION_LEVEL_EDIT:
                parts.append(f"{area['label']}: alterar")
            elif level == legacy.PERMISSION_LEVEL_VIEW:
                parts.append(f"{area['label']}: visualizar")
        return ', '.join(parts) or 'Sem acesso'

    def save_user(self, data: dict[str, Any], user_id: int | None=None):
        nome = (data.get('nome') or '').strip()
        login = (data.get('login') or '').strip()
        password = data.get('password') or ''
        profile = data.get('perfil') or 'consulta'
        ativo = 1 if data.get('ativo', True) else 0
        if not nome:
            raise legacy.AppError('Informe o nome.')
        if not login:
            raise legacy.AppError('Informe o login.')
        if not user_id and (not password):
            raise legacy.AppError('Informe a senha inicial.')
        if password and (not self._valid_api_password(password)):
            raise legacy.AppError('A senha deve ter pelo menos 4 caracteres e nao pode ser uma sequencia simples.')
        try:
            self.official_proposal_storage.save_user({'nome': nome, 'login': login, 'password': password, 'perfil': profile, 'ativo': bool(ativo), 'permissions': dict(data.get('permissions') or {})}, user_id)
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def _valid_api_password(self, password: str) -> bool:
        compact = ''.join(str(password or '').split()).lower()
        weak_passwords = {'1234567890', '123456789', 'password123', 'senha12345', 'administrador', 'admin123456'}
        return len(password) >= 4 and compact not in weak_passwords and (len(set(compact)) > 2)

    def toggle_user(self, user_id: int):
        try:
            self.official_proposal_storage.toggle_user(user_id)
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def delete_user(self, user_id: int):
        try:
            self.official_proposal_storage.delete_user(user_id)
            return
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def get_process(self, process_id: int):
        return self.get_process_dict(process_id)

    def get_process_dict(self, process_id: int) -> dict[str, Any]:
        try:
            try:
                return self.official_proposal_storage.get_expedition_process(process_id)
            except Exception:
                pass
            try:
                return self.official_proposal_storage.get_production_process(process_id)
            except Exception:
                pass
            return self.official_proposal_storage.get_process(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def get_process_area_dict(self, process_id: int, area: str | None) -> dict[str, Any]:
        try:
            if area == 'CONTROLE GERAL':
                return self.official_proposal_storage.get_process(process_id)
            if area == 'PRODUCAO':
                return self.official_proposal_storage.get_production_process(process_id)
            if area == 'GALVANIZACAO':
                row = next((item for item in self._official_galvanization_rows({}) if int(item.get('id') or 0) == int(process_id)), None)
                if row:
                    return row
                return self.official_proposal_storage.get_process(process_id)
            if area == 'EXPEDICAO':
                return self.official_proposal_storage.get_expedition_process(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc
        return self.get_process_dict(process_id)

    def _official_control_process(self, process_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.get_process(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def next_status_options(self, area: str, process_id: int) -> list[str]:
        if area not in {'CONTROLE GERAL', 'PRODUCAO', 'EXPEDICAO', 'ALMOXARIFADO'} or not self.can_edit(area):
            return []
        if area == 'CONTROLE GERAL':
            process = self._official_control_process(process_id)
            status = process.get('status_geral') or process.get('current_status') or ''
            if process.get('is_cancelled') or status == 'CANCELADA':
                return []
            completed = bool(process.get('is_completed')) or status == 'ENTREGUE' or (process.get('status_expedicao') or '') == 'ENTREGUE'
            if completed:
                return []
            if status == 'AGUARDANDO_LIBERACAO':
                return ['LIBERADO_PRODUCAO', 'CANCELADA']
            return ['CANCELADA']
        if area == 'PRODUCAO':
            process = self.official_proposal_storage.get_production_process(process_id)
            status = process.get('status_producao') or process.get('current_status') or ''
            actions = {str(action.get('id') or ''): bool(action.get('enabled', True)) for action in process.get('actions') or []}
            options: list[str] = []
            if status in {'LIBERADO_PRODUCAO', 'NAO_INICIADO', 'ITEM_PENDENTE_FABRICACAO'} and actions.get('START_PRODUCTION', True):
                options.append('INICIADO')
            if status == 'PARADO' and actions.get('RESUME_PRODUCTION', True):
                options.append('INICIADO')
            if status == 'INICIADO' and actions.get('PAUSE_PRODUCTION', True):
                options.append('PARADO')
            if status in {'INICIADO', 'FINALIZADO_PARCIAL'} and actions.get('COMPLETE_ITEMS', True):
                options.extend(['FINALIZADO_PARCIAL', 'FINALIZADO'])
            if status == 'FINALIZADO_PARCIAL' and 'FINALIZADO' not in options:
                options.append('FINALIZADO')
            return options
        if area == 'EXPEDICAO':
            process = self.official_proposal_storage.get_expedition_process(process_id)
            status = process.get('status_expedicao') or process.get('current_status') or ''
            actions = {str(action.get('id') or ''): bool(action.get('enabled', True)) for action in process.get('actions') or []}
            options: list[str] = []
            if status in {'EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL'} and actions.get('START_SEPARATION', True):
                options.append('SEPARACAO_INICIADA')
            if status in {'EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARACAO_INICIADA', 'SEPARADO_COM_PENDENCIA', 'ENTREGUE_PARCIAL'} and actions.get('SEPARATE_ITEMS', True):
                options.append('SEPARADO')
            if status in {'SEPARADO', 'ENTREGUE_PARCIAL'} and actions.get('REGISTER_DELIVERY', True):
                options.extend(['ENTREGUE_PARCIAL', 'ENTREGUE'])
            return options
        if area == 'ALMOXARIFADO':
            process = self.official_proposal_storage.get_process(process_id)
            status = process.get('status_almoxarifado') or ''
            if status in ('AGUARDANDO_CONFIRMACAO', 'NAO_DEFINIDO', ''):
                return ['EM_SEPARACAO', 'SEM_PARAFUSOS']
            if status == 'EM_SEPARACAO':
                return ['SEPARADO']
            if status == 'SEPARADO':
                return ['ALMOXARIFADO_ENTREGUE', 'ALMOXARIFADO_ENTREGUE_PARCIAL']
            if status == 'ALMOXARIFADO_ENTREGUE_PARCIAL':
                return ['ALMOXARIFADO_ENTREGUE']
            return []
        return []

    def administrative_correction_options(self, process_id: int) -> dict[str, Any]:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_admin():
            raise legacy.AppError('Apenas administradores podem consultar correcoes administrativas.')
        try:
            return self.official_proposal_storage.administrative_correction_options(process_id)
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def preview_administrative_correction(
        self,
        process_id: int,
        expected_version: int,
        new_area: str,
        new_status: str,
    ) -> dict[str, Any]:
        if not self.user or not self.can_admin():
            raise legacy.AppError('Apenas administradores podem visualizar a previa da correcao.')
        try:
            return self.official_proposal_storage.preview_administrative_correction(
                process_id, expected_version, new_area, new_status
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def administrative_correction(
        self,
        process_id: int,
        expected_version: int,
        new_area: str,
        new_status: str,
        reason: str,
        idempotency_key: str,
    ):
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_admin():
            raise legacy.AppError('Apenas administradores podem aplicar correcao administrativa.')
        reason = (reason or '').strip()
        if not reason:
            raise legacy.AppError('Informe o motivo da correcao.')
        try:
            return self.official_proposal_storage.administrative_correction(
                process_id,
                expected_version,
                new_area,
                new_status,
                reason,
                idempotency_key,
            )
        except Exception as exc:
            raise self._api_app_error(exc) from exc

    def process_actions(self, process_id: int, area: str | None=None, row_context: dict[str, Any] | None = None) -> list[dict[str, str]]:
        if area == 'CONTROLE GERAL':
            if not self.can_edit(area):
                return []
            process = self._official_control_process(process_id)
            status = process.get('status_geral') or process.get('current_status') or ''
            if process.get('is_cancelled') or status == 'CANCELADA':
                return []
            actions: list[dict[str, str]] = []
            if status == 'AGUARDANDO_LIBERACAO':
                actions.append({'id': 'STATUS', 'label': 'Liberar para producao', 'icon': 'production', 'status': 'LIBERADO_PRODUCAO', 'area': 'CONTROLE GERAL'})
            completed = bool(process.get('is_completed')) or status == 'ENTREGUE' or (process.get('status_expedicao') or '') == 'ENTREGUE'
            if not completed:
                actions.append({'id': 'STATUS', 'label': 'Cancelar proposta', 'icon': 'delete', 'status': 'CANCELADA', 'area': 'CONTROLE GERAL'})
            return actions
        if area == 'EXPEDICAO':
            if not self.can_edit(area):
                return []
            try:
                process = self.official_proposal_storage.get_expedition_process(process_id)
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
            status = process.get('status_expedicao') or ''
            enabled_actions = {str(action.get('id') or ''): bool(action.get('enabled', True)) for action in process.get('actions') or []}
            actions: list[dict[str, str]] = []

            def add(action_id: str, label: str, icon: str, status_value: str=''):
                actions.append({'id': action_id, 'label': label, 'icon': icon, 'status': status_value, 'area': 'EXPEDICAO'})
            if status in ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL') and enabled_actions.get('START_SEPARATION', True):
                add('STATUS', 'Iniciar separacao', 'status', 'SEPARACAO_INICIADA')
            if status in ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARACAO_INICIADA', 'SEPARADO_COM_PENDENCIA', 'ENTREGUE_PARCIAL') and enabled_actions.get('SEPARATE_ITEMS', True):
                add('STATUS', 'Registrar separacao', 'status', 'SEPARADO')
            if status in ('SEPARADO', 'ENTREGUE_PARCIAL') and enabled_actions.get('REGISTER_DELIVERY', True):
                add('REGISTER_DELIVERY', 'Registrar retirada do cliente', 'status')
            return actions
        if area == 'PRODUCAO':
            if not self.can_edit(area):
                return []
            try:
                process = self.official_proposal_storage.get_production_process(process_id)
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
            status = process.get('status_producao') or ''
            enabled_actions = {str(action.get('id') or ''): bool(action.get('enabled', True)) for action in process.get('actions') or []}
            actions: list[dict[str, str]] = []

            def add(action_id: str, label: str, icon: str, status_value: str=''):
                actions.append({'id': action_id, 'label': label, 'icon': icon, 'status': status_value, 'area': 'PRODUCAO'})
            summary = process.get('progresso_producao') or {}
            if enabled_actions.get('DEFINE_ITEM_FLOW', status != 'FINALIZADO'):
                add('DEFINE_ITEM_FLOW', 'Definir fluxo dos itens pendentes' if summary.get('undefined_flow_items') else 'Definir fluxo dos itens', 'settings')
            if status in ('NAO_INICIADO', 'LIBERADO_PRODUCAO', 'ITEM_PENDENTE_FABRICACAO') and enabled_actions.get('START_PRODUCTION', True):
                add('STATUS', 'Iniciar producao', 'production', 'INICIADO')
            if status == 'PARADO' and enabled_actions.get('RESUME_PRODUCTION', True):
                add('STATUS', 'Retomar producao', 'production', 'INICIADO')
            if status == 'INICIADO' and enabled_actions.get('PAUSE_PRODUCTION', True):
                add('STATUS', 'Pausar producao', 'pause', 'PARADO')
            if status in ('INICIADO', 'FINALIZADO_PARCIAL') and enabled_actions.get('COMPLETE_ITEMS', True):
                add('REGISTER_PRODUCTION', 'Registrar producao', 'status')
            if enabled_actions.get('UPDATE_ITEM_WEIGHTS', status != 'FINALIZADO'):
                add('EDIT_ITEM_WEIGHTS', 'Informar pesos dos itens', 'edit')
            return actions
        if area == 'GALVANIZACAO':
            if not self.can_edit(area):
                return []
            candidate_rows = [row for row in self._official_galvanization_rows({}) if int(row.get('id') or 0) == int(process_id)]
            process = None
            if row_context:
                desired_load = row_context.get('carga_galvanizacao')
                desired_status = row_context.get('status_galvanizacao')
                process = next((row for row in candidate_rows if str(row.get('carga_galvanizacao') or '') == str(desired_load or '') and (not desired_status or row.get('status_galvanizacao') == desired_status)), None)
            process = process or next((row for row in candidate_rows if row.get('carga_galvanizacao')), None) or (candidate_rows[0] if candidate_rows else None)
            if not process:
                return []
            status = process.get('status_galvanizacao') or ''
            actions: list[dict[str, str]] = []

            def add(action_id: str, label: str, icon: str, status_value: str=''):
                actions.append({'id': action_id, 'label': label, 'icon': icon, 'status': status_value, 'area': 'GALVANIZACAO'})
            if status in ('AGUARDANDO_ENVIO', 'DISPONIVEL_PARCIAL'):
                add('MANAGE_LOAD', 'Adicionar a uma carga', 'load', 'EM_CARGA')
            if status in ('ENVIADO_GALVANIZACAO', 'RETORNOU_PARCIAL'):
                active_loads = [row for row in self.process_loads(process_id) if (row.get('status') or '') in ('LIBERADA_PARA_ENVIO', 'RETORNO_PARCIAL')]
                if active_loads:
                    add('REGISTER_GALVANIZATION_RETURN', 'Registrar retorno da galvanizacao', 'load', 'RETORNOU_GALVANIZACAO')
            return actions
        if area == 'ALMOXARIFADO':
            if not self.can_edit(area):
                return []
            options = self.next_status_options(area, process_id)
            process = self.official_proposal_storage.get_process(process_id)
            current_status = process.get('status_almoxarifado') or ''
            if current_status in ('NAO_DEFINIDO', ''):
                labels = {'EM_SEPARACAO': ('Precisa de Almoxarifado', 'stock'), 'SEM_PARAFUSOS': ('Nao precisa de Almoxarifado', 'clear')}
            else:
                labels = {'EM_SEPARACAO': ('Confirmar que possui almoxarifado', 'stock'), 'SEM_PARAFUSOS': ('Confirmar sem almoxarifado', 'clear'), 'SEPARADO': ('Confirmar separacao concluida', 'status'), 'ALMOXARIFADO_ENTREGUE': ('Confirmar entrega do almoxarifado', 'status'), 'ALMOXARIFADO_ENTREGUE_PARCIAL': ('Registrar entrega parcial', 'status')}
            actions: list[dict[str, str]] = []
            for status in options:
                label, icon = labels.get(status, (self.area_status_label(area, status), 'status'))
                actions.append({'id': 'STATUS', 'label': label, 'icon': icon, 'status': status, 'area': 'ALMOXARIFADO'})
            return actions
        return []

    def action_label(self, area: str, status: str) -> str:
        if area == 'ALMOXARIFADO' and status == 'EM_SEPARACAO':
            return 'Confirmar que possui almoxarifado'
        labels = {'LIBERADO_PRODUCAO': 'Liberar para producao', 'CANCELADA': 'Cancelar proposta', 'INICIADO': 'Iniciar ou retomar producao', 'PARADO': 'Pausar producao', 'FINALIZADO': 'Concluir producao', 'FINALIZADO_PARCIAL': 'Registrar producao parcial', 'EM_CARGA': 'Adicionar a carga', 'ENVIADO_GALVANIZACAO': 'Liberar carga para envio', 'RETORNOU_GALVANIZACAO': 'Confirmar retorno da carga', 'SEPARADO': 'Confirmar separacao concluida', 'ENTREGUE': 'Confirmar entrega completa', 'ENTREGUE_PARCIAL': 'Registrar retirada parcial', 'SEPARACAO_INICIADA': 'Iniciar separacao', 'SEM_PARAFUSOS': 'Confirmar sem almoxarifado', 'ALMOXARIFADO_ENTREGUE': 'Confirmar entrega do almoxarifado', 'ALMOXARIFADO_ENTREGUE_PARCIAL': 'Registrar entrega parcial do almoxarifado'}
        if status == 'SEPARADO_COM_PENDENCIA':
            return 'Separado com pendencia'
        return labels.get(status, self.area_status_label(area, status))

    def update_status(self, process_id: int, area: str, status: str, observation: str='', item_ids: list[int] | None=None, produced_weight: float | None=None):
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if area == 'CONTROLE GERAL':
            try:
                process = self.official_proposal_storage.get_process(process_id)
                version = int(process.get('api_version') or process.get('version') or 0)
                if status == 'LIBERADO_PRODUCAO':
                    self.official_proposal_storage.release_to_production(process_id, version)
                    return
                if status == 'CANCELADA':
                    self.official_proposal_storage.cancel_process(process_id, version, observation)
                    return
                raise legacy.AppError('Status do Controle Geral nao suportado no fluxo oficial.')
            except legacy.AppError:
                raise
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'PRODUCAO':
            try:
                process = self.official_proposal_storage.get_production_process(process_id)
                version = int(process.get('api_version') or 0)
                current_status = str(process.get('status_producao') or process.get('current_status') or '').strip().upper()
                if status == 'INICIADO':
                    if current_status == 'PARADO':
                        self.official_proposal_storage.resume_production(process_id, version, observation)
                    else:
                        self.official_proposal_storage.start_production(process_id, version, observation)
                    return
                if status == 'PARADO':
                    reason = (observation or '').strip()
                    if not reason:
                        raise legacy.AppError('Informe o motivo da pausa.')
                    self.official_proposal_storage.pause_production(process_id, version, reason)
                    return
                if status in ('FINALIZADO', 'FINALIZADO_PARCIAL'):
                    self.official_proposal_storage.complete_production_items(process_id, version, item_ids=item_ids, observation=observation)
                    return
                raise legacy.AppError('Status de Producao nao suportado no fluxo oficial.')
            except legacy.AppError:
                raise
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'EXPEDICAO':
            if not self.can_edit(area):
                raise legacy.AppError('Seu usuario nao pode alterar a Expedicao.')
            try:
                process = self.official_proposal_storage.get_expedition_process(process_id)
                version = int(process.get('api_version') or 0)
                if status == 'SEPARACAO_INICIADA':
                    self.official_proposal_storage.start_expedition_separation(process_id, version, observation)
                    return
                if status == 'SEPARADO':
                    self.official_proposal_storage.separate_expedition_items(process_id, version, item_ids=item_ids, observation=observation)
                    return
                if status in ('ENTREGUE', 'ENTREGUE_PARCIAL'):
                    self.official_proposal_storage.deliver_expedition_items(process_id, version, item_ids=item_ids, observation=observation)
                    return
                raise legacy.AppError('Status de Expedicao nao suportado no fluxo oficial.')
            except legacy.AppError:
                raise
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        if area == 'ALMOXARIFADO':
            if not self.can_edit(area):
                raise legacy.AppError('Seu usuario nao pode alterar o Almoxarifado.')
            try:
                process = self.official_proposal_storage.get_process(process_id)
                version = int(process.get('api_version') or process.get('version') or 0)
                self.official_proposal_storage.update_warehouse_status(process_id, version, status, observation)
                return
            except legacy.AppError:
                raise
            except Exception as exc:
                raise AppError(user_message_for_api_error(exc)) from exc
        raise legacy.AppError('Area/status nao suportado no fluxo oficial.')

    def save_process(self, data: dict[str, Any], process_id: int | None=None, import_metadata: dict[str, Any] | None=None) -> int:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        try:
            return self.official_proposal_storage.save_process(data, process_id, import_metadata)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def proposal_items(self, process_id: int, pending_production: bool=False, pending_delivery: bool=False) -> list[dict[str, Any]]:
        try:
            if pending_delivery:
                return self.official_proposal_storage.expedition_items(process_id, pending_delivery=True)
            if pending_production:
                return self.official_proposal_storage.production_items(process_id, pending_production=True)
            return self.official_proposal_storage.proposal_items(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def cancel_official_proposal(self, process_id: int, version: int, reason: str) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.cancel_process(process_id, version, reason)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def release_official_proposal_to_production(self, process_id: int, version: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.release_to_production(process_id, version)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def update_item_weights(self, process_id: int, weights: dict[int, float]) -> int:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_edit('PRODUCAO'):
            raise legacy.AppError('Seu usuario nao pode alterar dados da Producao.')
        if not weights:
            return 0
        try:
            process = self.official_proposal_storage.get_production_process(process_id)
            return self.official_proposal_storage.update_production_item_weights(process_id, int(process.get('api_version') or 0), weights)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def item_flow_summary(self, process_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.production_item_flow_summary(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def item_no_production_reasons(self) -> list[tuple[str, str]]:
        return [(key, legacy.ITEM_NO_PRODUCTION_LABELS[key]) for key in ('pronta_entrega', 'comprado_terceiro', 'terceirizado', 'outro')]

    def flow_review_data(self, process_id: int) -> dict[str, Any]:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_edit('PRODUCAO'):
            raise legacy.AppError('Seu usuario nao pode definir fluxo dos itens.')
        try:
            return self.official_proposal_storage.flow_review_data(process_id)
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def update_item_flow(self, process_id: int, definitions: list[dict[str, Any]], origin: str='Producao') -> int:
        if not self.user:
            raise legacy.AppError('Usuario nao autenticado.')
        if not self.can_edit('PRODUCAO'):
            raise legacy.AppError('Seu usuario nao pode definir fluxo dos itens.')
        process = self.official_proposal_storage.get_production_process(process_id)
        version = int(process.get('api_version') or 0)
        log.debug('Salvando fluxo: process_id=%r version_enviada=%r itens=%d', process_id, version, len(definitions))
        try:
            return self.official_proposal_storage.update_production_item_flow(process_id, version, definitions, origin)
        except ApiBusinessError as exc:
            if exc.error_code == 'PROPOSAL_VERSION_CONFLICT':
                raise VersionConflictError(user_message_for_api_error(exc)) from exc
            raise AppError(user_message_for_api_error(exc)) from exc
        except Exception as exc:
            raise AppError(user_message_for_api_error(exc)) from exc

    def item_progress(self, process_id: int) -> dict[str, Any]:
        try:
            return self.official_proposal_storage.production_item_flow_summary(process_id)
        except Exception:
            return {'total': 0, 'produced': 0, 'pending': 0}

    def weight_progress_text(self, process_id: int) -> str:
        try:
            process = self.official_proposal_storage.get_production_process(process_id)
            produced = process.get('peso_produzido') or process.get('produced_weight') or 0
            total = process.get('peso') or process.get('total_weight') or 0
            return f'{produced}/{total} kg'
        except Exception:
            return '-'

    def current_location(self, process: dict[str, Any]) -> tuple[str, str, str]:
        area_order = (('EXPEDICAO', 'Expedicao', 'status_expedicao'), ('GALVANIZACAO', 'Galvanizacao', 'status_galvanizacao'), ('PRODUCAO', 'Producao', 'status_producao'), ('CONTROLE GERAL', 'Controle geral', 'status_geral'))
        if (process.get('tipo_processo') or 'PRINCIPAL') == 'PRINCIPAL':
            if (process.get('status_producao') or '') in ('FINALIZADO_PARCIAL', 'ITEM_PENDENTE_FABRICACAO'):
                return ('PRODUCAO', 'Producao', process.get('status_producao') or '')
        if (process.get('status_expedicao') or '') == 'UNIFICADA_PRINCIPAL':
            return ('CONTROLE GERAL', 'Controle geral', 'UNIFICADA_PRINCIPAL')
        for area_key, area_label, column in area_order:
            status = legacy.normalize_status(process.get(column) or '')
            if not status:
                continue
            if area_key != 'CONTROLE GERAL' and status in legacy.AREA_FINISHED_STATUS.get(area_key, set()):
                continue
            if area_key == 'EXPEDICAO' and status == 'UNIFICADA_PRINCIPAL':
                continue
            return (area_key, area_label, status)
        status = legacy.normalize_status(process.get('status_geral') or '')
        return ('CONTROLE GERAL', 'Controle geral', status) if status else ('', '', '')

    def display_cell(self, key: str, value: Any, row: dict[str, Any] | None=None) -> str:
        if key == 'id' and row:
            parent_id = row.get('processo_pai_id')
            partial_number = int(row.get('numero_parcial') or 0)
            if parent_id and partial_number:
                return f'{parent_id}-P{partial_number}'
            return str(row.get('id') or '')
        if key == 'progresso_peso' and row:
            if row.get('api_id'):
                produced = row.get('peso_produzido')
                total = row.get('peso')
                if produced not in (None, '') and total not in (None, ''):
                    return f'{produced}/{total} kg'
                return str(total or '-')
            return str(row.get('peso') or '-')
        if key == 'carga_galvanizacao' and row:
            load_id = row.get('carga_galvanizacao')
            return f'Carga {load_id}' if load_id else '-'
        if key == 'localizacao_atual' and row:
            return self.current_location(row)[1] or '-'
        if key == 'status_localizacao' and row:
            area, _label, status = self.current_location(row)
            return self.area_status_label(area, status) if status else '-'
        if key == 'status_almoxarifado' and row:
            return self.area_status_label('ALMOXARIFADO', value) if value else '-'
        if key == 'necessita_almoxarifado' and row:
            return self.status_label(value) if value else '-'
        if key == 'almoxarifado_info':
            status = (row or {}).get('status_almoxarifado', '') if row else ''
            need = legacy.normalize_stockroom_need((row or {}).get('necessita_almoxarifado', '') if row else '')
            status = legacy.normalize_status(status)
            if need == 'NAO' or status == 'SEM_PARAFUSOS':
                return 'Sem Almox.'
            if status == 'ALMOXARIFADO_ENTREGUE':
                return 'Almox. entregue'
            if status:
                return 'Tem Almox.'
            return 'Almox. indef.'
        return legacy.display_cell(key, value)

    def close(self):
        self.official_proposal_storage.close()
        return

def _desktop_operational_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.hostname or '').lower() != 'host.docker.internal':
        return value
    netloc = '127.0.0.1'
    if parsed.port:
        netloc = f'{netloc}:{parsed.port}'
    return urlunparse((parsed.scheme, netloc, parsed.path, '', '', ''))
