"""Script tab — script generation and editing."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QSpinBox, QSplitter, QScrollArea,
    QProgressBar, QSizePolicy, QLineEdit,
)

from app.config_manager import load_config
from app.api.claude_client import generate_script, count_words
from app.ui.widgets import WorkerThread, SectionHeader, StatusBar


class ScriptTab(QWidget):
    script_ready = pyqtSignal(dict)  # emitted when script is generated/saved

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_videos: list[dict] = []
        self._worker = None
        self._build_ui()

    def set_source_videos(self, videos: list[dict]):
        self._source_videos = videos
        count = len(videos)
        self._sources_label.setText(
            f"Источников для анализа: {count} видео"
            + (f" — {', '.join(v.get('title','')[:30] for v in videos[:3])}" if videos else "")
        )
        self._status.set_info(f"Загружено {count} видео. Нажмите «Создать сценарий».")

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Генерация сценария"))

        # Top controls
        top_group = QGroupBox("Параметры генерации")
        top_layout = QVBoxLayout(top_group)

        self._sources_label = QLabel("Источников для анализа: 0")
        self._sources_label.setWordWrap(True)
        self._sources_label.setStyleSheet("color:#9090aa; font-size:12px;")
        top_layout.addWidget(self._sources_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Длина сценария (слов):"))
        cfg = load_config()
        self.length_spin = QSpinBox()
        self.length_spin.setRange(200, 5000)
        self.length_spin.setSingleStep(50)
        self.length_spin.setValue(cfg.get("script_length", 800))
        self.length_spin.setFixedWidth(90)
        row1.addWidget(self.length_spin)
        row1.addStretch()

        self.gen_btn = QPushButton("Создать сценарий")
        self.gen_btn.setFixedWidth(180)
        self.gen_btn.clicked.connect(self._generate)
        row1.addWidget(self.gen_btn)
        top_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Мастер-промт:"))
        top_layout.addLayout(row2)

        self.master_prompt = QTextEdit()
        self.master_prompt.setPlaceholderText(
            "Дополнительные инструкции для написания сценария (необязательно)"
        )
        self.master_prompt.setFixedHeight(70)
        self.master_prompt.setText(cfg.get("master_prompt", ""))
        top_layout.addWidget(self.master_prompt)
        outer.addWidget(top_group)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        # Main splitter: script left, meta right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: script
        script_panel = QWidget()
        sp_layout = QVBoxLayout(script_panel)
        sp_layout.setContentsMargins(0, 0, 0, 0)

        script_header = QHBoxLayout()
        script_header.addWidget(QLabel("Сценарий:"))
        self._word_count_label = QLabel("")
        self._word_count_label.setStyleSheet("color:#9090aa; font-size:11px;")
        script_header.addStretch()
        script_header.addWidget(self._word_count_label)
        sp_layout.addLayout(script_header)

        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("Здесь появится сгенерированный сценарий...")
        self.script_edit.textChanged.connect(self._update_word_count)
        sp_layout.addWidget(self.script_edit)
        splitter.addWidget(script_panel)

        # Right: title / description / tags / thumbnail prompts
        meta_panel = QWidget()
        meta_scroll = QScrollArea()
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setWidget(meta_panel)
        m_layout = QVBoxLayout(meta_panel)
        m_layout.setContentsMargins(8, 0, 0, 0)
        m_layout.setSpacing(10)

        m_layout.addWidget(QLabel("SEO заголовок:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Заголовок видео (до 70 символов)")
        m_layout.addWidget(self.title_edit)

        m_layout.addWidget(QLabel("Описание:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Описание видео (150-300 слов)...")
        self.desc_edit.setFixedHeight(120)
        m_layout.addWidget(self.desc_edit)

        m_layout.addWidget(QLabel("Теги (через запятую):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("тег1, тег2, тег3...")
        m_layout.addWidget(self.tags_edit)

        m_layout.addWidget(QLabel("Промт для превью 1 (реалистичный):"))
        self.prompt1_edit = QTextEdit()
        self.prompt1_edit.setFixedHeight(70)
        m_layout.addWidget(self.prompt1_edit)

        m_layout.addWidget(QLabel("Промт для превью 2 (минималистичный):"))
        self.prompt2_edit = QTextEdit()
        self.prompt2_edit.setFixedHeight(70)
        m_layout.addWidget(self.prompt2_edit)

        m_layout.addWidget(QLabel("Промт для превью 3 (яркий/кричащий):"))
        self.prompt3_edit = QTextEdit()
        self.prompt3_edit.setFixedHeight(70)
        m_layout.addWidget(self.prompt3_edit)

        m_layout.addStretch()
        splitter.addWidget(meta_scroll)
        splitter.setSizes([550, 350])
        outer.addWidget(splitter, 1)

        # Bottom
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        save_master_btn = QPushButton("Сохранить промт")
        save_master_btn.setObjectName("secondary")
        save_master_btn.setFixedWidth(140)
        save_master_btn.clicked.connect(self._save_master_prompt)
        bottom.addWidget(save_master_btn)

        confirm_btn = QPushButton("Подтвердить →")
        confirm_btn.setFixedWidth(140)
        confirm_btn.clicked.connect(self._emit_data)
        bottom.addWidget(confirm_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _generate(self):
        cfg = load_config()
        api_key = cfg.get("anthropic_api_key", "")
        if not api_key:
            self._status.set_error("Введите Anthropic API key в настройках.")
            return
        if not self._source_videos:
            self._status.set_error("Сначала выберите видео на вкладке «Поиск».")
            return

        target_words = self.length_spin.value()
        master = self.master_prompt.toPlainText().strip()

        self._set_busy(True)
        self._status.set_info("Генерирую сценарий (Claude)...")

        self._worker = WorkerThread(
            generate_script,
            api_key, self._source_videos, master, target_words,
        )
        self._worker.finished.connect(self._on_script_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda _: self._set_busy(False))
        self._worker.error.connect(lambda _: self._set_busy(False))
        self._worker.start()

    def _on_script_done(self, data: dict):
        self.script_edit.setText(data.get("script", ""))
        self.title_edit.setText(data.get("title", ""))
        self.desc_edit.setText(data.get("description", ""))
        tags = data.get("tags", [])
        self.tags_edit.setText(", ".join(tags))
        prompts = data.get("thumbnail_prompts", [])
        self.prompt1_edit.setText(prompts[0] if len(prompts) > 0 else "")
        self.prompt2_edit.setText(prompts[1] if len(prompts) > 1 else "")
        self.prompt3_edit.setText(prompts[2] if len(prompts) > 2 else "")
        self._status.set_ok("Сценарий готов! Проверьте и нажмите «Подтвердить».")
        self._update_word_count()

    def _update_word_count(self):
        text = self.script_edit.toPlainText()
        w = count_words(text)
        target = self.length_spin.value()
        diff = w - target
        sign = "+" if diff >= 0 else ""
        self._word_count_label.setText(f"{w} слов ({sign}{diff} от цели {target})")

    def _save_master_prompt(self):
        cfg = load_config()
        cfg["master_prompt"] = self.master_prompt.toPlainText()
        from app.config_manager import save_config
        save_config(cfg)
        self._status.set_ok("Мастер-промт сохранён.")

    def _emit_data(self):
        data = self._collect()
        if not data.get("script"):
            self._status.set_error("Сценарий пустой.")
            return
        self.script_ready.emit(data)
        self._status.set_ok("Данные переданы на вкладку «Озвучка».")

    def _collect(self) -> dict:
        tags_raw = self.tags_edit.text()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        prompts = []
        for edit in (self.prompt1_edit, self.prompt2_edit, self.prompt3_edit):
            t = edit.toPlainText().strip()
            if t:
                prompts.append(t)
        return {
            "script": self.script_edit.toPlainText(),
            "title": self.title_edit.text(),
            "description": self.desc_edit.toPlainText(),
            "tags": tags,
            "thumbnail_prompts": prompts,
            "source_urls": [v.get("url", "") for v in self._source_videos],
            "keyword": (
                self._source_videos[0].get("keyword", "") if self._source_videos else ""
            ),
        }

    def get_data(self) -> dict:
        return self._collect()

    def _on_error(self, msg: str):
        self._status.set_error(f"Ошибка: {msg}")

    def _set_busy(self, busy: bool):
        self.gen_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
