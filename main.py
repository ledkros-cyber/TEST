"""
YouTube Video Generator
=======================
AI-powered pipeline:
  YouTube search → Script (Claude) → TTS (MiniMax) → Video (FFmpeg)

Requirements:
  pip install -r requirements.txt

Also requires FFmpeg installed and in PATH.
"""
import sys
import os

# Make sure the app package is importable when running from the project root
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Video Generator")
    app.setOrganizationName("YTGen")
    app.setStyle("Fusion")

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Import here to ensure Qt is initialized first
    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
