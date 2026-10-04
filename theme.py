"""Lightweight native graphics: painted once, no browser or image downloads."""
import os
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal, QSignalBlocker, QCollator, QLocale
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF


def action_icon(kind, color='#315c8e', size=24):
    image = QPixmap(size, size)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    if kind == 'download':
        painter.drawLine(12, 3, 12, 15)
        painter.drawLine(7, 10, 12, 15)
        painter.drawLine(12, 15, 17, 10)
        painter.drawLine(4, 18, 4, 21)
        painter.drawLine(4, 21, 20, 21)
        painter.drawLine(20, 21, 20, 18)
    elif kind == 'list':
        for y in (6, 12, 18):
            painter.drawLine(8, y, 21, y)
            painter.drawPoint(3, y)
    elif kind == 'folder':
        painter.drawPolyline(QPolygonF([QPointF(3, 19), QPointF(3, 6), QPointF(9, 6),
                                        QPointF(12, 9), QPointF(21, 9), QPointF(21, 19), QPointF(3, 19)]))
    elif kind == 'paste':
        painter.drawRoundedRect(5, 5, 14, 16, 2, 2)
        painter.setBrush(QColor('#f7f9fc'))
        painter.drawRoundedRect(9, 2, 6, 5, 1, 1)
        painter.drawLine(9, 12, 15, 12)
        painter.drawLine(9, 16, 14, 16)
    elif kind == 'search':
        painter.drawEllipse(3, 3, 12, 12)
        painter.drawLine(14, 14, 21, 21)
    elif kind == 'pause':
        painter.drawLine(8, 5, 8, 19)
        painter.drawLine(16, 5, 16, 19)
    elif kind == 'stop':
        painter.drawRoundedRect(5, 5, 14, 14, 2, 2)
    elif kind == 'retry':
        painter.drawArc(4, 4, 16, 16, 35 * 16, 285 * 16)
        painter.drawPolyline(QPolygonF([QPointF(15, 3), QPointF(21, 4), QPointF(20, 10)]))
    painter.end()
    return QIcon(image)


def apply_theme(window):
    family = 'Segoe UI' if os.name == 'nt' else 'Arial'
    window.setStyleSheet('''
        QWidget { background: #f3f6fa; color: #182b42; font-family: FAMILY; font-size: 16px; }
        QLabel { background: transparent; }
        QLabel#heading { font-size: 26px; font-weight: 700; }
        QLabel#brand { color: #176bd1; font-size: 16px; font-weight: 600; }
        QLabel#subtitle { color: #56667a; font-size: 15px; }
        QLabel#fieldLabel { font-size: 15px; color: #52647b; font-weight: 600; }
        QLabel#sectionTitle { font-size: 18px; font-weight: 600; }
        QLabel#summary { font-size: 15px; color: #52647b; }
        QLabel#status { padding: 3px 0; font-size: 15px; }
        QLineEdit, QComboBox { background: white; border: 1px solid #bccbdc; border-radius: 10px; padding: 7px 9px; min-height: 22px; selection-background-color: #dbeafd; selection-color: #182b42; }
        QLineEdit:focus, QComboBox:focus { border: 2px solid #176bd1; padding: 6px 8px; }
        QLineEdit:read-only { color: #52647b; background: #edf2f8; }
        QComboBox::down-arrow { width: 0px; height: 0px; }
        QComboBox::drop-down { border: none; width: 28px; }
        QComboBox QAbstractItemView { background: white; selection-background-color: #dbeafd; selection-color: #182b42; padding: 6px; }
        QToolButton { background: white; border: 1px solid #bccbdc; border-radius: 15px; padding: 10px 14px; min-height: 24px; }
        QToolButton:hover { background: #e6effb; }
        QToolButton:disabled { color: #65758b; background: #eaf0f6; }
        QLineEdit QToolButton { background: transparent; border: none; border-radius: 0; padding: 0; min-height: 0; }
        QMenu { background: white; border: 1px solid #bccbdc; padding: 6px; }
        QMenu::item { padding: 10px 20px; }
        QMenu::item:selected { background: #deebfc; }
        QPushButton { background: #ffffff; border: 1px solid #bccbdc; border-radius: 10px; padding: 7px 12px; min-height: 22px; font-weight: 500; }
        QPushButton:hover { background: #e6effb; border-color: #7598c6; }
        QPushButton:pressed { background: #d4e4f8; }
        QPushButton:focus { border: 2px solid #176bd1; padding: 6px 11px; }
        QPushButton:disabled { color: #65758b; border-color: #d6dfe9; background: #eaf0f6; }
        QPushButton#process { background: #176bd1; border-color: #176bd1; color: white; font-weight: 600; }
        QPushButton#process:hover { background: #125cb8; }
        QPushButton#process:disabled { background: #7a9bc4; border-color: #7a9bc4; }
        QPushButton#primary { background: #176bd1; border: none; color: white; font-size: 18px; font-weight: 700; padding: 10px; min-height: 26px; }
        QPushButton#primary:hover { background: #125cb8; }
        QPushButton#primary:pressed { background: #0e4d9b; }
        QPushButton#primary:disabled { background: #7a9bc4; }
        QPushButton#primary:focus { border: 2px solid #102b50; padding: 8px; }
        QTableWidget { background: white; alternate-background-color: #f5f8fc; border: 1px solid #c8d5e4; border-radius: 10px; selection-background-color: #deebfc; selection-color: #182b42; }
        QTableWidget::item { padding: 5px 8px; border-bottom: 1px solid #edf1f7; }
        QTableWidget:disabled { color: #182b42; }
        QHeaderView::section { background: #e7eef8; color: #405671; font-size: 15px; font-weight: 600; padding: 9px 8px; border: none; }
        QTableWidget::indicator { width: 20px; height: 20px; }
        QCheckBox { background: transparent; spacing: 10px; font-size: 16px; }
        QCheckBox::indicator { width: 22px; height: 22px; }
        QCheckBox::indicator:unchecked { background: white; border: 1px solid #9eafc4; border-radius: 5px; }
        QCheckBox::indicator:checked, QCheckBox::indicator:indeterminate { background: #176bd1; border: 1px solid #176bd1; border-radius: 5px; image: none; }
        QProgressBar { border: none; background: #dfe7f1; border-radius: 7px; text-align: center; color: #132a46; min-height: 18px; max-height: 18px; font-size: 13px; }
        QProgressBar::chunk { background: #4e9ae8; border-radius: 7px; }
        QScrollBar:vertical { background: #edf2f8; width: 14px; border: none; margin: 0; }
        QScrollBar::handle:vertical { background: #a7bad1; border-radius: 6px; min-height: 35px; margin: 2px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    '''.replace('FAMILY', '"' + family + '"'))


from PySide6.QtWidgets import QComboBox, QCheckBox, QStyleOptionButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QStyleFactory, QListView, QLabel, QSizePolicy, QTableWidget


class ElidedLabel(QLabel):
    """Long song titles stay on one line, with full status available in a tooltip."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.contentsRect().width())
        painter.drawText(self.contentsRect(), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.end()


class SelectionItemDelegate(QStyledItemDelegate):
    """Keep check marks visible on Windows and on inactive macOS windows."""
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        rect = opt.widget.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        if not rect.isValid():
            return
        checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#176bd1' if checked else '#9eafc4'), 1))
        painter.setBrush(QColor('#176bd1' if checked else 'white'))
        painter.drawRoundedRect(QRectF(rect), 4, 4)
        if checked:
            painter.setPen(QPen(QColor('white'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawPolyline(QPolygonF([QPointF(x + .23*w, y + .5*h), QPointF(x + .44*w, y + .73*h), QPointF(x + .78*w, y + .25*h)]))
        painter.restore()


class SelectionCheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.checkState() == Qt.Unchecked:
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('white'), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = rect.left(), rect.center().y()
        if self.checkState() == Qt.PartiallyChecked:
            painter.drawLine(x + 6, y, x + 17, y)
        else:
            painter.drawPolyline(QPolygonF([QPointF(x + 5, y), QPointF(x + 10, y + 5), QPointF(x + 18, y - 5)]))
        painter.end()

class FriendlyComboBox(QComboBox):
    """Use a list below the field, avoiding the macOS menu and its dark gutters."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._list_style = QStyleFactory.create('Fusion')
        self._list_style.setParent(self)
        self.setStyle(self._list_style)
        view = QListView(self)
        view.setStyle(self._list_style)
        view.setItemDelegate(QStyledItemDelegate(view))
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setView(view)
        self.setMaxVisibleItems(8)

    def showPopup(self):
        if not self.isEnabled() or not self.count():
            return
        popup = self.view().window()
        popup.setStyle(self._list_style)
        popup.setObjectName('bajadaComboPopup')
        family = 'Segoe UI' if os.name == 'nt' else 'Arial'
        popup.setStyleSheet('''
            QFrame#bajadaComboPopup { background: white; border: 1px solid #bccbdc; border-radius: 10px; padding: 0; margin: 0; }
            QListView { background: white; color: #182b42; border: none; padding: 4px; outline: 0; font-family: FAMILY; font-size: 16px; }
            QListView::item { min-height: 28px; padding: 5px 9px; border-radius: 6px; }
            QListView::item:selected { background: #dbeafd; color: #182b42; }
            QListView::item:hover { background: #edf4fd; color: #182b42; }
        '''.replace('FAMILY', '"' + family + '"'))
        super().showPopup()
        anchor = self.mapToGlobal(QPoint(0, self.height() + 6))
        available = self.screen().availableGeometry()
        # The selectors sit near the top of the app. If a window is moved to the
        # bottom of the screen, allow Qt's accessible fallback rather than clip it.
        below = available.bottom() - anchor.y() + 1
        if below >= 48:
            width = min(self.width(), available.width())
            x = max(available.left(), min(anchor.x(), available.right() - width + 1))
            popup.resize(width, min(popup.height(), below))
            popup.move(x, anchor.y())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = '#52647b' if self.isEnabled() else '#8996a7'
        painter.setPen(QPen(QColor(color), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 20, self.height() / 2
        painter.drawPolyline(QPolygonF([QPointF(x - 4, y - 2), QPointF(x, y + 2), QPointF(x + 4, y - 2)]))
        painter.end()


def brand_icon(size=256):
    image = QPixmap(size, size)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 256, size / 256)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#176bd1'))
    painter.drawRoundedRect(8, 8, 240, 240, 58, 58)
    painter.setPen(QPen(QColor('white'), 12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(112, 83, 112, 173)
    painter.drawLine(176, 66, 176, 155)
    painter.drawLine(112, 83, 176, 66)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('white'))
    painter.drawEllipse(77, 159, 36, 26)
    painter.drawEllipse(141, 141, 36, 26)
    painter.end()
    return QIcon(image)


class StableTableWidget(QTableWidget):
    """Sort whole rows without Qt's crashing native accessibility layout reset.

    Cell indices remain valid for assistive tools; their content is updated in
    place. Qt automatic sorting stays off, so data changes cannot reset its cache.
    """
    orderChanged = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sort_column = 1
        self._sort_order = Qt.AscendingOrder
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().sectionClicked.connect(self.sort_from_header)

    def sort_from_header(self, column):
        header = self.horizontalHeader()
        if column not in (1, 2):
            return
        # QHeaderView can flip its indicator before sectionClicked is delivered.
        # Track the last applied order separately so each click really toggles.
        order = (Qt.DescendingOrder if self._sort_column == column and
                 self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder)
        self.sortItems(column, order)

    def sortItems(self, column, order=Qt.AscendingOrder):
        from functools import cmp_to_key
        self._sort_column, self._sort_order = column, order
        rows = [[self.item(row, col) for col in range(self.columnCount())]
                for row in range(self.rowCount())]
        if not rows or any(cell is None for row in rows for cell in row):
            self.horizontalHeader().setSortIndicator(column, order)
            return
        collator = QCollator(QLocale('es'))
        collator.setCaseSensitivity(Qt.CaseInsensitive)
        collator.setNumericMode(True)
        if column == 1:
            key = lambda row: row[column].data(Qt.DisplayRole)
        else:
            key = cmp_to_key(lambda left, right: collator.compare(left[column].text(), right[column].text()))
        sorted_rows = sorted(rows, key=key, reverse=order == Qt.DescendingOrder)
        selected = self.currentItem()
        blocker = QSignalBlocker(self)
        self.setUpdatesEnabled(False)
        try:
            if any(left is not right for left, right in zip(rows, sorted_rows)):
                for row in range(self.rowCount()):
                    for col in range(self.columnCount()):
                        self.takeItem(row, col)
                for row, cells in enumerate(sorted_rows):
                    for col, cell in enumerate(cells):
                        self.setItem(row, col, cell)
                if selected:
                    self.setCurrentItem(selected)
            self.horizontalHeader().setSortIndicator(column, order)
        finally:
            self.setUpdatesEnabled(True)
            del blocker
        self.orderChanged.emit()
