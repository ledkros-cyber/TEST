"""Reusable widgets used across tabs."""
import os
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton,
    QSizePolicy,
)


class WorkerThread(QThread):
    """Generic background worker."""
    progress = pyqtSignal(int, str)   # percent, message
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class ThumbnailLabel(QLabel):
    """Label that loads an image from bytes."""
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


class SectionHeader(QLabel):
    """Bold section title label."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#6c63ff; "
            "padding-bottom:4px; border-bottom:1px solid #3a3b55;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class StatusBar(QWidget):
    """Simple status message bar at the bottom of a panel."""
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
