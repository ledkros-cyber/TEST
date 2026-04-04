"""Main application window."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QStatusBar,
)

from app import database
from app.ui.search_tab import SearchTab
from app.ui.script_tab import ScriptTab
from app.ui.audio_tab import AudioTab
from app.ui.video_tab import VideoTab
from app.ui.history_tab import HistoryTab
from app.ui.settings_tab import SettingsTab
from app.ui.styles import STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        database.init_db()
        self.setWindowTitle("YouTube Video Generator")
        self.setMinimumSize(1100, 750)
        self.resize(1280, 820)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        topbar = QWidget()
        topbar.setFixedHeight(52)
        topbar.setStyleSheet("background:#13132b; border-bottom:1px solid #3a3b55;")
        tb_layout = QHBoxLayout(topbar)
        tb_layout.setContentsMargins(20, 0, 20, 0)

        app_title = QLabel("▶ YouTube Video Generator")
        app_title.setStyleSheet(
            "font-size:17px; font-weight:bold; color:#6c63ff; letter-spacing:1px;"
        )
        tb_layout.addWidget(app_title)
        tb_layout.addStretch()

        subtitle = QLabel("AI-powered video creation pipeline")
        subtitle.setStyleSheet("font-size:12px; color:#9090aa;")
        tb_layout.addWidget(subtitle)
        root.addWidget(topbar)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.search_tab = SearchTab()
        self.script_tab = ScriptTab()
        self.audio_tab = AudioTab()
        self.video_tab = VideoTab()
        self.history_tab = HistoryTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.search_tab,   "1. Поиск")
        self.tabs.addTab(self.script_tab,   "2. Сценарий")
        self.tabs.addTab(self.audio_tab,    "3. Озвучка")
        self.tabs.addTab(self.video_tab,    "4. Видео")
        self.tabs.addTab(self.history_tab,  "5. История")
        self.tabs.addTab(self.settings_tab, "⚙ Настройки")

        root.addWidget(self.tabs)

        # Status bar
        status = QStatusBar()
        status.setStyleSheet("background:#13132b; color:#9090aa; font-size:11px;")
        status.showMessage(
            "Готово. Шаг 1: Настройте API ключи → вкладка «Настройки»."
            "  Шаг 2: Найдите видео → вкладка «Поиск».  Шаг 3: Создайте сценарий → и т.д."
        )
        self.setStatusBar(status)

        self._connect_signals()

    def _connect_signals(self):
        # Search → Script
        self.search_tab.videos_selected.connect(self._on_videos_selected)
        # Script → Audio
        self.script_tab.script_ready.connect(self._on_script_ready)
        # Audio → Video
        self.audio_tab.audio_ready.connect(self._on_audio_ready)
        # Video → History
        self.video_tab.video_created.connect(self._on_video_created)

    def _on_videos_selected(self, videos: list):
        self.script_tab.set_source_videos(videos)
        self.tabs.setCurrentWidget(self.script_tab)

    def _on_script_ready(self, data: dict):
        self.audio_tab.set_script_data(data)
        self.video_tab.set_script_data(data)
        self.tabs.setCurrentWidget(self.audio_tab)

    def _on_audio_ready(self, path: str):
        self.video_tab.set_audio_path(path)
        self.tabs.setCurrentWidget(self.video_tab)

    def _on_video_created(self, project: dict):
        self.history_tab.add_project(project)
        self.tabs.setCurrentWidget(self.history_tab)
        self.statusBar().showMessage(
            f"Видео #{project.get('number')} создано: {project.get('title', '')}"
        )
