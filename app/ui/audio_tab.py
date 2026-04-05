"""Audio tab — TTS generation via MiniMax."""
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QDoubleSpinBox, QTextEdit,
    QFileDialog, QProgressBar, QLineEdit,
)

from app.config_manager import load_config
from app.api.minimax_client import generate_audio, get_audio_duration_estimate, VOICES, fetch_voices
from app.processing.video_processor import get_audio_duration
from app.ui.widgets import WorkerThread, SectionHeader, StatusBar


class AudioTab(QWidget):
    audio_ready = pyqtSignal(str)    # path to generated audio

    def __init__(self, parent=None):
        super().__init__(parent)
        self._script    = ""
        self._audio_path = ""
        self._worker    = None
        self._voices: dict[str, str] = dict(VOICES)
        self._build_ui()

    def set_script_data(self, data: dict):
        self._script = data.get("script", "")
        self.script_preview.setText(
            self._script[:600] + ("..." if len(self._script) > 600 else "")
        )
        chars  = len(self._script)
        words  = len(self._script.split())
        speed  = self.speed_spin.value()
        est    = get_audio_duration_estimate(self._script, speed)
        self._info_label.setText(
            f"Script: {chars:,} chars | {words:,} words  |  "
            f"Estimated audio: ~{est:.0f}s (~{est/60:.1f} min)"
        )
        self._status.set_info("Script loaded. Choose a voice and click «Generate audio».")

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Voiceover (MiniMax TTS)"))

        # Script preview
        preview_group = QGroupBox("Script Preview")
        prev_layout = QVBoxLayout(preview_group)
        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFixedHeight(100)
        self.script_preview.setPlaceholderText(
            "Generate a script first (Script tab)..."
        )
        prev_layout.addWidget(self.script_preview)
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#9090aa; font-size:12px;")
        prev_layout.addWidget(self._info_label)
        outer.addWidget(preview_group)

        # Voice settings
        voice_group = QGroupBox("Voice Settings")
        vg_layout = QVBoxLayout(voice_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(260)
        cfg = load_config()
        cur_voice = cfg.get("voice_id", "female-shaonv")
        self._populate_voices(cur_voice)
        row1.addWidget(self.voice_combo)
        row1.addSpacing(10)

        refresh_btn = QPushButton("Refresh Voices")
        refresh_btn.setObjectName("secondary")
        refresh_btn.setFixedWidth(130)
        refresh_btn.setToolTip("Fetch the latest voice list from MiniMax API")
        refresh_btn.clicked.connect(self._refresh_voices)
        row1.addWidget(refresh_btn)
        row1.addStretch()
        vg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Speech speed:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(cfg.get("voice_speed", 1.0))
        self.speed_spin.setFixedWidth(80)
        self.speed_spin.valueChanged.connect(self._update_estimate)
        row2.addWidget(self.speed_spin)

        row2.addSpacing(24)
        row2.addWidget(QLabel("Volume:"))
        self.vol_spin = QDoubleSpinBox()
        self.vol_spin.setRange(0.1, 2.0)
        self.vol_spin.setSingleStep(0.05)
        self.vol_spin.setDecimals(2)
        self.vol_spin.setValue(cfg.get("voice_volume", 1.0))
        self.vol_spin.setFixedWidth(80)
        row2.addWidget(self.vol_spin)
        row2.addStretch()
        vg_layout.addLayout(row2)
        outer.addWidget(voice_group)

        # Output path
        out_group = QGroupBox("Save Audio To")
        out_layout = QHBoxLayout(out_group)
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Path to save MP3...")
        out_layout.addWidget(self.output_path)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondary")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(browse_btn)
        outer.addWidget(out_group)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        # Generated audio info
        self._audio_info = QLabel("")
        self._audio_info.setStyleSheet("color:#4caf81; font-weight:bold;")
        outer.addWidget(self._audio_info)

        outer.addStretch()

        # Bottom buttons
        bottom = QHBoxLayout()
        self._status = StatusBar()
        bottom.addWidget(self._status, 1)

        self.gen_btn = QPushButton("Generate Audio")
        self.gen_btn.setFixedWidth(160)
        self.gen_btn.clicked.connect(self._generate)
        bottom.addWidget(self.gen_btn)

        next_btn = QPushButton("To Video →")
        next_btn.setFixedWidth(120)
        next_btn.clicked.connect(self._confirm)
        bottom.addWidget(next_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _populate_voices(self, select_voice: str = ""):
        self.voice_combo.clear()
        for vid, label in self._voices.items():
            self.voice_combo.addItem(f"{label}  [{vid}]", vid)
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == select_voice:
                self.voice_combo.setCurrentIndex(i)
                break

    def _refresh_voices(self):
        cfg = load_config()
        api_key  = cfg.get("minimax_api_key", "")
        group_id = cfg.get("minimax_group_id", "")
        if not api_key or not group_id:
            self._status.set_error("Set MiniMax API key and Group ID in Settings first.")
            return

        self._status.set_info("Fetching voices from MiniMax API...")
        cur_voice = self.voice_combo.currentData()

        def _fetch():
            return fetch_voices(api_key, group_id)

        worker = WorkerThread(_fetch)
        worker.finished.connect(lambda voices: self._on_voices_fetched(voices, cur_voice))
        worker.error.connect(lambda e: self._status.set_error(f"Could not fetch voices: {e}"))
        worker.start()
        self._refresh_worker = worker  # keep ref

    def _on_voices_fetched(self, voices: dict, prev_voice: str):
        if voices:
            self._voices = voices
            self._populate_voices(prev_voice)
            self._status.set_ok(f"Voice list updated: {len(voices)} voices available.")
        else:
            self._status.set_info("No voices returned; using default list.")

    def _update_estimate(self):
        if self._script:
            speed = self.speed_spin.value()
            est   = get_audio_duration_estimate(self._script, speed)
            chars = len(self._script)
            words = len(self._script.split())
            self._info_label.setText(
                f"Script: {chars:,} chars | {words:,} words  |  "
                f"Estimated audio: ~{est:.0f}s (~{est/60:.1f} min)"
            )

    def _browse_output(self):
        cfg = load_config()
        default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save audio", os.path.join(default_dir, "voiceover.mp3"),
            "MP3 files (*.mp3)"
        )
        if path:
            self.output_path.setText(path)

    def _generate(self):
        cfg      = load_config()
        api_key  = cfg.get("minimax_api_key", "")
        group_id = cfg.get("minimax_group_id", "")
        if not api_key:
            self._status.set_error("Enter MiniMax API key in Settings.")
            return
        if not group_id:
            self._status.set_error("Enter MiniMax Group ID in Settings.")
            return
        if not self._script:
            self._status.set_error("Script is empty. Generate a script first.")
            return

        out_path = self.output_path.text().strip()
        if not out_path:
            default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
            out_path = os.path.join(default_dir, "voiceover.mp3")
            self.output_path.setText(out_path)

        voice_id = self.voice_combo.currentData()
        speed    = self.speed_spin.value()
        volume   = self.vol_spin.value()

        self._set_busy(True)
        self._status.set_info("Generating voiceover...")

        self._worker = WorkerThread(
            generate_audio,
            api_key, group_id, self._script, voice_id, speed, volume, out_path,
        )
        self._worker.finished.connect(self._on_audio_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda _: self._set_busy(False))
        self._worker.error.connect(lambda _: self._set_busy(False))
        self._worker.start()

    def _on_audio_done(self, path: str):
        self._audio_path = path
        try:
            dur = get_audio_duration(path)
            self._audio_info.setText(
                f"Audio ready: {os.path.basename(path)}  |  "
                f"Duration: {dur:.1f}s ({dur/60:.1f} min)"
            )
        except Exception:
            self._audio_info.setText(f"Audio ready: {path}")
        self._status.set_ok("Voiceover generated!")
        self.audio_ready.emit(path)

    def _confirm(self):
        if not self._audio_path:
            self._status.set_error("Generate voiceover first.")
            return
        self.audio_ready.emit(self._audio_path)
        self._status.set_ok("Audio sent to Video tab.")

    def get_audio_path(self) -> str:
        return self._audio_path

    def _on_error(self, msg: str):
        self._status.set_error(f"Error: {msg}")

    def _set_busy(self, busy: bool):
        self.gen_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
