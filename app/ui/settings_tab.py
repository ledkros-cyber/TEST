"""Settings tab — API keys and folder defaults ONLY.
Audio/video settings live in their own tabs.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QFormLayout, QFileDialog,
    QScrollArea, QLineEdit,
)

from app.config_manager import load_config, save_config
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

        # ── API Keys ──────────────────────────────────────────────────────
        api_group = QGroupBox("API Keys")
        api_form = QFormLayout(api_group)
        api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        api_form.setSpacing(12)
        api_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        cfg = load_config()

        self.yt_key = ApiKeyField("YouTube Data API v3 key...")
        self.yt_key.setText(cfg.get("youtube_api_key", ""))

        self.claude_key = ApiKeyField("Anthropic / Claude API key...")
        self.claude_key.setText(cfg.get("anthropic_api_key", ""))

        self.mm_key = ApiKeyField("MiniMax API key...")
        self.mm_key.setText(cfg.get("minimax_api_key", ""))

        self.mm_group = ApiKeyField("MiniMax Group ID...")
        self.mm_group.setText(cfg.get("minimax_group_id", ""))

        api_form.addRow("YouTube API Key:", self.yt_key)
        api_form.addRow("Anthropic (Claude) Key:", self.claude_key)
        api_form.addRow("MiniMax API Key:", self.mm_key)
        api_form.addRow("MiniMax Group ID:", self.mm_group)

        # Help text
        help_lbl = QLabel(
            "Click 👁 to show/hide each key.  "
            "Get keys at: console.cloud.google.com  |  "
            "console.anthropic.com  |  minimax.io"
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
        folder_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.output_folder = self._folder_row(
            cfg.get("output_folder", ""), folder_form, "Output folder (finished videos):"
        )
        self.source_folder = self._folder_row(
            cfg.get("source_videos_folder", ""), folder_form, "Source videos folder:"
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
        folder = QFileDialog.getExistingDirectory(self, "Select folder", field.text())
        if folder:
            field.setText(folder)

    def _save(self):
        cfg = load_config()
        cfg["youtube_api_key"]      = self.yt_key.text().strip()
        cfg["anthropic_api_key"]    = self.claude_key.text().strip()
        cfg["minimax_api_key"]      = self.mm_key.text().strip()
        cfg["minimax_group_id"]     = self.mm_group.text().strip()
        cfg["output_folder"]        = self.output_folder.text().strip()
        cfg["source_videos_folder"] = self.source_folder.text().strip()
        save_config(cfg)
        self._status.set_ok("Settings saved!")

    def get_config(self) -> dict:
        return load_config()
