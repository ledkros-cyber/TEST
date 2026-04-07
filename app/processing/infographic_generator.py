"""Infographic generator — renders matplotlib infographics from script text segments.

Pipeline:
  script text segment → Gemini extraction → InfographicData
  InfographicData → matplotlib render → PNG image → FFmpeg → video clip (5-8s)
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


# ─────────────────────────────────────────────────────────────────────────────
# Windows: suppress black console popup windows for every subprocess call
# ─────────────────────────────────────────────────────────────────────────────

_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

ACCENT_COLORS = [
    "#4c9be8", "#4caf81", "#e8964c", "#9b4ce8",
    "#e84c4c", "#4ce8d8", "#e8d84c", "#e84c9b",
]


@dataclass
class InfographicData:
    title: str                       # short title (max 60 chars)
    bullets: list[str]               # 3-5 key facts (max 70 chars each)
    key_stat: str = ""               # optional big highlighted number/stat (e.g. "21 miles", "40%")
    accent_color: str = "#4c9be8"   # hex color
    layout: str = "list"             # "list" | "highlight" | "split"


# ─────────────────────────────────────────────────────────────────────────────
# Gemini extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_with_key(api_key: str, text: str, model_id: str = None) -> InfographicData:
    """Call Gemini with a specific key to extract infographic data."""
    from app.api.gemini_client import _generate_with_sdk, DEFAULT_GEMINI_MODEL

    if model_id is None:
        model_id = DEFAULT_GEMINI_MODEL

    prompt = (
        "Analyze this script excerpt and extract key information for an infographic.\n"
        "Return ONLY valid JSON (no markdown, no code block):\n"
        "{\n"
        '  "title": "short impactful title under 55 chars",\n'
        '  "bullets": ["key fact 1 (under 65 chars)", "key fact 2", "key fact 3"],\n'
        '  "key_stat": "optional single standout number or statistic, empty string if none"\n'
        "}\n"
        "Keep it concise. Bullets should be facts/insights a viewer would want to remember.\n"
        "Script excerpt:\n"
        f"{text}"
    )

    raw = _generate_with_sdk(
        api_key=api_key,
        model_id=model_id,
        user_prompt=prompt,
    )

    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

    data = json.loads(raw)

    title = str(data.get("title", ""))[:60]
    bullets_raw = data.get("bullets", [])
    bullets = [str(b)[:70] for b in bullets_raw if b][:5]
    key_stat = str(data.get("key_stat", ""))

    if not bullets:
        raise ValueError("No bullets returned by Gemini")

    return InfographicData(
        title=title,
        bullets=bullets,
        key_stat=key_stat,
    )


def _extract_from_text_simple(text: str) -> InfographicData:
    """Simple fallback — no AI required."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    # Title: first sentence, truncated to 55 chars
    title = sentences[0][:55] if sentences else text[:55]

    # Bullets: split remaining text into 3-4 chunks of ~65 chars each
    remaining = " ".join(sentences[1:]) if len(sentences) > 1 else text
    words = remaining.split()
    bullets: list[str] = []
    chunk: list[str] = []
    for word in words:
        chunk.append(word)
        line = " ".join(chunk)
        if len(line) >= 60:
            bullets.append(line[:65])
            chunk = []
        if len(bullets) >= 4:
            break
    if chunk and len(bullets) < 4:
        bullets.append(" ".join(chunk)[:65])
    # Ensure at least 1 bullet
    if not bullets:
        bullets = [text[:65]]

    # key_stat: first number found in text
    m = re.search(r'\d+[\.,]?\d*\s*\w*', text)
    key_stat = m.group(0).strip() if m else ""

    return InfographicData(
        title=title,
        bullets=bullets[:4],
        key_stat=key_stat,
        accent_color=random.choice(ACCENT_COLORS),
        layout=random.choice(["list", "highlight", "split"]),
    )


def extract_infographic_data(text: str, cfg: dict) -> InfographicData:
    """Extract infographic data using Gemini, falling back to simple extraction."""
    from app.api.gemini_client import get_active_keys, _call_with_cascade, DEFAULT_GEMINI_MODEL

    try:
        result = _call_with_cascade(
            _extract_with_key, cfg, text,
            model_id=DEFAULT_GEMINI_MODEL,
        )
        return result
    except Exception as e:
        if log:
            log.warning(f"Gemini infographic extraction failed, using fallback: {e}")
        return _extract_from_text_simple(text)


# ─────────────────────────────────────────────────────────────────────────────
# Matplotlib renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_infographic(
    data: InfographicData,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Render InfographicData to a PNG image using matplotlib. Returns output_path."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        raise RuntimeError("Install matplotlib: pip install matplotlib")

    plt.rcParams["font.family"] = "DejaVu Sans"

    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor("#0d0d1a")
    ax.set_facecolor("#0d0d1a")
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    accent = data.accent_color
    layout = data.layout

    # ── Decorative border ────────────────────────────────────────────────────
    border = mpatches.Rectangle(
        (4, 4), width - 8, height - 8,
        linewidth=2, edgecolor=accent, facecolor="none", alpha=0.3,
    )
    ax.add_patch(border)

    # ── Corner accent circles ─────────────────────────────────────────────────
    corner_r = 40
    for cx, cy in [(0, 0), (width, 0), (0, height), (width, height)]:
        circle = plt.Circle((cx, cy), corner_r, color=accent, alpha=0.15)
        ax.add_patch(circle)

    # ── Layout rendering ──────────────────────────────────────────────────────
    if layout == "highlight" and data.key_stat:
        _render_highlight(ax, data, width, height, accent)
    elif layout == "split":
        _render_split(ax, data, width, height, accent)
    else:
        _render_list(ax, data, width, height, accent)

    plt.tight_layout(pad=0)
    plt.savefig(
        output_path, dpi=dpi, bbox_inches="tight",
        pad_inches=0, facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return output_path


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Simple word-wrap: split text into lines of at most max_chars."""
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        test = (line + " " + word).strip() if line else word
        if len(test) <= max_chars:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [text]


def _render_list(ax, data: InfographicData, width: int, height: int, accent: str):
    """Layout 'list': left accent bar, title, bullet list, optional key stat."""
    import matplotlib.patches as mpatches

    # Left accent bar
    bar = mpatches.Rectangle(
        (60, 80), 8, height - 160,
        linewidth=0, facecolor=accent,
    )
    ax.add_patch(bar)

    # Title
    title_lines = _wrap_text(data.title, 45)
    title_y = height - 100
    for i, tl in enumerate(title_lines[:2]):
        ax.text(
            100, title_y - i * 50, tl,
            color="white", fontsize=38, fontweight="bold",
            va="top", ha="left",
        )

    # Bullets
    bullet_start_y = height - 200 - max(0, len(title_lines) - 1) * 50
    for i, bullet in enumerate(data.bullets[:5]):
        by = bullet_start_y - i * 110
        if by < 100:
            break
        # Bullet circle
        circle = __import__("matplotlib").pyplot.Circle(
            (130, by - 12), 10, color=accent,
        )
        ax.add_patch(circle)
        # Bullet text
        ax.text(
            160, by - 2, bullet[:70],
            color="#d0d0e8", fontsize=26,
            va="top", ha="left",
        )

    # Key stat
    if data.key_stat:
        ax.text(
            width - 80, 120, data.key_stat,
            color=accent, fontsize=72, fontweight="bold",
            va="bottom", ha="right", alpha=0.9,
        )


def _render_highlight(ax, data: InfographicData, width: int, height: int, accent: str):
    """Layout 'highlight': big key_stat on left, title+bullets on right."""
    import matplotlib.patches as mpatches

    if not data.key_stat:
        _render_list(ax, data, width, height, accent)
        return

    half = width // 2

    # Divider line
    ax.plot([half, half], [80, height - 80], color=accent, alpha=0.3, linewidth=1.5)

    # Key stat — huge, centered in left half
    ax.text(
        half // 2, height // 2, data.key_stat,
        color=accent, fontsize=120, fontweight="bold",
        va="center", ha="center",
    )

    # Right half: title + bullets
    right_x = half + 60
    title_lines = _wrap_text(data.title, 35)
    title_y = height - 120
    for i, tl in enumerate(title_lines[:2]):
        ax.text(
            right_x, title_y - i * 50, tl,
            color="white", fontsize=34, fontweight="bold",
            va="top", ha="left",
        )

    bullet_start_y = title_y - max(1, len(title_lines)) * 50 - 60
    for i, bullet in enumerate(data.bullets[:4]):
        by = bullet_start_y - i * 100
        if by < 80:
            break
        circle = __import__("matplotlib").pyplot.Circle(
            (right_x + 18, by - 10), 9, color=accent,
        )
        ax.add_patch(circle)
        ax.text(
            right_x + 40, by - 2, bullet[:55],
            color="#d0d0e8", fontsize=24,
            va="top", ha="left",
        )


def _render_split(ax, data: InfographicData, width: int, height: int, accent: str):
    """Layout 'split': title top-center, 2-column bullet grid, top accent bar."""
    import matplotlib.patches as mpatches

    # Top accent bar
    bar = mpatches.Rectangle(
        (0, height - 10), width, 10,
        linewidth=0, facecolor=accent,
    )
    ax.add_patch(bar)

    # Title
    ax.text(
        width // 2, height - 80, data.title[:60],
        color="white", fontsize=42, fontweight="bold",
        va="top", ha="center",
    )

    # 2-column grid
    col_x = [120, width // 2 + 60]
    bullets = data.bullets[:4]
    start_y = height - 260
    row_h = 160

    for i, bullet in enumerate(bullets):
        col = i % 2
        row = i // 2
        bx = col_x[col]
        by = start_y - row * row_h

        # Background card
        card = mpatches.FancyBboxPatch(
            (bx - 20, by - 80), (width // 2 - 120), 100,
            boxstyle="round,pad=8",
            linewidth=1, edgecolor=accent,
            facecolor="#16162a", alpha=0.85,
        )
        ax.add_patch(card)
        # Bullet number
        ax.text(
            bx, by - 10, f"{i + 1}",
            color=accent, fontsize=32, fontweight="bold",
            va="center", ha="left",
        )
        ax.text(
            bx + 48, by - 10, bullet[:55],
            color="#d0d0e8", fontsize=22,
            va="center", ha="left",
        )

    # Key stat if present
    if data.key_stat:
        ax.text(
            width // 2, 80, data.key_stat,
            color=accent, fontsize=56, fontweight="bold",
            va="bottom", ha="center", alpha=0.85,
        )


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg clip creation
# ─────────────────────────────────────────────────────────────────────────────

def create_infographic_clip(
    image_path: str,
    output_path: str,
    duration: float,
    fps: int,
    ffmpeg_path: str = "ffmpeg",
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Convert a PNG image to a silent video clip of the given duration."""
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
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_POPEN_FLAGS,
    )
    if result.returncode != 0:
        stderr = result.stderr
        lines = stderr.splitlines()
        start = 0
        for i, ln in enumerate(lines):
            if ln.strip() == "" and i > 0:
                start = i + 1
                break
        relevant = lines[start:][-40:]
        msg = "\n".join(relevant) if relevant else stderr[-1500:]
        raise RuntimeError(f"FFmpeg infographic clip error:\n{msg}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Script text helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_text_at_time(
    script: str,
    timestamp: float,
    audio_duration: float,
    context_chars: int = 400,
) -> str:
    """Return a slice of the script corresponding to the given timestamp."""
    if not script:
        return ""
    if audio_duration <= 0:
        audio_duration = 1.0

    fraction = max(0.0, min(1.0, timestamp / audio_duration))
    center_pos = int(fraction * len(script))
    start = max(0, center_pos - context_chars // 2)
    end = center_pos + context_chars // 2

    snippet = script[start:end]

    # Strip to nearest word boundary
    if start > 0 and " " in snippet:
        first_space = snippet.find(" ")
        snippet = snippet[first_space:].lstrip()
    if end < len(script) and " " in snippet:
        last_space = snippet.rfind(" ")
        snippet = snippet[:last_space]

    return snippet.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Position planner
# ─────────────────────────────────────────────────────────────────────────────

def plan_infographic_positions(
    n_clips: int,
    min_gap: int = 5,
    max_gap: int = 15,
) -> list[int]:
    """Return sorted list of clip indices AFTER which to insert an infographic."""
    positions: list[int] = []
    current = random.randint(min_gap, max_gap)
    while current < n_clips - 2:
        positions.append(current)
        current += random.randint(min_gap, max_gap)
    return positions


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

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
    """Main entry: extract text → Gemini → render PNG → FFmpeg clip."""
    # 1. Get relevant script text
    text = get_text_at_time(script, timestamp, audio_duration)
    if not text:
        text = script[:400]

    # 2. Extract infographic data (with fallback)
    try:
        data = extract_infographic_data(text, cfg)
    except Exception as e:
        if log:
            log.warning(f"extract_infographic_data failed: {e}, using simple fallback")
        data = _extract_from_text_simple(text)

    # 3. Randomise visual style for each run
    data.accent_color = random.choice(ACCENT_COLORS)
    data.layout = random.choice(["list", "highlight", "split"])

    # 4. Render to temp PNG
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png_path = tmp.name

    try:
        render_infographic(data, png_path, width=width, height=height)
        if log:
            log.info(f"Rendered infographic PNG: {png_path} (layout={data.layout})")

        # 5. Convert to video clip
        create_infographic_clip(
            image_path=png_path,
            output_path=output_path,
            duration=duration,
            fps=fps,
            ffmpeg_path=ffmpeg_path,
            width=width,
            height=height,
        )
    finally:
        # 6. Delete temp PNG
        try:
            os.unlink(png_path)
        except OSError:
            pass

    return output_path
