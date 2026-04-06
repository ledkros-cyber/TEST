"""Settings tab — API keys and folder defaults."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout,
    QScrollArea, QFrame,
)

from app.config_manager import load_config, save_config
from app.api.gemini_client import GEMINI_MODELS, DEFAULT_GEMINI_MODEL, MAX_GEMINI_KEYS
from app.ui.widgets import ApiKeyField, SectionHeader, StatusBar


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._gemini_key_fields: list[ApiKeyField] = []
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

        api_form.addRow("YouTube API Key:", self.yt_key)
        api_form.addRow("Claude API Key:", self.claude_key)

        # ── Gemini multi-key section ──────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#3a3b55;")
        api_form.addRow(sep)

        gemini_hdr = QHBoxLayout()
        gemini_hdr.addWidget(QLabel("<b>Gemini API Keys</b> (up to 10 accounts — rotated on quota):"))
        gemini_hdr.addStretch()
        self._add_gemini_btn = QPushButton("+ Add key")
        self._add_gemini_btn.setObjectName("secondary")
        self._add_gemini_btn.setFixedWidth(80)
        self._add_gemini_btn.clicked.connect(self._add_gemini_key_field)
        gemini_hdr.addWidget(self._add_gemini_btn)
        hdr_widget = QWidget()
        hdr_widget.setLayout(gemini_hdr)
        api_form.addRow(hdr_widget)

        # Container for dynamic key rows
        self._gemini_keys_widget = QWidget()
        self._gemini_keys_layout = QVBoxLayout(self._gemini_keys_widget)
        self._gemini_keys_layout.setContentsMargins(0, 0, 0, 0)
        self._gemini_keys_layout.setSpacing(4)
        api_form.addRow(self._gemini_keys_widget)

        # Populate from config
        saved_keys = cfg.get("gemini_api_keys", [])
        # If no list but old single key exists, seed from it
        if not saved_keys:
            single = cfg.get("gemini_api_key", "")
            if single:
                saved_keys = [single]
        if not saved_keys:
            saved_keys = [""]   # at least one empty row
        for key_val in saved_keys:
            self._add_gemini_key_field(value=key_val)

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
        api_form.addRow("Gemini Model:", gemini_model_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#3a3b55;")
        api_form.addRow(sep2)

        self.mm_key = ApiKeyField("MiniMax API key...")
        self.mm_key.setText(cfg.get("minimax_api_key", ""))

        self.mm_group = ApiKeyField("MiniMax Group ID (optional, for .chat endpoint)...")
        self.mm_group.setText(cfg.get("minimax_group_id", ""))

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

    # ── Gemini multi-key helpers ──────────────────────────────────────────
    def _add_gemini_key_field(self, checked=False, value: str = ""):
        if len(self._gemini_key_fields) >= MAX_GEMINI_KEYS:
            self._status.set_error(f"Maximum {MAX_GEMINI_KEYS} Gemini keys allowed.")
            return

        idx = len(self._gemini_key_fields) + 1
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        lbl = QLabel(f"Key {idx}:")
        lbl.setFixedWidth(50)
        row_layout.addWidget(lbl)

        field = ApiKeyField(f"Gemini API key {idx}...")
        field.setText(value)
        row_layout.addWidget(field, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setObjectName("secondary")
        remove_btn.setFixedWidth(28)
        remove_btn.setFixedHeight(28)
        remove_btn.setToolTip("Remove this key")
        remove_btn.clicked.connect(lambda: self._remove_gemini_key_row(row_widget, field))
        row_layout.addWidget(remove_btn)

        self._gemini_keys_layout.addWidget(row_widget)
        self._gemini_key_fields.append(field)
        self._update_add_btn_state()

    def _remove_gemini_key_row(self, row_widget: QWidget, field: ApiKeyField):
        if len(self._gemini_key_fields) <= 1:
            # Keep at least one row, just clear it
            field.setText("")
            return
        if field in self._gemini_key_fields:
            self._gemini_key_fields.remove(field)
        row_widget.setParent(None)
        row_widget.deleteLater()
        # Renumber labels
        for i, f in enumerate(self._gemini_key_fields):
            parent = f.parent()
            if parent:
                labels = parent.findChildren(QLabel)
                if labels:
                    labels[0].setText(f"Key {i + 1}:")
        self._update_add_btn_state()

    def _update_add_btn_state(self):
        self._add_gemini_btn.setEnabled(
            len(self._gemini_key_fields) < MAX_GEMINI_KEYS
        )

    # ── Helpers ───────────────────────────────────────────────────────────
    def _on_provider_changed(self):
        is_gemini = self.provider_combo.currentData() == "gemini"
        self.claude_key._field.setStyleSheet(
            "" if not is_gemini else "color:#9090aa;"
        )

    def _save(self):
        cfg = load_config()
        cfg["youtube_api_key"]      = self.yt_key.text().strip()
        cfg["anthropic_api_key"]    = self.claude_key.text().strip()
        cfg["gemini_model"]         = self.gemini_model_combo.currentData()
        cfg["ai_provider"]          = self.provider_combo.currentData()
        cfg["minimax_api_key"]      = self.mm_key.text().strip()
        cfg["minimax_group_id"]     = self.mm_group.text().strip()
        # Save multi-key Gemini list (filter empty entries)
        keys = [f.text().strip() for f in self._gemini_key_fields if f.text().strip()]
        cfg["gemini_api_keys"] = keys
        # Keep legacy single-key field in sync (first key)
        cfg["gemini_api_key"] = keys[0] if keys else ""
        # Reset rotation index if keys changed
        cfg["gemini_key_index"] = 0

        save_config(cfg)
        self._status.set_ok(f"Settings saved! ({len(keys)} Gemini key(s) stored)")

    def get_config(self) -> dict:
        return load_config()
