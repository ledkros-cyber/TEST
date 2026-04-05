"""Script tab — script generation and editing."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QSpinBox, QSplitter, QScrollArea,
    QProgressBar, QSizePolicy, QLineEdit, QComboBox,
)

from app.config_manager import load_config, save_config
from app.api.claude_client import generate_script, count_chars, count_words, LANGUAGES
from app.ui.widgets import WorkerThread, SectionHeader, StatusBar


class ScriptTab(QWidget):
    script_ready = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_videos: list[dict] = []
        self._worker = None
        self._build_ui()

    def set_source_videos(self, videos: list[dict]):
        self._source_videos = videos
        count = len(videos)
        if count:
            self._sources_label.setText(
                f"SEO sources: {count} videos — "
                + ", ".join(v.get("title", "")[:25] for v in videos[:3])
            )
            self._status.set_info(f"Loaded {count} videos for SEO context. Click «Generate script».")
        else:
            self._sources_label.setText("No source videos — script will be generated from master prompt only.")

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Script Generation"))

        # Top controls
        top_group = QGroupBox("Generation Parameters")
        top_layout = QVBoxLayout(top_group)

        self._sources_label = QLabel("SEO sources: 0 (optional — search YouTube first, or generate directly)")
        self._sources_label.setWordWrap(True)
        self._sources_label.setStyleSheet("color:#9090aa; font-size:12px;")
        top_layout.addWidget(self._sources_label)

        row1 = QHBoxLayout()

        # Language selector
        row1.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        cfg = load_config()
        cur_lang = cfg.get("script_language", "English")
        for lang_key in LANGUAGES:
            self.lang_combo.addItem(lang_key, lang_key)
        idx = self.lang_combo.findData(cur_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.setFixedWidth(130)
        row1.addWidget(self.lang_combo)

        row1.addSpacing(20)

        # Character length
        row1.addWidget(QLabel("Length (chars):"))
        self.length_spin = QSpinBox()
        self.length_spin.setRange(1000, 20000)
        self.length_spin.setSingleStep(500)
        self.length_spin.setValue(cfg.get("script_length", 8000))
        self.length_spin.setFixedWidth(100)
        self.length_spin.setToolTip(
            "Target script length in characters.\n"
            "Approx: 4000 chars ≈ 3 min, 8000 ≈ 7 min, 12000 ≈ 10 min"
        )
        row1.addWidget(self.length_spin)
        row1.addStretch()

        self.gen_btn = QPushButton("Generate Script")
        self.gen_btn.setFixedWidth(180)
        self.gen_btn.clicked.connect(self._generate)
        row1.addWidget(self.gen_btn)
        top_layout.addLayout(row1)

        top_layout.addWidget(QLabel("Master Prompt (topic & style instructions):"))
        self.master_prompt = QTextEdit()
        self.master_prompt.setPlaceholderText(
            "Examples:\n"
            "• Write about the mental health benefits of regular exercise\n"
            "• Focus on how exercise improves sleep and energy levels\n"
            "• Emphasize the science behind muscle growth and metabolism"
        )
        self.master_prompt.setFixedHeight(75)
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
        script_header.addWidget(QLabel("Script:"))
        self._char_count_label = QLabel("")
        self._char_count_label.setStyleSheet("color:#9090aa; font-size:11px;")
        script_header.addStretch()
        script_header.addWidget(self._char_count_label)
        sp_layout.addLayout(script_header)

        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("Generated script will appear here...")
        self.script_edit.textChanged.connect(self._update_char_count)
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

        m_layout.addWidget(QLabel("SEO Title (max 70 chars):"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Video title...")
        m_layout.addWidget(self.title_edit)

        m_layout.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("YouTube description (150-300 words)...")
        self.desc_edit.setFixedHeight(120)
        m_layout.addWidget(self.desc_edit)

        m_layout.addWidget(QLabel("Tags (comma-separated):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3...")
        m_layout.addWidget(self.tags_edit)

        m_layout.addWidget(QLabel("Thumbnail Prompt 1 (photorealistic):"))
        self.prompt1_edit = QTextEdit()
        self.prompt1_edit.setFixedHeight(65)
        m_layout.addWidget(self.prompt1_edit)

        m_layout.addWidget(QLabel("Thumbnail Prompt 2 (minimalist):"))
        self.prompt2_edit = QTextEdit()
        self.prompt2_edit.setFixedHeight(65)
        m_layout.addWidget(self.prompt2_edit)

        m_layout.addWidget(QLabel("Thumbnail Prompt 3 (bold/eye-catching):"))
        self.prompt3_edit = QTextEdit()
        self.prompt3_edit.setFixedHeight(65)
        m_layout.addWidget(self.prompt3_edit)

        m_layout.addStretch()
        splitter.addWidget(meta_scroll)
        splitter.setSizes([560, 340])
        outer.addWidget(splitter, 1)

        # Bottom
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        save_master_btn = QPushButton("Save Prompt")
        save_master_btn.setObjectName("secondary")
        save_master_btn.setFixedWidth(120)
        save_master_btn.clicked.connect(self._save_master_prompt)
        bottom.addWidget(save_master_btn)

        confirm_btn = QPushButton("Confirm →")
        confirm_btn.setFixedWidth(120)
        confirm_btn.clicked.connect(self._emit_data)
        bottom.addWidget(confirm_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _generate(self):
        cfg = load_config()
        api_key = cfg.get("anthropic_api_key", "")
        if not api_key:
            self._status.set_error("Enter Anthropic API key in Settings.")
            return

        target_chars = self.length_spin.value()
        master       = self.master_prompt.toPlainText().strip()
        language     = self.lang_combo.currentData() or "English"

        self._set_busy(True)
        self._status.set_info(f"Generating script in {language} (~{target_chars} chars)...")

        self._worker = WorkerThread(
            generate_script,
            api_key, self._source_videos, master, target_chars, language,
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
        self.tags_edit.setText(", ".join(data.get("tags", [])))
        prompts = data.get("thumbnail_prompts", [])
        self.prompt1_edit.setText(prompts[0] if len(prompts) > 0 else "")
        self.prompt2_edit.setText(prompts[1] if len(prompts) > 1 else "")
        self.prompt3_edit.setText(prompts[2] if len(prompts) > 2 else "")
        self._status.set_ok("Script ready! Review and click «Confirm».")
        self._update_char_count()

    def _update_char_count(self):
        text   = self.script_edit.toPlainText()
        chars  = count_chars(text)
        words  = count_words(text)
        target = self.length_spin.value()
        diff   = chars - target
        sign   = "+" if diff >= 0 else ""
        self._char_count_label.setText(
            f"{chars:,} chars | {words:,} words  ({sign}{diff} vs target {target:,})"
        )

    def _save_master_prompt(self):
        cfg = load_config()
        cfg["master_prompt"]    = self.master_prompt.toPlainText()
        cfg["script_language"]  = self.lang_combo.currentData()
        cfg["script_length"]    = self.length_spin.value()
        save_config(cfg)
        self._status.set_ok("Settings saved.")

    def _emit_data(self):
        data = self._collect()
        if not data.get("script"):
            self._status.set_error("Script is empty.")
            return
        self.script_ready.emit(data)
        self._status.set_ok("Data sent to Audio tab.")

    def _collect(self) -> dict:
        tags_raw = self.tags_edit.text()
        tags     = [t.strip() for t in tags_raw.split(",") if t.strip()]
        prompts  = []
        for edit in (self.prompt1_edit, self.prompt2_edit, self.prompt3_edit):
            t = edit.toPlainText().strip()
            if t:
                prompts.append(t)
        return {
            "script":             self.script_edit.toPlainText(),
            "title":              self.title_edit.text(),
            "description":        self.desc_edit.toPlainText(),
            "tags":               tags,
            "thumbnail_prompts":  prompts,
            "language":           self.lang_combo.currentData() or "English",
            "source_urls":        [v.get("url", "") for v in self._source_videos],
            "keyword":            (
                self._source_videos[0].get("keyword", "") if self._source_videos else ""
            ),
        }

    def get_data(self) -> dict:
        return self._collect()

    def _on_error(self, msg: str):
        self._status.set_error(f"Error: {msg}")

    def _set_busy(self, busy: bool):
        self.gen_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
