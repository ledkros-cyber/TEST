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
import traceback
import datetime

# Make sure the app package is importable when running from the project root
sys.path.insert(0, os.path.dirname(__file__))

ERROR_LOG = os.path.join(os.path.dirname(__file__), "data", "error.log")


def _write_error(text: str):
    """Write error with timestamp to data/error.log."""
    try:
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{ts}\n")
            f.write(f"{'='*60}\n")
            f.write(text)
            f.write("\n")
    except Exception:
        pass


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Video Generator")
    app.setOrganizationName("YTGen")
    app.setStyle("Fusion")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        _write_error(err)
        # Also try to show a message box if Qt is available
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            msg = QMessageBox()
            msg.setWindowTitle("Ошибка запуска")
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setText("Программа не смогла запуститься.\n\nОшибка сохранена в файл:\ndata\\error.log")
            msg.setDetailedText(err)
            msg.exec()
        except Exception:
            pass
        sys.exit(1)
