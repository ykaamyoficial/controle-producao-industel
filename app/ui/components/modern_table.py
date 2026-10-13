from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTableView

from app.services.status_sorting import _parse_date
from app.ui.components.modern_header import ModernHeaderView
from app.ui.components.operational_table import configure_operational_table
from app.ui.styles import _contrast_text, area_color, status_color
from app.ui.theme_tokens import active_tokens, ui_tokens
from app.ui.icons import IconSize, make_icon, status_icon
from app.ui.fonts import scaled_px

# Medidas do padrao visual (skill qt-industrial-ui).
TABLE_ROW_HEIGHT = 40
TABLE_HEADER_HEIGHT = 38
_BADGE_HEIGHT = 22
_DEADLINE_KEYS = {"prazo_entrega"}
_DEADLINE_WARNING_DAYS = 7

# Marca de remanejamento junto do codigo da proposta (Fase D do plano de logistica): icone + codigo
# inteiro (letras e numero) em vermelho; o clique no icone ou no codigo mostra para onde as pecas
# foram. O modelo responde a este papel com True na celula "proposta" das linhas marcadas.
REMANAGEMENT_MARK_ROLE = Qt.UserRole + 4
_MARK_ICON_SIZE = 14
_MARK_GAP = 6


def remanagement_mark_geometry(rect: QRectF, text: str, font: QFont) -> tuple[QRectF, QRectF]:
    """Onde ficam, na celula da proposta, o icone e o codigo (vermelho).
    O bloco inteiro fica centralizado (como todo texto das tabelas operacionais); se nao couber, o
    codigo e cortado com reticencias e o icone continua inteiro. Usado pelo desenho e pelo clique,
    para os dois concordarem."""
    metrics = QFontMetricsF(font)
    available = max(0.0, rect.width() - 12 - _MARK_ICON_SIZE - _MARK_GAP)
    text_width = metrics.horizontalAdvance(metrics.elidedText(text, Qt.ElideRight, available))
    block = _MARK_ICON_SIZE + _MARK_GAP + text_width
    x = rect.x() + max(6.0, (rect.width() - block) / 2)
    icon = QRectF(x, rect.center().y() - _MARK_ICON_SIZE / 2, _MARK_ICON_SIZE, _MARK_ICON_SIZE)
    text_rect = QRectF(icon.right() + _MARK_GAP, rect.y(), text_width, rect.height())
    return icon, text_rect


def remanagement_mark_hotspot(rect: QRectF, text: str, font: QFont) -> QRectF:
    """Area clicavel: o icone e o codigo vermelho, com uma folga para facilitar o clique."""
    icon, text_rect = remanagement_mark_geometry(rect, text, font)
    return icon.united(text_rect).adjusted(-4, -rect.height() / 2 + 8, 4, rect.height() / 2 - 8)


def deadline_alert(row: dict | None, today: date | None = None) -> tuple[str, str]:
    """Aviso mostrado ao lado do prazo: ("vencido ha 3 d", "danger"),
    ("em 2 d", "warning") ou ("", "") quando o prazo nao pede atencao.

    So apresentacao: nao muda nenhum status. Proposta cancelada ou ja
    entregue nao gera aviso, mesmo com a data no passado."""
    if not isinstance(row, dict):
        return "", ""
    deadline = _parse_date(row.get("prazo_entrega"))
    if deadline is None:
        return "", ""
    general = str(row.get("status_geral") or "").strip().upper()
    expedition = str(row.get("status_expedicao") or "").strip().upper()
    if row.get("is_cancelled") or general == "CANCELADA" or expedition == "ENTREGUE":
        return "", ""
    days = (deadline.date() - (today or date.today())).days
    if days < 0:
        return f"vencido há {-days} d", "danger"
    if days == 0:
        return "vence hoje", "warning"
    if days <= _DEADLINE_WARNING_DAYS:
        return f"em {days} d", "warning"
    return "", ""


# Texto de celula e titulo de coluna das tabelas operacionais: centralizados.
TABLE_TEXT_ALIGNMENT = Qt.AlignCenter


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
        self._tokens_source: dict | None = None
        self._tokens_cache: dict = {}

    def _tokens(self) -> dict:
        """Tokens derivados da paleta ativa, recalculados so quando ela muda
        (paint() roda por celula)."""
        palette = self.service.palette
        if palette is not self._tokens_source:
            try:
                self._tokens_cache = ui_tokens(palette)
            except KeyError:
                # Paleta parcial (dubles de teste): cai nos tons que ela tiver.
                alt = palette.get("surface_alt", "#e8f1ff")
                self._tokens_cache = {
                    "surface": "#ffffff",
                    "border": "#cbd5e1",
                    "text": "#0f172a",
                    "muted": "#475569",
                    "accent": "#006fc9",
                    "danger": "#b91c1c",
                    "warning": "#b45309",
                    **palette,
                    "selected": alt,
                    "surface_hover": alt,
                }
            self._tokens_source = palette
        return self._tokens_cache

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:  # noqa: N802 (Qt override)
        super().initStyleOption(option, index)
        # O fundo de linha (selecao, hover) e pintado em paint() para a linha
        # inteira; sem estes estados o estilo nao repinta cada celula por cima.
        option.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver)
        # Todo texto de tabela operacional fica centralizado (pedido do usuario
        # em 08/10/2026), independente do alinhamento que o modelo devolve.
        option.displayAlignment = TABLE_TEXT_ALIGNMENT
        if index.data(Qt.UserRole + 1) == "proposta":
            font = QFont(option.font)
            font.setWeight(QFont.Weight.DemiBold)
            option.font = font

    def _paint_row_background(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        tokens = self._tokens()
        selected = bool(option.state & QStyle.State_Selected)
        batch_background = index.data(Qt.BackgroundRole)
        hovered = getattr(self.parent(), "hovered_row", -1) == index.row()
        painter.save()
        if selected:
            painter.fillRect(option.rect, QColor(tokens["selected"]))
            if index.column() == 0:
                painter.fillRect(QRectF(option.rect.x(), option.rect.y(), 4, option.rect.height()), QColor(tokens["accent"]))
        elif batch_background is not None:
            painter.fillRect(option.rect, batch_background)
        elif hovered:
            painter.fillRect(option.rect, QColor(tokens["surface_hover"]))
        painter.restore()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        key = index.data(Qt.UserRole + 1)
        tokens = self._tokens()
        self._paint_row_background(painter, option, index)
        rect = QRectF(option.rect)
        center_y = rect.center().y()
        if key == "chat_icon":
            unread = int(index.data(Qt.UserRole + 2) or 0)
            has_messages = bool(index.data(Qt.UserRole + 3))
            painter.save()
            color = tokens["accent"] if unread > 0 or has_messages else tokens["muted"]
            pix = make_icon("chat", color, 18).pixmap(18, 18)
            x = rect.center().x() - 9 - (5 if unread > 0 else 0)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.drawPixmap(int(x), int(center_y - 9), pix)
            if unread > 0:
                badge_text = str(unread) if unread < 100 else "99+"
                font = QFont(option.font)
                font.setPixelSize(scaled_px(10))
                font.setWeight(QFont.Weight.Bold)
                width = max(16.0, QFontMetricsF(font).horizontalAdvance(badge_text) + 8)
                badge_rect = QRectF(x + 11, center_y - 15, width, 15)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(tokens["danger"])))
                painter.drawRoundedRect(badge_rect, 7.5, 7.5)
                painter.setFont(font)
                painter.setPen(QPen(QColor(_contrast_text(tokens["danger"]))))
                painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
            painter.restore()
            return
        if key in {"status_icon", "fiscal_action"}:
            raw = index.data(Qt.UserRole + 2) or "status"
            area = index.data(Qt.UserRole + 3) or None
            painter.save()
            size = int(IconSize.TABLE_STATUS)
            pix = status_icon(str(raw), area=area, palette=self.service.palette, size=size).pixmap(size, size)
            painter.setRenderHint(QPainter.Antialiasing)
            # Icone de status dentro de um circulo, como sempre foi.
            painter.setPen(QPen(QColor(tokens["border"]), 1))
            painter.setBrush(QBrush(QColor(tokens["surface"])))
            painter.drawEllipse(QPointF(rect.center().x(), center_y), 13, 13)
            painter.drawPixmap(int(rect.center().x() - size / 2), int(center_y - size / 2), pix)
            painter.restore()
            return
        if key == "proposta" and index.data(REMANAGEMENT_MARK_ROLE):
            self._paint_remanagement_proposal(painter, option, index)
            return
        if key and ("status" in key or key == "localizacao_atual"):
            text = index.data(Qt.DisplayRole) or "-"
            raw = index.data(Qt.UserRole + 2) or text
            area = index.data(Qt.UserRole + 3) or ""
            if key == "localizacao_atual":
                bg = area_color(str(raw or area), self.service.palette)
                fg = _contrast_text(bg)
            else:
                bg, fg = status_color(str(raw), self.service.palette, str(area))
            painter.save()
            # Selo solido de largura fixa: as cores se alinham em coluna.
            badge = QRectF(rect.x() + 8, center_y - _BADGE_HEIGHT / 2, max(20.0, rect.width() - 16), _BADGE_HEIGHT)
            font = QFont(option.font)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(bg)))
            painter.drawRoundedRect(badge, _BADGE_HEIGHT / 2, _BADGE_HEIGHT / 2)
            painter.setFont(font)
            painter.setPen(QPen(QColor(fg)))
            visible_text = QFontMetricsF(font).elidedText(str(text), Qt.ElideRight, max(20.0, badge.width() - 14))
            painter.drawText(badge, Qt.AlignCenter, visible_text)
            painter.restore()
            return
        if key in _DEADLINE_KEYS:
            alert, kind = deadline_alert(index.data(Qt.UserRole))
            if alert:
                self._paint_deadline(painter, option, str(index.data(Qt.DisplayRole) or ""), alert, kind)
                return
        super().paint(painter, option, index)

    def _paint_remanagement_proposal(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Codigo da proposta (letras e numero) em vermelho (token danger), com o icone de remanejamento antes."""
        tokens = self._tokens()
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold)
        text = str(index.data(Qt.DisplayRole) or "")
        icon, text_rect = remanagement_mark_geometry(QRectF(option.rect), text, font)
        visible = QFontMetricsF(font).elidedText(text, Qt.ElideRight, text_rect.width() + 0.5)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(int(icon.x()), int(icon.y()), make_icon("refresh", tokens["accent"], _MARK_ICON_SIZE).pixmap(_MARK_ICON_SIZE, _MARK_ICON_SIZE))
        painter.setFont(font)
        painter.setPen(QPen(QColor(tokens["danger"])))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, visible)
        painter.restore()

    def _paint_deadline(self, painter: QPainter, option: QStyleOptionViewItem, text: str, alert: str, kind: str) -> None:
        """Data do prazo + aviso ("vencido ha X d" / "em X d"). Vencido leva
        tambem um icone: o aviso nunca depende so da cor."""
        tokens = self._tokens()
        rect = QRectF(option.rect)
        center_y = rect.center().y()
        color = tokens.get(kind, tokens["text"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(rect)
        font = QFont(option.font)
        metrics = QFontMetricsF(font)
        alert_font = QFont(option.font)
        alert_font.setWeight(QFont.Weight.DemiBold)
        # Data + aviso formam um bloco so, centralizado na celula.
        block_width = metrics.horizontalAdvance(text) + 10 + (18 if kind == "danger" else 0) + QFontMetricsF(alert_font).horizontalAdvance(alert)
        x = rect.x() + max(8.0, (rect.width() - block_width) / 2)
        painter.setFont(font)
        painter.setPen(QPen(QColor(tokens["text"])))
        painter.drawText(QRectF(x, rect.y(), rect.width(), rect.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        x += metrics.horizontalAdvance(text) + 10
        if kind == "danger":
            painter.drawPixmap(int(x), int(center_y - 7), make_icon("warning", color, 14).pixmap(14, 14))
            x += 18
        painter.setFont(alert_font)
        painter.setPen(QPen(QColor(color)))
        painter.drawText(QRectF(x, rect.y(), rect.width(), rect.height()), Qt.AlignVCenter | Qt.AlignLeft, alert)
        painter.restore()


class ModernTable(QTableView):
    status_shortcut_requested = Signal(int)
    chat_shortcut_requested = Signal(int)
    # Clique no icone ou no codigo vermelho da proposta marcada por remanejamento; leva o id da proposta da linha.
    remanagement_mark_requested = Signal(int)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        # Linha (do modelo exibido) sob o mouse; o delegate usa para pintar o
        # hover na linha inteira, e nao so na celula.
        self.hovered_row = -1
        self.setHorizontalHeader(ModernHeaderView(Qt.Horizontal, self))
        configure_operational_table(self)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
        self.verticalHeader().setMinimumSectionSize(TABLE_ROW_HEIGHT)
        self.horizontalHeader().setFixedHeight(TABLE_HEADER_HEIGHT)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setDefaultAlignment(TABLE_TEXT_ALIGNMENT)
        self.setItemDelegate(StatusBadgeDelegate(service, self))
        self.setWordWrap(True)
        self.setToolTip("Clique no ícone de status para abrir as ações da proposta, ou no ícone de chat para abrir a conversa.")
        self.setMouseTracking(True)
        self.status_shortcut_enabled = True

    def _set_hovered_row(self, row: int) -> None:
        if row != self.hovered_row:
            self.hovered_row = row
            self.viewport().update()

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._set_hovered_row(-1)
        super().leaveEvent(event)

    def _sync_header_corner(self) -> None:
        """Canto superior direito: a barra de rolagem comeca ABAIXO do cabecalho e o espaco acima dela
        fica na cor do cabecalho, entao a faixa azul vai de ponta a ponta (sem degrau)."""
        header_color = QColor(active_tokens()["table_header"])
        if getattr(self, "_corner_color", None) == header_color.name():
            return
        self._corner_color = header_color.name()
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, header_color)
        self.setPalette(palette)
        self.setStyleSheet(f"QScrollBar:vertical {{ margin: {self.horizontalHeader().height()}px 0 0 0; }}")

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        self._sync_header_corner()
        super().paintEvent(event)
        # Sombra fina sob o cabecalho quando a tabela foi rolada: da profundidade sem pesar.
        if self.verticalScrollBar().isVisible() and self.verticalScrollBar().value() > 0:
            painter = QPainter(self.viewport())
            gradient = QLinearGradient(0, 0, 0, 7)
            dark = QColor(0, 0, 0, 38 if QColor(active_tokens()["surface"]).lightness() > 128 else 90)
            gradient.setColorAt(0, dark)
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(0, 0, self.viewport().width(), 7, gradient)
            painter.end()

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
            "cliente": 200,
            "proposta": 132,
            "pedido_compra": 112,
            "obra_site": 190,
            "numero_nf": 130,
            "peso": 84,
            "progresso_peso": 125,
            "lote": 82,
            "carga_galvanizacao": 96,
            "data_entrada": 96,
            "prazo_entrega": 200,
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
            "quantidade_separada": 95,
            "status_expedicao_item": 250,
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

    def _on_remanagement_mark(self, index, position) -> bool:
        """True quando `position` esta sobre o icone/letras de remanejamento da celula da proposta."""
        if not index.isValid() or not index.data(REMANAGEMENT_MARK_ROLE):
            return False
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        rect = QRectF(self.visualRect(index))
        return remanagement_mark_hotspot(rect, str(index.data(Qt.DisplayRole) or ""), font).contains(QPointF(position))

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
                if self._on_remanagement_mark(index, event.position()):
                    self.remanagement_mark_requested.emit(process_id)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        self._set_hovered_row(index.row() if index.isValid() else -1)
        shortcut_cell = False
        if self.status_shortcut_enabled and index.isValid():
            if index.column() == 0:
                shortcut_cell = True
            else:
                model = self.model()
                source_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
                shortcut_cell = source_index.data(Qt.UserRole + 1) == "chat_icon" or self._on_remanagement_mark(index, event.position())
        self.setCursor(Qt.PointingHandCursor if shortcut_cell else Qt.ArrowCursor)
        super().mouseMoveEvent(event)
