"""Log viewer tab — shows recent entries from data/ytgen.log."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel,
)

try:
    from app.utils.logger import log
except Exception:
    log = None


class LogTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Журнал событий")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#c0bfff;")
        header.addWidget(title)
        header.addStretch()

        btn_refresh = QPushButton("Обновить")
        btn_refresh.setFixedWidth(110)
        btn_refresh.clicked.connect(self.refresh)

        btn_clear = QPushButton("Очистить")
        btn_clear.setFixedWidth(110)
        btn_clear.clicked.connect(self._clear_display)

        header.addWidget(btn_refresh)
        header.addWidget(btn_clear)
        layout.addLayout(header)

        # Log display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(mono)
        self.text_edit.setStyleSheet(
            "background:#0d0d1a; color:#c8c8d8; border:1px solid #3a3b55;"
            " selection-background-color:#3a3b80;"
        )
        layout.addWidget(self.text_edit)

    def refresh(self):
        """Reload last 300 lines from the log file and display them."""
        if log is not None:
            content = log.get_recent(300)
        else:
            content = "(Logger not available)"
        self.text_edit.setPlainText(content)
        # Scroll to bottom so newest entries are visible
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_display(self):
        """Clear the display widget only — does not delete the log file."""
        self.text_edit.clear()

    def showEvent(self, event):
        """Auto-refresh whenever this tab becomes visible."""
        super().showEvent(event)
        self.refresh()
