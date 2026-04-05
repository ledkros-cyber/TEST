"""Video tab — video assembly and rendering."""
import os
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QSlider, QCheckBox, QFileDialog, QProgressBar, QTextEdit,
)

from app.config_manager import load_config
from app.processing.video_processor import (
    VideoConfig, process_video, get_gpu_info, clear_scene_cache,
)
from app.ui.widgets import WorkerThread, SectionHeader, StatusBar
from app import database


class VideoTab(QWidget):
    video_created = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_path = ""
        self._script_data: dict = {}
        self._worker = None
        self._build_ui()
        QTimer.singleShot(500, self._detect_gpu)

    def set_audio_path(self, path: str):
        self._audio_path = path
        self.audio_path_label.setText(os.path.basename(path) if path else "not set")

    def set_script_data(self, data: dict):
        self._script_data = data

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Video Assembly"))

        # Info row
        info_row = QHBoxLayout()
        info_row.addWidget(QLabel("Audio:"))
        self.audio_path_label = QLabel("not set")
        self.audio_path_label.setStyleSheet("color:#9090aa;")
        info_row.addWidget(self.audio_path_label)
        info_row.addStretch()
        outer.addLayout(info_row)

        # Source videos folder
        src_group = QGroupBox("Source Videos Folder")
        src_layout = QHBoxLayout(src_group)
        self.source_folder = QLineEdit()
        cfg = load_config()
        self.source_folder.setText(cfg.get("source_videos_folder", ""))
        self.source_folder.setPlaceholderText("Folder with exercise video files (.mp4, .mov, .avi...)")
        src_layout.addWidget(self.source_folder)
        src_browse = QPushButton("Browse")
        src_browse.setObjectName("secondary")
        src_browse.setFixedWidth(70)
        src_browse.clicked.connect(lambda: self._browse_folder(self.source_folder))
        src_layout.addWidget(src_browse)

        clear_cache_btn = QPushButton("Clear Scene Cache")
        clear_cache_btn.setObjectName("secondary")
        clear_cache_btn.setFixedWidth(140)
        clear_cache_btn.setToolTip(
            "Delete cached scene detection files (.scenes.json).\n"
            "Forces re-detection on the next render."
        )
        clear_cache_btn.clicked.connect(self._clear_cache)
        src_layout.addWidget(clear_cache_btn)
        outer.addWidget(src_group)

        # Output
        out_group = QGroupBox("Output Video")
        out_layout = QHBoxLayout(out_group)
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Path to save the finished video...")
        out_layout.addWidget(self.output_path)
        out_browse = QPushButton("Browse")
        out_browse.setObjectName("secondary")
        out_browse.setFixedWidth(70)
        out_browse.clicked.connect(self._browse_output)
        out_layout.addWidget(out_browse)
        outer.addWidget(out_group)

        # Video settings
        settings_group = QGroupBox("Render Settings")
        sg_layout = QVBoxLayout(settings_group)

        # GPU status banner
        self._gpu_label = QLabel("Detecting GPU...")
        self._gpu_label.setStyleSheet(
            "background:#1e1f35; border:1px solid #3a3b55; border-radius:4px; "
            "padding:4px 10px; color:#9090aa; font-size:12px;"
        )
        sg_layout.addWidget(self._gpu_label)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["1080p (Full HD)", "720p (HD)"])
        self.quality_combo.setCurrentText(
            "1080p (Full HD)" if cfg.get("quality", "1080p") == "1080p" else "720p (HD)"
        )
        self.quality_combo.setFixedWidth(160)
        row1.addWidget(self.quality_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("FPS:"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["60", "30", "24"])
        self.fps_combo.setCurrentText(str(cfg.get("fps", 60)))
        self.fps_combo.setFixedWidth(70)
        row1.addWidget(self.fps_combo)

        row1.addSpacing(16)
        row1.addWidget(QLabel("GPU (NVENC):"))
        self.gpu_check = QCheckBox("Enable")
        self.gpu_check.setChecked(cfg.get("use_gpu", True))
        row1.addWidget(self.gpu_check)

        row1.addSpacing(16)
        row1.addWidget(QLabel("Cut threads:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        self.workers_spin.setValue(3)
        self.workers_spin.setToolTip("Parallel clip-cut jobs. Recommended: 3 for Legion RTX.")
        self.workers_spin.setFixedWidth(55)
        row1.addWidget(self.workers_spin)
        row1.addStretch()
        sg_layout.addLayout(row1)

        # Scene detection row
        row_scene = QHBoxLayout()
        self.scene_detect_check = QCheckBox("Exercise scene detection")
        self.scene_detect_check.setChecked(cfg.get("use_scene_detect", True))
        self.scene_detect_check.setToolTip(
            "Detect exercise start/end in each video file using FFmpeg.\n"
            "Results are cached — first run may take extra time.\n"
            "Ensures clips come from DIFFERENT source files for variety."
        )
        row_scene.addWidget(self.scene_detect_check)

        row_scene.addSpacing(16)
        row_scene.addWidget(QLabel("Scene sensitivity:"))
        self.scene_threshold_spin = QDoubleSpinBox()
        self.scene_threshold_spin.setRange(0.1, 0.8)
        self.scene_threshold_spin.setSingleStep(0.05)
        self.scene_threshold_spin.setDecimals(2)
        self.scene_threshold_spin.setValue(cfg.get("scene_threshold", 0.35))
        self.scene_threshold_spin.setFixedWidth(70)
        self.scene_threshold_spin.setToolTip(
            "FFmpeg scene change threshold (0.1 = very sensitive, 0.5 = less sensitive).\n"
            "Default 0.35 works well for most exercise videos."
        )
        row_scene.addWidget(self.scene_threshold_spin)
        row_scene.addStretch()
        sg_layout.addLayout(row_scene)

        # Audio volumes
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Background vol:"))
        self.bg_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_vol_slider.setRange(0, 100)
        bg_vol_init = int(cfg.get("bg_audio_volume", 0.05) * 100)
        self.bg_vol_slider.setValue(bg_vol_init)
        self.bg_vol_slider.setFixedWidth(140)
        self._bg_vol_label = QLabel(f"{bg_vol_init}%")
        self._bg_vol_label.setFixedWidth(35)
        self.bg_vol_slider.valueChanged.connect(lambda v: self._bg_vol_label.setText(f"{v}%"))
        row2.addWidget(self.bg_vol_slider)
        row2.addWidget(self._bg_vol_label)

        row2.addSpacing(16)
        row2.addWidget(QLabel("Voice vol:"))
        self.voice_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.voice_vol_slider.setRange(0, 200)
        self.voice_vol_slider.setValue(100)
        self.voice_vol_slider.setFixedWidth(140)
        self._voice_vol_label = QLabel("100%")
        self._voice_vol_label.setFixedWidth(40)
        self.voice_vol_slider.valueChanged.connect(lambda v: self._voice_vol_label.setText(f"{v}%"))
        row2.addWidget(self.voice_vol_slider)
        row2.addWidget(self._voice_vol_label)
        row2.addStretch()
        sg_layout.addLayout(row2)

        # Noise & clip length
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Grain/noise:"))
        self.noise_spin = QSpinBox()
        self.noise_spin.setRange(0, 30)
        self.noise_spin.setValue(cfg.get("noise_intensity", 8))
        self.noise_spin.setFixedWidth(65)
        self.noise_spin.setSuffix("  (0=off)")
        row3.addWidget(self.noise_spin)

        row3.addSpacing(16)
        row3.addWidget(QLabel("Clip duration (sec):"))
        self.clip_min_spin = QDoubleSpinBox()
        self.clip_min_spin.setRange(1.0, 10.0)
        self.clip_min_spin.setValue(3.0)
        self.clip_min_spin.setDecimals(1)
        self.clip_min_spin.setFixedWidth(65)
        row3.addWidget(self.clip_min_spin)
        row3.addWidget(QLabel("—"))
        self.clip_max_spin = QDoubleSpinBox()
        self.clip_max_spin.setRange(1.0, 30.0)
        self.clip_max_spin.setValue(8.0)
        self.clip_max_spin.setDecimals(1)
        self.clip_max_spin.setFixedWidth(65)
        row3.addWidget(self.clip_max_spin)

        row3.addSpacing(16)
        row3.addWidget(QLabel("Extra seconds:"))
        self.extra_spin = QDoubleSpinBox()
        self.extra_spin.setRange(0, 60)
        self.extra_spin.setValue(10.0)
        self.extra_spin.setDecimals(1)
        self.extra_spin.setFixedWidth(65)
        row3.addWidget(self.extra_spin)
        row3.addStretch()
        sg_layout.addLayout(row3)

        outer.addWidget(settings_group)

        # Notes
        notes_group = QGroupBox("Notes (optional)")
        notes_layout = QVBoxLayout(notes_group)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(55)
        self.notes_edit.setPlaceholderText("Personal notes saved with project history...")
        notes_layout.addWidget(self.notes_edit)
        outer.addWidget(notes_group)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color:#9090aa; font-size:12px;")
        outer.addWidget(self._progress_label)

        outer.addStretch()

        # Bottom
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        self.render_btn = QPushButton("Create Video")
        self.render_btn.setFixedWidth(160)
        self.render_btn.clicked.connect(self._render)
        bottom.addWidget(self.render_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _detect_gpu(self):
        worker = WorkerThread(get_gpu_info)
        worker.finished.connect(self._on_gpu_info)
        worker.start()
        self._gpu_worker = worker

    def _on_gpu_info(self, info: str):
        if "NVENC" in info:
            self._gpu_label.setText(f"⚡ GPU: {info}")
            self._gpu_label.setStyleSheet(
                "background:#0d2b0d; border:1px solid #4caf81; border-radius:4px; "
                "padding:4px 10px; color:#4caf81; font-size:12px; font-weight:bold;"
            )
        else:
            self._gpu_label.setText(f"⚠ GPU: {info}")
            self._gpu_label.setStyleSheet(
                "background:#2b1a0d; border:1px solid #f0a030; border-radius:4px; "
                "padding:4px 10px; color:#f0a030; font-size:12px;"
            )

    def _browse_folder(self, field: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select folder", field.text())
        if folder:
            field.setText(folder)

    def _browse_output(self):
        cfg = load_config()
        default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
        num = database.next_project_number()
        default_name = f"video_{num:04d}.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save video",
            os.path.join(default_dir, default_name),
            "MP4 files (*.mp4)"
        )
        if path:
            self.output_path.setText(path)

    def _clear_cache(self):
        src = self.source_folder.text().strip()
        if not src:
            self._status.set_error("Set source folder first.")
            return
        try:
            clear_scene_cache(src)
            self._status.set_ok("Scene cache cleared — will re-detect on next render.")
        except Exception as e:
            self._status.set_error(f"Error clearing cache: {e}")

    def _get_quality(self) -> str:
        return "1080p" if "1080" in self.quality_combo.currentText() else "720p"

    def _render(self):
        src   = self.source_folder.text().strip()
        audio = self._audio_path
        out   = self.output_path.text().strip()

        if not src:
            self._status.set_error("Set source videos folder.")
            return
        if not audio:
            self._status.set_error("No audio. Generate voiceover in Audio tab first.")
            return
        if not out:
            cfg = load_config()
            default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
            num = database.next_project_number()
            out = os.path.join(default_dir, f"video_{num:04d}.mp4")
            self.output_path.setText(out)

        cfg_vid = VideoConfig(
            source_folder     = src,
            audio_path        = audio,
            output_path       = out,
            quality           = self._get_quality(),
            fps               = int(self.fps_combo.currentText()),
            bg_volume         = self.bg_vol_slider.value() / 100.0,
            voice_volume      = self.voice_vol_slider.value() / 100.0,
            noise_intensity   = self.noise_spin.value(),
            clip_min_dur      = self.clip_min_spin.value(),
            clip_max_dur      = self.clip_max_spin.value(),
            extra_seconds     = self.extra_spin.value(),
            script            = self._script_data.get("script", ""),
            use_gpu           = self.gpu_check.isChecked(),
            parallel_workers  = self.workers_spin.value(),
            use_scene_detect  = self.scene_detect_check.isChecked(),
            scene_threshold   = self.scene_threshold_spin.value(),
            progress_callback = self._on_progress,
        )

        self._set_busy(True)
        self.progress.setValue(0)
        self._status.set_info("Rendering video...")

        self._worker = WorkerThread(process_video, cfg_vid)
        self._worker.finished.connect(self._on_render_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self._progress_label.setText(msg)

    def _on_render_done(self, video_path: str):
        self._set_busy(False)
        self._status.set_ok(f"Video created: {os.path.basename(video_path)}")

        data = dict(self._script_data)
        data["audio_path"] = self._audio_path
        data["video_path"] = video_path
        data["notes"]      = self.notes_edit.toPlainText()

        project_id = database.save_project(data)
        project    = database.get_project(project_id)
        if project:
            self.video_created.emit(project)

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._status.set_error(f"Render error: {msg}")

    def _set_busy(self, busy: bool):
        self.render_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        self._progress_label.setVisible(busy)
