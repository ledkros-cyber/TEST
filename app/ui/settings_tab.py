"""Settings tab — API keys and global defaults."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QScrollArea,
)
from PyQt6.QtCore import Qt

from app.config_manager import load_config, save_config
from app.api.minimax_client import VOICES
from app.ui.widgets import SectionHeader, StatusBar


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = load_config()
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        main = QVBoxLayout(content)
        main.setSpacing(16)
        main.setContentsMargins(20, 16, 20, 16)

        main.addWidget(SectionHeader("Настройки"))

        # --- API Keys ---
        api_group = QGroupBox("API ключи")
        api_form = QFormLayout(api_group)
        api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        api_form.setSpacing(10)

        self.yt_key = self._make_key_field(self._cfg.get("youtube_api_key", ""))
        self.anthropic_key = self._make_key_field(self._cfg.get("anthropic_api_key", ""))
        self.minimax_key = self._make_key_field(self._cfg.get("minimax_api_key", ""))
        self.minimax_group = QLineEdit(self._cfg.get("minimax_group_id", ""))
        self.minimax_group.setPlaceholderText("MiniMax Group ID")

        api_form.addRow("YouTube API Key:", self.yt_key)
        api_form.addRow("Anthropic (Claude) Key:", self.anthropic_key)
        api_form.addRow("MiniMax API Key:", self.minimax_key)
        api_form.addRow("MiniMax Group ID:", self.minimax_group)
        main.addWidget(api_group)

        # --- Folders ---
        folder_group = QGroupBox("Папки по умолчанию")
        folder_form = QFormLayout(folder_group)
        folder_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        folder_form.setSpacing(10)

        self.output_folder = self._make_folder_row(
            self._cfg.get("output_folder", ""), folder_form, "Папка для готовых видео:"
        )
        self.source_folder = self._make_folder_row(
            self._cfg.get("source_videos_folder", ""), folder_form, "Папка с исходными видео:"
        )
        main.addWidget(folder_group)

        # --- Video defaults ---
        vid_group = QGroupBox("Настройки видео по умолчанию")
        vid_form = QFormLayout(vid_group)
        vid_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        vid_form.setSpacing(10)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["1080p", "720p"])
        self.quality_combo.setCurrentText(self._cfg.get("quality", "1080p"))

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(24, 60)
        self.fps_spin.setValue(self._cfg.get("fps", 60))

        self.bg_vol_spin = QDoubleSpinBox()
        self.bg_vol_spin.setRange(0.0, 1.0)
        self.bg_vol_spin.setSingleStep(0.01)
        self.bg_vol_spin.setDecimals(2)
        self.bg_vol_spin.setValue(self._cfg.get("bg_audio_volume", 0.05))

        self.noise_spin = QSpinBox()
        self.noise_spin.setRange(0, 30)
        self.noise_spin.setValue(self._cfg.get("noise_intensity", 8))

        self.use_gpu_combo = QComboBox()
        self.use_gpu_combo.addItems(["Да (NVENC — быстро)", "Нет (CPU — совместимо)"])
        self.use_gpu_combo.setCurrentIndex(0 if self._cfg.get("use_gpu", True) else 1)

        vid_form.addRow("Качество:", self.quality_combo)
        vid_form.addRow("FPS:", self.fps_spin)
        vid_form.addRow("Громкость фонового видео:", self.bg_vol_spin)
        vid_form.addRow("Интенсивность шума (0=нет):", self.noise_spin)
        vid_form.addRow("Ускорение GPU (NVENC):", self.use_gpu_combo)
        main.addWidget(vid_group)

        # --- Voice defaults ---
        voice_group = QGroupBox("Голос по умолчанию (MiniMax)")
        voice_form = QFormLayout(voice_group)
        voice_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        voice_form.setSpacing(10)

        self.voice_combo = QComboBox()
        for vid, label in VOICES.items():
            self.voice_combo.addItem(label, vid)
        cur_voice = self._cfg.get("voice_id", "female-shaonv")
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == cur_voice:
                self.voice_combo.setCurrentIndex(i)
                break

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(self._cfg.get("voice_speed", 1.0))

        voice_form.addRow("Голос:", self.voice_combo)
        voice_form.addRow("Скорость речи:", self.speed_spin)
        main.addWidget(voice_group)

        # --- Script defaults ---
        script_group = QGroupBox("Сценарий по умолчанию")
        script_form = QFormLayout(script_group)
        script_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        script_form.setSpacing(10)

        self.script_len_spin = QSpinBox()
        self.script_len_spin.setRange(200, 5000)
        self.script_len_spin.setSingleStep(50)
        self.script_len_spin.setValue(self._cfg.get("script_length", 800))
        self.script_len_spin.setSuffix(" слов")

        script_form.addRow("Длина сценария:", self.script_len_spin)
        main.addWidget(script_group)

        # --- Save button ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Сохранить настройки")
        save_btn.setFixedWidth(200)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        main.addLayout(btn_row)

        self._status = StatusBar()
        main.addWidget(self._status)
        main.addStretch()

    def _make_key_field(self, value: str) -> QLineEdit:
        field = QLineEdit(value)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("Введите ключ...")
        return field

    def _make_folder_row(self, value: str, form: QFormLayout, label: str) -> QLineEdit:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(value)
        field.setPlaceholderText("Путь к папке...")
        btn = QPushButton("Обзор")
        btn.setObjectName("secondary")
        btn.setFixedWidth(70)
        btn.clicked.connect(lambda: self._browse_folder(field))
        layout.addWidget(field)
        layout.addWidget(btn)
        form.addRow(label, row)
        return field

    def _browse_folder(self, field: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", field.text())
        if folder:
            field.setText(folder)

    def _save(self):
        cfg = load_config()
        cfg["youtube_api_key"] = self.yt_key.text().strip()
        cfg["anthropic_api_key"] = self.anthropic_key.text().strip()
        cfg["minimax_api_key"] = self.minimax_key.text().strip()
        cfg["minimax_group_id"] = self.minimax_group.text().strip()
        cfg["output_folder"] = self.output_folder.text().strip()
        cfg["source_videos_folder"] = self.source_folder.text().strip()
        cfg["quality"] = self.quality_combo.currentText()
        cfg["fps"] = self.fps_spin.value()
        cfg["bg_audio_volume"] = self.bg_vol_spin.value()
        cfg["noise_intensity"] = self.noise_spin.value()
        cfg["use_gpu"] = self.use_gpu_combo.currentIndex() == 0
        cfg["voice_id"] = self.voice_combo.currentData()
        cfg["voice_speed"] = self.speed_spin.value()
        cfg["script_length"] = self.script_len_spin.value()
        save_config(cfg)
        self._status.set_ok("Настройки сохранены!")

    def get_config(self) -> dict:
        return load_config()
