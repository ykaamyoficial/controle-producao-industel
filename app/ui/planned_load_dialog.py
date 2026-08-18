from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
)

from app.models.planned_load_item_table_model import PlannedLoadItemTableModel
from app.services.backend_adapter import VersionConflictError
from app.ui.background_worker import start_worker
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.galvanization_load_dialog import GalvanizationLoadDialog
from app.ui.planned_load_build_summary_dialog import PlannedLoadBuildSummaryDialog
from app.ui.planned_load_item_picker_dialog import PlannedLoadItemPickerDialog

# Status finais (PlannedLoadSummary.status) em que nao faz mais sentido
# cancelar nem montar carga a partir do planejamento -- mesma lista de
# valores reais definida em `app/ui/planned_loads_page.py`
# (PLANNED_LOAD_STATUS_OPTIONS).
CLOSED_PLANNED_LOAD_STATUSES = {"Convertida em carga", "Cancelada"}

# Traducao de `PlannedLoadHistoryEntry.event_type` (api/app/modules/
# planned_loads/service.py::_record_history) para a aba "Acompanhamento"
# (FASE_PL6). Lista fechada com os event_type reais emitidos pelo backend --
# qualquer valor novo cai no fallback (mostra o codigo bruto).
HISTORY_EVENT_LABELS = {
    "PLANNED_LOAD_CREATED": "Planejamento criado",
    "PLANNED_LOAD_UPDATED": "Planejamento atualizado",
    "PLANNED_LOAD_ITEM_ADDED": "Item adicionado",
    "PLANNED_LOAD_ITEM_UPDATED": "Item atualizado",
    "PLANNED_LOAD_ITEM_REMOVED": "Item removido",
    "PLANNED_LOAD_CANCELLED": "Planejamento cancelado",
    "PLANNED_LOAD_BUILD_EVALUATED": "Disponibilidade avaliada",
    "PLANNED_LOAD_CONVERTED": "Convertido em carga",
}


def _history_event_label(event_type: str | None) -> str:
    return HISTORY_EVENT_LABELS.get(event_type or "", event_type or "-")


def _format_history_when(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.strftime("%d/%m/%Y %H:%M")


class PlannedLoadDialog(QDialog):
    """Edicao/criacao de planejamento de carga.

    3 abas: "Dados do planejamento" (cabecalho -- salva via PATCH quando o
    planejamento ja existe, ou via POST na criacao), "Itens planejados"
    (tabela + adicionar/remover/editar quantidade, com indicador visual de
    divergencia por item -- FASE_PL6) e "Acompanhamento" (historico
    somente-leitura vindo de `PlannedLoadDetail.history`, FASE_PL6).
    Conflito de versao (`VersionConflictError`) nas operacoes de salvar
    cabeçalho/editar/remover item segue o mesmo padrao de
    `ItemFlowDialog._handle_version_conflict`: pergunta se recarrega e
    preserva o que for possivel da edicao pendente do usuario. O fluxo de
    conversao para carga real (`/build`, `/mark-converted`) e o cancelamento
    (`/cancel`) sao o botao "Montar carga a partir deste planejamento" e o
    botao "Cancelar planejamento" (FASE_PL7): `/build` so avalia
    disponibilidade -- a carga real e sempre criada pelo `GalvanizationLoadDialog`
    ja existente (pre-preenchido com os itens prontos), e so depois de aquele
    dialogo confirmar sucesso e que `mark_planned_load_converted` e chamado.
    `/mark-converted` nunca e chamado antes disso nem se o usuario cancelar o
    `GalvanizationLoadDialog`."""

    def __init__(self, service, planned_load_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.planned_load_id = planned_load_id
        self.version: int | None = None
        self._detail: dict[str, Any] = {}
        # Itens ainda nao persistidos (planejamento novo, sem id) -- entram
        # no payload de criacao (POST aceita `items` direto). Depois de
        # salvo, cada alteracao de item passa a ser uma chamada imediata aos
        # endpoints .../items (POST/PATCH/DELETE).
        self._pending_items: dict[int, dict[str, Any]] = {}
        self._busy = False
        self.saved = False
        self.setWindowTitle("Editar planejamento de carga" if planned_load_id else "Novo planejamento de carga")
        apply_large_dialog_geometry(self, parent, minimum_width=900, minimum_height=560)
        style_dialog_from_parent(self, parent)
        self._build()
        if planned_load_id:
            self._load_existing()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ModernTabs")
        self.tabs.addTab(self._build_header_tab(), "Dados do planejamento")
        self.tabs.addTab(self._build_items_tab(), "Itens planejados")
        self.tabs.addTab(self._build_history_tab(), "Acompanhamento")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.cancel_planning_button = QPushButton("Cancelar planejamento")
        self.cancel_planning_button.clicked.connect(self.cancel_planning)
        self.build_load_button = QPushButton("Montar carga a partir deste planejamento")
        self.build_load_button.clicked.connect(self.build_load)
        self.cancel_button = QPushButton("Cancelar")
        self.save_button = QPushButton("Salvar")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save)
        footer.addWidget(self.cancel_planning_button)
        footer.addWidget(self.build_load_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self._update_conversion_buttons_state()

    def _build_header_tab(self) -> QFrame:
        frame = QFrame()
        layout = QGridLayout(frame)
        self.code_field = QLineEdit()
        self.code_field.setReadOnly(bool(self.planned_load_id))
        self.code_field.setPlaceholderText("Opcional - gerado automaticamente se vazio")
        self.expected_ship_date = QLineEdit()
        self.expected_ship_date.setPlaceholderText("dd/mm/aaaa")
        self.carrier_name = QLineEdit()
        self.vehicle_info = QLineEdit()
        # TODO PL6: combo de usuarios -- por ora, id numerico simples.
        self.responsible_user_id = QLineEdit()
        self.responsible_user_id.setPlaceholderText("ID do usuario responsavel")
        self.notes = QTextEdit()
        self.notes.setFixedHeight(60)

        layout.addWidget(QLabel("Codigo"), 0, 0)
        layout.addWidget(self.code_field, 0, 1)
        layout.addWidget(QLabel("Previsao de envio"), 0, 2)
        layout.addWidget(self.expected_ship_date, 0, 3)
        layout.addWidget(QLabel("Transportadora"), 1, 0)
        layout.addWidget(self.carrier_name, 1, 1)
        layout.addWidget(QLabel("Veiculo"), 1, 2)
        layout.addWidget(self.vehicle_info, 1, 3)
        layout.addWidget(QLabel("Responsavel (ID)"), 2, 0)
        layout.addWidget(self.responsible_user_id, 2, 1)
        layout.addWidget(QLabel("Observacoes"), 3, 0)
        layout.addWidget(self.notes, 3, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return frame

    def _build_items_tab(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        items_label = QLabel("Itens planejados")
        items_label.setObjectName("FieldLabel")
        layout.addWidget(items_label)
        self.items_model = PlannedLoadItemTableModel()
        self.items_table = QTableView()
        self.items_table.setModel(self.items_model)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        self.items_table.doubleClicked.connect(self._edit_selected_quantity)
        layout.addWidget(self.items_table, 1)

        actions = QHBoxLayout()
        self.add_items_button = QPushButton("Adicionar itens")
        self.add_items_button.clicked.connect(self.open_item_picker)
        self.edit_quantity_button = QPushButton("Editar quantidade")
        self.edit_quantity_button.clicked.connect(self._edit_selected_quantity)
        self.remove_item_button = QPushButton("Remover")
        self.remove_item_button.clicked.connect(self.remove_selected_item)
        actions.addWidget(self.add_items_button)
        actions.addWidget(self.edit_quantity_button)
        actions.addWidget(self.remove_item_button)
        actions.addStretch()
        layout.addLayout(actions)
        return frame

    def _build_history_tab(self) -> QFrame:
        """Aba "Acompanhamento" (FASE_PL6) -- historico somente-leitura de
        `PlannedLoadDetail.history`, ja embutido em `planned_load_detail`
        (sem endpoint novo). Um planejamento ainda nao salvo nao tem
        historico; a tabela so e populada em `_apply_detail`."""
        frame = QFrame()
        layout = QVBoxLayout(frame)
        history_label = QLabel("Historico do planejamento")
        history_label.setObjectName("FieldLabel")
        layout.addWidget(history_label)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Evento", "Status anterior -> novo", "Autor", "Quando"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionMode(QTableWidget.NoSelection)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.history_table, 1)

        self.history_empty_label = QLabel("Nenhum evento registrado ainda.")
        self.history_empty_label.setObjectName("Caption")
        self.history_empty_label.setVisible(False)
        layout.addWidget(self.history_empty_label)
        return frame

    def _load_history_rows(self, history: list[dict[str, Any]]) -> None:
        self.history_table.setRowCount(0)
        for entry in history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            from_status = entry.get("from_status") or "-"
            to_status = entry.get("to_status") or "-"
            transition = f"{from_status} -> {to_status}" if entry.get("from_status") or entry.get("to_status") else "-"
            values = [
                _history_event_label(entry.get("event_type")),
                transition,
                entry.get("actor_name") or "Sistema",
                _format_history_when(entry.get("created_at")),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.history_table.setItem(row, column, item)
        self.history_empty_label.setVisible(not history)

    # -- carregamento -------------------------------------------------

    def _load_existing(self):
        detail = self.service.planned_load_detail(self.planned_load_id)
        self._apply_detail(detail)

    def _apply_detail(self, detail: dict[str, Any]):
        self._detail = detail or {}
        self.planned_load_id = self._detail.get("id") or self.planned_load_id
        self.version = self._detail.get("version")
        self.code_field.setReadOnly(bool(self.planned_load_id))
        self.code_field.setText(self._detail.get("code") or "")
        self.expected_ship_date.setText(_format_date_display(self._detail.get("expected_ship_date")))
        self.carrier_name.setText(self._detail.get("carrier_name") or "")
        self.vehicle_info.setText(self._detail.get("vehicle_info") or "")
        responsible_id = self._detail.get("responsible_user_id")
        self.responsible_user_id.setText(str(responsible_id) if responsible_id else "")
        self.notes.setPlainText(self._detail.get("notes") or "")
        self.items_model.set_rows(list(self._detail.get("items") or []))
        self._load_history_rows(list(self._detail.get("history") or []))
        self._update_conversion_buttons_state()

    def _update_conversion_buttons_state(self) -> None:
        """"Cancelar planejamento" e "Montar carga a partir deste
        planejamento" (FASE_PL7) so fazem sentido para um planejamento ja
        salvo (tem `planned_load_id`), ainda aberto (status fora de
        `CLOSED_PLANNED_LOAD_STATUSES`) -- checado aqui ao carregar/recarregar
        o dialogo, sem esperar o erro do servidor (que continua sendo tratado
        como rede de seguranca em `cancel_planning`/`build_load`). Montar
        carga exige tambem ao menos um item planejado."""
        status = self._detail.get("status")
        is_open = bool(self.planned_load_id) and status not in CLOSED_PLANNED_LOAD_STATUSES
        self.cancel_planning_button.setEnabled(is_open)
        self.build_load_button.setEnabled(is_open and self.items_model.rowCount() > 0)

    # -- itens ----------------------------------------------------------

    def open_item_picker(self):
        dialog = PlannedLoadItemPickerDialog(self.service, parent=self)
        if not dialog.exec():
            return
        picked = dialog.get_selected_items()
        if not picked:
            return
        if self.planned_load_id:
            self._add_items_live(picked)
        else:
            self._add_items_pending(picked)

    def _add_items_pending(self, picked: list[dict[str, Any]]):
        for entry in picked:
            proposal_item_id = int(entry["proposal_item_id"])
            self._pending_items[proposal_item_id] = entry
        self._refresh_pending_table()

    def _refresh_pending_table(self):
        rows = [
            {
                "id": None,
                "proposal_item_id": entry.get("proposal_item_id"),
                "proposal_number": entry.get("proposal_number", ""),
                "customer_name": entry.get("customer_name", ""),
                "item_number": entry.get("item_number", ""),
                "description": entry.get("description", ""),
                "planned_quantity": entry.get("planned_quantity"),
                "currently_available_quantity": "-",
                "missing_quantity": "-",
            }
            for entry in self._pending_items.values()
        ]
        self.items_model.set_rows(rows)

    def _add_items_live(self, picked: list[dict[str, Any]]):
        items_payload = [
            {
                "proposal_item_id": int(entry["proposal_item_id"]),
                "planned_quantity": str(entry["planned_quantity"]),
                "notes": entry.get("notes") or None,
            }
            for entry in picked
        ]
        try:
            detail = self.service.add_planned_load_items(self.planned_load_id, items_payload)
        except VersionConflictError:
            self._handle_item_version_conflict("Adicionar itens")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Adicionar itens", str(exc))
            return
        self._apply_detail(detail)

    def _selected_item_row(self) -> int | None:
        selection_model = self.items_table.selectionModel()
        indexes = selection_model.selectedRows() if selection_model else []
        if not indexes:
            return None
        return indexes[0].row()

    def remove_selected_item(self):
        row = self._selected_item_row()
        if row is None:
            QMessageBox.warning(self, "Itens planejados", "Selecione um item.")
            return
        item_row = self.items_model.item_row_at(row)
        if not item_row:
            return
        if not self.planned_load_id:
            proposal_item_id = item_row.get("proposal_item_id")
            if proposal_item_id is not None:
                self._pending_items.pop(int(proposal_item_id), None)
            self._refresh_pending_table()
            return
        item_id = item_row.get("id")
        if not item_id:
            return
        version = item_row.get("version")
        try:
            detail = self.service.delete_planned_load_item(self.planned_load_id, int(item_id), int(version or 0))
        except VersionConflictError:
            self._handle_item_version_conflict("Remover item")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Remover item", str(exc))
            return
        self._apply_detail(detail)

    def _edit_selected_quantity(self, *_args):
        row = self._selected_item_row()
        if row is None:
            QMessageBox.warning(self, "Itens planejados", "Selecione um item.")
            return
        item_row = self.items_model.item_row_at(row)
        if not item_row:
            return
        current = item_row.get("planned_quantity") or 0
        try:
            current_value = float(str(current).replace(",", "."))
        except (TypeError, ValueError):
            current_value = 0.0
        new_value, ok = QInputDialog.getDouble(
            self, "Quantidade planejada", "Nova quantidade planejada:", current_value, 0.0001, 1_000_000_000.0, 4
        )
        if not ok:
            return
        if not self.planned_load_id:
            proposal_item_id = item_row.get("proposal_item_id")
            if proposal_item_id is not None:
                entry = self._pending_items.get(int(proposal_item_id))
                if entry:
                    entry["planned_quantity"] = new_value
            self._refresh_pending_table()
            return
        item_id = item_row.get("id")
        if not item_id:
            return
        version = item_row.get("version")
        self._apply_quantity_update(int(item_id), int(version or 0), new_value)

    def _apply_quantity_update(self, item_id: int, version: int, new_value: float) -> None:
        try:
            detail = self.service.update_planned_load_item(
                self.planned_load_id, item_id, {"version": version, "planned_quantity": str(new_value)}
            )
        except VersionConflictError:
            self._handle_quantity_version_conflict(item_id, new_value)
            return
        except Exception as exc:
            QMessageBox.critical(self, "Editar quantidade", str(exc))
            return
        self._apply_detail(detail)

    # -- conflito de versao (VersionConflictError) -----------------------
    # Mesmo padrao de `ItemFlowDialog._handle_version_conflict`
    # (app/ui/item_flow_dialog.py): pergunta via QMessageBox.question se o
    # usuario quer recarregar, e so entao recarrega -- nunca sobrescreve
    # silenciosamente o que o usuario tinha digitado.

    def _handle_item_version_conflict(self, context: str) -> None:
        """Usado por adicionar/remover item -- nao ha um valor pendente
        significativo para reaplicar (a intencao era so incluir/excluir),
        entao a melhor preservacao possivel e recarregar o planejamento sem
        fechar a tela, para o usuario decidir o proximo passo com dados
        atuais."""
        answer = QMessageBox.question(
            self,
            context,
            "Este item foi atualizado por outra pessoa desde que esta tela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes deste planejamento?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.planned_load_detail(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, context, str(exc))
            return
        self._apply_detail(detail)

    def _handle_quantity_version_conflict(self, item_id: int, pending_value: float) -> None:
        """Recarrega e, se o item ainda existir, reabre o input de
        quantidade com o valor que o usuario tinha digitado (`pending_value`)
        pre-preenchido -- ele so precisa confirmar de novo, sem redigitar."""
        answer = QMessageBox.question(
            self,
            "Editar quantidade",
            "Este item foi atualizado por outra pessoa desde que esta tela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes e revisar a quantidade antes de tentar novamente?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.planned_load_detail(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Editar quantidade", str(exc))
            return
        self._apply_detail(detail)
        updated_row = next((row for row in self.items_model.rows if row.get("id") == item_id), None)
        if updated_row is None:
            return
        new_value, ok = QInputDialog.getDouble(
            self,
            "Quantidade planejada",
            "Nova quantidade planejada (revisar apos recarregar):",
            pending_value,
            0.0001,
            1_000_000_000.0,
            4,
        )
        if not ok:
            return
        self._apply_quantity_update(int(updated_row["id"]), int(updated_row.get("version") or 0), new_value)

    # -- cancelamento (FASE_PL7) ------------------------------------------

    def cancel_planning(self) -> None:
        if self._busy or not self.planned_load_id:
            return
        answer = QMessageBox.question(
            self,
            "Cancelar planejamento",
            "Deseja realmente cancelar este planejamento de carga?\n"
            "Esta acao nao pode ser desfeita.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.cancel_planned_load(self.planned_load_id, int(self.version or 0))
        except VersionConflictError:
            self._handle_cancel_version_conflict()
            return
        except Exception as exc:
            QMessageBox.critical(self, "Cancelar planejamento", str(exc))
            return
        self._apply_detail(detail)
        QMessageBox.information(self, "Cancelar planejamento", "Planejamento cancelado.")

    def _handle_cancel_version_conflict(self) -> None:
        answer = QMessageBox.question(
            self,
            "Cancelar planejamento",
            "Este planejamento foi atualizado por outra pessoa desde que esta tela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes deste planejamento?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.planned_load_detail(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Cancelar planejamento", str(exc))
            return
        self._apply_detail(detail)

    # -- montar carga a partir do planejamento (FASE_PL7) -----------------
    # Nucleo da fase: POST /build so avalia disponibilidade (nunca cria a
    # carga real). Se tudo disponivel, abre direto o GalvanizationLoadDialog
    # ja existente pre-preenchido; senao mostra o resumo
    # (PlannedLoadBuildSummaryDialog) com a opcao de montar so o disponivel.
    # mark_planned_load_converted so e chamado DEPOIS que o
    # GalvanizationLoadDialog confirma sucesso (`dialog.saved`/`dialog.load_id`)
    # -- nunca antes, nunca se o usuario cancelar aquele dialogo.

    def build_load(self) -> None:
        if self._busy or not self.planned_load_id:
            return
        try:
            result = self.service.build_planned_load(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Montar carga", str(exc))
            return
        self._handle_build_result(result)

    def _handle_build_result(self, result: dict[str, Any]) -> None:
        if result.get("fully_available"):
            self._open_galvanization_load_dialog(list(result.get("ready_items") or []))
            return
        summary_dialog = PlannedLoadBuildSummaryDialog(result, parent=self)
        if summary_dialog.exec():
            self._open_galvanization_load_dialog(list(result.get("ready_items") or []))

    def _open_galvanization_load_dialog(self, ready_items: list[dict[str, Any]]) -> None:
        item_ids = [int(entry["proposal_item_id"]) for entry in ready_items if entry.get("proposal_item_id")]
        if not item_ids:
            QMessageBox.warning(self, "Montar carga", "Nenhum item disponivel para montar a carga.")
            return
        dialog = GalvanizationLoadDialog(self.service, preselected_item_ids=item_ids, parent=self)
        if not dialog.exec() or not dialog.saved or not dialog.load_id:
            return
        self._mark_converted(int(dialog.load_id))

    def _mark_converted(self, real_load_id: int) -> None:
        try:
            detail = self.service.mark_planned_load_converted(self.planned_load_id, int(self.version or 0), real_load_id)
        except VersionConflictError:
            self._handle_mark_converted_version_conflict(real_load_id)
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Montar carga",
                f"A carga real {real_load_id} foi criada, mas nao foi possivel marcar este planejamento "
                f"como convertido: {exc}",
            )
            return
        self._apply_detail(detail)
        self.saved = True
        QMessageBox.information(self, "Montar carga", f"Planejamento convertido para a carga {real_load_id}.")
        self.accept()

    def _handle_mark_converted_version_conflict(self, real_load_id: int) -> None:
        answer = QMessageBox.question(
            self,
            "Montar carga",
            f"A carga real {real_load_id} foi criada, mas este planejamento foi atualizado por outra pessoa "
            "desde que esta tela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes e tentar marcar a conversao novamente?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.planned_load_detail(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Montar carga", str(exc))
            return
        self._apply_detail(detail)
        self._mark_converted(real_load_id)

    # -- salvar -----------------------------------------------------------

    def _common_header_fields(self) -> dict[str, Any]:
        responsible_text = self.responsible_user_id.text().strip()
        return {
            "expected_ship_date": _parse_date_input(self.expected_ship_date.text()),
            "carrier_name": self.carrier_name.text().strip() or None,
            "vehicle_info": self.vehicle_info.text().strip() or None,
            "responsible_user_id": int(responsible_text) if responsible_text else None,
            "notes": self.notes.toPlainText().strip() or None,
        }

    def save(self):
        if self._busy:
            return
        responsible_text = self.responsible_user_id.text().strip()
        if responsible_text and not responsible_text.isdigit():
            QMessageBox.warning(self, "Planejamento de carga", "Informe um ID numerico para o responsavel.")
            return
        if self.planned_load_id:
            self._save_existing()
        else:
            self._save_new()

    def _save_existing(self):
        payload = self._common_header_fields()
        payload["version"] = int(self.version or 0)
        self._set_busy(True)

        def operation():
            return self.service.update_planned_load(self.planned_load_id, payload)

        def success(detail):
            self._set_busy(False)
            self.saved = True
            self._apply_detail(detail)
            self.accept()

        def error(exc):
            self._set_busy(False)
            if isinstance(exc, VersionConflictError):
                self._handle_header_version_conflict(payload)
                return
            QMessageBox.critical(self, "Planejamento de carga", str(exc))

        self._worker = start_worker(self, operation, success, error, operation_name="planned_load_dialog.update")

    def _handle_header_version_conflict(self, pending_payload: dict[str, Any]) -> None:
        """Mesmo padrao de `ItemFlowDialog._handle_version_conflict`: pergunta
        se recarrega e, se sim, restaura nos campos os valores que o usuario
        tinha digitado (`pending_payload`) -- so a versao vem do servidor.
        O dialogo continua aberto para o usuario clicar Salvar de novo."""
        answer = QMessageBox.question(
            self,
            "Planejamento de carga",
            "Este planejamento foi atualizado por outra pessoa desde que esta janela foi aberta.\n\n"
            "Deseja recarregar os dados mais recentes?\n"
            "Os campos que voce ja preencheu serao mantidos para voce revisar antes de salvar novamente.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            detail = self.service.planned_load_detail(self.planned_load_id)
        except Exception as exc:
            QMessageBox.critical(self, "Planejamento de carga", str(exc))
            return
        self._apply_detail(detail)
        self.carrier_name.setText(pending_payload.get("carrier_name") or "")
        self.vehicle_info.setText(pending_payload.get("vehicle_info") or "")
        self.notes.setPlainText(pending_payload.get("notes") or "")
        responsible = pending_payload.get("responsible_user_id")
        self.responsible_user_id.setText(str(responsible) if responsible else "")
        self.expected_ship_date.setText(_format_date_display(pending_payload.get("expected_ship_date")))

    def _save_new(self):
        payload = self._common_header_fields()
        payload["code"] = self.code_field.text().strip() or None
        payload["items"] = [
            {
                "proposal_item_id": int(entry["proposal_item_id"]),
                "planned_quantity": str(entry["planned_quantity"]),
                "notes": entry.get("notes") or None,
            }
            for entry in self._pending_items.values()
        ]
        self._set_busy(True)

        def operation():
            return self.service.create_planned_load(payload)

        def success(detail):
            self._set_busy(False)
            self.saved = True
            self._apply_detail(detail)
            self.accept()

        def error(exc):
            self._set_busy(False)
            QMessageBox.critical(self, "Planejamento de carga", str(exc))

        self._worker = start_worker(self, operation, success, error, operation_name="planned_load_dialog.create")

    def _set_busy(self, busy: bool):
        self._busy = busy
        for widget in (
            self.code_field, self.expected_ship_date, self.carrier_name, self.vehicle_info,
            self.responsible_user_id, self.notes, self.add_items_button, self.edit_quantity_button,
            self.remove_item_button, self.cancel_button, self.save_button,
            self.cancel_planning_button, self.build_load_button,
        ):
            widget.setEnabled(not busy)
        self.save_button.setText("Salvando..." if busy else "Salvar")
        if not busy:
            # `cancel_planning_button`/`build_load_button` tem regras propias
            # de habilitacao (status/itens) -- nao basta reabilitar tudo.
            self._update_conversion_buttons_state()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)


def _format_date_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        year, month, day = parts
        return f"{day}/{month}/{year}"
    return text


def _parse_date_input(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "/" in text:
        parts = text.split("/")
        if len(parts) == 3:
            day, month, year = parts
            return f"{year.zfill(4)}-{month.zfill(2)}-{day.zfill(2)}"
    return text
