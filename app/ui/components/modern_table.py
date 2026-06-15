from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTableView

from app.ui.styles import area_color, status_color
from app.ui.icons import make_icon


class ProcessFilterProxy(QSortFilterProxyModel):
    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        text = self.filterRegularExpression().pattern().lower()
        if not text:
            return True
        model = self.sourceModel()
        row = model.rows[source_row]
        haystack = " ".join(str(row.get(key) or "") for key, _label in model.columns).lower()
        return text in haystack


class StatusBadgeDelegate(QStyledItemDelegate):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        key = index.data(Qt.UserRole + 1)
        if key == "status_icon":
            raw = index.data(Qt.UserRole + 2) or "status"
            painter.save()
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(self.service.palette["accent"]))
            icon = make_icon(str(raw), self.service.palette["accent"], 20)
            pix = icon.pixmap(20, 20)
            x = option.rect.x() + (option.rect.width() - 20) // 2
            y = option.rect.y() + (option.rect.height() - 20) // 2
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(self.service.palette["surface"])))
            painter.drawRoundedRect(option.rect.adjusted(7, 5, -7, -5), 12, 12)
            painter.drawPixmap(x, y, pix)
            painter.restore()
            return
        if key and ("status" in key or key == "localizacao_atual"):
            text = index.data(Qt.DisplayRole) or "-"
            raw = index.data(Qt.UserRole + 2) or text
            area = index.data(Qt.UserRole + 3) or ""
            if key == "localizacao_atual":
                bg = area_color(str(raw or area), self.service.palette)
                _, fg = status_color("", self.service.palette, str(raw or area))
            else:
                bg, fg = status_color(str(raw), self.service.palette, str(area))
            painter.save()
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(self.service.palette["accent"]))
            rect = option.rect.adjusted(8, 6, -8, -6)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(bg)))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QPen(QColor(fg)))
            visible_text = option.fontMetrics.elidedText(str(text), Qt.ElideRight, max(20, rect.width() - 14))
            painter.drawText(rect, Qt.AlignCenter, visible_text)
            painter.restore()
            return
        super().paint(painter, option, index)


class ModernTable(QTableView):
    status_shortcut_requested = Signal(int)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setMinimumHeight(28)
        self.horizontalHeader().setFixedHeight(30)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setItemDelegate(StatusBadgeDelegate(service, self))
        self.setWordWrap(True)
        self.setToolTip("Clique no icone da primeira coluna para abrir as acoes da proposta.")
        self.setMouseTracking(True)

    def setModel(self, model):
        super().setModel(model)
        self.apply_column_layout()

    def apply_column_layout(self):
        model = self.model()
        source = model.sourceModel() if hasattr(model, "sourceModel") else model
        columns = getattr(source, "columns", [])
        widths = {
            "status_icon": 44,
            "id": 58,
            "tipo_processo": 92,
            "cliente": 140,
            "proposta": 130,
            "pedido_compra": 120,
            "obra_site": 170,
            "peso": 88,
            "progresso_peso": 125,
            "lote": 90,
            "carga_galvanizacao": 105,
            "data_entrada": 110,
            "prazo_entrega": 110,
            "data_envio_galv": 120,
            "data_prevista_retorno_galv": 132,
            "data_retorno_galv": 122,
            "almoxarifado_info": 115,
            "necessita_almoxarifado": 115,
            "status_localizacao": 210,
            "localizacao_atual": 175,
            "status_producao": 220,
            "status_galvanizacao": 230,
            "status_expedicao": 220,
            "status_almoxarifado": 220,
            "status_fiscal": 170,
            "data_entrada_fiscal": 125,
            "data_ultima_emissao": 130,
            "quantidade_itens": 80,
            "itens_pendentes": 95,
            "itens_faturados": 95,
            "peso_total": 110,
            "peso_pendente": 125,
            "peso_faturado": 120,
            "pendencia_critica": 150,
            "quantidade_total": 95,
            "quantidade_faturada": 110,
            "quantidade_pendente": 112,
            "status_item_fiscal": 150,
        }
        for index, (key, _label) in enumerate(columns):
            self.setColumnWidth(index, widths.get(key, 120))

    def selected_process_id(self) -> int | None:
        selected = self.selectionModel().selectedRows()
        if not selected:
            return None
        proxy_index = selected[0]
        model = self.model()
        source_index = model.mapToSource(proxy_index) if hasattr(model, "mapToSource") else proxy_index
        return model.sourceModel().process_id_at(source_index.row()) if hasattr(model, "sourceModel") else model.process_id_at(source_index.row())

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == 0:
            model = self.model()
            source_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
            process_id = model.sourceModel().process_id_at(source_index.row()) if hasattr(model, "sourceModel") else model.process_id_at(source_index.row())
            if process_id:
                self.status_shortcut_requested.emit(process_id)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        self.setCursor(Qt.PointingHandCursor if index.isValid() and index.column() == 0 else Qt.ArrowCursor)
        super().mouseMoveEvent(event)
