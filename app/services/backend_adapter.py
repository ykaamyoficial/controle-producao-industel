from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.services import production_repository as legacy
from app.services.migration_runner import apply_migrations


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "app"
APP_CONFIG_FILE = APP_DIR / "config" / "controle_producao_config.json"
APP_DB_FILE = APP_DIR / "data" / "controle_producao.db"
APP_BACKUP_DIR = APP_DIR / "data" / "backups"


def load_app_config() -> dict[str, Any]:
    if APP_CONFIG_FILE.exists():
        with APP_CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = legacy.json.load(file)
    else:
        data = {}
    data.setdefault("db_path", str(APP_DB_FILE))
    data.setdefault("backup_dir", str(APP_BACKUP_DIR))
    data.setdefault("backup_keep", 20)
    data.setdefault("company", "Industel")
    data.setdefault("color_palette", "aurora")
    data.setdefault("saved_reports", legacy.DEFAULT_REPORT_DEFINITIONS)
    if data["color_palette"] not in legacy.COLOR_PALETTES:
        data["color_palette"] = "aurora"
    APP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    save_app_config(data)
    return data


def save_app_config(config: dict[str, Any]):
    APP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with APP_CONFIG_FILE.open("w", encoding="utf-8") as file:
        legacy.json.dump(config, file, ensure_ascii=False, indent=2)


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


class BackendService:
    """Adapter that preserves the existing SQLite backend and business rules."""

    def __init__(self):
        self.config = load_app_config()
        self.conn = legacy.db_connect(self.config["db_path"])
        apply_migrations(self.conn)
        legacy.initialize_database(self.conn)
        self.repo = legacy.Repository(self.conn)
        self.user = None

    @property
    def palettes(self):
        return legacy.COLOR_PALETTES

    @property
    def palette_name(self) -> str:
        return self.config.get("color_palette", "aurora")

    @property
    def palette(self):
        return self.palettes.get(self.palette_name, self.palettes["aurora"])

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
        return legacy.visible_area_names(self.user) if self.user else []

    def can_edit_process(self) -> bool:
        return bool(self.user and legacy.user_can_edit_process(self.user))

    def can_admin(self) -> bool:
        return bool(self.user and legacy.user_can_admin(self.user))

    def can_access_area(self, area: str) -> bool:
        return bool(self.user and legacy.user_can_access_area(self.user, area))

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
        return result

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
        return bool(self.user and legacy.user_can_mount_galvanization_load(self.user))

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

    def galvanization_load_proposal_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        return [row_to_dict(row) for row in self.repo.list_galvanization_load_proposal_items(load_id, process_id)]

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
        if palette_name not in self.palettes:
            raise legacy.AppError("Paleta invalida.")
        self.config["color_palette"] = palette_name
        save_app_config(self.config)

    def backup_now(self):
        target = legacy.backup_database(self.config, "manual")
        if not target:
            raise legacy.AppError("Banco atual nao encontrado para backup.")
        return target

    def choose_database(self, path: str):
        if not path:
            return
        self.config["db_path"] = path
        save_app_config(self.config)

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
            data["areas_label"] = ", ".join(area.title() for area in legacy.user_areas(row)) or "Somente consulta"
            data["ativo_label"] = "Sim" if row["ativo"] else "Nao"
            result.append(data)
        return result

    def get_user(self, user_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        return row_to_dict(row)

    def profile_options(self):
        return list(legacy.PROFILE_OPTIONS)

    def profile_default_areas(self, profile: str) -> list[str]:
        return list(legacy.PROFILE_DEFAULT_AREAS.get(profile, []))

    def save_user(self, data: dict[str, Any], user_id: int | None = None):
        nome = (data.get("nome") or "").strip()
        login = (data.get("login") or "").strip()
        password = data.get("password") or ""
        profile = data.get("perfil") or "consulta"
        areas = list(data.get("areas") or [])
        ativo = 1 if data.get("ativo", True) else 0
        if profile == "admin":
            areas = list(legacy.AREAS.keys())
        if not nome:
            raise legacy.AppError("Informe o nome.")
        if not login:
            raise legacy.AppError("Informe o login.")
        if not user_id and not password:
            raise legacy.AppError("Informe a senha inicial.")
        if profile != "consulta" and not areas:
            raise legacy.AppError("Selecione pelo menos uma area de acesso.")
        try:
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
            else:
                salt, digest = legacy.pbkdf2_hash(password)
                self.conn.execute(
                    """
                    INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nome, login, salt, digest, profile, ativo, legacy.now_br(), legacy.area_csv(areas)),
                )
            self.conn.commit()
        except legacy.sqlite3.IntegrityError as exc:
            raise legacy.AppError("Ja existe um usuario com esse login.") from exc

    def toggle_user(self, user_id: int):
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

    def process_actions(self, process_id: int, area: str | None = None) -> list[dict[str, str]]:
        process = self.repo.get_process(process_id)
        if not process:
            return []
        area = area or self.current_location(row_to_dict(process))[0] or "CONTROLE GERAL"
        if area not in legacy.AREAS or not self.can_access_area(area):
            return []
        options = self.repo.next_status_options(area, process)
        actions: list[dict[str, str]] = []

        def add(action_id: str, label: str, icon: str, status: str = ""):
            actions.append({"id": action_id, "label": label, "icon": icon, "status": status, "area": area})

        if area == "PRODUCAO":
            current_production = process["status_producao"] or ""
            if "INICIADO" in options:
                label = "Retomar producao" if current_production == "PARADO" else "Iniciar producao"
                add("STATUS", label, "production", "INICIADO")
            if "PARADO" in options and current_production == "INICIADO":
                add("STATUS", "Pausar producao", "pause", "PARADO")
            if any(status in options for status in ("FINALIZADO", "FINALIZADO_PARCIAL")):
                add("REGISTER_PRODUCTION", "Registrar producao", "status")
            return actions

        if area == "GALVANIZACAO":
            if (process["status_galvanizacao"] or "") in ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL"):
                add("MANAGE_LOAD", "Adicionar a uma carga", "load")
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
