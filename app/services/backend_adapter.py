from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.services import production_repository as legacy
from app.services.status_sorting import sort_fiscal_rows, sort_process_rows
from app.services.app_paths import (
    ensure_app_data_dirs,
    get_backup_dir,
    get_config_example_path,
    get_config_path,
    get_database_path,
)
from app.services.migration_runner import apply_migrations
from app.services.app_logging import get_logger
from app.services.sqlite_safety import create_daily_backup, inspect_database, require_healthy_database, safe_backup


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "app"
log = get_logger("backend")

THEME_ALIASES = {
    "aurora": "claro",
    "aurora professional": "claro",
    "aurora profissional": "claro",
    "energia": "claro",
    "verde operacional": "claro",
    "grafite": "escuro",
    "grafite alto contraste": "escuro",
    "pulso": "escuro",
    "pulso executivo": "escuro",
}

OFFICIAL_COLOR_PALETTES = {
    "claro": {
        **legacy.COLOR_PALETTES["aurora"],
        "label": "Claro",
    },
    "escuro": {
        **legacy.COLOR_PALETTES["grafite"],
        "label": "Escuro",
        "bg": "#0f172a",
        "surface": "#172033",
        "surface_alt": "#24324a",
        "text": "#f8fafc",
        "muted": "#dbeafe",
        "border": "#475569",
        "accent": "#38bdf8",
        "accent_hover": "#7dd3fc",
        "accent_text": "#0f172a",
    },
}


def normalize_palette_name(name: str | None) -> str:
    normalized = (name or "claro").strip().lower()
    normalized = THEME_ALIASES.get(normalized, normalized)
    return normalized if normalized in OFFICIAL_COLOR_PALETTES else "claro"


def _load_config_example() -> dict[str, Any]:
    example_path = get_config_example_path()
    if not example_path.exists():
        return {}
    with example_path.open("r", encoding="utf-8") as file:
        return legacy.json.load(file)


def load_app_config() -> dict[str, Any]:
    ensure_app_data_dirs()
    config_path = get_config_path()
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as file:
            data = legacy.json.load(file)
        data.setdefault("db_path", str(get_database_path()))
        data.setdefault("backup_dir", str(get_backup_dir()))
    else:
        data = _load_config_example()
        data["db_path"] = str(get_database_path())
        data["backup_dir"] = str(get_backup_dir())
    data.setdefault("backup_keep", 20)
    data.setdefault("company", "Industel")
    data.setdefault("color_palette", "claro")
    data.setdefault("saved_reports", legacy.DEFAULT_REPORT_DEFINITIONS)
    data["color_palette"] = normalize_palette_name(data.get("color_palette"))
    save_app_config(data)
    return data


def save_app_config(config: dict[str, Any]):
    ensure_app_data_dirs()
    with get_config_path().open("w", encoding="utf-8") as file:
        legacy.json.dump(config, file, ensure_ascii=False, indent=2)


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


class BackendService:
    """Adapter that preserves the existing SQLite backend and business rules."""

    def __init__(self):
        self.config = load_app_config()
        db_path = Path(self.config["db_path"])
        if db_path.exists() and db_path.stat().st_size > 0:
            require_healthy_database(db_path)
            safe_backup(db_path, self.config["backup_dir"], "antes_migracao")
        self.conn = legacy.db_connect(self.config["db_path"])
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.repo = legacy.Repository(self.conn)
        self.user = None
        if db_path.exists() and db_path.stat().st_size > 0:
            create_daily_backup(db_path, self.config["backup_dir"])
        log.info("Backend inicializado | banco=%s", self.config["db_path"])

    @property
    def palettes(self):
        return OFFICIAL_COLOR_PALETTES

    @property
    def palette_name(self) -> str:
        return normalize_palette_name(self.config.get("color_palette"))

    @property
    def palette(self):
        return self.palettes.get(self.palette_name, self.palettes["claro"])

    @property
    def company(self) -> str:
        return self.config.get("company", "Industel")

    def authenticate(self, login: str, password: str) -> bool:
        user = self.repo.authenticate(login, password)
        self.user = user
        return bool(user)

    def user_name(self) -> str:
        if not self.user:
            return "-"
        return self.user["nome"] or self.user["login"]

    def user_profile(self) -> str:
        if not self.user:
            return "-"
        return "Administrador" if legacy.user_can_admin(self.user) else "Usuario"

    def visible_areas(self) -> list[str]:
        if not self.user:
            return []
        return [
            area
            for area in legacy.AREAS
            if legacy.user_can_view_area(self.conn, self.user, area)
        ]

    def permission_key(self, area: str) -> str:
        return legacy.normalize_permission_area(area)

    def permission_area_options(self) -> list[dict[str, str]]:
        return legacy.permission_area_options()

    def access_level_options(self) -> list[tuple[str, str]]:
        return [(level, legacy.permission_level_label(level)) for level in legacy.PERMISSION_LEVELS]

    def permission_level(self, area_key: str) -> str:
        return legacy.user_permission_level(self.conn, self.user, area_key)

    def can_view(self, area_key: str) -> bool:
        return bool(self.user and legacy.user_can_view_area(self.conn, self.user, area_key))

    def can_edit(self, area_key: str) -> bool:
        return bool(self.user and legacy.user_can_edit_area(self.conn, self.user, area_key))

    def can_view_nav(self, nav_key: str) -> bool:
        return self.can_view(self.permission_key(nav_key))

    def can_edit_process(self) -> bool:
        return self.can_edit("control_general")

    def can_admin(self) -> bool:
        return bool(self.user and legacy.user_can_admin(self.user))

    def can_access_area(self, area: str) -> bool:
        return self.can_view(area)

    def can_edit_area(self, area: str) -> bool:
        return self.can_edit(area)

    def dashboard(self) -> dict[str, Any]:
        return dict(self.repo.dashboard())

    def dashboard_charts(self) -> dict[str, Any]:
        return self.repo.dashboard_charts()

    def focus_text(self) -> str:
        return self.repo.dashboard_focus_text()

    def dashboard_metric_rows(self, metric: str) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.dashboard_metric_rows(metric)]

    def dashboard_chart_rows(self, chart_key: str, label: str) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.dashboard_chart_rows(chart_key, label)]

    def list_status(self, area: str | None = None) -> list[str]:
        return self.repo.list_status(area)

    def status_label(self, status: str) -> str:
        return legacy.status_label(status)

    def area_status_label(self, area: str, status: str) -> str:
        return legacy.area_status_label(area, status)

    def process_rows(self, area: str | None = None, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        filters = dict(filters or {})
        if area and area in legacy.AREAS:
            filters["area"] = area
            filters["status_area"] = area
        rows = self.repo.list_processes(filters)
        if area and area in legacy.AREAS:
            rows = [row for row in rows if self.repo.visible_for_area(row, area)]
            if area == "CONTROLE GERAL":
                rows = [row for row in rows if not self.repo.is_partial_process(row)]
        elif area == "PARCIAIS":
            rows = self.repo.list_partial_pending_processes(filters)
        result = [row_to_dict(row) for row in rows]
        if area == "GALVANIZACAO":
            load_ids = self.repo.current_galvanization_load_ids(row["id"] for row in result)
            for row in result:
                row["carga_galvanizacao"] = load_ids.get(int(row["id"]))
        return sort_process_rows(area, result)

    def sort_process_rows(self, area: str | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sort_process_rows(area, rows)

    def process_visible_in_area(self, process: dict[str, Any] | Any, area: str) -> bool:
        if area == "CONTROLE GERAL":
            process_row = process
            if isinstance(process, dict):
                process_row = self.repo.get_process(int(process["id"]))
            return bool(process_row and not self.repo.is_partial_process(process_row))
        if area not in legacy.AREAS:
            return False
        process_row = process
        if isinstance(process, dict):
            process_row = self.repo.get_process(int(process["id"]))
        return bool(process_row and self.repo.visible_for_area(process_row, area))

    def batch_status_candidates(self, area: str, text: str = "", exclude_ids: set[int] | None = None) -> list[dict[str, Any]]:
        exclude_ids = exclude_ids or set()
        filters = {"text": text.strip()} if text.strip() else {}
        rows = self.repo.list_processes(filters)
        result = []
        for row in rows:
            if int(row["id"]) in exclude_ids:
                continue
            if not self.process_visible_in_area(row, area):
                continue
            options = set(self.repo.next_status_options(area, row))
            if (
                area == "EXPEDICAO"
                and (row["status_expedicao"] or "") == "ENTREGUE_PARCIAL"
                and self.repo.expedition_completion_requires_remanagement(row)
                and not self.repo.expedition_delivery_can_close_after_customer_partial(row)
            ):
                options.discard("ENTREGUE")
            if not options:
                continue
            result.append(row_to_dict(row))
            if len(result) >= 300:
                break
        return result

    def status_for_area(self, process: dict[str, Any], area: str) -> str:
        if area in legacy.AREAS:
            return process.get(legacy.AREAS[area]["column"]) or process.get("status_geral") or ""
        return process.get("status_geral") or ""

    def common_next_statuses(self, area: str, process_ids: list[int]) -> list[str]:
        common = None
        valid_ids = []
        for process_id in process_ids:
            process = self.repo.get_process(process_id)
            if not process:
                continue
            if not self.process_visible_in_area(process, area):
                continue
            options = set(self.repo.next_status_options(area, process))
            if self.repo.list_proposal_items(process_id):
                if area == "PRODUCAO":
                    options.discard("FINALIZADO_PARCIAL")
            if (
                area == "EXPEDICAO"
                and (process["status_expedicao"] or "") == "ENTREGUE_PARCIAL"
                and self.repo.expedition_completion_requires_remanagement(process)
                and not self.repo.expedition_delivery_can_close_after_customer_partial(process)
            ):
                options.discard("ENTREGUE")
            common = options if common is None else common & options
            valid_ids.append(process_id)
        ordered = legacy.STATUS_FLOW_ORDER.get(area, self.repo.list_status(area))
        return [status for status in ordered if common and status in common and valid_ids]

    def load_status_label(self, status: str) -> str:
        return legacy.load_status_label(status)

    def can_mount_galvanization_load(self) -> bool:
        return self.can_edit("galvanization") or self.can_edit("expedition")

    def galvanization_load_candidates(self, proposal: str = "", client: str = "") -> list[dict[str, Any]]:
        proposal = proposal.strip().upper()
        client = client.strip().upper()
        rows = []
        for row in self.repo.list_galvanization_load_candidates():
            if proposal and proposal not in (row["proposta"] or "").upper():
                continue
            if client and client not in (row["cliente"] or "").upper():
                continue
            rows.append(row_to_dict(row))
        return rows

    def galvanization_loads(self) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_loads()]

    def galvanization_load_items(self, load_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_load_items(load_id)]

    def galvanization_available_weight_info(self, process_id: int, load_id: int | None = None) -> dict[str, Any]:
        return self.repo.galvanization_available_weight_info(process_id, exclude_load_id=load_id)

    def galvanization_load_proposal_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_load_proposal_items(load_id, process_id)]

    def galvanization_return_proposals(self, load_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_return_proposals(load_id)]

    def galvanization_return_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_return_items(load_id, process_id)]

    def get_galvanization_load_dict(self, load_id: int) -> dict[str, Any]:
        return row_to_dict(self.repo.get_galvanization_load(load_id))

    def save_galvanization_load(
        self,
        driver: str,
        max_weight: str,
        expected_return_date: str,
        items: list[dict[str, Any]],
        load_id: int | None = None,
    ) -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        return self.repo.save_galvanization_load(driver, max_weight, expected_return_date, items, self.user, load_id)

    def release_galvanization_load(self, load_id: int):
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        self.repo.release_galvanization_load(load_id, self.user)

    def mark_galvanization_load_returned(self, load_id: int):
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        self.repo.mark_galvanization_load_returned(load_id, self.user)

    def register_galvanization_partial_return(self, load_id: int, returned_items: list[dict[str, Any]], observation: str = "") -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        return self.repo.register_galvanization_partial_return(load_id, returned_items, self.user, observation)

    def fiscal_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return sort_fiscal_rows(row_to_dict(row) for row in self.repo.list_fiscal_processes(filters))

    def fiscal_items(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_fiscal_items(fiscal_processo_id)]

    def fiscal_indicators(self) -> dict[str, Any]:
        return self.repo.fiscal_indicators()

    def fiscal_indicator_rows(self, indicator: str) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.fiscal_indicator_rows(indicator)]

    def fiscal_report_rows(self, report_type: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.fiscal_report_rows(report_type, filters)]

    def fiscal_movements(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_fiscal_movements(fiscal_processo_id)]

    def fiscal_emissions(self, fiscal_processo_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_fiscal_emissions(fiscal_processo_id)]

    def fiscal_critical_pending(self, process_id: int) -> bool:
        return self.repo.identificar_pendencia_fiscal_critica(process_id)

    def can_register_fiscal_emission(self) -> bool:
        return self.can_edit("fiscal")

    def register_fiscal_emission(
        self,
        fiscal_processo_id: int,
        emissions: list[dict[str, Any]],
        numero_controle: str = "",
        observacao: str = "",
    ) -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        return self.repo.register_fiscal_emission(
            fiscal_processo_id,
            emissions,
            self.user,
            numero_controle=numero_controle,
            observacao=observacao,
        )

    def fiscal_status_label(self, status: str) -> str:
        labels = {
            "FALTA_EMITIR_NOTA_FISCAL": "Falta emitir NF",
            "NOTA_FISCAL_PARCIAL": "NF parcial",
            "NOTA_FISCAL_EMITIDA": "NF emitida",
            "FISCAL_CANCELADO": "Fiscal cancelado",
            "PENDENTE": "Pendente",
            "PARCIAL": "Parcial",
            "FATURADO": "Faturado",
            "CANCELADO": "Cancelado",
        }
        return labels.get(legacy.normalize_status(status or ""), status or "-")

    def early_delivery_destination_candidates(self, search: str = "") -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_early_delivery_destination_candidates(search)]

    def remanagement_source_candidates(self, exclude_process_id: int | None = None, search: str = "") -> list[dict[str, Any]]:
        text = search.strip().upper()
        rows = []
        for row in self.repo.list_remanagement_source_candidates(exclude_process_id):
            if text and text not in (row["proposta"] or "").upper() and text not in (row["cliente"] or "").upper() and text not in (row["obra_site"] or "").upper():
                continue
            rows.append(row_to_dict(row))
        return rows

    def deliver_by_material_remanagement(
        self,
        destination_id: int,
        source_id: int,
        observation: str,
        item_ids: list[int] | None = None,
    ):
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        self.repo.deliver_by_material_remanagement(
            destination_id,
            source_id,
            self.user,
            observation,
            item_ids=item_ids,
        )

    def stockroom_delivery_required(self, process_id: int) -> bool:
        process = self.repo.get_process(process_id)
        return bool(process and self.repo.stockroom_delivery_required(process))

    def history_rows(self) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.history()]

    def process_history_rows(self, process_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.history(process_id)]

    def process_partials(self, process_id: int) -> list[dict[str, Any]]:
        process = self.repo.get_process(process_id)
        if not process:
            return []
        return [row_to_dict(row) for row in self.repo.list_process_partials(process)]

    def process_loads(self, process_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_process_loads(process_id)]

    def audit_rows(self) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.audit()]

    def saved_reports(self) -> list[dict[str, Any]]:
        return list(self.config.get("saved_reports", []))

    def save_palette(self, palette_name: str):
        palette_name = normalize_palette_name(palette_name)
        if palette_name not in self.palettes:
            raise legacy.AppError("Paleta invalida.")
        self.config["color_palette"] = palette_name
        save_app_config(self.config)

    def toggle_palette(self) -> str:
        next_palette = "escuro" if self.palette_name == "claro" else "claro"
        self.save_palette(next_palette)
        return next_palette

    def backup_now(self):
        target = legacy.backup_database(self.config, "manual")
        if not target:
            raise legacy.AppError("Banco atual nao encontrado para backup.")
        return target

    def choose_database(self, path: str):
        if not path:
            return
        candidate = Path(path)
        current = Path(self.config["db_path"])
        if candidate.exists():
            require_healthy_database(candidate, require_schema=True)
        if current.exists():
            safe_backup(current, self.config["backup_dir"], "antes_trocar_banco")
        self.config["db_path"] = path
        save_app_config(self.config)
        log.info("Troca de banco preparada | anterior=%s | novo=%s", current, candidate)

    def database_health(self):
        return inspect_database(self.config["db_path"], require_schema=True)

    def restore_backup(self, backup_path: str):
        if not backup_path:
            return None
        legacy.validate_database_file(backup_path)
        current = Path(self.config["db_path"])
        source = Path(backup_path)
        if source.resolve() == current.resolve():
            raise legacy.AppError("Escolha um backup diferente do banco que esta em uso.")
        safety = legacy.backup_database(self.config, "antes_restaurar")
        self.conn.close()
        legacy.remove_database_sidecars(current)
        shutil.copy2(source, current)
        legacy.remove_database_sidecars(current)
        self.conn = legacy.db_connect(self.config["db_path"])
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.repo = legacy.Repository(self.conn)
        return safety

    def user_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, nome, login, perfil, ativo, areas_acesso FROM usuarios ORDER BY nome"
        ).fetchall()
        result = []
        for row in rows:
            data = row_to_dict(row)
            data["perfil_label"] = legacy.profile_label(row["perfil"])
            data["areas_label"] = self._permission_summary(int(row["id"]))
            data["ativo_label"] = "Sim" if row["ativo"] else "Nao"
            result.append(data)
        return result

    def get_user(self, user_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        data = row_to_dict(row)
        data["permissions"] = self.user_permissions(user_id)
        return data

    def profile_options(self):
        return list(legacy.PROFILE_OPTIONS)

    def profile_default_areas(self, profile: str) -> list[str]:
        return list(legacy.PROFILE_DEFAULT_AREAS.get(profile, []))

    def profile_default_permissions(self, profile: str) -> dict[str, str]:
        return dict(legacy.profile_default_permissions(profile))

    def user_permissions(self, user_id: int) -> dict[str, str]:
        defaults = {area["key"]: legacy.PERMISSION_LEVEL_NONE for area in self.permission_area_options()}
        user_row = self.conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if user_row and legacy.user_can_admin(user_row):
            return {area["key"]: legacy.PERMISSION_LEVEL_EDIT for area in self.permission_area_options()}
        if legacy.permission_table_exists(self.conn):
            rows = self.conn.execute(
                "SELECT area_key, access_level FROM usuario_permissoes WHERE usuario_id = ?",
                (user_id,),
            ).fetchall()
            for row in rows:
                if row["area_key"] in defaults and row["access_level"] in legacy.PERMISSION_LEVELS:
                    defaults[row["area_key"]] = row["access_level"]
            if rows:
                return defaults
        if user_row:
            for area in legacy.AREAS:
                key = legacy.normalize_permission_area(area)
                defaults[key] = legacy._legacy_permission_level(user_row, key)
            if user_row["perfil"] == "fiscal":
                defaults["fiscal"] = legacy.PERMISSION_LEVEL_EDIT
            return defaults
        return defaults

    def _permission_summary(self, user_id: int) -> str:
        permissions = self.user_permissions(user_id)
        parts = []
        for area in self.permission_area_options():
            level = permissions.get(area["key"], legacy.PERMISSION_LEVEL_NONE)
            if level == legacy.PERMISSION_LEVEL_EDIT:
                parts.append(f"{area['label']}: alterar")
            elif level == legacy.PERMISSION_LEVEL_VIEW:
                parts.append(f"{area['label']}: visualizar")
        return ", ".join(parts) or "Sem acesso"

    def _active_admin_count(self, exclude_user_id: int | None = None) -> int:
        params: list[Any] = []
        where = "WHERE perfil = 'admin' AND ativo = 1"
        if exclude_user_id is not None:
            where += " AND id <> ?"
            params.append(exclude_user_id)
        row = self.conn.execute(f"SELECT COUNT(*) AS total FROM usuarios {where}", tuple(params)).fetchone()
        return int(row["total"] or 0)

    def _active_user_management_count(self, exclude_user_id: int | None = None) -> int:
        params: list[Any] = []
        exclude = ""
        if exclude_user_id is not None:
            exclude = "AND u.id <> ?"
            params.append(exclude_user_id)
        if legacy.permission_table_exists(self.conn):
            row = self.conn.execute(
                f"""
                SELECT COUNT(DISTINCT u.id) AS total
                FROM usuarios u
                LEFT JOIN usuario_permissoes up
                  ON up.usuario_id = u.id
                 AND up.area_key = 'users_permissions'
                 AND up.access_level = 'EDIT'
                WHERE u.ativo = 1
                  {exclude}
                  AND (u.perfil = 'admin' OR up.id IS NOT NULL)
                """,
                tuple(params),
            ).fetchone()
        else:
            row = self.conn.execute(
                f"SELECT COUNT(*) AS total FROM usuarios u WHERE u.ativo = 1 {exclude} AND u.perfil = 'admin'",
                tuple(params),
            ).fetchone()
        return int(row["total"] or 0)

    def _validate_admin_safety(self, user_id: int | None, profile: str, active: int, permissions: dict[str, str]):
        if not user_id:
            return
        current = self.conn.execute("SELECT id, perfil, ativo FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if not current:
            return
        was_active_admin = current["perfil"] == "admin" and int(current["ativo"] or 0) == 1
        will_be_active_admin = profile == "admin" and active == 1
        if was_active_admin and not will_be_active_admin and self._active_admin_count(exclude_user_id=user_id) == 0:
            raise legacy.AppError("Nao e permitido deixar o sistema sem administrador ativo.")
        current_user_id = int(self.user["id"]) if self.user and "id" in self.user.keys() else None
        if current_user_id == user_id:
            user_management_level = permissions.get("users_permissions", legacy.PERMISSION_LEVEL_NONE)
            will_manage_users = will_be_active_admin or user_management_level == legacy.PERMISSION_LEVEL_EDIT
            if not will_manage_users and self._active_user_management_count(exclude_user_id=user_id) == 0:
                raise legacy.AppError("Nao remova seu proprio acesso a Usuarios e Permissoes sem outro responsavel ativo.")

    def save_user(self, data: dict[str, Any], user_id: int | None = None):
        nome = (data.get("nome") or "").strip()
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        profile = data.get("perfil") or "consulta"
        ativo = 1 if data.get("ativo", True) else 0
        permissions = dict(data.get("permissions") or legacy.profile_default_permissions(profile))
        if profile == "admin":
            permissions = {area["key"]: legacy.PERMISSION_LEVEL_EDIT for area in self.permission_area_options()}
        permissions = {
            legacy.normalize_permission_area(key): level if level in legacy.PERMISSION_LEVELS else legacy.PERMISSION_LEVEL_NONE
            for key, level in permissions.items()
        }
        for area in self.permission_area_options():
            permissions.setdefault(area["key"], legacy.PERMISSION_LEVEL_NONE)
        areas = [
            legacy.PERMISSION_LEGACY_AREAS[key]
            for key, level in permissions.items()
            if level == legacy.PERMISSION_LEVEL_EDIT and key in legacy.PERMISSION_LEGACY_AREAS
        ]
        if not nome:
            raise legacy.AppError("Informe o nome.")
        if not login:
            raise legacy.AppError("Informe o login.")
        if not user_id and not password:
            raise legacy.AppError("Informe a senha inicial.")
        self._validate_admin_safety(user_id, profile, ativo, permissions)
        try:
            with self.conn:
                if user_id:
                    values = [nome, login, profile, ativo, legacy.area_csv(areas)]
                    sql = "UPDATE usuarios SET nome = ?, login = ?, perfil = ?, ativo = ?, areas_acesso = ?"
                    if password:
                        salt, digest = legacy.pbkdf2_hash(password)
                        sql += ", senha_salt = ?, senha_hash = ?"
                        values.extend([salt, digest])
                    sql += " WHERE id = ?"
                    values.append(user_id)
                    self.conn.execute(sql, tuple(values))
                    saved_id = user_id
                else:
                    salt, digest = legacy.pbkdf2_hash(password)
                    cur = self.conn.execute(
                        """
                        INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (nome, login, salt, digest, profile, ativo, legacy.now_br(), legacy.area_csv(areas)),
                    )
                    saved_id = int(cur.lastrowid)
                if legacy.permission_table_exists(self.conn):
                    self.conn.execute("DELETE FROM usuario_permissoes WHERE usuario_id = ?", (saved_id,))
                    for area in self.permission_area_options():
                        key = area["key"]
                        self.conn.execute(
                            """
                            INSERT INTO usuario_permissoes(usuario_id, area_key, access_level, created_at, updated_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            """,
                            (saved_id, key, permissions.get(key, legacy.PERMISSION_LEVEL_NONE)),
                        )
        except legacy.sqlite3.IntegrityError as exc:
            raise legacy.AppError("Ja existe um usuario com esse login.") from exc

    def toggle_user(self, user_id: int):
        row = self.conn.execute("SELECT id, perfil, ativo FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return
        if row["perfil"] == "admin" and int(row["ativo"] or 0) == 1 and self._active_admin_count(exclude_user_id=user_id) == 0:
            raise legacy.AppError("Nao e permitido desativar o ultimo administrador ativo.")
        self.conn.execute("UPDATE usuarios SET ativo = CASE ativo WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
        self.conn.commit()

    def get_process(self, process_id: int):
        return self.repo.get_process(process_id)

    def get_process_dict(self, process_id: int) -> dict[str, Any]:
        return row_to_dict(self.get_process(process_id))

    def next_status_options(self, area: str, process_id: int) -> list[str]:
        row = self.repo.get_process(process_id)
        if not row:
            return []
        return self.repo.next_status_options(area, row)

    def administrative_status_options(self, area: str) -> list[str]:
        if area not in legacy.AREAS:
            return []
        ordered = legacy.STATUS_FLOW_ORDER.get(area, [])
        available = set(self.list_status(area))
        ordered_options = [status for status in ordered if status in available]
        remaining = sorted(available - set(ordered_options))
        return ordered_options + remaining

    def administrative_correction(
        self,
        process_id: int,
        new_area: str,
        new_status: str,
        justification: str,
    ):
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        if not self.can_admin():
            raise legacy.AppError("Apenas administradores podem aplicar correcao administrativa.")

        new_area = (new_area or "").strip().upper()
        new_status = legacy.normalize_status(new_status or "")
        justification = (justification or "").strip()
        if new_area not in legacy.AREAS:
            raise legacy.AppError("Nova area invalida.")
        if not new_status:
            raise legacy.AppError("Informe o novo status.")
        if new_status not in self.list_status(new_area):
            raise legacy.AppError("Status invalido para a nova area.")
        if not justification:
            raise legacy.AppError("Informe a justificativa da correcao.")

        process = self.repo.get_process(process_id)
        if not process:
            raise legacy.AppError("Processo nao encontrado.")
        previous = row_to_dict(process)
        previous_area, previous_area_label, previous_status = self.current_location(previous)
        previous_area = previous_area or new_area
        previous_area_label = previous_area_label or previous_area.title()
        previous_status = previous_status or self.status_for_area(previous, previous_area) or ""

        column = legacy.AREAS[new_area]["column"]
        old_target_status = legacy.normalize_status(previous.get(column) or "")
        if previous_area == new_area and old_target_status == new_status:
            raise legacy.AppError("A area e o status selecionados ja estao aplicados.")

        now = legacy.now_br()
        updates: dict[str, Any] = {
            column: new_status,
            "atualizado_em": now,
            "atualizado_por": self.user["login"],
        }

        # Manual corrections must make the selected stage become the current visible
        # stage. Clearing downstream stage statuses prevents an old later-stage status
        # from continuing to pull the proposal forward visually.
        flow_order = ("CONTROLE GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO")
        if new_area in flow_order:
            for downstream_area in flow_order[flow_order.index(new_area) + 1:]:
                downstream_column = legacy.AREAS[downstream_area]["column"]
                if downstream_column != column:
                    updates[downstream_column] = ""

        date_column = legacy.AREAS[new_area]["date_columns"].get(new_status)
        if date_column:
            updates[date_column] = legacy.today_br()
        observation_column = legacy.AREAS[new_area]["observation_column"]
        updates[observation_column] = justification

        preview = dict(previous)
        preview.update(updates)
        general_status = self.repo.general_status_for(new_area, new_status, preview)
        if general_status:
            updates["status_geral"] = general_status
            preview["status_geral"] = general_status
        updates.update(self.repo.flow_state_updates(preview))

        assignments = ", ".join(f"{key} = ?" for key in updates)
        history_note = (
            "CORREÇÃO ADMINISTRATIVA\n"
            f"Area anterior: {previous_area_label}\n"
            f"Status anterior: {self.area_status_label(previous_area, previous_status) if previous_status else '-'}\n"
            f"Nova area: {new_area.title()}\n"
            f"Novo status: {self.area_status_label(new_area, new_status)}\n"
            f"Justificativa: {justification}"
        )
        try:
            self.conn.execute(
                f"UPDATE processos SET {assignments} WHERE id = ?",
                tuple(updates.values()) + (process_id,),
            )
            self.conn.execute(
                """
                INSERT INTO historico_status(
                    processo_id, proposta, area, status_anterior, status_novo,
                    data_hora, usuario, computador, observacao
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    process_id,
                    previous.get("proposta") or "",
                    new_area,
                    previous_status,
                    new_status,
                    now,
                    self.user["login"],
                    legacy.socket.gethostname(),
                    history_note,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def process_actions(self, process_id: int, area: str | None = None) -> list[dict[str, str]]:
        process = self.repo.get_process(process_id)
        if not process:
            return []
        area = area or self.current_location(row_to_dict(process))[0] or "CONTROLE GERAL"
        if area not in legacy.AREAS or not self.can_view(area):
            return []
        if not self.can_edit(area):
            return []
        options = self.repo.next_status_options(area, process)
        actions: list[dict[str, str]] = []

        def add(action_id: str, label: str, icon: str, status: str = ""):
            actions.append({"id": action_id, "label": label, "icon": icon, "status": status, "area": area})

        if area == "PRODUCAO":
            current_production = process["status_producao"] or ""
            flow_summary = self.repo.item_flow_summary(process_id)
            if flow_summary["undefined_count"]:
                add("DEFINE_ITEM_FLOW", "Definir fluxo dos itens pendentes", "settings")
            else:
                add("DEFINE_ITEM_FLOW", "Definir fluxo dos itens", "settings")
            if "INICIADO" in options:
                label = "Retomar producao" if current_production == "PARADO" else "Iniciar producao"
                add("STATUS", label, "production", "INICIADO")
            if "PARADO" in options and current_production == "INICIADO":
                add("STATUS", "Pausar producao", "pause", "PARADO")
            if any(status in options for status in ("FINALIZADO", "FINALIZADO_PARCIAL")):
                add("REGISTER_PRODUCTION", "Registrar producao", "status")
            add("EDIT_ITEM_WEIGHTS", "Informar pesos dos itens", "edit")
            return actions

        if area == "GALVANIZACAO":
            if (process["status_galvanizacao"] or "") in ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL"):
                add("MANAGE_LOAD", "Adicionar a uma carga", "load")
            if (process["status_galvanizacao"] or "") in ("ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL"):
                active_loads = [
                    row for row in self.process_loads(process_id)
                    if (row.get("status") or "") in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")
                ]
                if active_loads:
                    add("REGISTER_GALVANIZATION_RETURN", "Registrar retorno da galvanizacao", "load")
            return actions

        labels = {
            ("CONTROLE GERAL", "LIBERADO_PRODUCAO"): ("Liberar para producao", "production"),
            ("CONTROLE GERAL", "CANCELADA"): ("Cancelar proposta", "delete"),
            ("EXPEDICAO", "SEPARACAO_INICIADA"): ("Iniciar separacao", "status"),
            ("EXPEDICAO", "SEPARADO"): ("Confirmar separacao concluida", "status"),
            ("ALMOXARIFADO", "EM_SEPARACAO"): ("Confirmar que possui almoxarifado", "stock"),
            ("ALMOXARIFADO", "SEM_PARAFUSOS"): ("Confirmar sem almoxarifado", "clear"),
            ("ALMOXARIFADO", "SEPARADO"): ("Confirmar separacao concluida", "status"),
            ("ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE"): ("Confirmar entrega do almoxarifado", "status"),
            ("ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE_PARCIAL"): ("Registrar entrega parcial", "status"),
        }
        if area == "EXPEDICAO" and any(status in options for status in ("ENTREGUE", "ENTREGUE_PARCIAL")):
            add("REGISTER_DELIVERY", "Registrar retirada do cliente", "status")
            options = [status for status in options if status not in ("ENTREGUE", "ENTREGUE_PARCIAL")]
        for status in options:
            label, icon = labels.get((area, status), (self.area_status_label(area, status), "status"))
            add("STATUS", label, icon, status)
        return actions

    def action_label(self, area: str, status: str) -> str:
        if area == "ALMOXARIFADO" and status == "EM_SEPARACAO":
            return "Confirmar que possui almoxarifado"
        labels = {
            "LIBERADO_PRODUCAO": "Liberar para producao",
            "CANCELADA": "Cancelar proposta",
            "INICIADO": "Iniciar ou retomar producao",
            "PARADO": "Pausar producao",
            "FINALIZADO": "Concluir producao",
            "FINALIZADO_PARCIAL": "Registrar producao parcial",
            "EM_CARGA": "Adicionar a carga",
            "ENVIADO_GALVANIZACAO": "Liberar carga para envio",
            "RETORNOU_GALVANIZACAO": "Confirmar retorno da carga",
            "SEPARADO": "Confirmar separacao concluida",
            "ENTREGUE": "Confirmar entrega completa",
            "ENTREGUE_PARCIAL": "Registrar retirada parcial",
            "SEPARACAO_INICIADA": "Iniciar separacao",
            "SEM_PARAFUSOS": "Confirmar sem almoxarifado",
            "ALMOXARIFADO_ENTREGUE": "Confirmar entrega do almoxarifado",
            "ALMOXARIFADO_ENTREGUE_PARCIAL": "Registrar entrega parcial do almoxarifado",
        }
        return labels.get(status, self.area_status_label(area, status))

    def update_status(
        self,
        process_id: int,
        area: str,
        status: str,
        observation: str = "",
        item_ids: list[int] | None = None,
        produced_weight: float | None = None,
    ):
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        process = self.repo.get_process(process_id)
        if (
            process
            and area == "EXPEDICAO"
            and status == "ENTREGUE"
            and self.repo.stockroom_delivery_required(process)
        ):
            self.repo.confirm_stockroom_delivery(process_id, self.user)
        if area == "EXPEDICAO" and status == "ENTREGUE_PARCIAL" and item_ids:
            self.repo.register_item_delivery(process_id, item_ids, self.user, observation)
            return
        if area == "EXPEDICAO" and status == "ENTREGUE":
            remaining = self.repo.list_proposal_items(process_id, pending_delivery=True)
            if remaining:
                self.repo.register_item_delivery(process_id, [row["id"] for row in remaining], self.user, observation or "Entrega completa")
                return
        self.repo.update_status(
            process_id,
            area,
            status,
            observation,
            self.user,
            item_ids=item_ids,
            produced_weight=produced_weight,
        )

    def save_process(
        self,
        data: dict[str, Any],
        process_id: int | None = None,
        import_metadata: dict[str, Any] | None = None,
    ) -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        return self.repo.save_process(data, self.user, process_id, import_metadata)

    def proposal_items(self, process_id: int, pending_production: bool = False, pending_delivery: bool = False) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_proposal_items(process_id, pending_production, pending_delivery)]

    def update_item_weights(self, process_id: int, weights: dict[int, float]) -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        if not self.can_edit("PRODUCAO"):
            raise legacy.AppError("Seu usuario nao pode alterar dados da Producao.")
        if not weights:
            return 0
        legacy.backup_database(self.config, "antes_pesos_itens")
        return self.repo.update_item_weights(process_id, weights, self.user)

    def item_flow_summary(self, process_id: int) -> dict[str, Any]:
        return self.repo.item_flow_summary(process_id)

    def item_no_production_reasons(self) -> list[tuple[str, str]]:
        return [(key, legacy.ITEM_NO_PRODUCTION_LABELS[key]) for key in ("pronta_entrega", "comprado_terceiro", "terceirizado", "outro")]

    def update_item_flow(self, process_id: int, definitions: list[dict[str, Any]], origin: str = "Producao") -> int:
        if not self.user:
            raise legacy.AppError("Usuario nao autenticado.")
        if not self.can_edit("PRODUCAO"):
            raise legacy.AppError("Seu usuario nao pode definir fluxo dos itens.")
        legacy.backup_database(self.config, "antes_fluxo_itens")
        return self.repo.update_item_flow(process_id, definitions, self.user, origin)

    def item_progress(self, process_id: int) -> dict[str, Any]:
        return self.repo.item_progress(process_id)

    def weight_progress_text(self, process_id: int) -> str:
        return self.repo.weight_progress_text(process_id)

    def current_location(self, process: dict[str, Any]) -> tuple[str, str, str]:
        area_order = (
            ("EXPEDICAO", "Expedicao", "status_expedicao"),
            ("GALVANIZACAO", "Galvanizacao", "status_galvanizacao"),
            ("PRODUCAO", "Producao", "status_producao"),
            ("CONTROLE GERAL", "Controle geral", "status_geral"),
        )
        if (process.get("tipo_processo") or "PRINCIPAL") == "PRINCIPAL":
            if (process.get("status_producao") or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"):
                return "PRODUCAO", "Producao", process.get("status_producao") or ""
        if (process.get("status_expedicao") or "") == "UNIFICADA_PRINCIPAL":
            return "CONTROLE GERAL", "Controle geral", "UNIFICADA_PRINCIPAL"
        for area_key, area_label, column in area_order:
            status = legacy.normalize_status(process.get(column) or "")
            if not status:
                continue
            if area_key != "CONTROLE GERAL" and status in legacy.AREA_FINISHED_STATUS.get(area_key, set()):
                continue
            if area_key == "EXPEDICAO" and status == "UNIFICADA_PRINCIPAL":
                continue
            return area_key, area_label, status
        status = legacy.normalize_status(process.get("status_geral") or "")
        return ("CONTROLE GERAL", "Controle geral", status) if status else ("", "", "")

    def display_cell(self, key: str, value: Any, row: dict[str, Any] | None = None) -> str:
        if key == "id" and row:
            parent_id = row.get("processo_pai_id")
            partial_number = int(row.get("numero_parcial") or 0)
            if parent_id and partial_number:
                return f"{parent_id}-P{partial_number}"
            return str(row.get("id") or "")
        if key == "progresso_peso" and row:
            return self.repo.weight_progress_text(int(row["id"]))
        if key == "carga_galvanizacao" and row:
            load_id = row.get("carga_galvanizacao")
            if load_id is None:
                load_id = self.repo.current_galvanization_load_id(int(row["id"]))
            return f"Carga {load_id}" if load_id else "-"
        if key == "localizacao_atual" and row:
            return self.current_location(row)[1] or "-"
        if key == "status_localizacao" and row:
            area, _label, status = self.current_location(row)
            return self.area_status_label(area, status) if status else "-"
        if key == "almoxarifado_info":
            status = (row or {}).get("status_almoxarifado", "") if row else ""
            need = legacy.normalize_stockroom_need((row or {}).get("necessita_almoxarifado", "") if row else "")
            status = legacy.normalize_status(status)
            if need == "NAO" or status == "SEM_PARAFUSOS":
                return "Sem Almox."
            if status == "ALMOXARIFADO_ENTREGUE":
                return "Almox. entregue"
            if status:
                return "Tem Almox."
            return "Almox. indef."
        return legacy.display_cell(key, value)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
