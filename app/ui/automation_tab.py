"""
Automation tab — fully automatic batch video creation.

Workflow per video:
  1. (Optional) Fetch YouTube SEO data for the topic
  2. Generate script via Claude (language + char target from duration)
  3. Generate voiceover via MiniMax TTS
  4. Build video reel with scene detection
  5. Render final video with subtitles
  6. Save project to history

All videos are saved with numbered filenames so SEO data is always
easy to match: video_0001.mp4 → video_0001_seo.json
"""
import json
import os
import time
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QScrollArea, QCheckBox, QFileDialog,
)

from app.config_manager import load_config
from app.api.claude_client import generate_script, LANGUAGES
from app.api.minimax_client import generate_audio, VOICES
from app.api.youtube_client import search_videos
from app.processing.video_processor import (
    VideoConfig, process_video, get_audio_duration,
)
from app import database
from app.ui.widgets import SectionHeader, StatusBar


# ─────────────────────────────────────────────────────────────────────────────
# Duration → target character count  (~750 chars/min at normal speed)
# ─────────────────────────────────────────────────────────────────────────────
CHARS_PER_MINUTE = 750


def duration_to_chars(minutes: float) -> int:
    return max(1000, int(minutes * CHARS_PER_MINUTE))


# ─────────────────────────────────────────────────────────────────────────────
# Background worker that runs the full pipeline for N videos
# ─────────────────────────────────────────────────────────────────────────────

class AutoWorker(QObject):
    progress      = pyqtSignal(int, str)         # overall %, message
    video_done    = pyqtSignal(int, dict)         # video index (1-based), project dict
    video_error   = pyqtSignal(int, str)          # video index, error message
    all_done      = pyqtSignal()

    def __init__(self, jobs: list[dict], cfg: dict):
        super().__init__()
        self._jobs   = jobs    # list of job dicts
        self._cfg    = cfg
        self._stop   = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self._jobs)
        for idx, job in enumerate(self._jobs, 1):
            if self._stop:
                break
            try:
                self.progress.emit(
                    int((idx - 1) / total * 100),
                    f"Video {idx}/{total}: starting...",
                )
                project = self._run_job(idx, job)
                self.video_done.emit(idx, project)
            except Exception as e:
                self.video_error.emit(idx, str(e))
        self.progress.emit(100, "All done!")
        self.all_done.emit()

    def _run_job(self, idx: int, job: dict) -> dict:
        cfg         = self._cfg
        topic       = job["topic"]
        language    = job["language"]
        target_min  = job["duration_min"]
        target_chars = duration_to_chars(target_min)
        master_prompt = job.get("master_prompt", "")
        voice_id    = job.get("voice_id", cfg.get("voice_id", "female-shaonv"))
        total       = len(self._jobs)

        def _prog(pct: int, msg: str):
            overall = int((idx - 1) / total * 100 + pct / total)
            self.progress.emit(overall, f"Video {idx}/{total}: {msg}")

        # ── 1. YouTube SEO fetch ──────────────────────────────────────────────
        source_videos: list[dict] = []
        if job.get("fetch_seo") and cfg.get("youtube_api_key"):
            _prog(2, "Fetching YouTube SEO data...")
            try:
                results = search_videos(
                    api_key   = cfg["youtube_api_key"],
                    query     = topic,
                    max_results = 5,
                    order     = "relevance",
                )
                source_videos = results[:5]
            except Exception:
                pass

        # ── 2. Generate script ────────────────────────────────────────────────
        _prog(8, f"Generating script ({language}, ~{target_chars} chars)...")
        script_data = generate_script(
            api_key       = cfg["anthropic_api_key"],
            source_videos = source_videos,
            master_prompt = master_prompt or f"Write about: {topic}",
            target_chars  = target_chars,
            language      = language,
        )

        # ── 3. Save SEO data alongside video ────────────────────────────────
        out_dir   = cfg.get("output_folder", "") or os.path.expanduser("~")
        proj_num  = database.next_project_number()
        base_name = f"video_{proj_num:04d}"
        video_out = os.path.join(out_dir, f"{base_name}.mp4")
        audio_out = os.path.join(out_dir, f"{base_name}_voice.mp3")
        seo_out   = os.path.join(out_dir, f"{base_name}_seo.json")

        seo_payload = {
            "project_number": proj_num,
            "topic":          topic,
            "language":       language,
            "title":          script_data.get("title", ""),
            "description":    script_data.get("description", ""),
            "tags":           script_data.get("tags", []),
            "thumbnail_prompts": script_data.get("thumbnail_prompts", []),
            "created_at":     datetime.now().isoformat(),
        }
        os.makedirs(out_dir, exist_ok=True)
        with open(seo_out, "w", encoding="utf-8") as f:
            json.dump(seo_payload, f, ensure_ascii=False, indent=2)

        # ── 4. Generate voiceover ─────────────────────────────────────────────
        _prog(30, "Generating voiceover (MiniMax)...")
        generate_audio(
            api_key   = cfg["minimax_api_key"],
            group_id  = cfg["minimax_group_id"],
            text      = script_data["script"],
            voice_id  = voice_id,
            speed     = cfg.get("voice_speed", 1.0),
            volume    = 1.0,
            output_path = audio_out,
        )

        # ── 5. Build & render video ───────────────────────────────────────────
        _prog(50, "Rendering video...")
        quality_map = {"720p": "720p", "1080p": "1080p"}
        quality = quality_map.get(cfg.get("quality", "1080p"), "1080p")

        vid_cfg = VideoConfig(
            source_folder     = cfg["source_videos_folder"],
            audio_path        = audio_out,
            output_path       = video_out,
            quality           = quality,
            fps               = cfg.get("fps", 60),
            bg_volume         = cfg.get("bg_audio_volume", 0.05),
            voice_volume      = 1.0,
            noise_intensity   = cfg.get("noise_intensity", 8),
            clip_min_dur      = 3.0,
            clip_max_dur      = 8.0,
            extra_seconds     = 10.0,
            script            = script_data["script"],
            use_gpu           = cfg.get("use_gpu", True),
            parallel_workers  = 3,
            use_scene_detect  = cfg.get("use_scene_detect", True),
            scene_threshold   = cfg.get("scene_threshold", 0.35),
            progress_callback = lambda p, m: _prog(50 + p // 2, m),
        )
        process_video(vid_cfg)

        # ── 6. Save to history ────────────────────────────────────────────────
        _prog(98, "Saving to history...")
        data = dict(script_data)
        data["audio_path"] = audio_out
        data["video_path"] = video_out
        data["keyword"]    = topic
        data["seo_file"]   = seo_out
        data["notes"]      = f"Auto-generated | topic: {topic} | lang: {language} | {target_min:.1f} min"

        project_id = database.save_project(data)
        project    = database.get_project(project_id) or {}
        project["seo_file"] = seo_out
        return project


# ─────────────────────────────────────────────────────────────────────────────
# Thread wrapper
# ─────────────────────────────────────────────────────────────────────────────

class AutoThread(QThread):
    def __init__(self, worker: AutoWorker):
        super().__init__()
        self._worker = worker

    def run(self):
        self._worker.run()


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────

class AutomationTab(QWidget):
    videos_created = pyqtSignal(list)   # list of project dicts

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread  = None
        self._worker  = None
        self._results: list[dict] = []
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Batch Automation — Create Multiple Videos Automatically"))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: configuration ───────────────────────────────────────────────
        left = QScrollArea()
        left.setWidgetResizable(True)
        left_w = QWidget()
        left.setWidget(left_w)
        left_layout = QVBoxLayout(left_w)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        # Topic & language
        topic_group = QGroupBox("Topic & Language")
        tg_layout = QVBoxLayout(topic_group)

        tg_layout.addWidget(QLabel("Topic / Keywords:"))
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("e.g. workout benefits, fitness motivation, exercise science")
        tg_layout.addWidget(self.topic_edit)

        row_lang = QHBoxLayout()
        row_lang.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        cfg = load_config()
        cur_lang = cfg.get("script_language", "English")
        for lang_key in LANGUAGES:
            self.lang_combo.addItem(lang_key, lang_key)
        idx = self.lang_combo.findData(cur_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.setFixedWidth(140)
        row_lang.addWidget(self.lang_combo)

        row_lang.addSpacing(16)
        self.fetch_seo_check = QCheckBox("Auto-fetch YouTube SEO")
        self.fetch_seo_check.setChecked(True)
        self.fetch_seo_check.setToolTip(
            "Search YouTube for the topic and use the top results\n"
            "as SEO context when writing the script."
        )
        row_lang.addWidget(self.fetch_seo_check)
        row_lang.addStretch()
        tg_layout.addLayout(row_lang)

        tg_layout.addWidget(QLabel("Master Prompt (optional — applied to all videos):"))
        self.master_prompt = QTextEdit()
        self.master_prompt.setFixedHeight(65)
        self.master_prompt.setPlaceholderText(
            "e.g. Focus on science-backed benefits. Use an energetic, motivating tone."
        )
        self.master_prompt.setText(cfg.get("master_prompt", ""))
        tg_layout.addWidget(self.master_prompt)
        left_layout.addWidget(topic_group)

        # Videos to create
        videos_group = QGroupBox("Videos to Create")
        vg_layout = QVBoxLayout(videos_group)

        row_count = QHBoxLayout()
        row_count.addWidget(QLabel("Number of videos:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 50)
        self.count_spin.setValue(3)
        self.count_spin.setFixedWidth(65)
        self.count_spin.valueChanged.connect(self._rebuild_duration_table)
        row_count.addWidget(self.count_spin)
        row_count.addStretch()
        vg_layout.addLayout(row_count)

        vg_layout.addWidget(QLabel("Duration per video (minutes):"))
        self.duration_table = QTableWidget(3, 3)
        self.duration_table.setHorizontalHeaderLabels(["Video #", "Duration (min)", "Custom Prompt"])
        self.duration_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.duration_table.setFixedHeight(140)
        self._rebuild_duration_table(3)
        vg_layout.addWidget(self.duration_table)
        left_layout.addWidget(videos_group)

        # Voice selection
        voice_group = QGroupBox("Voice")
        voice_layout = QHBoxLayout(voice_group)
        voice_layout.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(220)
        cur_voice = cfg.get("voice_id", "female-shaonv")
        for vid, label in VOICES.items():
            self.voice_combo.addItem(f"{label}  [{vid}]", vid)
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == cur_voice:
                self.voice_combo.setCurrentIndex(i)
                break
        voice_layout.addWidget(self.voice_combo)
        voice_layout.addStretch()
        left_layout.addWidget(voice_group)

        # Validation checklist
        check_group = QGroupBox("Requirements Check")
        check_layout = QVBoxLayout(check_group)
        self._check_label = QLabel("")
        self._check_label.setWordWrap(True)
        self._check_label.setStyleSheet("font-size:11px; color:#9090aa;")
        check_layout.addWidget(self._check_label)
        validate_btn = QPushButton("Check Config")
        validate_btn.setObjectName("secondary")
        validate_btn.setFixedWidth(120)
        validate_btn.clicked.connect(self._validate)
        check_layout.addWidget(validate_btn)
        left_layout.addWidget(check_group)

        left_layout.addStretch()
        splitter.addWidget(left)

        # ── Right: progress & results ─────────────────────────────────────────
        right_w = QWidget()
        right_layout = QVBoxLayout(right_w)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        right_layout.addWidget(QLabel("Progress:"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        right_layout.addWidget(self.overall_progress)

        self._progress_label = QLabel("Ready")
        self._progress_label.setStyleSheet("color:#9090aa; font-size:12px;")
        right_layout.addWidget(self._progress_label)

        right_layout.addWidget(QLabel("Results:"))
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["#", "Title", "Duration", "Status"])
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.results_table, 1)

        # Log
        right_layout.addWidget(QLabel("Log:"))
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(130)
        self.log_edit.setStyleSheet("font-size:11px; font-family: monospace;")
        right_layout.addWidget(self.log_edit)

        splitter.addWidget(right_w)
        splitter.setSizes([420, 580])
        outer.addWidget(splitter, 1)

        # Bottom controls
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(90)
        self.stop_btn.setObjectName("secondary")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        bottom.addWidget(self.stop_btn)

        self.start_btn = QPushButton("▶  Start Automation")
        self.start_btn.setFixedWidth(180)
        self.start_btn.clicked.connect(self._start)
        bottom.addWidget(self.start_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _rebuild_duration_table(self, count: int = None):
        if count is None:
            count = self.count_spin.value()
        # Preserve existing values
        old_data: list[tuple] = []
        for r in range(self.duration_table.rowCount()):
            dur_item   = self.duration_table.item(r, 1)
            prompt_item = self.duration_table.item(r, 2)
            dur_val    = float(dur_item.text())    if dur_item    else 7.0
            prompt_val = prompt_item.text()         if prompt_item else ""
            old_data.append((dur_val, prompt_val))

        self.duration_table.setRowCount(count)
        for r in range(count):
            num_item = QTableWidgetItem(f"Video {r+1:02d}")
            num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.duration_table.setItem(r, 0, num_item)

            dur_val    = old_data[r][0]    if r < len(old_data) else 7.0
            prompt_val = old_data[r][1]    if r < len(old_data) else ""
            self.duration_table.setItem(r, 1, QTableWidgetItem(str(dur_val)))
            self.duration_table.setItem(r, 2, QTableWidgetItem(prompt_val))

        self.duration_table.setFixedHeight(min(200, 30 + count * 30))

    def _validate(self) -> bool:
        cfg    = load_config()
        issues = []
        ok     = []

        if cfg.get("anthropic_api_key"):
            ok.append("✓ Anthropic API key")
        else:
            issues.append("✗ Anthropic API key missing (Settings)")

        if cfg.get("minimax_api_key") and cfg.get("minimax_group_id"):
            ok.append("✓ MiniMax API key + Group ID")
        else:
            issues.append("✗ MiniMax API key / Group ID missing (Settings)")

        if cfg.get("source_videos_folder") and os.path.isdir(cfg["source_videos_folder"]):
            ok.append("✓ Source videos folder exists")
        else:
            issues.append("✗ Source videos folder not set or doesn't exist (Settings)")

        if cfg.get("output_folder"):
            ok.append("✓ Output folder set")
        else:
            issues.append("✗ Output folder not set (Settings)")

        if self.fetch_seo_check.isChecked() and not cfg.get("youtube_api_key"):
            issues.append("⚠ YouTube API key missing — SEO fetch will be skipped")

        lines = ok + issues
        self._check_label.setText("\n".join(lines))
        if issues and not all("⚠" in i for i in issues):
            self._status.set_error("Fix issues before starting automation.")
            return False
        self._status.set_ok("Ready to start!")
        return True

    def _build_jobs(self) -> list[dict]:
        language   = self.lang_combo.currentData() or "English"
        fetch_seo  = self.fetch_seo_check.isChecked()
        topic      = self.topic_edit.text().strip()
        master     = self.master_prompt.toPlainText().strip()
        voice_id   = self.voice_combo.currentData()
        jobs = []

        for r in range(self.duration_table.rowCount()):
            dur_item    = self.duration_table.item(r, 1)
            prompt_item = self.duration_table.item(r, 2)
            try:
                dur = float(dur_item.text()) if dur_item else 7.0
            except ValueError:
                dur = 7.0
            custom_prompt = prompt_item.text().strip() if prompt_item else ""

            jobs.append({
                "topic":         topic,
                "language":      language,
                "duration_min":  dur,
                "fetch_seo":     fetch_seo,
                "master_prompt": custom_prompt or master,
                "voice_id":      voice_id,
            })
        return jobs

    def _start(self):
        if not self.topic_edit.text().strip():
            self._status.set_error("Enter a topic/keywords.")
            return
        if not self._validate():
            return

        cfg  = load_config()
        jobs = self._build_jobs()

        # Reset UI
        self.results_table.setRowCount(0)
        self.log_edit.clear()
        self.overall_progress.setValue(0)
        self._results.clear()

        # Populate results table with pending rows
        self.results_table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            chars = duration_to_chars(job["duration_min"])
            self.results_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.results_table.setItem(i, 1, QTableWidgetItem(f"{job['topic']} ({job['language']})"))
            self.results_table.setItem(i, 2, QTableWidgetItem(f"{job['duration_min']:.1f} min / ~{chars:,} chars"))
            status_item = QTableWidgetItem("Pending")
            status_item.setForeground(Qt.GlobalColor.gray)
            self.results_table.setItem(i, 3, status_item)

        self._set_busy(True)
        self._log(f"Starting automation: {len(jobs)} videos, language: {jobs[0]['language']}")

        self._worker = AutoWorker(jobs, cfg)
        self._worker.progress.connect(self._on_progress)
        self._worker.video_done.connect(self._on_video_done)
        self._worker.video_error.connect(self._on_video_error)
        self._worker.all_done.connect(self._on_all_done)

        self._thread = AutoThread(self._worker)
        self._thread.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self._log("Stop requested — finishing current video...")
        self.stop_btn.setEnabled(False)

    def _on_progress(self, pct: int, msg: str):
        self.overall_progress.setValue(pct)
        self._progress_label.setText(msg)

    def _on_video_done(self, idx: int, project: dict):
        self._results.append(project)
        self._log(f"✓ Video {idx} done: {project.get('title', 'N/A')}")
        if idx <= self.results_table.rowCount():
            row = idx - 1
            self.results_table.setItem(row, 1, QTableWidgetItem(project.get("title", "Done")))
            status_item = QTableWidgetItem("Done")
            status_item.setForeground(Qt.GlobalColor.green)
            self.results_table.setItem(row, 3, status_item)
            seo = project.get("seo_file", "")
            if seo:
                self._log(f"  SEO saved: {os.path.basename(seo)}")

    def _on_video_error(self, idx: int, msg: str):
        self._log(f"✗ Video {idx} FAILED: {msg}")
        if idx <= self.results_table.rowCount():
            status_item = QTableWidgetItem("Error")
            status_item.setForeground(Qt.GlobalColor.red)
            self.results_table.setItem(idx - 1, 3, status_item)

    def _on_all_done(self):
        self._set_busy(False)
        done  = sum(1 for r in self._results if r)
        total = self.count_spin.value()
        self._status.set_ok(f"Automation complete: {done}/{total} videos created.")
        self._log(f"\n=== Finished: {done}/{total} videos ===")
        if self._results:
            self.videos_created.emit(self._results)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_edit.append(f"[{ts}] {msg}")

    def _set_busy(self, busy: bool):
        self.start_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.count_spin.setEnabled(not busy)
        self.topic_edit.setEnabled(not busy)
