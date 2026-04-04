"""Search tab — YouTube video search and source selection."""
import os
import threading
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QImage, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextEdit, QSplitter, QScrollArea, QSizePolicy, QFrame,
    QProgressBar,
)

from app.config_manager import load_config
from app.api.youtube_client import (
    search_videos, get_video_details, get_transcript,
    download_thumbnail, extract_video_id,
)
from app.ui.widgets import WorkerThread, ThumbnailLabel, SectionHeader, StatusBar


def _fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


class SearchTab(QWidget):
    videos_selected = pyqtSignal(list)   # emitted when user clicks "Анализировать"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[dict] = []
        self._selected: list[dict] = []
        self._workers: list[QThread] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI build
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Поиск видео на YouTube"))

        # Top controls
        controls = QGroupBox("Параметры поиска")
        c_layout = QVBoxLayout(controls)

        # Row 1: keyword
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Ключевые слова:"))
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("Например: как похудеть быстро")
        self.keyword_input.returnPressed.connect(self._start_search)
        row1.addWidget(self.keyword_input, 1)
        c_layout.addLayout(row1)

        # Row 2: filters
        row2 = QHBoxLayout()

        row2.addWidget(QLabel("Период:"))
        self.date_combo = QComboBox()
        self.date_combo.addItems(["Всё время", "За неделю", "За месяц", "За год"])
        self.date_combo.setFixedWidth(130)
        row2.addWidget(self.date_combo)

        row2.addWidget(QLabel("Мин. просмотров:"))
        self.min_views_combo = QComboBox()
        self.min_views_combo.addItems([
            "100K", "200K", "500K", "1M", "Без фильтра"
        ])
        self.min_views_combo.setFixedWidth(120)
        row2.addWidget(self.min_views_combo)

        row2.addWidget(QLabel("Сортировка:"))
        self.order_combo = QComboBox()
        self.order_combo.addItems([
            "По релевантности", "По просмотрам", "По дате"
        ])
        self.order_combo.setFixedWidth(160)
        row2.addWidget(self.order_combo)

        row2.addWidget(QLabel("Результатов:"))
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(5, 50)
        self.max_results_spin.setValue(15)
        self.max_results_spin.setFixedWidth(65)
        row2.addWidget(self.max_results_spin)
        row2.addStretch()

        self.search_btn = QPushButton("Найти")
        self.search_btn.setFixedWidth(100)
        self.search_btn.clicked.connect(self._start_search)
        row2.addWidget(self.search_btn)
        c_layout.addLayout(row2)
        outer.addWidget(controls)

        # Progress bar (hidden)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        # Results table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "", "Превью", "Название", "Канал", "Просмотры", "Дата", "Ссылка", "Выбрать"
        ])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 70)
        self.table.setColumnWidth(7, 70)
        self.table.setRowHeight(0, 72)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget {alternate-background-color: #252640;}"
        )
        outer.addWidget(self.table, 1)

        # Manual URL input
        manual_group = QGroupBox("Принудительно добавить URL видео")
        m_layout = QHBoxLayout(manual_group)
        self.manual_urls = QTextEdit()
        self.manual_urls.setPlaceholderText(
            "Вставьте ссылки на видео (по одной на строку)\n"
            "https://www.youtube.com/watch?v=...\n"
            "https://www.youtube.com/watch?v=..."
        )
        self.manual_urls.setFixedHeight(80)
        m_layout.addWidget(self.manual_urls)
        add_manual_btn = QPushButton("Добавить")
        add_manual_btn.setFixedWidth(100)
        add_manual_btn.clicked.connect(self._add_manual_urls)
        m_layout.addWidget(add_manual_btn)
        outer.addWidget(manual_group)

        # Bottom bar
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.setObjectName("secondary")
        self.select_all_btn.setFixedWidth(110)
        self.select_all_btn.clicked.connect(self._select_all)
        bottom.addWidget(self.select_all_btn)

        self.analyze_btn = QPushButton("Анализировать выбранные →")
        self.analyze_btn.setFixedWidth(210)
        self.analyze_btn.clicked.connect(self._emit_selected)
        bottom.addWidget(self.analyze_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------ Actions
    def _start_search(self):
        cfg = load_config()
        api_key = cfg.get("youtube_api_key", "")
        if not api_key:
            self._status.set_error("Введите YouTube API key в настройках.")
            return

        keyword = self.keyword_input.text().strip()
        if not keyword:
            self._status.set_error("Введите ключевые слова.")
            return

        date_map = {
            "Всё время": "all",
            "За неделю": "week",
            "За месяц": "month",
            "За год": "year",
        }
        order_map = {
            "По релевантности": "relevance",
            "По просмотрам": "viewCount",
            "По дате": "date",
        }
        date_filter = date_map[self.date_combo.currentText()]
        order = order_map[self.order_combo.currentText()]
        max_results = self.max_results_spin.value()

        min_views_map = {
            "100K": 100_000, "200K": 200_000, "500K": 500_000,
            "1M": 1_000_000, "Без фильтра": 0,
        }
        min_views = min_views_map[self.min_views_combo.currentText()]

        self._set_busy(True)
        self._results = []
        self.table.setRowCount(0)
        self._status.set_info(f"Ищем: «{keyword}»...")

        worker = WorkerThread(
            search_videos,
            api_key, keyword, date_filter, order, max_results,
        )
        worker.finished.connect(lambda r: self._on_search_done(r, min_views))
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda _: self._set_busy(False))
        worker.error.connect(lambda _: self._set_busy(False))
        self._workers.append(worker)
        worker.start()

    def _on_search_done(self, results: list, min_views: int):
        filtered = [v for v in results if v["view_count"] >= min_views] if min_views else results
        self._results = filtered
        self._status.set_ok(f"Найдено: {len(filtered)} видео")
        self._populate_table(filtered)

    def _populate_table(self, videos: list):
        self.table.setRowCount(len(videos))
        for row, v in enumerate(videos):
            self.table.setRowHeight(row, 72)

            # Row number
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, num_item)

            # Thumbnail
            thumb = ThumbnailLabel()
            self.table.setCellWidget(row, 1, thumb)
            if v.get("thumbnail"):
                self._load_thumbnail_async(thumb, v["thumbnail"])

            # Title
            title_item = QTableWidgetItem(v.get("title", ""))
            title_item.setToolTip(v.get("title", ""))
            self.table.setItem(row, 2, title_item)

            # Channel
            self.table.setItem(row, 3, QTableWidgetItem(v.get("channel", "")))

            # Views
            views_item = QTableWidgetItem(_fmt_views(v.get("view_count", 0)))
            views_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, views_item)

            # Date
            date_str = v.get("published_at", "")[:10]
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, date_item)

            # Link button
            link_btn = QPushButton("Открыть")
            link_btn.setObjectName("secondary")
            url = v.get("url", "")
            link_btn.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            self.table.setCellWidget(row, 6, link_btn)

            # Select checkbox
            chk = QCheckBox()
            chk.setStyleSheet("margin-left:20px;")
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 7, chk_widget)

    def _load_thumbnail_async(self, label: ThumbnailLabel, url: str):
        def _fetch():
            try:
                data = download_thumbnail(url)
                label.set_image_bytes(data)
            except Exception:
                pass
        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

    def _select_all(self):
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 7)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(True)

    def _get_checked_videos(self) -> list[dict]:
        checked = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 7)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.isChecked() and row < len(self._results):
                    checked.append(self._results[row])
        return checked

    def _emit_selected(self):
        selected = self._get_checked_videos()
        if not selected:
            self._status.set_error("Выберите хотя бы одно видео (галочка справа).")
            return

        cfg = load_config()
        api_key = cfg.get("youtube_api_key", "")
        self._status.set_info(f"Загружаем субтитры для {len(selected)} видео...")
        self._set_busy(True)

        worker = WorkerThread(self._fetch_transcripts, selected, api_key)
        worker.finished.connect(self._on_transcripts_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda _: self._set_busy(False))
        worker.error.connect(lambda _: self._set_busy(False))
        self._workers.append(worker)
        worker.start()

    def _fetch_transcripts(self, videos: list, api_key: str) -> list:
        enriched = []
        for v in videos:
            vid_id = v.get("id", "")
            transcript = get_transcript(vid_id) if vid_id else ""
            v = dict(v)
            v["transcript"] = transcript
            enriched.append(v)
        return enriched

    def _on_transcripts_done(self, enriched: list):
        self._status.set_ok(f"Готово! {len(enriched)} видео выбраны для анализа.")
        self.videos_selected.emit(enriched)

    def _add_manual_urls(self):
        cfg = load_config()
        api_key = cfg.get("youtube_api_key", "")
        if not api_key:
            self._status.set_error("Введите YouTube API key в настройках.")
            return
        raw = self.manual_urls.toPlainText().strip()
        if not raw:
            return
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        self._status.set_info(f"Загружаем {len(urls)} видео...")
        self._set_busy(True)

        worker = WorkerThread(self._fetch_manual, urls, api_key)
        worker.finished.connect(self._on_manual_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(lambda _: self._set_busy(False))
        worker.error.connect(lambda _: self._set_busy(False))
        self._workers.append(worker)
        worker.start()

    def _fetch_manual(self, urls: list, api_key: str) -> list:
        videos = []
        for url in urls:
            try:
                v = get_video_details(api_key, url)
                vid_id = v.get("id", "")
                v["transcript"] = get_transcript(vid_id) if vid_id else ""
                videos.append(v)
            except Exception as e:
                pass
        return videos

    def _on_manual_done(self, videos: list):
        if not videos:
            self._status.set_error("Не удалось загрузить видео по указанным ссылкам.")
            return
        self._status.set_ok(f"Загружено {len(videos)} видео вручную.")
        self.videos_selected.emit(videos)
        self.manual_urls.clear()

    def _on_error(self, msg: str):
        self._status.set_error(f"Ошибка: {msg}")

    def _set_busy(self, busy: bool):
        self.search_btn.setEnabled(not busy)
        self.analyze_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
