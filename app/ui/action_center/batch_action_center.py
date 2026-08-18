from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.services.app_logging import get_logger
from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import (
    AREA_COLOR_KEYS, CATEGORY_TO_CARD_TYPE, action_category, action_description, action_icon, primary_action_index,
)
from app.ui.action_center.handlers.galvanization import (
    RETURNABLE_LOAD_STATUSES,
    choose_existing_load_for_addition,
    resolve_return_load_ids,
)
from app.ui.background_worker import start_worker
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.flow_review_dialog import FlowReviewDialog
from app.ui.galvanization_load_dialog import GalvanizationLoadDialog, GalvanizationReturnDialog
from app.ui.icons import AppIcons
from app.ui.item_selection_dialog import ItemSelectionDialog
from app.ui.production_registration_dialog import ProductionRegistrationDialog
from app.ui.theme_tokens import with_alpha

log = get_logger("batch_action_center")

_ACTIONS_SCROLL_MAX_HEIGHT = 420
# Estatuses que, quando comuns a toda a selecao, viram um card especial em
# vez de aparecerem como transicao de STATUS simples - mesma regra que
# BatchStatusDialog.refresh_selected() ja aplicava (backend nao tem um
# "REGISTER_PRODUCTION"/"REGISTER_DELIVERY" no meio de STATUS_FLOW_ORDER,
# essas duas exigem selecao de itens por proposta).
_PRODUCTION_COMPLETION_STATUSES = ("FINALIZADO", "FINALIZADO_PARCIAL")
_DELIVERY_COMPLETION_STATUSES = ("ENTREGUE", "ENTREGUE_PARCIAL")


class BatchProposalActionCenter(QDialog):
    """Central de Acoes para a selecao em lote (varias propostas por
    checkbox) - mesma linguagem visual/estrutural do `ProposalActionCenter`
    individual (cards, observacao, cabecalho), mas o contexto e uma lista de
    process_id em vez de um so. Nao substitui `BatchStatusDialog` como
    classe (ela continua existindo/testada), so deixa de ser a porta de
    entrada do "Acoes em lote" por checkbox: cada card aqui encaminha
    diretamente para o mesmo service/dialog especializado que a acao
    individual correspondente ja usa - nenhuma regra de elegibilidade ou
    transicao e recalculada aqui."""

    def __init__(
        self,
        service,
        process_ids: list[int],
        area: str,
        parent=None,
        *,
        proposal_labels: dict[int, str] | None = None,
        item_rows: list[dict] | None = None,
        item_action_host=None,
    ):
        super().__init__(parent)
        self.service = service
        self.process_ids = list(dict.fromkeys(int(value) for value in process_ids if value))
        self.area = area
        self.proposal_labels = proposal_labels or {}
        self.item_rows = self._deduplicate_item_rows(item_rows or [])
        self.item_ids = [int(row.get("api_id") or row.get("id")) for row in self.item_rows]
        self.item_action_host = item_action_host
        self.changed = False
        self._running_action = False
        self._action_thread = None
        self._action_buttons: list[ActionCardButton] = []
        self.actions = self._load_actions()
        self.setWindowTitle("Acoes dos itens selecionados" if self.item_rows else "Acoes em lote")
        style_dialog_from_parent(self, parent)
        self._build()
        self.setMinimumWidth(720)
        self.resize(760, self.sizeHint().height())
        self._center_on_parent(parent)
        log.info(
            "Central de acoes em lote aberta: area=%s propostas=%s itens=%s",
            area,
            len(self.process_ids),
            len(self.item_ids),
        )

    @staticmethod
    def _deduplicate_item_rows(rows: list[dict]) -> list[dict]:
        result: list[dict] = []
        seen: set[int] = set()
        for row in rows:
            item_id = int(row.get("api_id") or row.get("id") or 0)
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            result.append(dict(row))
        return result

    def _center_on_parent(self, parent):
        owner = parent.window() if parent and parent.window() else None
        if not owner:
            return
        frame = self.frameGeometry()
        frame.moveCenter(owner.geometry().center())
        self.move(frame.topLeft())

    def _proposal_label(self, process_id: int) -> str:
        return self.proposal_labels.get(process_id) or f"ID {process_id}"

    # -- acoes disponiveis ---------------------------------------------

    def _raw_actions(self) -> list[dict]:
        if self.item_rows:
            return self._raw_item_actions()
        if self.area == "GALVANIZACAO":
            # Galvanizacao nao tem STATUS de proposta generico (o dominio e
            # MANAGE_LOAD/retorno de carga). "Adicionar a uma carga" foi
            # dividida em dois cards - escolher uma carga existente ou criar
            # uma nova - em vez de abrir o gerenciador generico de cargas.
            # Nenhum dos dois ids vem do backend, sao puramente de UI/roteamento
            # (mesmo principio de OPEN_RELATED_GALVANIZATION_LOAD na Fase 6).
            # Os dois grupos de card so aparecem quando fazem sentido pra
            # selecao atual: montar carga exige saldo ainda nao enviado,
            # retorno exige uma carga ativa aguardando retorno - propostas ja
            # enviadas e sem saldo livre so oferecem "Registrar retorno".
            raw: list[dict] = []
            if self._has_galvanization_load_candidates():
                raw.append({"id": "MANAGE_LOAD_EXISTING", "label": "Adicionar a uma carga existente", "icon": "load", "status": "", "area": self.area})
                raw.append({"id": "MANAGE_LOAD_NEW", "label": "Criar nova carga", "icon": "new", "status": "", "area": self.area})
            if self._has_returnable_galvanization_load():
                raw.append({"id": "REGISTER_RETURN", "label": "Registrar retorno", "icon": "status", "status": "", "area": self.area})
            return raw
        return self._raw_status_actions()

    def _raw_item_actions(self) -> list[dict]:
        total = len(self.item_rows)
        actions: list[dict] = []
        can_edit_production = bool(self.service.can_edit("PRODUCAO"))
        can_mount_load = (
            bool(self.service.can_mount_galvanization_load())
            if hasattr(self.service, "can_mount_galvanization_load")
            else bool(self.service.can_edit("GALVANIZACAO"))
        )
        all_flow_defined = all(bool(row.get("fluxo_definido")) for row in self.item_rows)
        proposal_flow_ready = self._production_flow_selection_state() == "defined"

        if can_edit_production:
            actions.append(
                {
                    "id": "DEFINE_ITEM_FLOW",
                    "label": "Redefinir fluxo dos itens" if all_flow_defined else "Definir fluxo dos itens",
                    "description": "Altere o fluxo somente dos itens selecionados.",
                    "icon": "settings",
                    "status": "",
                    "area": self.area,
                }
            )

        try:
            common_statuses = set(self.service.common_next_statuses("PRODUCAO", self.process_ids))
        except Exception:
            common_statuses = set()
        if can_edit_production and proposal_flow_ready and "INICIADO" in common_statuses:
            actions.append(
                {
                    "id": "STATUS",
                    "label": self.service.action_label("PRODUCAO", "INICIADO"),
                    "description": "Inicia ou retoma as propostas dos itens selecionados.",
                    "icon": "status",
                    "status": "INICIADO",
                    "area": self.area,
                }
            )

        production_eligible = (
            [row for row in self.item_rows if self._is_production_registration_eligible(row)]
            if proposal_flow_ready
            else []
        )
        if can_edit_production and production_eligible:
            actions.append(
                {
                    "id": "REGISTER_PRODUCTION",
                    "label": "Registrar producao dos itens selecionados",
                    "description": self._coverage_description(
                        len(production_eligible), total, "Registre a producao sem alterar os demais itens das propostas."
                    ),
                    "icon": "status",
                    "status": "",
                    "area": self.area,
                }
            )

        load_eligible_rows = [row for row in self.item_rows if self._is_load_eligible(row)]
        load_eligible_ids = [int(row.get("api_id") or row.get("id")) for row in load_eligible_rows]
        if can_mount_load and load_eligible_rows:
            # Adicionar a uma carga existente e criar carga nova levam os
            # itens pelo mesmo pipeline de montagem (producao pendente e
            # registrada automaticamente antes de entrar na carga - ver
            # ProductionItemsPage.open_assemble_load), logo compartilham a
            # mesma elegibilidade: a diferenca entre as duas acoes e somente
            # o destino (carga existente vs. carga nova), nunca quais itens
            # qualificam.
            actions.append(
                {
                    "id": "MANAGE_LOAD_EXISTING",
                    "label": "Adicionar a uma carga existente",
                    "description": self._coverage_description(
                        len(load_eligible_rows), total, "Escolha uma carga aberta e inclua os itens elegiveis."
                    ),
                    "eligible_item_ids": load_eligible_ids,
                    "icon": "load",
                    "status": "",
                    "area": self.area,
                }
            )
            actions.append(
                {
                    "id": "MANAGE_LOAD_NEW",
                    "label": "Criar nova carga",
                    "description": self._coverage_description(
                        len(load_eligible_rows), total, "Crie uma carga com os itens elegiveis selecionados."
                    ),
                    "eligible_item_ids": load_eligible_ids,
                    "icon": "new",
                    "status": "",
                    "area": self.area,
                }
            )
        return actions

    @staticmethod
    def _coverage_description(eligible: int, total: int, description: str) -> str:
        if eligible == total:
            return description
        return f"Disponivel para {eligible} de {total} itens. {description}"

    @staticmethod
    def _is_production_registration_eligible(row: dict) -> bool:
        produce = str(row.get("produzir_internamente") or "").strip().lower()
        return bool(
            row.get("fluxo_definido")
            and not row.get("produzido")
            and produce not in {"nao", "não", "false", "0"}
            and not row.get("motivo_bloqueio")
        )

    @staticmethod
    def _is_load_eligible(row: dict) -> bool:
        needs_galvanization = str(row.get("precisa_galvanizacao") or "").strip().lower() in {"sim", "true", "1"}
        paused = str(row.get("status_producao") or "").strip().upper() == "PARADO"
        return bool(row.get("fluxo_definido") and needs_galvanization and not paused)

    def _has_galvanization_load_candidates(self) -> bool:
        try:
            candidates = self.service.galvanization_load_candidates()
        except Exception:
            return False
        selected = set(self.process_ids)
        for row in candidates:
            if int(row.get("id") or 0) not in selected:
                continue
            for item in row.get("_galvanization_items") or []:
                # A lista pode trazer itens com saldo zerado (o proprio
                # GalvanizationLoadDialog ja se protege disso em
                # _add_item_entry) - so conta como candidata se sobrar
                # saldo de verdade, senao uma proposta ja totalmente
                # enviada continua oferecendo "Adicionar a uma carga".
                try:
                    available = float(str(item.get("available_quantity") or "0").replace(",", "."))
                except (TypeError, ValueError):
                    available = 0.0
                if available > 0:
                    return True
        return False

    def _has_returnable_galvanization_load(self) -> bool:
        if not hasattr(self.service, "process_loads"):
            return False
        for proposal_id in self.process_ids:
            try:
                loads = self.service.process_loads(proposal_id)
            except Exception:
                loads = []
            if any((load.get("status") or "") in RETURNABLE_LOAD_STATUSES for load in loads):
                return True
        return False

    def _raw_status_actions(self) -> list[dict]:
        if self.area == "PRODUCAO":
            flow_state = self._production_flow_selection_state()
            flow_action = {
                "id": "DEFINE_ITEM_FLOW",
                "label": "Redefinir fluxo dos itens" if flow_state == "defined" else "Definir fluxo dos itens",
                "icon": "settings",
                "status": "",
                "area": self.area,
            }
            # Em selecao mista, definir o fluxo tem precedencia. O inicio so
            # reaparece quando todas as propostas selecionadas estao completas.
            if flow_state != "defined":
                return [flow_action]

        statuses = list(self.service.common_next_statuses(self.area, self.process_ids))
        raw: list[dict] = [flow_action] if self.area == "PRODUCAO" else []
        if self.area == "PRODUCAO" and any(status in statuses for status in _PRODUCTION_COMPLETION_STATUSES):
            statuses = [status for status in statuses if status not in _PRODUCTION_COMPLETION_STATUSES]
            raw.append({"id": "REGISTER_PRODUCTION", "label": "Registrar producao", "icon": "status", "status": "", "area": self.area})
        if self.area == "EXPEDICAO" and any(status in statuses for status in _DELIVERY_COMPLETION_STATUSES):
            statuses = [status for status in statuses if status not in _DELIVERY_COMPLETION_STATUSES]
            raw.append({"id": "REGISTER_DELIVERY", "label": "Registrar retirada do cliente", "icon": "status", "status": "", "area": self.area})
        for status in statuses:
            raw.append({"id": "STATUS", "label": self.service.action_label(self.area, status), "icon": "status", "status": status, "area": self.area})
        return raw

    def _production_flow_selection_state(self) -> str:
        defined: list[bool] = []
        for process_id in self.process_ids:
            try:
                summary = self.service.item_flow_summary(process_id)
                total = int(summary.get("total") or 0)
                undefined_count = int(summary.get("undefined_count") or 0)
            except Exception as exc:
                log.warning("Nao foi possivel consultar o fluxo da proposta %s: %s", process_id, exc)
                return "unknown"
            defined.append(total > 0 and undefined_count == 0)
        if defined and all(defined):
            return "defined"
        if any(defined):
            return "mixed"
        return "undefined"

    def _load_actions(self) -> list[ActionDescriptor]:
        raw_actions = self._raw_actions()
        primary_index = primary_action_index(raw_actions)
        return [
            ActionDescriptor(
                id=action["id"],
                label=action["label"],
                description=action.get("description") or action_description(action),
                icon=action_icon(action),
                category=action_category(action, index, primary_index),
                area=action.get("area", self.area),
                order=index,
                status=action.get("status", ""),
                raw=action,
            )
            for index, action in enumerate(raw_actions)
        ]

    # -- layout ----------------------------------------------------------

    def _build(self):
        palette = self.service.palette
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(12)

        root.addLayout(self._build_header(palette))

        instruction = QLabel("Acoes disponiveis")
        instruction.setStyleSheet("font-weight: 700; font-size: 13px;")
        root.addWidget(instruction)

        actions_container = QWidget()
        actions_layout = QVBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(0)
        root.addWidget(actions_container, 1)
        self._populate_actions(actions_layout, palette)

        root.addWidget(QLabel("Observacao (opcional)"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Acrescente uma informacao importante sobre esta operacao")
        self.observation.setFixedHeight(68)
        root.addWidget(self.observation)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {palette['border']}; border: 0;")
        root.addWidget(divider)

        root.addLayout(self._build_footer())

    def _build_header(self, palette) -> QVBoxLayout:
        header = QVBoxLayout()
        header.setSpacing(4)
        count = len(self.item_ids) if self.item_rows else len(self.process_ids)
        if self.item_rows:
            title = f"{count} {'item' if count == 1 else 'itens'} selecionado{'s' if count != 1 else ''}"
        else:
            title = f"{count} proposta{'s' if count != 1 else ''} selecionada{'s' if count != 1 else ''}"
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("font-size: 16px; font-weight: 800;")
        self._title_label.setWordWrap(True)
        header.addWidget(self._title_label)

        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(6)
        area_label = self.area.title()
        stage_color = palette.get(AREA_COLOR_KEYS.get(self.area, ""), palette["accent"])
        badges.addWidget(StatusBadge(area_label or "-", with_alpha(stage_color, 34), stage_color))
        if self.item_rows:
            proposals = len(self.process_ids)
            badges.addWidget(
                StatusBadge(
                    f"{proposals} proposta{'s' if proposals != 1 else ''}",
                    with_alpha(palette["muted"], 30),
                    palette["text"],
                )
            )
        badges.addStretch()
        header.addLayout(badges)
        return header

    def _populate_actions(self, layout: QVBoxLayout, palette):
        if not self.actions:
            message = "Nenhuma acao em lote disponivel para esta selecao neste momento."
            empty = QLabel(message)
            empty.setObjectName("Caption")
            layout.addWidget(empty)
            return

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        secondary_actions = [action for action in self.actions if action.category != ActionCategory.PRIMARY]
        primary_action = next((action for action in self.actions if action.category == ActionCategory.PRIMARY), None)

        row = col = 0
        for descriptor in secondary_actions:
            grid.addWidget(self._build_card(descriptor, palette), row, col)
            col += 1
            if col == 2:
                col = 0
                row += 1
        if primary_action is not None:
            grid.addWidget(self._build_card(primary_action, palette), row + 1 if col else row, 0, 1, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(grid_widget)
        scroll.setMinimumHeight(min(grid_widget.sizeHint().height(), _ACTIONS_SCROLL_MAX_HEIGHT))
        layout.addWidget(scroll)

    def _build_card(self, descriptor: ActionDescriptor, palette) -> ActionCardButton:
        card = ActionCardButton(
            title=descriptor.label,
            description=descriptor.description,
            icon=descriptor.icon,
            action_type=CATEGORY_TO_CARD_TYPE.get(descriptor.category, "secondary"),
            palette=palette,
        )
        card.clicked.connect(lambda _checked=False, data=descriptor: self.run_action(data))
        self._action_buttons.append(card)
        return card

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Cancelar", AppIcons.CLOSE)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        return footer

    # -- routing -----------------------------------------------------------

    def run_action(self, descriptor: ActionDescriptor):
        if self._running_action:
            return
        if self.item_rows:
            self._run_item_action(descriptor)
            return
        if descriptor.id == "STATUS":
            self._apply_status(descriptor.status)
        elif descriptor.id == "REGISTER_PRODUCTION":
            self._open_register_production()
        elif descriptor.id == "REGISTER_DELIVERY":
            self._open_register_delivery()
        elif descriptor.id == "DEFINE_ITEM_FLOW":
            self._open_define_flow()
        elif descriptor.id == "MANAGE_LOAD_EXISTING":
            self._open_manage_load_existing()
        elif descriptor.id == "MANAGE_LOAD_NEW":
            self._open_manage_load_new()
        elif descriptor.id == "REGISTER_RETURN":
            self._open_register_return()
        else:
            log.error("Acao de lote sem rota: id=%s area=%s", descriptor.id, self.area)
            QMessageBox.warning(self, "Acoes em lote", "Esta acao nao esta disponivel nesta versao.")

    def _run_item_action(self, descriptor: ActionDescriptor) -> None:
        if self.item_action_host is None:
            QMessageBox.warning(self, "Acoes dos itens", "O contexto da tela de itens nao esta disponivel.")
            return
        observation = self.observation.toPlainText().strip()
        if descriptor.id == "MANAGE_LOAD_EXISTING":
            eligible_ids = {int(value) for value in descriptor.raw.get("eligible_item_ids") or self.item_ids}
            rows = [row for row in self.item_rows if int(row.get("api_id") or row.get("id") or 0) in eligible_ids]
            load_id = choose_existing_load_for_addition(self.service, self)
            if load_id is None:
                return
            self.changed = True
            self.accept()
            self.item_action_host.open_assemble_load(rows, load_id=load_id)
            return
        if descriptor.id == "MANAGE_LOAD_NEW":
            eligible_ids = {int(value) for value in descriptor.raw.get("eligible_item_ids") or self.item_ids}
            rows = [row for row in self.item_rows if int(row.get("api_id") or row.get("id") or 0) in eligible_ids]
            self.changed = True
            self.accept()
            self.item_action_host.open_assemble_load(rows)
            return
        self.changed = True
        self.accept()
        if descriptor.id == "STATUS" and descriptor.status == "INICIADO":
            self.item_action_host.start_selected(self.item_rows, observation)
        elif descriptor.id == "REGISTER_PRODUCTION":
            self.item_action_host.register_selected(self.item_rows)
        elif descriptor.id == "DEFINE_ITEM_FLOW":
            self.item_action_host.open_flow_review(self.item_rows)
        else:
            log.error("Acao de itens sem rota: id=%s", descriptor.id)

    def _confirmation_text(self, label: str) -> str:
        proposals = [self._proposal_label(process_id) for process_id in self.process_ids[:12]]
        visible = "\n".join(f"- {proposal}" for proposal in proposals)
        extra = f"\n- ... e mais {len(self.process_ids) - 12}" if len(self.process_ids) > 12 else ""
        suffix = f"\n\nPropostas afetadas:\n{visible}{extra}" if visible else ""
        return f"Aplicar {label} em {len(self.process_ids)} proposta(s)?{suffix}"

    def _validated_process_ids(self, action_id: str) -> list[int] | None:
        """Revalida no estado oficial atual a selecao acumulada (a mesma
        checagem que `ProcessPage._validated_batch_ids()` fazia antes de
        abrir o dialogo antigo) - a selecao pode ter ficado obsoleta entre o
        momento em que o usuario marcou os checkboxes e o clique no card.
        `None` significa "nao prossiga"; a mensagem ja foi mostrada."""
        if not hasattr(self.service, "validate_batch_selection"):
            return self.process_ids
        result = self.service.validate_batch_selection(self.area, self.process_ids, action_id)
        invalid = result.get("incompatible") or []
        global_reason = result.get("global_reason") or ""
        if invalid or global_reason:
            lines = [
                f"{row.get('proposta') or 'ID ' + str(row.get('id'))}: {row.get('reason') or 'não disponível'}"
                for row in invalid
            ]
            message = "As propostas foram revalidadas e a ação não pode ser aplicada a toda a seleção."
            if global_reason:
                message += f"\n\n{global_reason}"
            if lines:
                message += "\n\nIncompatíveis:\n" + "\n".join(lines[:20])
            QMessageBox.warning(self, "Acoes em lote", message)
            return None
        valid_ids = [int(value) for value in result.get("valid_ids") or []]
        return valid_ids if len(valid_ids) == len(self.process_ids) else None

    def _apply_status(self, status: str):
        if self._validated_process_ids("STATUS") is None:
            return
        label = self.service.action_label(self.area, status)
        observation = self.observation.toPlainText().strip()
        if self.area == "PRODUCAO" and status == "PARADO" and not observation:
            QMessageBox.warning(self, "Pausar producao", "Informe o motivo da pausa na observacao.")
            return
        if QMessageBox.question(self, "Acoes em lote", self._confirmation_text(label)) != QMessageBox.Yes:
            return
        self._run_background_action(lambda: self._apply_status_to_all(status, observation))

    def _apply_status_to_all(self, status: str, observation: str) -> tuple[int, list[str]]:
        changed = 0
        failures: list[str] = []
        for process_id in self.process_ids:
            try:
                self.service.update_status(process_id, self.area, status, observation)
                changed += 1
            except Exception as exc:
                failures.append(f"{self._proposal_label(process_id)}: {exc}")
        return changed, failures

    def _open_register_production(self):
        if self._validated_process_ids("STATUS") is None:
            return
        observation = self.observation.toPlainText().strip()
        dialog = ProductionRegistrationDialog(self.service, self.process_ids, self, observation=observation)
        if dialog.exec():
            self.changed = True
            self.accept()

    def _open_register_delivery(self):
        if self._validated_process_ids("STATUS") is None:
            return
        observation = self.observation.toPlainText().strip()
        item_selections: dict[int, list[int]] = {}
        target_statuses: dict[int, str] = {}
        for process_id in self.process_ids:
            available = self.service.proposal_items(process_id, pending_delivery=True)
            if not available:
                target_statuses[process_id] = "ENTREGUE"
                continue
            selector = ItemSelectionDialog(self.service, process_id, "delivery", self, allow_full_selection=True)
            selector.setWindowTitle(f"Retirada | {self._proposal_label(process_id)}")
            if not selector.exec():
                return
            item_selections[process_id] = selector.selected_ids
            target_statuses[process_id] = "ENTREGUE" if len(selector.selected_ids) == len(available) else "ENTREGUE_PARCIAL"
        if QMessageBox.question(
            self, "Acoes em lote", self._confirmation_text("Registrar retirada do cliente")
        ) != QMessageBox.Yes:
            return
        self._run_background_action(
            lambda: self._apply_delivery_to_all(target_statuses, item_selections, observation)
        )

    def _apply_delivery_to_all(
        self, target_statuses: dict[int, str], item_selections: dict[int, list[int]], observation: str
    ) -> tuple[int, list[str]]:
        changed = 0
        failures: list[str] = []
        for process_id in self.process_ids:
            try:
                self.service.update_status(
                    process_id, self.area, target_statuses.get(process_id, "ENTREGUE"), observation,
                    item_selections.get(process_id),
                )
                changed += 1
            except Exception as exc:
                failures.append(f"{self._proposal_label(process_id)}: {exc}")
        return changed, failures

    def _open_define_flow(self):
        if self._validated_process_ids("DEFINE_ITEM_FLOW") is None:
            return
        dialog = FlowReviewDialog(self.service, self.process_ids, self, origin="ProducaoLote")
        if dialog.exec() or dialog.changed:
            self.changed = True
            self.accept()

    def _open_manage_load_existing(self):
        load_id = choose_existing_load_for_addition(self.service, self)
        if load_id is None:
            return
        try:
            result = self.service.add_items_to_galvanization_load(
                load_id,
                proposal_ids=list(self.process_ids),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Adicionar a uma carga", str(exc))
            return
        added_items = result.get("added_item_ids") or [] if isinstance(result, dict) else []
        QMessageBox.information(
            self,
            "Carga atualizada",
            f"{len(self.process_ids)} proposta(s) adicionada(s) à carga #{load_id}.\n"
            f"Itens adicionados: {len(added_items)}.",
        )
        self.changed = True
        self.accept()

    def _open_manage_load_new(self):
        dialog = GalvanizationLoadDialog(self.service, self.process_ids, parent=self)
        if dialog.exec():
            self.changed = True
            self.accept()

    def _open_register_return(self):
        load_ids = resolve_return_load_ids(self.service, self.process_ids, self)
        if not load_ids:
            return
        # A selecao pode abranger cargas diferentes de proposito (mesma
        # proposta pode ter saldo em mais de uma) - uma unica tela mostra as
        # propostas de todas elas juntas (coluna "Carga" as diferencia) em
        # vez de obrigar o usuario a passar por uma tela por carga.
        dialog = GalvanizationReturnDialog(
            self.service, load_ids[0], self, proposal_ids=self.process_ids, extra_load_ids=load_ids[1:]
        )
        if dialog.exec():
            self.changed = True
            self.accept()

    # -- execucao em segundo plano ------------------------------------

    def _run_background_action(self, operation):
        self._set_running(True)
        self._action_thread = start_worker(self, operation, self._on_action_success, self._on_action_error)

    def _on_action_success(self, result):
        self._set_running(False)
        changed, failures = result
        if failures:
            QMessageBox.warning(
                self, "Acoes em lote",
                f"{changed} proposta(s) alterada(s).\n\nNao alteradas:\n" + "\n".join(failures[:12]),
            )
        self.changed = True
        self.accept()

    def _on_action_error(self, exc):
        self._set_running(False)
        QMessageBox.warning(self, "Acoes em lote", str(exc))

    def _set_running(self, running: bool):
        self._running_action = running
        self.observation.setEnabled(not running)
        for button in self._action_buttons:
            button.setEnabled(not running)
