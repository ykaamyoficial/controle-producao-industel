from __future__ import annotations

from PySide6.QtCore import QRectF, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTableView

from app.ui.styles import area_color, status_color
from app.ui.icons import IconSize, make_icon, status_icon


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
        batch_background = index.data(Qt.BackgroundRole)
        if batch_background is not None and not (option.state & QStyle.State_Selected):
            painter.save()
            painter.fillRect(option.rect, batch_background)
            painter.restore()
        if key == "chat_icon":
            unread = int(index.data(Qt.UserRole + 2) or 0)
            has_messages = bool(index.data(Qt.UserRole + 3))
            painter.save()
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(self.service.palette["accent"]))
            if unread > 0:
                color = self.service.palette.get("danger", "#dc2626")
            elif has_messages:
                color = self.service.palette["accent"]
            else:
                color = self.service.palette.get("muted", "#94a3b8")
            icon = make_icon("chat", color, 18)
            pix = icon.pixmap(18, 18)
            offset = 6 if unread > 0 else 0
            x = option.rect.x() + (option.rect.width() - 18) // 2 - offset
            y = option.rect.y() + (option.rect.height() - 18) // 2
            painter.setRenderHint(QPainter.Antialiasing)
            painter.drawPixmap(x, y, pix)
            if unread > 0:
                badge_text = str(unread) if unread < 100 else "99+"
                badge_rect = QRectF(x + 12, y - 2, 20, 14)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(self.service.palette.get("danger", "#dc2626"))))
                painter.drawRoundedRect(badge_rect, 7, 7)
                painter.setPen(QPen(QColor("#ffffff")))
                font = painter.font()
                font.setPointSize(max(6, font.pointSize() - 3))
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
            painter.restore()
            return
        if key in {"status_icon", "fiscal_action"}:
            raw = index.data(Qt.UserRole + 2) or "status"
            area = index.data(Qt.UserRole + 3) or None
            painter.save()
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(self.service.palette["accent"]))
            size = int(IconSize.TABLE_STATUS)
            icon = status_icon(str(raw), area=area, palette=self.service.palette, size=size)
            pix = icon.pixmap(size, size)
            x = option.rect.x() + (option.rect.width() - size) // 2
            y = option.rect.y() + (option.rect.height() - size) // 2
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
    chat_shortcut_requested = Signal(int)

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
        self.verticalHeader().setDefaultSectionSize(28)
        self.horizontalHeader().setMinimumHeight(26)
        self.horizontalHeader().setFixedHeight(28)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setItemDelegate(StatusBadgeDelegate(service, self))
        self.setWordWrap(True)
        self.setToolTip("Clique no icone de status para abrir as acoes da proposta, ou no icone de chat para abrir a conversa.")
        self.setMouseTracking(True)
        self.status_shortcut_enabled = True

    def setModel(self, model):
        super().setModel(model)
        self.apply_column_layout()

    def apply_column_layout(self):
        model = self.model()
        source = model.sourceModel() if hasattr(model, "sourceModel") else model
        columns = getattr(source, "columns", [])
        widths = {
            "batch_select": 42,
            "status_icon": 44,
            "chat_icon": 44,
            "fiscal_action": 44,
            "id": 54,
            "tipo_processo": 86,
            "cliente": 150,
            "proposta": 130,
            "pedido_compra": 112,
            "obra_site": 190,
            "peso": 84,
            "progresso_peso": 125,
            "lote": 82,
            "carga_galvanizacao": 96,
            "data_entrada": 96,
            "prazo_entrega": 96,
            "data_envio_galv": 108,
            "data_prevista_retorno_galv": 124,
            "data_retorno_galv": 112,
            "almoxarifado_info": 115,
            "necessita_almoxarifado": 115,
            "status_localizacao": 210,
            "localizacao_atual": 175,
            "status_producao": 215,
            "status_producao_item": 150,
            "status_galvanizacao": 220,
            "status_expedicao": 215,
            "status_almoxarifado": 215,
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
            "acoes": 72,
            "alerta": 120,
            "carga_id": 75,
            "status_carga": 170,
            "motorista": 130,
            "data_prevista_retorno": 130,
            "data_retorno": 115,
            "criado_em": 150,
            "data_final_producao": 130,
            "data_retirada": 115,
            "data_separacao": 115,
            "total_itens": 85,
            "itens_produzidos": 110,
            "itens_entregues": 110,
            "peso_total_itens": 125,
            "peso_produzido_atual": 145,
            "kg_entregue_atual": 125,
            "origem_remanejamento": 145,
            "proposta_origem": 130,
            "proposta_destino": 130,
            "cliente_origem": 140,
            "cliente_destino": 140,
            "numero_item": 75,
            "codigo_produto": 95,
            "product_code": 95,
            "descricao": 280,
            "item_descricao": 220,
            "peso_remanejado": 130,
            "proposta_reposicao": 145,
        }
        has_long_description = any(key in {"descricao", "item_descricao", "observacao"} for key, _label in columns)
        self.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents if has_long_description else QHeaderView.Fixed
        )
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
        if self.status_shortcut_enabled and index.isValid():
            model = self.model()
            source_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
            process_id = model.sourceModel().process_id_at(source_index.row()) if hasattr(model, "sourceModel") else model.process_id_at(source_index.row())
            if process_id:
                if index.column() == 0:
                    self.status_shortcut_requested.emit(process_id)
                    return
                if source_index.data(Qt.UserRole + 1) == "chat_icon":
                    self.chat_shortcut_requested.emit(process_id)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        shortcut_cell = False
        if self.status_shortcut_enabled and index.isValid():
            if index.column() == 0:
                shortcut_cell = True
            else:
                model = self.model()
                source_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
                shortcut_cell = source_index.data(Qt.UserRole + 1) == "chat_icon"
        self.setCursor(Qt.PointingHandCursor if shortcut_cell else Qt.ArrowCursor)
        super().mouseMoveEvent(event)
