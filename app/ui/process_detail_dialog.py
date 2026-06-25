from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.backend_adapter import legacy
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import make_icon
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.status_dialog import StatusDialog
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


class ProcessDetailDialog(QDialog):
    def __init__(self, service, process_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.changed = False
        self.setWindowTitle("Detalhes da proposta")
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        self._build()
        self.load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header_panel = QFrame()
        header_panel.setObjectName("Panel")
        header = QHBoxLayout(header_panel)
        header.setContentsMargins(16, 10, 12, 10)
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Caption")
        edit = ModernButton("Editar", "edit")
        status = ModernButton("Acoes", "status", accent=True)
        close = ModernButton("Fechar", "clear")
        edit.clicked.connect(self.edit_process)
        status.clicked.connect(self.change_status)
        close.clicked.connect(self.accept)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box, 1)
        header.addStretch()
        header.addWidget(edit)
        header.addWidget(status)
        header.addWidget(close)
        root.addWidget(header_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 6, 8)
        content_layout.setSpacing(12)

        body = QGridLayout()
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(12)
        self.status_panel = self._panel("Status por area")
        self.info_panel = self._panel("Resumo operacional")
        body.addWidget(self.status_panel, 0, 0)
        body.addWidget(self.info_panel, 0, 1)
        body.setColumnStretch(0, 2)
        body.setColumnStretch(1, 3)
        content_layout.addLayout(body)

        items_panel = self._panel("Itens da proposta")
        self.items_summary = QLabel("0 item(ns)")
        self.items_summary.setObjectName("Caption")
        items_panel.layout().addWidget(self.items_summary)
        self.items_table = QTableWidget(0, 9)
        self.items_table.setHorizontalHeaderLabels(["Item", "Codigo", "Descricao", "Qtd.", "Peso unit.", "Processo", "Produzido", "Galvanizado", "Entregue"])
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in enumerate((70, 90, 320, 65, 90, 120, 90, 100, 90)):
            self.items_table.setColumnWidth(col, width)
        configure_wrapping_table(self.items_table, description_columns=(2,), code_columns=(1,), min_row_height=42)
        self.items_table.setMinimumHeight(150)
        self.items_table.setMaximumHeight(240)
        items_panel.layout().addWidget(self.items_table)
        content_layout.addWidget(items_panel)

        timeline_panel = self._panel("Linha do tempo")
        timeline_layout = timeline_panel.layout()
        self.timeline_summary = QLabel("Historico completo das movimentacoes desta proposta")
        self.timeline_summary.setObjectName("Caption")
        timeline_layout.addWidget(self.timeline_summary)
        self.timeline = QTableWidget(0, 6)
        self.timeline.setHorizontalHeaderLabels(["Area", "Anterior", "Novo", "Quando", "Usuario", "Observacao"])
        self.timeline.verticalHeader().setVisible(False)
        self.timeline.setSelectionBehavior(QTableWidget.SelectRows)
        self.timeline.setEditTriggers(QTableWidget.NoEditTriggers)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        for col, width in enumerate((130, 160, 160, 145, 110, 360)):
            self.timeline.setColumnWidth(col, width)
        self.timeline.setMinimumHeight(230)
        timeline_layout.addWidget(self.timeline)
        content_layout.addWidget(timeline_panel, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 800;")
        layout.addWidget(label)
        return panel

    def clear_panel_content(self, panel: QFrame):
        layout = panel.layout()
        while layout.count() > 1:
            item = layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def load(self):
        self.process = self.service.get_process_dict(self.process_id)
        if not self.process:
            self.reject()
            return
        p = self.process
        self.title.setText(f"{p.get('proposta') or '-'} | {p.get('cliente') or '-'}")
        self.subtitle.setText(
            f"Obra/Site: {p.get('obra_site') or '-'} | Lote: {p.get('lote') or '-'} | "
            f"Prazo: {p.get('prazo_entrega') or '-'} | Situacao: {self.service.status_label(p.get('situacao_fluxo') or '')}"
        )
        self.load_status()
        self.load_info()
        self.load_items()
        self.load_timeline()

    def load_items(self):
        items = self.service.proposal_items(self.process_id)
        self.items_table.setRowCount(len(items))
        total_units = sum(int(item.get("quantidade") or 1) for item in items)
        total_weight = sum(int(item.get("quantidade") or 1) * float(item.get("peso") or 0) for item in items)
        self.items_summary.setText(f"{len(items)} linha(s) | {total_units} unidade(s) | {total_weight:g} kg")
        process_names = {row.get("id"): row.get("proposta") for row in self.service.process_partials(self.process_id)}
        for row, item in enumerate(items):
            values = [
                item.get("numero_item"), item_product_code(item), item.get("descricao"), item.get("quantidade") or 1,
                f"{float(item.get('peso') or 0):g} kg",
                process_names.get(item.get("processo_atual_id"), "-"),
                "Sim" if item.get("produzido") else "Nao",
                "Sim" if item.get("galvanizado") else "Nao",
                "Sim" if item.get("entregue") else "Nao",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if col == 2 else Qt.AlignCenter)
                self.items_table.setItem(row, col, cell)
        resize_rows_to_contents(self.items_table)
        visible_rows = min(max(len(items), 2), 6)
        self.items_table.setFixedHeight(68 + visible_rows * 46)

    def load_status(self):
        self.clear_panel_content(self.status_panel)
        layout = self.status_panel.layout()
        for area, meta in legacy.AREAS.items():
            status = self.process.get(meta["column"]) or ""
            row_frame = QFrame()
            row_frame.setStyleSheet(
                f"background: {self.service.palette['surface_alt']}; border-radius: 8px;"
            )
            line = QHBoxLayout(row_frame)
            line.setContentsMargins(10, 7, 10, 7)
            line.setSpacing(8)
            icon = QLabel()
            icon.setPixmap(make_icon(status or "status", self.service.palette["accent"], 18).pixmap(18, 18))
            icon.setFixedWidth(24)
            area_label = QLabel(area.title())
            area_label.setObjectName("Caption")
            area_label.setMinimumWidth(115)
            status_label = QLabel(self.service.area_status_label(area, status) if status else "Nao iniciado")
            status_label.setStyleSheet("font-weight: 800;")
            line.addWidget(icon)
            line.addWidget(area_label)
            line.addWidget(status_label, 1)
            layout.addWidget(row_frame)

    def load_info(self):
        self.clear_panel_content(self.info_panel)
        layout = self.info_panel.layout()
        grid = QGridLayout()
        rows = [
            ("Tipo", self.service.status_label(self.process.get("tipo_processo") or "")),
            ("Peso total", self.service.display_cell("peso", self.process.get("peso"), self.process)),
            ("Peso / saldo", self.service.weight_progress_text(self.process_id)),
            ("Peso parcial", self.service.display_cell("peso_parcial", self.process.get("peso_parcial"), self.process)),
            ("Saldo pendente", self.service.display_cell("saldo_pendente", self.process.get("saldo_pendente"), self.process)),
            ("Origem remanejamento", self.process.get("origem_remanejamento") or "-"),
            ("Obs. remanejamento", self.process.get("observacao_remanejamento") or "-"),
            ("Atualizado por", self.process.get("atualizado_por") or "-"),
            ("Atualizado em", self.process.get("atualizado_em") or "-"),
        ]
        for row, (label, value) in enumerate(rows):
            left = QLabel(label)
            left.setObjectName("Caption")
            right = QLabel(str(value or "-"))
            right.setWordWrap(True)
            right.setStyleSheet("font-weight: 700;")
            grid.addWidget(left, row, 0, Qt.AlignTop)
            grid.addWidget(right, row, 1)
        grid.setColumnMinimumWidth(0, 145)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        partials = self.service.process_partials(self.process_id)
        loads = self.service.process_loads(self.process_id)
        layout.addWidget(QLabel(f"Parciais vinculadas: {max(0, len(partials) - 1)}"))
        for partial in partials[:5]:
            layout.addWidget(QLabel(f"{partial.get('proposta')} | {self.service.status_label(partial.get('situacao_fluxo') or '')}"))
        layout.addWidget(QLabel(f"Cargas vinculadas: {len(loads)}"))
        for load in loads[:4]:
            layout.addWidget(QLabel(
                f"Carga {load.get('id')} | {self.service.load_status_label(load.get('status') or '')} | "
                f"Prev.: {load.get('data_prevista_retorno') or '-'} | Retorno: {load.get('data_retorno') or '-'}"
            ))

    def load_timeline(self):
        self.timeline.setRowCount(0)
        history = self.service.process_history_rows(self.process_id)
        self.timeline_summary.setText(f"{len(history)} movimentacao(oes) registrada(s)")
        for item in history:
            row = self.timeline.rowCount()
            self.timeline.insertRow(row)
            values = [
                item.get("area"),
                self.service.area_status_label(item.get("area") or "", item.get("status_anterior") or ""),
                self.service.area_status_label(item.get("area") or "", item.get("status_novo") or ""),
                item.get("data_hora"),
                item.get("usuario"),
                item.get("observacao"),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignCenter if col < 5 else Qt.AlignVCenter | Qt.AlignLeft)
                self.timeline.setItem(row, col, cell)

    def edit_process(self):
        dialog = ProcessFormDialog(self.service, self.process_id, self)
        if dialog.exec():
            self.changed = True
            self.load()

    def change_status(self):
        area, _label, _status = self.service.current_location(self.process)
        area = area if area in self.service.visible_areas() else None
        dialog = StatusDialog(self.service, self.process_id, area, self)
        if dialog.exec():
            self.changed = True
            self.load()
