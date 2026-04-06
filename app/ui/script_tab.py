"""Script tab — script generation, thumbnail analysis, editing."""
import threading
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QSplitter, QScrollArea,
    QProgressBar, QLineEdit,
)

from app.config_manager import load_config, save_config
from app.api.claude_client import generate_script, analyze_thumbnails, count_chars
from app.api.youtube_client import download_thumbnail
from app.ui.widgets import WorkerThread, WheelSpinBox, SectionHeader, StatusBar


class ScriptTab(QWidget):
    script_ready = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_videos: list[dict] = []
        self._worker = None
        self._thumb_worker = None
        self._build_ui()

    def set_source_videos(self, videos: list[dict]):
        self._source_videos = videos
        count = len(videos)
        titles = ", ".join(v.get("title", "")[:30] for v in videos[:3])
        self._sources_label.setText(
            f"Sources loaded: {count} video(s)  —  {titles}"
        )
        self._status.set_info(
            f"{count} video(s) loaded. Click 'Generate Script' to start."
        )

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)
        outer.addWidget(SectionHeader("Script Generation"))

        cfg = load_config()

        # Controls
        ctrl = QGroupBox("Generation settings")
        cl = QVBoxLayout(ctrl)

        self._sources_label = QLabel("Sources: 0")
        self._sources_label.setWordWrap(True)
        self._sources_label.setStyleSheet("color:#9090aa; font-size:12px;")
        cl.addWidget(self._sources_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Script length (characters):"))
        self.length_spin = WheelSpinBox()
        self.length_spin.setRange(100, 100_000)
        self.length_spin.setSingleStep(500)
        self.length_spin.setValue(cfg.get("script_length", 3000))
        self.length_spin.setFixedWidth(100)
        self.length_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row1.addWidget(self.length_spin)
        row1.addStretch()
        self.gen_btn = QPushButton("Generate Script")
        self.gen_btn.setFixedWidth(180)
        self.gen_btn.clicked.connect(self._generate)
        row1.addWidget(self.gen_btn)
        cl.addLayout(row1)

        cl.addWidget(QLabel("Master prompt (optional instructions for Claude):"))
        self.master_prompt = QTextEdit()
        self.master_prompt.setFixedHeight(65)
        self.master_prompt.setText(cfg.get("master_prompt", ""))
        self.master_prompt.setPlaceholderText(
            "Extra instructions for the scriptwriter AI..."
        )
        cl.addWidget(self.master_prompt)
        outer.addWidget(ctrl)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        # Main splitter: script | metadata
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — script
        sp = QWidget()
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(0, 0, 0, 0)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Script:"))
        self._char_label = QLabel("")
        self._char_label.setStyleSheet("color:#9090aa; font-size:11px;")
        hdr.addStretch()
        hdr.addWidget(self._char_label)
        sl.addLayout(hdr)
        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("Generated script will appear here...")
        self.script_edit.textChanged.connect(self._update_char_count)
        sl.addWidget(self.script_edit)
        splitter.addWidget(sp)

        # Right — SEO metadata + thumbnail prompts
        meta_widget = QWidget()
        meta_scroll = QScrollArea()
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setWidget(meta_widget)
        ml = QVBoxLayout(meta_widget)
        ml.setContentsMargins(8, 0, 0, 0)
        ml.setSpacing(8)

        ml.addWidget(QLabel("SEO Title (max 70 chars):"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Video title...")
        ml.addWidget(self.title_edit)

        ml.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(110)
        self.desc_edit.setPlaceholderText("Video description (150-300 words)...")
        ml.addWidget(self.desc_edit)

        ml.addWidget(QLabel("Tags (comma-separated):"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3...")
        ml.addWidget(self.tags_edit)

        # Thumbnail prompts section
        thumb_hdr = QHBoxLayout()
        thumb_hdr.addWidget(QLabel("Thumbnail prompts (from competitor analysis):"))
        self.analyze_thumb_btn = QPushButton("Analyse thumbnails")
        self.analyze_thumb_btn.setObjectName("secondary")
        self.analyze_thumb_btn.setFixedWidth(170)
        self.analyze_thumb_btn.setToolTip(
            "Download competitor thumbnails and analyse them with Claude Vision "
            "to generate adapted prompts for your new video."
        )
        self.analyze_thumb_btn.clicked.connect(self._analyze_thumbnails)
        thumb_hdr.addStretch()
        thumb_hdr.addWidget(self.analyze_thumb_btn)
        ml.addLayout(thumb_hdr)

        self._thumb_status = QLabel("Not analysed yet. Click 'Analyse thumbnails'.")
        self._thumb_status.setStyleSheet("color:#9090aa; font-size:11px;")
        ml.addWidget(self._thumb_status)

        for i in range(1, 4):
            ml.addWidget(QLabel(f"Prompt {i}:"))
            edit = QTextEdit()
            edit.setFixedHeight(72)
            edit.setPlaceholderText(f"Thumbnail prompt {i} will appear after analysis...")
            setattr(self, f"prompt{i}_edit", edit)
            ml.addWidget(edit)

        ml.addStretch()
        splitter.addWidget(meta_scroll)
        splitter.setSizes([560, 340])
        outer.addWidget(splitter, 1)

        # Bottom bar
        btm = QHBoxLayout()
        self._status = StatusBar()
        btm.addWidget(self._status, 1)

        save_mp_btn = QPushButton("Save prompt")
        save_mp_btn.setObjectName("secondary")
        save_mp_btn.setFixedWidth(120)
        save_mp_btn.clicked.connect(self._save_master_prompt)
        btm.addWidget(save_mp_btn)

        confirm_btn = QPushButton("Confirm →")
        confirm_btn.setFixedWidth(120)
        confirm_btn.clicked.connect(self._emit_data)
        btm.addWidget(confirm_btn)
        outer.addLayout(btm)

    # ── Actions ───────────────────────────────────────────────────────────
    def _generate(self):
        cfg = load_config()
        api_key = cfg.get("anthropic_api_key", "")
        if not api_key:
            self._status.set_error("Enter Anthropic API key in Settings.")
            return
        if not self._source_videos:
            self._status.set_error("First select videos on the Search tab.")
            return

        target = self.length_spin.value()
        master = self.master_prompt.toPlainText().strip()
        self._set_busy(True)
        self._status.set_info("Generating script (Claude)...")

        self._worker = WorkerThread(
            generate_script, api_key, self._source_videos, master, target
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
        # Clear thumbnail prompts — need fresh analysis
        for i in range(1, 4):
            getattr(self, f"prompt{i}_edit").clear()
        self._thumb_status.setText(
            "Script ready. Click 'Analyse thumbnails' to generate prompts."
        )
        self._status.set_ok("Script generated! Review and click 'Analyse thumbnails'.")
        self._update_char_count()

    def _analyze_thumbnails(self):
        cfg = load_config()
        api_key = cfg.get("anthropic_api_key", "")
        if not api_key:
            self._status.set_error("Enter Anthropic API key in Settings.")
            return
        if not self._source_videos:
            self._status.set_error("No source videos loaded.")
            return

        thumbnail_urls = [
            v.get("thumbnail", "") for v in self._source_videos if v.get("thumbnail")
        ][:3]
        if not thumbnail_urls:
            self._status.set_error("No thumbnail URLs found in source videos.")
            return

        new_title = self.title_edit.text()
        new_desc  = self.desc_edit.toPlainText()[:300]

        self._set_busy(True)
        self._thumb_status.setText("Downloading thumbnails and analysing with Claude Vision...")
        self._status.set_info("Analysing thumbnails...")

        self._thumb_worker = WorkerThread(
            self._run_thumb_analysis, api_key, thumbnail_urls, new_title, new_desc
        )
        self._thumb_worker.finished.connect(self._on_thumbs_done)
        self._thumb_worker.error.connect(self._on_error)
        self._thumb_worker.finished.connect(lambda _: self._set_busy(False))
        self._thumb_worker.error.connect(lambda _: self._set_busy(False))
        self._thumb_worker.start()

    @staticmethod
    def _run_thumb_analysis(
        api_key: str,
        urls: list[str],
        new_title: str,
        new_desc: str,
    ) -> list[str]:
        pairs = []
        for url in urls:
            try:
                img_bytes = download_thumbnail(url)
                pairs.append((img_bytes, ""))
            except Exception:
                pass
        return analyze_thumbnails(api_key, pairs, new_title, new_desc)

    def _on_thumbs_done(self, prompts: list[str]):
        for i, prompt in enumerate(prompts[:3], 1):
            getattr(self, f"prompt{i}_edit").setText(prompt)
        self._thumb_status.setText(
            f"{len(prompts)} thumbnail prompt(s) generated from competitor analysis."
        )
        self._status.set_ok("Thumbnail prompts ready!")

    def _update_char_count(self):
        text   = self.script_edit.toPlainText()
        chars  = count_chars(text)
        target = self.length_spin.value()
        diff   = chars - target
        sign   = "+" if diff >= 0 else ""
        self._char_label.setText(f"{chars:,} chars ({sign}{diff} from target {target:,})")

    def _save_master_prompt(self):
        cfg = load_config()
        cfg["master_prompt"] = self.master_prompt.toPlainText()
        cfg["script_length"] = self.length_spin.value()
        save_config(cfg)
        self._status.set_ok("Master prompt saved.")

    def _emit_data(self):
        data = self._collect()
        if not data.get("script"):
            self._status.set_error("Script is empty.")
            return
        self.script_ready.emit(data)
        self._status.set_ok("Data passed to Audio tab.")

    def _collect(self) -> dict:
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        prompts = [
            getattr(self, f"prompt{i}_edit").toPlainText().strip()
            for i in range(1, 4)
        ]
        prompts = [p for p in prompts if p]
        return {
            "script": self.script_edit.toPlainText(),
            "title": self.title_edit.text(),
            "description": self.desc_edit.toPlainText(),
            "tags": tags,
            "thumbnail_prompts": prompts,
            "source_urls": [v.get("url", "") for v in self._source_videos],
            "keyword": self._source_videos[0].get("keyword", "") if self._source_videos else "",
        }

    def get_data(self) -> dict:
        return self._collect()

    def _on_error(self, msg: str):
        self._status.set_error(f"Error: {msg}")
        self._thumb_status.setText("Analysis failed — see error above.")

    def _set_busy(self, busy: bool):
        self.gen_btn.setEnabled(not busy)
        self.analyze_thumb_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
