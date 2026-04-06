"""Audio tab — TTS generation via MiniMax."""
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QTextEdit, QFileDialog, QProgressBar, QLineEdit,
)

from app.config_manager import load_config, save_config
from app.api.minimax_client import (
    generate_audio, get_audio_duration_estimate, VOICES, MODELS, DEFAULT_MODEL
)
from app.processing.video_processor import get_audio_duration
from app.ui.widgets import WheelDoubleSpinBox, WorkerThread, SectionHeader, StatusBar

# Internal audio storage — inside the project's data/ folder
_AUDIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "audio"
)


class AudioTab(QWidget):
    audio_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._script = ""
        self._audio_path = ""
        self._worker = None
        self._build_ui()

    def set_script_data(self, data: dict):
        self._script = data.get("script", "")
        preview = self._script[:600] + ("..." if len(self._script) > 600 else "")
        self.script_preview.setText(preview)
        self._update_estimate()
        self._status.set_info("Script loaded. Configure voice and click 'Generate Audio'.")

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)
        outer.addWidget(SectionHeader("Voiceover — MiniMax TTS"))

        cfg = load_config()

        # Script preview
        prev_group = QGroupBox("Script preview")
        pl = QVBoxLayout(prev_group)
        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFixedHeight(95)
        self.script_preview.setPlaceholderText(
            "First create a script on the Script tab..."
        )
        pl.addWidget(self.script_preview)
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#9090aa; font-size:12px;")
        pl.addWidget(self._info_label)
        outer.addWidget(prev_group)

        # Voice settings
        vg = QGroupBox("Voice settings")
        vl = QVBoxLayout(vg)

        # Model
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        for mid, mlabel in MODELS.items():
            self.model_combo.addItem(mlabel, mid)
        # Set default
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == DEFAULT_MODEL:
                self.model_combo.setCurrentIndex(i)
                break
        r0.addWidget(self.model_combo)
        r0.addStretch()
        vl.addLayout(r0)

        # Voice
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        cur_voice = cfg.get("voice_id", "English_Trustful_Man")
        for vid, vlabel in VOICES.items():
            self.voice_combo.addItem(vlabel, vid)
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == cur_voice:
                self.voice_combo.setCurrentIndex(i)
                break
        r1.addWidget(self.voice_combo, 1)
        vl.addLayout(r1)

        # Speed / Volume
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Speed:"))
        self.speed_spin = WheelDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(cfg.get("voice_speed", 1.0))
        self.speed_spin.setFixedWidth(75)
        self.speed_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.speed_spin.valueChanged.connect(self._update_estimate)
        r2.addWidget(self.speed_spin)

        r2.addSpacing(20)
        r2.addWidget(QLabel("Volume:"))
        self.vol_spin = WheelDoubleSpinBox()
        self.vol_spin.setRange(0.1, 2.0)
        self.vol_spin.setSingleStep(0.05)
        self.vol_spin.setDecimals(2)
        self.vol_spin.setValue(cfg.get("voice_volume", 1.0))
        self.vol_spin.setFixedWidth(75)
        self.vol_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        r2.addWidget(self.vol_spin)
        r2.addStretch()
        vl.addLayout(r2)
        outer.addWidget(vg)

        # Optional custom save path
        og = QGroupBox("Save audio to (optional — leave empty for auto)")
        ol = QHBoxLayout(og)
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText(
            "Auto-saved internally. Browse to choose a custom location..."
        )
        ol.addWidget(self.output_path)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondary")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_output)
        ol.addWidget(browse_btn)
        outer.addWidget(og)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(8)
        outer.addWidget(self.progress)

        self._audio_info = QLabel("")
        self._audio_info.setStyleSheet("color:#4caf81; font-weight:bold;")
        outer.addWidget(self._audio_info)
        outer.addStretch()

        # Buttons
        btm = QHBoxLayout()
        self._status = StatusBar()
        btm.addWidget(self._status, 1)

        self.gen_btn = QPushButton("Generate Audio")
        self.gen_btn.setFixedWidth(160)
        self.gen_btn.clicked.connect(self._generate)
        btm.addWidget(self.gen_btn)

        next_btn = QPushButton("To Video →")
        next_btn.setFixedWidth(110)
        next_btn.clicked.connect(self._confirm)
        btm.addWidget(next_btn)
        outer.addLayout(btm)

    # ── Actions ───────────────────────────────────────────────────────────
    def _update_estimate(self):
        if not self._script:
            return
        speed = self.speed_spin.value()
        est   = get_audio_duration_estimate(self._script, speed)
        chars = len(self._script)
        self._info_label.setText(
            f"Characters: {chars:,}  |  Estimated duration: ~{est:.0f}s (~{est/60:.1f} min)"
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
        api_key  = cfg.get("minimax_api_key",  "").strip()
        group_id = cfg.get("minimax_group_id", "").strip()

        if not api_key:
            self._status.set_error(
                "MiniMax API key not set. Go to Settings tab."
            )
            return
        if not self._script:
            self._status.set_error("Script is empty. Create a script first.")
            return

        out_path = self.output_path.text().strip()
        if not out_path:
            # Auto-save to internal data/audio/ folder
            os.makedirs(_AUDIO_DIR, exist_ok=True)
            out_path = os.path.join(_AUDIO_DIR, "voiceover.mp3")

        # Persist audio settings before generating
        cfg["voice_id"]     = self.voice_combo.currentData()
        cfg["voice_speed"]  = self.speed_spin.value()
        cfg["voice_volume"] = self.vol_spin.value()
        save_config(cfg)

        self._set_busy(True)
        self._status.set_info("Generating voiceover via MiniMax...")

        self._worker = WorkerThread(
            generate_audio,
            api_key,
            group_id,                          # optional for .io endpoint
            self._script,
            self.voice_combo.currentData(),
            self.speed_spin.value(),
            self.vol_spin.value(),
            self.model_combo.currentData(),
            out_path,
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
                f"Duration: {dur:.1f}s ({dur/60:.1f} min)  |  "
                f"Sent to Video tab automatically."
            )
        except Exception:
            self._audio_info.setText(
                f"Audio ready: {os.path.basename(path)}  |  Sent to Video tab automatically."
            )
        self._status.set_ok("Voiceover ready! Switched to Video tab.")
        self.audio_ready.emit(path)

    def _confirm(self):
        if not self._audio_path:
            self._status.set_error("Generate audio first.")
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
