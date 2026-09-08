from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from app.ui.components.modern_button import ModernButton
from app.ui.background_worker import start_worker
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.numeric_utils import format_decimal, parse_decimal


_GROUP_ROLE = Qt.UserRole + 10
_ITEM_ROLE = Qt.UserRole + 11


def _number(value) -> Decimal:
    return parse_decimal(value, "0")


def _is_production_eligible(row: dict) -> bool:
    if row.get("produzido"):
        return False
    if str(row.get("produzir_internamente") or "").strip().lower() in {"nao", "não", "false", "0"}:
        return False
    if row.get("motivo_bloqueio"):
        return False
    return True


class ProductionReviewDialog(QDialog):
    def __init__(self, groups: list[dict], observation: str, parent=None):
        super().__init__(parent)
        self.confirmed = False
        self.setWindowTitle("Revisar registro de producao")
        apply_large_dialog_geometry(self, parent, minimum_width=720, minimum_height=480)
        style_dialog_from_parent(self, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        title = QLabel("Revisar e registrar producao")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)

        total_items = sum(len(group["selected"]) for group in groups)
        total_weight = sum((row["_weight"] for group in groups for row in group["selected"]), Decimal("0"))
        missing_weight = sum(1 for group in groups for row in group["selected"] if row["_weight"] <= 0)
        summary = QLabel(
            f"{len(groups)} proposta(s) | {total_items} item(ns) | "
            f"{format_decimal(total_weight)} kg"
            + (f" | {missing_weight} sem peso" if missing_weight else "")
        )
        summary.setStyleSheet("font-weight: 700;")
        root.addWidget(summary)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Proposta", "Itens", "Classificacao", "Peso"])
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for group in groups:
            selected = group["selected"]
            available = group["available_count"]
            classification = "TOTAL" if len(selected) == available else "PARCIAL"
            weight = sum((row["_weight"] for row in selected), Decimal("0"))
            top = QTreeWidgetItem([
                f"{group['proposal']} — {group['client']}".strip(" —"),
                f"{len(selected)} de {available}",
                classification,
                f"{format_decimal(weight)} kg" + (" + sem peso" if any(row["_weight"] <= 0 for row in selected) else ""),
            ])
            tree.addTopLevelItem(top)
            for row in selected:
                QTreeWidgetItem(top, [
                    f"{row.get('codigo_produto') or row.get('numero_item') or row['id']}",
                    row.get("descricao") or "-",
                    "Item selecionado",
                    f"{format_decimal(row['_weight'])} kg" if row["_weight"] > 0 else "Nao informado",
                ])
            top.setExpanded(True)
        tree.expandAll()
        root.addWidget(tree, 1)

        if observation.strip():
            note = QLabel(f"Observacao: {observation.strip()}")
            note.setWordWrap(True)
            note.setObjectName("Caption")
            root.addWidget(note)

        footer = QHBoxLayout()
        footer.addStretch()
        back = ModernButton("Voltar", "back")
        confirm = ModernButton("Confirmar producao", "status", accent=True)
        back.clicked.connect(self.reject)
        confirm.clicked.connect(self._confirm)
        footer.addWidget(back)
        footer.addWidget(confirm)
        root.addLayout(footer)

    def _confirm(self):
        self.confirmed = True
        self.accept()


class ProductionRegistrationDialog(QDialog):
    """Mesa de trabalho local para registrar producao de uma ou varias propostas.

    A selecao e a busca permanecem em memoria. A gravacao usa exclusivamente
    ``service.update_status`` e os status oficiais ja calculados pelo backend.
    """

    def __init__(
        self,
        service,
        process_ids: list[int],
        parent=None,
        observation: str = "",
        preselected_item_ids: set[int] | list[int] | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.process_ids = list(dict.fromkeys(int(value) for value in process_ids))
        self.observation = observation
        self.selected_item_ids: set[int] = {int(value) for value in (preselected_item_ids or [])}
        self._groups: list[dict] = []
        self._items_by_id: dict[int, dict] = {}
        self._worker = None
        self._busy = False
        self._build()
        self._load()

    def _build(self):
        self.setWindowTitle("Registrar producao")
        apply_large_dialog_geometry(self, self.parentWidget(), minimum_width=1120, minimum_height=680)
        style_dialog_from_parent(self, self.parentWidget())
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        title = QLabel("Registrar producao")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        root.addWidget(title)
        self.header_summary = QLabel()
        self.header_summary.setStyleSheet("font-weight: 700;")
        root.addWidget(self.header_summary)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proposta, cliente, codigo ou descricao do item...")
        self.search.textChanged.connect(self._apply_filter)
        root.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([
            "Proposta / Item", "Codigo", "Descricao", "Total", "Produzido", "Pendente", "Peso", "Status",
        ])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.setColumnWidth(0, 235)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 360)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 90)
        self.tree.setColumnWidth(5, 90)
        self.tree.setColumnWidth(6, 100)
        root.addWidget(self.tree, 1)

        controls = QHBoxLayout()
        select_all = ModernButton("Selecionar todos", "status")
        clear = ModernButton("Limpar selecao", "clear")
        select_all.clicked.connect(lambda: self._set_all(True))
        clear.clicked.connect(lambda: self._set_all(False))
        controls.addWidget(select_all)
        controls.addWidget(clear)
        controls.addStretch()
        root.addLayout(controls)

        self.observation_input = QLineEdit()
        self.observation_input.setPlaceholderText("Observacao (opcional)")
        self.observation_input.setText(self.observation)
        root.addWidget(self.observation_input)

        footer_frame = QFrame()
        footer_frame.setObjectName("Panel")
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(12, 8, 12, 8)
        self.footer_summary = QLabel()
        self.footer_summary.setStyleSheet("font-weight: 700;")
        footer.addWidget(self.footer_summary)
        footer.addStretch()
        cancel = ModernButton("Cancelar", "clear")
        self.review_button = ModernButton("Confirmar producao", "status", accent=True)
        cancel.clicked.connect(self.reject)
        self.review_button.clicked.connect(self._review)
        footer.addWidget(cancel)
        footer.addWidget(self.review_button)
        root.addWidget(footer_frame)

        QShortcut(QKeySequence("Ctrl+A"), self, activated=lambda: self._set_all(True))
        QShortcut(QKeySequence("Escape"), self, activated=self.reject)
        QShortcut(QKeySequence("Return"), self, activated=self._review)
        self._update_summary()

    def _load(self):
        groups = []
        for process_id in self.process_ids:
            if hasattr(self.service, "get_process_area_dict"):
                process = self.service.get_process_area_dict(process_id, "PRODUCAO")
            else:
                process = self.service.get_process_dict(process_id)
            all_items = self.service.proposal_items(process_id)
            available = [row for row in all_items if _is_production_eligible(row)]
            groups.append({
                "process_id": process_id,
                "proposal": process.get("proposta") or str(process_id),
                "client": process.get("cliente") or "",
                "items": all_items,
                "available": available,
                "available_count": len(available),
                "selected": [],
            })
            for row in all_items:
                item_id = int(row.get("api_id") or row.get("id"))
                quantity = _number(row.get("quantidade"))
                unit_weight = _number(row.get("peso"))
                row["_total_quantity"] = quantity
                row["_weight"] = quantity * unit_weight if unit_weight > 0 else Decimal("0")
                row["_eligible"] = _is_production_eligible(row)
                self._items_by_id[item_id] = row
        self._groups = groups
        eligible_ids = {
            int(row.get("api_id") or row.get("id"))
            for group in groups
            for row in group["available"]
        }
        self.selected_item_ids.intersection_update(eligible_ids)
        self._render()

    def _render(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for group in self._groups:
            selected = [row for row in group["available"] if int(row.get("api_id") or row.get("id")) in self.selected_item_ids]
            group["selected"] = selected
            top = QTreeWidgetItem([
                f"{group['proposal']} — {group['client']}".strip(" —"), "", "",
                f"{group['available_count']} item(ns)", "", f"{len(selected)} selecionado(s)", "", "",
            ])
            top.setData(0, _GROUP_ROLE, group["process_id"])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            if not group["available_count"]:
                top.setCheckState(0, Qt.Unchecked)
                top.setDisabled(True)
                top.setText(7, "Nenhum item disponivel")
            else:
                eligible_count = len(group["available"])
                top.setCheckState(0, Qt.Checked if len(selected) == eligible_count else Qt.PartiallyChecked if selected else Qt.Unchecked)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
            for row in group["items"]:
                item_id = int(row.get("api_id") or row.get("id"))
                total = row["_total_quantity"]
                produced = total if row.get("produzido") else Decimal("0")
                pending = max(total - produced, Decimal("0"))
                eligible = row["_eligible"]
                status = "Disponivel" if eligible else "Produzido" if row.get("produzido") else "Indisponivel"
                child = QTreeWidgetItem([
                    row.get("numero_item") or str(item_id),
                    row.get("codigo_produto") or "-",
                    row.get("descricao") or "-",
                    format_decimal(total),
                    format_decimal(produced),
                    format_decimal(pending),
                    f"{format_decimal(row['_weight'])} kg" if row["_weight"] > 0 else "Nao informado",
                    status,
                ])
                child.setData(0, _ITEM_ROLE, item_id)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if item_id in self.selected_item_ids else Qt.Unchecked)
                if not eligible:
                    child.setDisabled(True)
                top.addChild(child)
        self.tree.blockSignals(False)
        self._apply_filter()
        self._update_summary()

    def _item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or self._busy:
            return
        process_id = item.data(0, _GROUP_ROLE)
        item_id = item.data(0, _ITEM_ROLE)
        if item_id:
            if item.checkState(0) == Qt.Checked:
                self.selected_item_ids.add(int(item_id))
            else:
                self.selected_item_ids.discard(int(item_id))
        elif process_id:
            group = next((value for value in self._groups if value["process_id"] == int(process_id)), None)
            if group:
                ids = {int(row.get("api_id") or row.get("id")) for row in group["available"]}
                if item.checkState(0) == Qt.Checked:
                    self.selected_item_ids.update(ids)
                else:
                    self.selected_item_ids.difference_update(ids)
                self._render()
                return
        self._sync_group_checks()
        self._update_summary()

    def _item_clicked(self, item: QTreeWidgetItem, column: int):
        if item is None or column == 0 or item.data(0, _GROUP_ROLE) or not item.data(0, _ITEM_ROLE):
            return
        item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)

    def _sync_group_checks(self):
        self.tree.blockSignals(True)
        for index, group in enumerate(self._groups):
            top = self.tree.topLevelItem(index)
            ids = {int(row.get("api_id") or row.get("id")) for row in group["available"]}
            count = len(ids.intersection(self.selected_item_ids))
            top.setCheckState(0, Qt.Checked if ids and count == len(ids) else Qt.PartiallyChecked if count else Qt.Unchecked)
            top.setText(5, f"{count} selecionado(s)")
        self.tree.blockSignals(False)

    def _set_all(self, checked: bool):
        if checked:
            for group in self._groups:
                self.selected_item_ids.update(int(row.get("api_id") or row.get("id")) for row in group["available"])
        else:
            self.selected_item_ids.clear()
        self._render()

    def _apply_filter(self):
        text = self.search.text().strip().casefold()
        for index, group in enumerate(self._groups):
            top = self.tree.topLevelItem(index)
            group_match = not text or text in f"{group['proposal']} {group['client']}".casefold()
            visible_children = 0
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                row = self._items_by_id.get(int(child.data(0, _ITEM_ROLE)))
                item_match = not text or text in " ".join(str(row.get(key) or "") for key in ("numero_item", "codigo_produto", "descricao")).casefold()
                child.setHidden(not (group_match or item_match))
                visible_children += int(not child.isHidden())
            top.setHidden(bool(text and not group_match and not visible_children))

    def _update_summary(self):
        selected = [self._items_by_id[item_id] for item_id in self.selected_item_ids if item_id in self._items_by_id]
        proposal_count = len({int(row.get("processo_atual_id") or 0) for row in selected})
        weight = sum((row.get("_weight", Decimal("0")) for row in selected), Decimal("0"))
        missing = sum(1 for row in selected if row.get("_weight", Decimal("0")) <= 0)
        self.header_summary.setText(f"{len(self.process_ids)} proposta(s) | {sum(g['available_count'] for g in self._groups)} itens disponiveis")
        self.footer_summary.setText(
            f"{len(selected)} item(ns) | {proposal_count} proposta(s) | {format_decimal(weight)} kg"
            + (f" | {missing} sem peso" if missing else "")
        )
        self.review_button.setEnabled(bool(selected) and not self._busy)

    def _review(self):
        groups = []
        for group in self._groups:
            selected = [row for row in group["available"] if int(row.get("api_id") or row.get("id")) in self.selected_item_ids]
            if selected:
                groups.append({**group, "selected": selected})
        if not groups:
            QMessageBox.warning(self, "Registrar producao", "Selecione ao menos um item disponivel.")
            return
        review = ProductionReviewDialog(groups, self.observation_input.text(), self)
        if review.exec() and review.confirmed:
            self._execute(groups)

    def _revalidate(self, groups: list[dict]) -> tuple[bool, str]:
        for group in groups:
            current = self.service.proposal_items(group["process_id"], pending_production=True)
            current_ids = {int(row.get("api_id") or row.get("id")) for row in current}
            selected_ids = {int(row.get("api_id") or row.get("id")) for row in group["selected"]}
            if not selected_ids.issubset(current_ids):
                return False, f"A proposta {group['proposal']} foi atualizada por outro usuario. Revise os itens disponiveis."
            options = self.service.next_status_options("PRODUCAO", group["process_id"])
            target = "FINALIZADO" if selected_ids == current_ids else "FINALIZADO_PARCIAL"
            if target not in options:
                return False, f"A proposta {group['proposal']} nao permite mais este registro no estado atual."
        return True, ""

    def _execute(self, groups: list[dict]):
        self._busy = True
        self._update_summary()
        observation = self.observation_input.text().strip()

        def operation():
            valid, message = self._revalidate(groups)
            if not valid:
                return {"valid": False, "message": message}
            processed = 0
            items = 0
            weight = Decimal("0")
            for group in groups:
                selected_ids = [int(row.get("api_id") or row.get("id")) for row in group["selected"]]
                current = self.service.proposal_items(group["process_id"], pending_production=True)
                target = "FINALIZADO" if {int(row.get("api_id") or row.get("id")) for row in current} == set(selected_ids) else "FINALIZADO_PARCIAL"
                self.service.update_status(group["process_id"], "PRODUCAO", target, observation, item_ids=selected_ids)
                processed += 1
                items += len(selected_ids)
                weight += sum((row.get("_weight", Decimal("0")) for row in group["selected"]), Decimal("0"))
            return {"valid": True, "processed": processed, "items": items, "weight": weight}

        def success(result):
            self._busy = False
            self._update_summary()
            if not result.get("valid"):
                QMessageBox.warning(self, "Registro desatualizado", result.get("message") or "Revise os itens disponiveis.")
                self._load()
                return
            QMessageBox.information(self, "Produçao", f"Produçao registrada com sucesso.\n\n{result['processed']} proposta(s) processada(s)\n{result['items']} item(ns) registrado(s)\n{format_decimal(result['weight'])} kg registrado(s)")
            self.accept()

        def error(exc):
            self._busy = False
            self._update_summary()
            QMessageBox.warning(self, "Registrar producao", f"A operacao nao foi concluida integralmente:\n{exc}")

        self._worker = start_worker(
            self, operation, success, error, operation_name="production_registration.execute"
        )
