"""Infographic generator — renders visually rich matplotlib infographics from script text.

Layouts (randomly selected per clip):
  facts      — Colored cards on white background
  stats      — Large key-stat display with supporting facts
  timeline   — Horizontal timeline of events
  comparison — Two-column split comparison
  bars       — Horizontal bar chart style
  quote      — Large bold quote/highlight

Pipeline:
  script text → Gemini extraction → InfographicData
  → matplotlib render → PNG → FFmpeg → video clip (5-8 s)
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

try:
    from app.utils.logger import log
except Exception:
    log = None

# ── Windows: suppress console popups ─────────────────────────────────────────
_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# ── Color palettes ────────────────────────────────────────────────────────────
ACCENT_COLORS = [
    "#2196F3",  # Blue
    "#4CAF50",  # Green
    "#FF9800",  # Orange
    "#9C27B0",  # Purple
    "#F44336",  # Red
    "#00BCD4",  # Cyan
    "#FF5722",  # Deep Orange
    "#3F51B5",  # Indigo
    "#009688",  # Teal
    "#E91E63",  # Pink
]

# Light background colors paired with dark text
_BG_OPTIONS = [
    ("#FFFFFF", "#1a1a2e"),   # pure white
    ("#F5F5F5", "#1a1a2e"),   # light gray
    ("#FFF8E1", "#1a1a2e"),   # warm cream
    ("#E8F5E9", "#1a1a2e"),   # mint
    ("#E3F2FD", "#1a1a2e"),   # sky blue
    ("#F3E5F5", "#1a1a2e"),   # lavender
    ("#FBE9E7", "#1a1a2e"),   # peach
]

LAYOUTS = ["facts", "stats", "timeline", "comparison", "bars", "quote"]


# ── Data structure ────────────────────────────────────────────────────────────
@dataclass
class InfographicData:
    title: str
    bullets: list[str]
    key_stat: str = ""
    key_stat_label: str = ""
    accent_color: str = "#2196F3"
    bg_color: str = "#FFFFFF"
    text_color: str = "#1a1a2e"
    layout: str = "facts"


# ── Gemini extraction ─────────────────────────────────────────────────────────
def _extract_with_key(api_key: str, text: str, model_id: str = None) -> InfographicData:
    from app.api.gemini_client import _generate_with_sdk, DEFAULT_GEMINI_MODEL
    if model_id is None:
        model_id = DEFAULT_GEMINI_MODEL

    prompt = (
        "You are an infographic content designer. Analyze this script excerpt "
        "and extract data for a visual infographic.\n"
        "Return ONLY valid JSON (no markdown):\n"
        "{\n"
        '  "title": "short impactful title, max 50 chars",\n'
        '  "bullets": ["concise fact 1 (max 55 chars)", "fact 2", "fact 3"],\n'
        '  "key_stat": "single standout number/percentage/year or empty string",\n'
        '  "key_stat_label": "what this number means, max 30 chars, or empty",\n'
        '  "layout": "one of: facts | stats | timeline | comparison | bars | quote"\n'
        "}\n"
        "Layout guide:\n"
        "  facts — general key facts, any topic\n"
        "  stats — if there are notable numbers/percentages\n"
        "  timeline — if there is a sequence of events or history\n"
        "  comparison — if two things are being compared\n"
        "  bars — if there are ranked items or quantities\n"
        "  quote — if there is a powerful statement or revelation\n"
        "Bullets: 3 to 5, each max 55 chars, punchy and factual.\n"
        "Script excerpt:\n"
        f"{text[:800]}"
    )

    raw = _generate_with_sdk(api_key=api_key, model_id=model_id, user_prompt=prompt)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

    data = json.loads(raw)
    title = str(data.get("title", ""))[:55]
    bullets = [str(b)[:55] for b in data.get("bullets", []) if b][:5]
    key_stat = str(data.get("key_stat", ""))[:20]
    key_stat_label = str(data.get("key_stat_label", ""))[:35]
    layout = data.get("layout", "facts")
    if layout not in LAYOUTS:
        layout = "facts"
    if not bullets:
        raise ValueError("No bullets returned")

    accent = random.choice(ACCENT_COLORS)
    bg, tc = random.choice(_BG_OPTIONS)
    return InfographicData(
        title=title, bullets=bullets,
        key_stat=key_stat, key_stat_label=key_stat_label,
        accent_color=accent, bg_color=bg, text_color=tc,
        layout=layout,
    )


def _extract_from_text_simple(text: str) -> InfographicData:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    title = sentences[0][:50] if sentences else text[:50]
    remaining = " ".join(sentences[1:]) if len(sentences) > 1 else text
    words = remaining.split()
    bullets: list[str] = []
    chunk: list[str] = []
    for word in words:
        chunk.append(word)
        if len(" ".join(chunk)) >= 45:
            bullets.append(" ".join(chunk)[:55])
            chunk = []
        if len(bullets) >= 4:
            break
    if chunk and len(bullets) < 4:
        bullets.append(" ".join(chunk)[:55])
    if not bullets:
        bullets = [text[:55]]
    m = re.search(r'\d+[\.,]?\d*\s*%?', text)
    key_stat = m.group(0).strip() if m else ""
    accent = random.choice(ACCENT_COLORS)
    bg, tc = random.choice(_BG_OPTIONS)
    return InfographicData(
        title=title, bullets=bullets[:4],
        key_stat=key_stat,
        accent_color=accent, bg_color=bg, text_color=tc,
        layout=random.choice(LAYOUTS),
    )


def extract_infographic_data(text: str, cfg: dict) -> InfographicData:
    from app.api.gemini_client import _call_with_cascade, DEFAULT_GEMINI_MODEL
    try:
        return _call_with_cascade(_extract_with_key, cfg, text, model_id=DEFAULT_GEMINI_MODEL)
    except Exception as e:
        if log:
            log.warning(f"Gemini infographic extraction failed: {e}")
        return _extract_from_text_simple(text)


# ── Matplotlib helpers ────────────────────────────────────────────────────────
def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip() if line else w
        if len(test) <= max_chars:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [text[:max_chars]]


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def _darken(hex_color: str, factor: float = 0.7) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * factor * 255), int(g * factor * 255), int(b * factor * 255)
    )


def _alpha_color(hex_color: str, alpha: float = 0.15) -> tuple:
    r, g, b = _hex_to_rgb(hex_color)
    return (r, g, b, alpha)


# ── Layout renderers ──────────────────────────────────────────────────────────

def _render_facts(ax, fig, data: InfographicData, W: int, H: int):
    """Colored fact cards on white/light background."""
    import matplotlib.patches as mp

    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)
    acc = data.accent_color
    tc = data.text_color

    # Top accent header bar
    ax.add_patch(mp.FancyBboxPatch(
        (0, H - 140), W, 140,
        boxstyle="square,pad=0",
        facecolor=acc, edgecolor="none", zorder=2,
    ))
    # Title in header
    for i, line in enumerate(_wrap(data.title, 60)[:2]):
        ax.text(W / 2, H - 45 - i * 52, line,
                ha="center", va="center", fontsize=38, fontweight="bold",
                color="white", zorder=3)

    # Cards
    bullets = data.bullets[:4]
    n = len(bullets)
    pad = 40
    gap = 20
    card_w = (W - pad * 2 - gap * (n - 1)) / n
    card_h = H - 140 - 80 - pad
    card_y = pad

    for i, bullet in enumerate(bullets):
        cx = pad + i * (card_w + gap)

        # Card shadow (offset)
        ax.add_patch(mp.FancyBboxPatch(
            (cx + 4, card_y - 4), card_w, card_h,
            boxstyle="round,pad=10",
            facecolor=_alpha_color(acc, 0.18), edgecolor="none", zorder=2,
        ))
        # Card body
        ax.add_patch(mp.FancyBboxPatch(
            (cx, card_y), card_w, card_h,
            boxstyle="round,pad=10",
            facecolor="white", edgecolor=acc, linewidth=2.5, zorder=3,
        ))
        # Number badge circle
        badge_cx = cx + 52
        badge_cy = card_y + card_h - 52
        ax.add_patch(mp.Circle((badge_cx, badge_cy), 36, color=acc, zorder=4))
        ax.text(badge_cx, badge_cy, str(i + 1),
                ha="center", va="center", fontsize=26, fontweight="bold",
                color="white", zorder=5)

        # Bullet text (wrapped)
        lines = _wrap(bullet, 22)
        text_y = card_y + card_h / 2 + (len(lines) - 1) * 20
        for j, ln in enumerate(lines[:4]):
            ax.text(cx + card_w / 2, text_y - j * 38, ln,
                    ha="center", va="center", fontsize=22, color=tc,
                    fontweight="bold" if j == 0 else "normal", zorder=4)

        # Bottom accent line
        ax.plot([cx + 20, cx + card_w - 20], [card_y + 18, card_y + 18],
                color=acc, linewidth=3, alpha=0.4, zorder=4)


def _render_stats(ax, fig, data: InfographicData, W: int, H: int):
    """Large key-stat in center, facts arranged around it."""
    import matplotlib.patches as mp

    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)
    acc = data.accent_color
    tc = data.text_color

    # Background circle behind stat
    ax.add_patch(mp.Circle((W / 2, H / 2 + 30), 210,
                            color=_alpha_color(acc, 0.12), zorder=1))
    ax.add_patch(mp.Circle((W / 2, H / 2 + 30), 175,
                            color=_alpha_color(acc, 0.1), zorder=1))

    # Title at top
    ax.text(W / 2, H - 60, data.title,
            ha="center", va="center", fontsize=34, fontweight="bold",
            color=tc, zorder=3)
    ax.plot([W * 0.2, W * 0.8], [H - 90, H - 90],
            color=acc, linewidth=3, alpha=0.5, zorder=2)

    # Big stat
    stat_text = data.key_stat if data.key_stat else (data.bullets[0][:12] if data.bullets else "")
    ax.text(W / 2, H / 2 + 70, stat_text,
            ha="center", va="center", fontsize=110, fontweight="bold",
            color=acc, zorder=3)
    if data.key_stat_label:
        ax.text(W / 2, H / 2 - 90, data.key_stat_label.upper(),
                ha="center", va="center", fontsize=22, color=tc,
                fontweight="bold", alpha=0.7, zorder=3,
                letterspacing=3)

    # Supporting bullets in bottom strip
    bullets = data.bullets[1:] if data.key_stat else data.bullets
    bullets = bullets[:3]
    if bullets:
        strip_h = 130
        ax.add_patch(mp.FancyBboxPatch(
            (0, 0), W, strip_h,
            boxstyle="square,pad=0",
            facecolor=acc, edgecolor="none", zorder=2,
        ))
        seg_w = W / len(bullets)
        for i, b in enumerate(bullets):
            bx = seg_w * i + seg_w / 2
            ax.text(bx, strip_h / 2, b[:50],
                    ha="center", va="center", fontsize=21,
                    color="white", fontweight="bold", zorder=3)
            if i > 0:
                ax.plot([seg_w * i, seg_w * i], [10, strip_h - 10],
                        color="white", linewidth=1, alpha=0.4, zorder=3)


def _render_timeline(ax, fig, data: InfographicData, W: int, H: int):
    """Horizontal timeline with labeled events."""
    import matplotlib.patches as mp

    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)
    acc = data.accent_color
    tc = data.text_color

    # Title
    ax.text(W / 2, H - 55, data.title,
            ha="center", va="center", fontsize=36, fontweight="bold", color=tc)
    ax.plot([60, W - 60], [H - 90, H - 90], color=acc, linewidth=2, alpha=0.3)

    bullets = data.bullets[:5]
    n = len(bullets)
    line_y = H / 2
    margin = 130
    step = (W - margin * 2) / max(n - 1, 1) if n > 1 else 0

    # Timeline line
    ax.plot([margin, W - margin], [line_y, line_y],
            color=acc, linewidth=5, solid_capstyle="round", zorder=2)

    for i, bullet in enumerate(bullets):
        x = margin + i * step if n > 1 else W / 2
        above = (i % 2 == 0)
        dot_y = line_y

        # Dot
        ax.add_patch(mp.Circle((x, dot_y), 22, color=acc, zorder=4))
        ax.add_patch(mp.Circle((x, dot_y), 12, color="white", zorder=5))

        # Connector line
        text_y = dot_y + 140 if above else dot_y - 140
        ax.plot([x, x], [dot_y + 22, text_y - 10 if above else text_y + 10],
                color=acc, linewidth=2, alpha=0.5, zorder=3)

        # Label box
        lines = _wrap(bullet, 20)
        box_h = 40 + len(lines) * 32
        box_w = 220
        bx = max(10, min(x - box_w / 2, W - box_w - 10))
        by = text_y - box_h / 2
        ax.add_patch(mp.FancyBboxPatch(
            (bx, by), box_w, box_h,
            boxstyle="round,pad=8",
            facecolor=_alpha_color(acc, 0.12),
            edgecolor=acc, linewidth=2, zorder=3,
        ))
        for j, ln in enumerate(lines[:3]):
            ax.text(bx + box_w / 2, by + box_h - 22 - j * 32, ln,
                    ha="center", va="center", fontsize=18, color=tc,
                    fontweight="bold" if j == 0 else "normal", zorder=4)

    # Key stat
    if data.key_stat:
        ax.text(W - 80, 60, data.key_stat,
                ha="right", va="center", fontsize=52, fontweight="bold",
                color=acc, alpha=0.85)


def _render_comparison(ax, fig, data: InfographicData, W: int, H: int):
    """Split left/right comparison layout."""
    import matplotlib.patches as mp

    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)
    acc = data.accent_color
    tc = data.text_color
    dark_acc = _darken(acc, 0.75)

    half = W // 2

    # Left panel (accent color bg)
    ax.add_patch(mp.FancyBboxPatch(
        (0, 0), half - 4, H,
        boxstyle="square,pad=0",
        facecolor=acc, edgecolor="none", zorder=1,
    ))
    # Right panel stays bg color
    # Center divider
    ax.add_patch(mp.FancyBboxPatch(
        (half - 4, 0), 8, H,
        boxstyle="square,pad=0",
        facecolor="white", edgecolor="none", zorder=2,
    ))

    # Title centered over both
    ax.text(W / 2, H - 50, data.title,
            ha="center", va="center", fontsize=32, fontweight="bold",
            color="white", zorder=3,
            bbox=dict(boxstyle="round,pad=8", facecolor=dark_acc, edgecolor="none"))

    bullets = data.bullets
    left_bullets = bullets[:len(bullets) // 2 + len(bullets) % 2]
    right_bullets = bullets[len(bullets) // 2 + len(bullets) % 2:]
    if not right_bullets:
        right_bullets = left_bullets[1:]
        left_bullets = left_bullets[:1]

    def draw_bullets(items, x_center, text_color, start_y):
        for i, b in enumerate(items[:3]):
            by = start_y - i * 150
            ax.add_patch(mp.Circle((x_center - 80, by), 20, color=text_color, alpha=0.3, zorder=3))
            ax.text(x_center - 80, by, "•",
                    ha="center", va="center", fontsize=26, color=text_color, zorder=4)
            for j, ln in enumerate(_wrap(b, 22)[:2]):
                ax.text(x_center - 50, by + 10 - j * 30, ln,
                        ha="left", va="center", fontsize=22,
                        color=text_color, fontweight="bold" if j == 0 else "normal", zorder=4)

    draw_bullets(left_bullets, half // 2 + 40, "white", H - 160)
    draw_bullets(right_bullets, half + half // 2 - 40, tc, H - 160)


def _render_bars(ax, fig, data: InfographicData, W: int, H: int):
    """Horizontal bar chart with ranked items."""
    import matplotlib.patches as mp

    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)
    acc = data.accent_color
    tc = data.text_color

    # Title
    ax.add_patch(mp.FancyBboxPatch(
        (0, H - 120), W, 120,
        boxstyle="square,pad=0",
        facecolor=acc, edgecolor="none", zorder=2,
    ))
    ax.text(W / 2, H - 55, data.title,
            ha="center", va="center", fontsize=36, fontweight="bold",
            color="white", zorder=3)

    bullets = data.bullets[:5]
    n = len(bullets)
    bar_area_h = H - 140 - 60
    row_h = bar_area_h / n
    label_w = 420
    bar_max_w = W - label_w - 80

    # Assign random bar widths (descending, largest first)
    widths = sorted([random.uniform(0.45, 1.0) for _ in bullets], reverse=True)

    for i, (bullet, w) in enumerate(zip(bullets, widths)):
        by = H - 140 - (i + 0.5) * row_h
        bar_w = bar_max_w * w
        alpha_fill = 0.85 - i * 0.1

        # Bar background track
        ax.add_patch(mp.FancyBboxPatch(
            (label_w, by - 24), bar_max_w, 48,
            boxstyle="round,pad=4",
            facecolor=_alpha_color(acc, 0.1), edgecolor="none", zorder=2,
        ))
        # Bar fill
        ax.add_patch(mp.FancyBboxPatch(
            (label_w, by - 24), max(bar_w, 40), 48,
            boxstyle="round,pad=4",
            facecolor=acc, edgecolor="none", alpha=alpha_fill, zorder=3,
        ))
        # Label
        ax.text(label_w - 20, by, bullet[:38],
                ha="right", va="center", fontsize=21, color=tc, fontweight="bold")
        # Rank number
        ax.add_patch(mp.Circle((50, by), 28, color=acc, zorder=4))
        ax.text(50, by, str(i + 1),
                ha="center", va="center", fontsize=22, fontweight="bold",
                color="white", zorder=5)

    # Key stat
    if data.key_stat:
        ax.text(W - 50, 40, data.key_stat,
                ha="right", va="center", fontsize=42, fontweight="bold",
                color=acc, alpha=0.9)


def _render_quote(ax, fig, data: InfographicData, W: int, H: int):
    """Large bold quote/statement with decorative elements."""
    import matplotlib.patches as mp

    acc = data.accent_color
    bg, tc = random.choice([
        (acc, "white"),                            # accent bg, white text
        ("#FFFFFF", data.text_color),              # white bg, dark text
        (_darken(acc, 0.6), "white"),              # dark accent bg
    ])

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    # Large decorative quotation marks
    ax.text(80, H - 80, "\u201C",
            fontsize=220, color=acc, alpha=0.25, va="top", ha="left",
            fontweight="bold")
    ax.text(W - 80, 80, "\u201D",
            fontsize=220, color=acc, alpha=0.25, va="bottom", ha="right",
            fontweight="bold")

    # Main quote text (title = the powerful statement)
    lines = _wrap(data.title, 38)
    total_h = len(lines) * 70
    start_y = H / 2 + total_h / 2
    for i, ln in enumerate(lines[:3]):
        ax.text(W / 2, start_y - i * 70, ln,
                ha="center", va="center", fontsize=46, fontweight="bold",
                color=tc, zorder=3)

    # Accent divider
    ax.plot([W * 0.3, W * 0.7], [H / 2 - total_h / 2 - 40, H / 2 - total_h / 2 - 40],
            color=acc, linewidth=5, solid_capstyle="round", zorder=2)

    # Supporting facts below
    facts = data.bullets[:3]
    fact_y = H / 2 - total_h / 2 - 90
    for i, f in enumerate(facts):
        ax.text(W / 2, fact_y - i * 55, f"• {f[:60]}",
                ha="center", va="center", fontsize=22,
                color=tc, alpha=0.8, zorder=3)

    # Key stat badge
    if data.key_stat:
        ax.add_patch(mp.FancyBboxPatch(
            (W - 250, H - 120), 210, 90,
            boxstyle="round,pad=8",
            facecolor=acc, edgecolor="none", zorder=4,
        ))
        ax.text(W - 145, H - 75, data.key_stat,
                ha="center", va="center", fontsize=34, fontweight="bold",
                color="white", zorder=5)


# ── Main render dispatcher ────────────────────────────────────────────────────

def render_infographic(
    data: InfographicData,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise RuntimeError("Install matplotlib: pip install matplotlib")

    plt.rcParams["font.family"] = "DejaVu Sans"

    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    dispatch = {
        "facts":      _render_facts,
        "stats":      _render_stats,
        "timeline":   _render_timeline,
        "comparison": _render_comparison,
        "bars":       _render_bars,
        "quote":      _render_quote,
    }
    fn = dispatch.get(data.layout, _render_facts)
    fn(ax, fig, data, width, height)

    plt.savefig(
        output_path, dpi=dpi, bbox_inches="tight",
        pad_inches=0, facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return output_path


# ── FFmpeg clip creation ──────────────────────────────────────────────────────

def create_infographic_clip(
    image_path: str,
    output_path: str,
    duration: float,
    fps: int,
    ffmpeg_path: str = "ffmpeg",
    width: int = 1920,
    height: int = 1080,
) -> str:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps}"
    )
    cmd = [
        ffmpeg_path, "-y", "-hide_banner",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-video_track_timescale", "90000",
        "-an",
        output_path,
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, **_POPEN_FLAGS,
    )
    if result.returncode != 0:
        lines = result.stderr.splitlines()
        raise RuntimeError(f"FFmpeg infographic clip error:\n{chr(10).join(lines[-30:])}")
    return output_path


# ── Script text helpers ───────────────────────────────────────────────────────

def get_text_at_time(
    script: str,
    timestamp: float,
    audio_duration: float,
    context_chars: int = 600,
) -> str:
    if not script:
        return ""
    if audio_duration <= 0:
        audio_duration = 1.0
    fraction = max(0.0, min(1.0, timestamp / audio_duration))
    center = int(fraction * len(script))
    start = max(0, center - context_chars // 2)
    end = center + context_chars // 2
    snippet = script[start:end]
    if start > 0 and " " in snippet:
        snippet = snippet[snippet.find(" "):].lstrip()
    if end < len(script) and " " in snippet:
        snippet = snippet[:snippet.rfind(" ")]
    return snippet.strip()


# ── Position planner ──────────────────────────────────────────────────────────

def plan_infographic_positions(n_clips: int, min_gap: int = 5, max_gap: int = 15) -> list[int]:
    positions: list[int] = []
    current = random.randint(min_gap, max_gap)
    while current < n_clips - 2:
        positions.append(current)
        current += random.randint(min_gap, max_gap)
    return positions


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_infographic_clip(
    script: str,
    timestamp: float,
    audio_duration: float,
    output_path: str,
    cfg: dict,
    duration: float,
    fps: int,
    width: int,
    height: int,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    text = get_text_at_time(script, timestamp, audio_duration)
    if not text:
        text = script[:600]

    try:
        data = extract_infographic_data(text, cfg)
    except Exception as e:
        if log:
            log.warning(f"extract_infographic_data failed: {e}")
        data = _extract_from_text_simple(text)

    # Always randomize colors per clip for visual variety
    data.accent_color = random.choice(ACCENT_COLORS)
    data.bg_color, data.text_color = random.choice(_BG_OPTIONS)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png_path = tmp.name

    try:
        render_infographic(data, png_path, width=width, height=height)
        if log:
            log.info(f"Infographic rendered: layout={data.layout}, bg={data.bg_color}, accent={data.accent_color}")
        create_infographic_clip(
            image_path=png_path, output_path=output_path,
            duration=duration, fps=fps,
            ffmpeg_path=ffmpeg_path, width=width, height=height,
        )
    finally:
        try:
            os.unlink(png_path)
        except OSError:
            pass

    return output_path
