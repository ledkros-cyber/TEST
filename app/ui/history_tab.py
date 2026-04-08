"""History tab — all created video projects."""
import os
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter, QTextEdit, QTextBrowser, QGroupBox, QScrollArea, QMessageBox,
    QSizePolicy,
)

from app import database
from app.ui.widgets import SectionHeader, StatusBar


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[dict] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.addWidget(SectionHeader("История проектов"))
        refresh_btn = QPushButton("Обновить")
        refresh_btn.setObjectName("secondary")
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        outer.addLayout(header_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "#", "Заголовок", "Ключ. слово", "Дата создания",
            "Видео", "Аудио", "Действия"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 160)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # Detail panel
        detail_widget = QWidget()
        d_layout = QVBoxLayout(detail_widget)
        d_layout.setContentsMargins(0, 0, 0, 0)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_content = QWidget()
        detail_scroll.setWidget(detail_content)
        dc_layout = QVBoxLayout(detail_content)
        dc_layout.setContentsMargins(4, 4, 4, 4)
        dc_layout.setSpacing(8)

        self._detail_title = QLabel("")
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet("font-size:15px; font-weight:bold; color:#e8e8f0;")
        dc_layout.addWidget(self._detail_title)

        self._detail_desc = QTextEdit()
        self._detail_desc.setReadOnly(True)
        self._detail_desc.setFixedHeight(80)
        self._detail_desc.setPlaceholderText("Описание появится здесь...")
        dc_layout.addWidget(QLabel("Описание:"))
        dc_layout.addWidget(self._detail_desc)

        self._detail_tags = QLabel("")
        self._detail_tags.setWordWrap(True)
        self._detail_tags.setStyleSheet("color:#9090aa;")
        dc_layout.addWidget(QLabel("Теги:"))
        dc_layout.addWidget(self._detail_tags)

        dc_layout.addWidget(QLabel("Промты для превью:"))
        self._detail_prompts = QTextEdit()
        self._detail_prompts.setReadOnly(True)
        self._detail_prompts.setFixedHeight(80)
        dc_layout.addWidget(self._detail_prompts)

        dc_layout.addWidget(QLabel("Сценарий:"))
        self._detail_script = QTextEdit()
        self._detail_script.setReadOnly(True)
        self._detail_script.setFixedHeight(100)
        dc_layout.addWidget(self._detail_script)

        dc_layout.addWidget(QLabel("Источники:"))
        self._detail_sources = QTextBrowser()
        self._detail_sources.setFixedHeight(90)
        self._detail_sources.setOpenExternalLinks(True)
        self._detail_sources.setStyleSheet("font-size:11px; background:#1a1a2e; border:1px solid #3a3b55;")
        self._detail_sources.anchorClicked.connect(
            lambda url: QDesktopServices.openUrl(url)
        )
        dc_layout.addWidget(self._detail_sources)

        dc_layout.addStretch()
        d_layout.addWidget(detail_scroll)
        splitter.addWidget(detail_widget)
        splitter.setSizes([280, 320])
        outer.addWidget(splitter, 1)

        # Bottom
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        del_btn = QPushButton("Удалить проект")
        del_btn.setObjectName("danger")
        del_btn.setFixedWidth(150)
        del_btn.clicked.connect(self._delete_selected)
        bottom.addWidget(del_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def refresh(self):
        self._projects = database.get_all_projects()
        self.table.setRowCount(len(self._projects))
        for row, p in enumerate(self._projects):
            self.table.setRowHeight(row, 36)

            num_item = QTableWidgetItem(str(p.get("number", row + 1)))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, num_item)

            self.table.setItem(row, 1, QTableWidgetItem(p.get("title", "")))
            self.table.setItem(row, 2, QTableWidgetItem(p.get("keyword", "")))

            date_str = p.get("created_at", "")[:16]
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, date_item)

            vid_path = p.get("video_path", "")
            vid_ok = "✓" if vid_path and os.path.exists(vid_path) else "—"
            vid_item = QTableWidgetItem(vid_ok)
            vid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            vid_item.setForeground(
                Qt.GlobalColor.green if vid_ok == "✓" else Qt.GlobalColor.gray
            )
            self.table.setItem(row, 4, vid_item)

            aud_path = p.get("audio_path", "")
            aud_ok = "✓" if aud_path and os.path.exists(aud_path) else "—"
            aud_item = QTableWidgetItem(aud_ok)
            aud_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            aud_item.setForeground(
                Qt.GlobalColor.green if aud_ok == "✓" else Qt.GlobalColor.gray
            )
            self.table.setItem(row, 5, aud_item)

            # Action buttons
            action_widget = QWidget()
            a_layout = QHBoxLayout(action_widget)
            a_layout.setContentsMargins(4, 2, 4, 2)
            a_layout.setSpacing(4)

            open_vid_btn = QPushButton("Видео")
            open_vid_btn.setObjectName("secondary")
            open_vid_btn.setFixedHeight(26)
            open_vid_btn.setEnabled(bool(vid_path and os.path.exists(vid_path)))
            open_vid_btn.clicked.connect(
                lambda _, v=vid_path: QDesktopServices.openUrl(QUrl.fromLocalFile(v))
            )
            a_layout.addWidget(open_vid_btn)

            open_dir_btn = QPushButton("Папка")
            open_dir_btn.setObjectName("secondary")
            open_dir_btn.setFixedHeight(26)
            d = os.path.dirname(vid_path) if vid_path else ""
            open_dir_btn.setEnabled(bool(d and os.path.isdir(d)))
            open_dir_btn.clicked.connect(
                lambda _, d=d: QDesktopServices.openUrl(QUrl.fromLocalFile(d))
            )
            a_layout.addWidget(open_dir_btn)
            self.table.setCellWidget(row, 6, action_widget)

        self._status.set_info(f"Проектов: {len(self._projects)}")

    def _on_selection_changed(self):
        rows = self.table.selectedItems()
        if not rows:
            return
        row = self.table.currentRow()
        if row < 0 or row >= len(self._projects):
            return
        p = self._projects[row]

        self._detail_title.setText(p.get("title", "(без заголовка)"))
        self._detail_desc.setText(p.get("description", ""))
        tags = p.get("tags", [])
        self._detail_tags.setText(", ".join(tags) if tags else "—")

        prompts = p.get("thumbnail_prompts", [])
        prompt_text = "\n\n".join(
            f"Промт {i+1}:\n{pr}" for i, pr in enumerate(prompts)
        ) if prompts else "—"
        self._detail_prompts.setText(prompt_text)
        self._detail_script.setText(p.get("script", ""))

        sources = p.get("source_urls", [])
        if sources:
            links_html = "<br>".join(
                f'<a href="{url}" style="color:#6c9be8;">{url}</a>'
                for url in sources
            )
            self._detail_sources.setHtml(links_html)
        else:
            self._detail_sources.setPlainText("—")

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._projects):
            self._status.set_error("Выберите проект для удаления.")
            return
        p = self._projects[row]
        reply = QMessageBox.question(
            self, "Удалить проект",
            f"Удалить проект #{p.get('number')} — «{p.get('title', '?')}»?\n"
            "Файлы видео и аудио не будут удалены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            database.delete_project(p["id"])
            self.refresh()

    def add_project(self, project: dict):
        """Called from main window when a new video is created."""
        self.refresh()
