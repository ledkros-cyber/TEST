"""Audio tab — TTS generation via MiniMax."""
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QDoubleSpinBox, QTextEdit,
    QFileDialog, QProgressBar, QLineEdit,
)

from app.config_manager import load_config
from app.api.minimax_client import generate_audio, get_audio_duration_estimate, VOICES
from app.processing.video_processor import get_audio_duration
from app.ui.widgets import WorkerThread, SectionHeader, StatusBar


class AudioTab(QWidget):
    audio_ready = pyqtSignal(str)    # path to generated audio

    def __init__(self, parent=None):
        super().__init__(parent)
        self._script = ""
        self._audio_path = ""
        self._worker = None
        self._build_ui()

    def set_script_data(self, data: dict):
        self._script = data.get("script", "")
        self.script_preview.setText(
            self._script[:500] + ("..." if len(self._script) > 500 else "")
        )
        words = len(self._script.split())
        cfg = load_config()
        speed = self.speed_spin.value()
        est = get_audio_duration_estimate(self._script, speed)
        self._info_label.setText(
            f"Слов в сценарии: {words}  |  Ожидаемая длина аудио: ~{est:.0f} сек "
            f"(~{est/60:.1f} мин)"
        )
        self._status.set_info("Сценарий загружен. Настройте голос и нажмите «Озвучить».")

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        outer.addWidget(SectionHeader("Озвучка (MiniMax TTS)"))

        # Script preview
        preview_group = QGroupBox("Сценарий (фрагмент)")
        prev_layout = QVBoxLayout(preview_group)
        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFixedHeight(100)
        self.script_preview.setPlaceholderText(
            "Сначала создайте сценарий на вкладке «Сценарий»..."
        )
        prev_layout.addWidget(self.script_preview)
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#9090aa; font-size:12px;")
        prev_layout.addWidget(self._info_label)
        outer.addWidget(preview_group)

        # Voice settings
        voice_group = QGroupBox("Настройки голоса")
        vg_layout = QVBoxLayout(voice_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Голос:"))
        self.voice_combo = QComboBox()
        cfg = load_config()
        cur_voice = cfg.get("voice_id", "female-shaonv")
        for vid, label in VOICES.items():
            self.voice_combo.addItem(label, vid)
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == cur_voice:
                self.voice_combo.setCurrentIndex(i)
                break
        row1.addWidget(self.voice_combo)
        row1.addStretch()
        vg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Скорость речи:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(cfg.get("voice_speed", 1.0))
        self.speed_spin.setFixedWidth(80)
        self.speed_spin.valueChanged.connect(self._update_estimate)
        row2.addWidget(self.speed_spin)

        row2.addSpacing(24)
        row2.addWidget(QLabel("Громкость голоса:"))
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
        out_group = QGroupBox("Сохранить аудио в")
        out_layout = QHBoxLayout(out_group)
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Путь для сохранения MP3...")
        out_layout.addWidget(self.output_path)
        browse_btn = QPushButton("Обзор")
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

        self.gen_btn = QPushButton("Озвучить текст")
        self.gen_btn.setFixedWidth(160)
        self.gen_btn.clicked.connect(self._generate)
        bottom.addWidget(self.gen_btn)

        next_btn = QPushButton("К видео →")
        next_btn.setFixedWidth(120)
        next_btn.clicked.connect(self._confirm)
        bottom.addWidget(next_btn)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    def _update_estimate(self):
        if self._script:
            speed = self.speed_spin.value()
            est = get_audio_duration_estimate(self._script, speed)
            words = len(self._script.split())
            self._info_label.setText(
                f"Слов: {words}  |  Ожидаемая длина аудио: ~{est:.0f} сек (~{est/60:.1f} мин)"
            )

    def _browse_output(self):
        cfg = load_config()
        default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить аудио", os.path.join(default_dir, "voiceover.mp3"),
            "MP3 файлы (*.mp3)"
        )
        if path:
            self.output_path.setText(path)

    def _generate(self):
        cfg = load_config()
        api_key = cfg.get("minimax_api_key", "")
        group_id = cfg.get("minimax_group_id", "")
        if not api_key:
            self._status.set_error("Введите MiniMax API key в настройках.")
            return
        if not group_id:
            self._status.set_error("Введите MiniMax Group ID в настройках.")
            return
        if not self._script:
            self._status.set_error("Сценарий пустой. Сначала создайте сценарий.")
            return

        out_path = self.output_path.text().strip()
        if not out_path:
            default_dir = cfg.get("output_folder", "") or os.path.expanduser("~")
            out_path = os.path.join(default_dir, "voiceover.mp3")
            self.output_path.setText(out_path)

        voice_id = self.voice_combo.currentData()
        speed = self.speed_spin.value()
        volume = self.vol_spin.value()

        self._set_busy(True)
        self._status.set_info("Генерирую озвучку...")

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
                f"Аудио создано: {os.path.basename(path)}  |  "
                f"Длина: {dur:.1f} сек ({dur/60:.1f} мин)"
            )
        except Exception:
            self._audio_info.setText(f"Аудио создано: {path}")
        self._status.set_ok("Озвучка готова!")
        self.audio_ready.emit(path)

    def _confirm(self):
        if not self._audio_path:
            self._status.set_error("Сначала сгенерируйте озвучку.")
            return
        self.audio_ready.emit(self._audio_path)
        self._status.set_ok("Аудио передано на вкладку «Видео».")

    def get_audio_path(self) -> str:
        return self._audio_path

    def _on_error(self, msg: str):
        self._status.set_error(f"Ошибка: {msg}")

    def _set_busy(self, busy: bool):
        self.gen_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
