"""Settings tab — API keys and folder defaults."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QFileDialog,
    QScrollArea, QLineEdit,
)

from app.config_manager import load_config, save_config
from app.api.gemini_client import GEMINI_MODELS, DEFAULT_GEMINI_MODEL
from app.ui.widgets import ApiKeyField, SectionHeader, StatusBar


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
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
        main.setContentsMargins(24, 16, 24, 16)

        main.addWidget(SectionHeader("Settings — API keys & folders"))

        cfg = load_config()

        # ── AI Provider ───────────────────────────────────────────────────
        ai_group = QGroupBox("AI Provider for script generation")
        ai_layout = QVBoxLayout(ai_group)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Use AI:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Claude (Anthropic)", "claude")
        self.provider_combo.addItem("Gemini (Google)", "gemini")
        cur_provider = cfg.get("ai_provider", "claude")
        self.provider_combo.setCurrentIndex(
            0 if cur_provider == "claude" else 1
        )
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.setFixedWidth(220)
        provider_row.addWidget(self.provider_combo)
        provider_row.addStretch()
        ai_layout.addLayout(provider_row)

        hint = QLabel(
            "Claude — best quality, vision analysis.\n"
            "Gemini — Google AI, free tier available at aistudio.google.com."
        )
        hint.setStyleSheet("color:#9090aa; font-size:11px;")
        ai_layout.addWidget(hint)
        main.addWidget(ai_group)

        # ── API Keys ──────────────────────────────────────────────────────
        api_group = QGroupBox("API Keys")
        api_form = QFormLayout(api_group)
        api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        api_form.setSpacing(12)
        api_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.yt_key = ApiKeyField("YouTube Data API v3 key...")
        self.yt_key.setText(cfg.get("youtube_api_key", ""))

        self.claude_key = ApiKeyField("Anthropic / Claude API key...")
        self.claude_key.setText(cfg.get("anthropic_api_key", ""))

        self.gemini_key = ApiKeyField("Google Gemini API key (aistudio.google.com)...")
        self.gemini_key.setText(cfg.get("gemini_api_key", ""))

        # Gemini model selector
        gemini_model_row = QWidget()
        gmr_layout = QHBoxLayout(gemini_model_row)
        gmr_layout.setContentsMargins(0, 0, 0, 0)
        self.gemini_model_combo = QComboBox()
        for mid, mlabel in GEMINI_MODELS.items():
            self.gemini_model_combo.addItem(mlabel, mid)
        cur_gm = cfg.get("gemini_model", DEFAULT_GEMINI_MODEL)
        for i in range(self.gemini_model_combo.count()):
            if self.gemini_model_combo.itemData(i) == cur_gm:
                self.gemini_model_combo.setCurrentIndex(i)
                break
        gmr_layout.addWidget(self.gemini_model_combo)
        gmr_layout.addStretch()

        self.mm_key = ApiKeyField("MiniMax API key...")
        self.mm_key.setText(cfg.get("minimax_api_key", ""))

        self.mm_group = ApiKeyField("MiniMax Group ID (optional, for .chat endpoint)...")
        self.mm_group.setText(cfg.get("minimax_group_id", ""))

        api_form.addRow("YouTube API Key:", self.yt_key)
        api_form.addRow("Claude API Key:", self.claude_key)
        api_form.addRow("Gemini API Key:", self.gemini_key)
        api_form.addRow("Gemini Model:", gemini_model_row)
        api_form.addRow("MiniMax API Key:", self.mm_key)
        api_form.addRow("MiniMax Group ID:", self.mm_group)

        help_lbl = QLabel(
            "👁 button shows/hides each key.  "
            "YouTube: console.cloud.google.com  |  "
            "Claude: console.anthropic.com  |  "
            "Gemini: aistudio.google.com/app/apikey  |  "
            "MiniMax: platform.minimax.io"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color:#9090aa; font-size:11px;")
        api_form.addRow("", help_lbl)
        main.addWidget(api_group)

        # ── Default folders ───────────────────────────────────────────────
        folder_group = QGroupBox("Default folders")
        folder_form = QFormLayout(folder_group)
        folder_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        folder_form.setSpacing(12)
        folder_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.output_folder = self._folder_row(
            cfg.get("output_folder", ""),
            folder_form, "Output folder (finished videos):"
        )
        self.source_folder = self._folder_row(
            cfg.get("source_videos_folder", ""),
            folder_form, "Source videos folder:"
        )
        main.addWidget(folder_group)

        # ── Save ─────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save settings")
        save_btn.setFixedWidth(160)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        main.addLayout(btn_row)

        self._status = StatusBar()
        main.addWidget(self._status)
        main.addStretch()

        # Highlight active provider
        self._on_provider_changed()

    # ── Helpers ───────────────────────────────────────────────────────────
    def _on_provider_changed(self):
        is_gemini = self.provider_combo.currentData() == "gemini"
        # Visually highlight the active provider section
        dim   = "color:#9090aa;"
        bright = "color:#e8e8f0;"
        self.claude_key._field.setStyleSheet(
            "" if not is_gemini else "color:#9090aa;"
        )
        self.gemini_key._field.setStyleSheet(
            "" if is_gemini else "color:#9090aa;"
        )

    def _folder_row(self, value: str, form: QFormLayout, label: str) -> QLineEdit:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(value)
        field.setPlaceholderText("Select folder...")
        btn = QPushButton("Browse")
        btn.setObjectName("secondary")
        btn.setFixedWidth(70)
        btn.clicked.connect(lambda: self._browse(field))
        layout.addWidget(field)
        layout.addWidget(btn)
        form.addRow(label, row)
        return field

    def _browse(self, field: QLineEdit):
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder", field.text()
        )
        if folder:
            field.setText(folder)

    def _save(self):
        cfg = load_config()
        cfg["youtube_api_key"]      = self.yt_key.text().strip()
        cfg["anthropic_api_key"]    = self.claude_key.text().strip()
        cfg["gemini_api_key"]       = self.gemini_key.text().strip()
        cfg["gemini_model"]         = self.gemini_model_combo.currentData()
        cfg["ai_provider"]          = self.provider_combo.currentData()
        cfg["minimax_api_key"]      = self.mm_key.text().strip()
        cfg["minimax_group_id"]     = self.mm_group.text().strip()
        cfg["output_folder"]        = self.output_folder.text().strip()
        cfg["source_videos_folder"] = self.source_folder.text().strip()
        save_config(cfg)
        self._status.set_ok("Settings saved!")

    def get_config(self) -> dict:
        return load_config()
