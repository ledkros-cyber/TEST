"""Reusable widgets used across tabs."""
import os
import threading

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton,
    QSizePolicy, QSpinBox, QDoubleSpinBox, QLineEdit,
)


# ─── Wheel-safe spinboxes ─────────────────────────────────────────────────────
# On Windows inside QScrollArea the default spinbox consumes every scroll event,
# making it hard to scroll the panel. These variants require the widget to be
# focused before accepting wheel input.

class WheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class WheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


# ─── Background worker ────────────────────────────────────────────────────────

class WorkerThread(QThread):
    """Generic background worker."""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func   = func
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ─── Thumbnail label ──────────────────────────────────────────────────────────

class ThumbnailLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 68)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#1e1f35; border-radius:4px;")
        self.setText("...")

    def set_image_bytes(self, data: bytes):
        img = QImage()
        img.loadFromData(data)
        pix = QPixmap.fromImage(img).scaled(
            120, 68,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pix)
        self.setText("")


# ─── API Key field with show/hide toggle ─────────────────────────────────────

class ApiKeyField(QWidget):
    """Password field with an eye-button to reveal/hide the value."""
    def __init__(self, placeholder: str = "Enter key...", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._field = QLineEdit()
        self._field.setEchoMode(QLineEdit.EchoMode.Password)
        self._field.setPlaceholderText(placeholder)
        layout.addWidget(self._field)

        self._btn = QPushButton("👁")
        self._btn.setFixedWidth(34)
        self._btn.setFixedHeight(32)
        self._btn.setCheckable(True)
        self._btn.setToolTip("Show / hide")
        self._btn.setStyleSheet(
            "QPushButton { background:#2f3050; border:1px solid #3a3b55; "
            "border-radius:5px; font-size:14px; padding:0; }"
            "QPushButton:checked { background:#6c63ff; }"
        )
        self._btn.toggled.connect(self._toggle)
        layout.addWidget(self._btn)

    def _toggle(self, visible: bool):
        self._field.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def text(self) -> str:
        return self._field.text()

    def setText(self, value: str):
        self._field.setText(value)

    def setPlaceholderText(self, text: str):
        self._field.setPlaceholderText(text)


# ─── Section header ───────────────────────────────────────────────────────────

class SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#6c63ff; "
            "padding-bottom:4px; border-bottom:1px solid #3a3b55;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


# ─── Status bar ───────────────────────────────────────────────────────────────

class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def set_ok(self, msg: str):
        self._label.setText(msg)
        self._label.setStyleSheet("color:#4caf81; font-weight:bold;")

    def set_error(self, msg: str):
        self._label.setText(msg)
        self._label.setStyleSheet("color:#e05260; font-weight:bold;")

    def set_info(self, msg: str):
        self._label.setText(msg)
        self._label.setStyleSheet("color:#9090aa;")

    def clear(self):
        self._label.setText("")
