"""Infographic generator — factcards + data charts via QuickChart.io + Pillow.

Pipeline:
  script text → Gemini (extract data OR key fact)
  → factcard (Pillow gradient card) OR chart (QuickChart.io PNG)
  → Pillow compose 1920×1080
  → FFmpeg → video clip with subtle zoom animation

Two modes:
  factcard — when text has no real statistics: beautiful gradient card with
             a bold key statement. No confusing chart with random words.
  chart    — when text has actual numbers/stats: bar/pie/doughnut/radar chart.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

try:
    from app.utils.logger import log
except Exception:
    log = None

_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# ── Color palettes ────────────────────────────────────────────────────────────
ACCENT_COLORS = [
    "#1565C0", "#2E7D32", "#E65100", "#6A1B9A",
    "#B71C1C", "#00695C", "#AD1457", "#283593",
    "#4E342E", "#00838F",
]

_BG_LIGHT = [
    "#FFFFFF", "#F8F9FA", "#FFF8E1", "#E8F5E9",
    "#E3F2FD", "#F3E5F5", "#FBE9E7", "#E0F7FA",
]

CHART_TYPES = ["bar", "doughnut", "radar", "pie"]


@dataclass
class InfographicData:
    title: str
    infographic_type: str = "factcard"  # "factcard" or "chart"
    chart_type: str = "bar"             # bar | doughnut | pie | radar
    labels: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    unit: str = ""
    key_fact: str = ""   # bold headline for factcard
    context: str = ""    # supporting sentence
    accent_color: str = "#1565C0"
    bg_color: str = "#FFFFFF"


# ── Gemini extraction ─────────────────────────────────────────────────────────
def _extract_with_key(api_key: str, text: str, model_id: str = None) -> InfographicData:
    from app.api.gemini_client import _generate_with_sdk, DEFAULT_GEMINI_MODEL
    if model_id is None:
        model_id = DEFAULT_GEMINI_MODEL

    prompt = (
        "You analyze script text to decide what type of infographic to create.\n\n"
        "DECISION:\n"
        "  → Use 'chart' ONLY if the text contains ACTUAL NUMBERS, STATISTICS, "
        "or FACTUAL QUANTITIES (years, percentages, speeds, distances, counts, etc.)\n"
        "  → Use 'factcard' for EVERYTHING ELSE — dramatic statements, "
        "descriptions, events, narratives without clear numbers.\n\n"
        "Return ONLY valid JSON, no markdown, no code blocks:\n"
        "{\n"
        '  "infographic_type": "factcard" OR "chart",\n'
        '  "title": "short headline max 55 chars",\n'
        '  "chart_type": "bar OR doughnut OR pie OR radar",\n'
        '  "labels": ["Concept Name 1", "Concept Name 2", "Concept Name 3"],\n'
        '  "values": [45.0, 30.0, 25.0],\n'
        '  "unit": "% or km or people or tons or empty string",\n'
        '  "key_fact": "The single most striking fact or statement, max 70 chars",\n'
        '  "context": "One supporting sentence, max 90 chars"\n'
        "}\n\n"
        "STRICT RULES:\n"
        "1. labels MUST be MEANINGFUL CONCEPT NAMES (e.g. 'Navy Fleet', 'Ground Forces').\n"
        "   NEVER single articles, prepositions or random words like "
        "'The', 'after', 'waiting', 'boats', 'a'.\n"
        "2. For 'chart': values must be REAL numbers found or reasonably inferred "
        "from the text. labels length must equal values length. Min 2, max 5 items.\n"
        "3. For 'factcard': set chart_type='', labels=[], values=[]. "
        "key_fact MUST be a complete dramatic statement (not just a word).\n"
        "4. key_fact and context must be meaningful sentences in the same language as text.\n"
        "5. When in doubt → use 'factcard'. A good factcard is better than a bad chart.\n\n"
        f"Script segment:\n{text[:900]}"
    )

    raw = _generate_with_sdk(api_key=api_key, model_id=model_id, user_prompt=prompt)
    raw = raw.strip()
    # Strip markdown code block if model wraps in ```json
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

    d = json.loads(raw)

    infographic_type = d.get("infographic_type", "factcard")
    if infographic_type not in ("chart", "factcard"):
        infographic_type = "factcard"

    chart_type = d.get("chart_type", "bar")
    if chart_type not in CHART_TYPES:
        chart_type = "bar"

    labels = [str(l).strip()[:40] for l in d.get("labels", []) if str(l).strip()][:5]
    values_raw = d.get("values", [])
    values: list[float] = []
    for v in values_raw:
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            values.append(0.0)
    values = values[:len(labels)]

    # Validate chart data — fall back to factcard if bad labels detected
    if infographic_type == "chart" and labels:
        # Reject if any label is a single word shorter than 3 chars or a common article
        bad_words = {"the", "a", "an", "of", "in", "at", "to", "by",
                     "for", "on", "is", "it", "as", "be", "or", "and"}
        bad_labels = [l for l in labels if l.lower() in bad_words or len(l) <= 2]
        if bad_labels or not values:
            infographic_type = "factcard"

    key_fact = str(d.get("key_fact", "")).strip()[:72]
    context = str(d.get("context", "")).strip()[:92]

    if not key_fact:
        # Build key_fact from title as fallback
        key_fact = str(d.get("title", "")).strip()[:72]

    return InfographicData(
        title=str(d.get("title", "")).strip()[:55],
        infographic_type=infographic_type,
        chart_type=chart_type,
        labels=labels,
        values=values,
        unit=str(d.get("unit", "")).strip()[:10],
        key_fact=key_fact,
        context=context,
        accent_color=random.choice(ACCENT_COLORS),
        bg_color=random.choice(_BG_LIGHT),
    )


def _extract_from_text_simple(text: str) -> InfographicData:
    """Fallback without Gemini — extract numbers or return factcard."""
    numbers = re.findall(r'\b(\d[\d,\.]*)\s*(%|km|miles?|kg|tons?|people|soldiers?)?\b', text)
    labels, values = [], []

    if len(numbers) >= 2:
        words = text.split()
        for num_str, unit_str in numbers[:4]:
            try:
                val = float(num_str.replace(",", ""))
            except ValueError:
                continue
            idx = next((j for j, w in enumerate(words) if num_str in w), -1)
            # Look for a noun before the number (skip short stop words)
            label = ""
            for back in range(1, 4):
                if idx - back >= 0:
                    candidate = words[idx - back].strip(".,!?()").capitalize()
                    if len(candidate) >= 3 and candidate.lower() not in {
                        "the", "a", "an", "of", "in", "at", "to", "by", "was", "were",
                        "has", "had", "its", "their", "with", "from",
                    }:
                        label = candidate
                        break
            if label:
                labels.append(label[:30])
                values.append(val)

    if len(labels) >= 2:
        return InfographicData(
            title=text.split(".")[0][:50],
            infographic_type="chart",
            chart_type="bar",
            labels=labels,
            values=values,
            accent_color=random.choice(ACCENT_COLORS),
            bg_color=random.choice(_BG_LIGHT),
        )

    # No real numbers → factcard with first sentence as key fact
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    key = sentences[0][:70] if sentences else text[:70]
    ctx = sentences[1][:90] if len(sentences) > 1 else ""
    return InfographicData(
        title=key[:50],
        infographic_type="factcard",
        key_fact=key,
        context=ctx,
        accent_color=random.choice(ACCENT_COLORS),
        bg_color=random.choice(_BG_LIGHT),
    )


def extract_infographic_data(text: str, cfg: dict) -> InfographicData:
    from app.api.gemini_client import _call_with_cascade, DEFAULT_GEMINI_MODEL
    try:
        return _call_with_cascade(
            _extract_with_key, cfg, text, model_id=DEFAULT_GEMINI_MODEL
        )
    except Exception as e:
        if log:
            log.warning(f"Gemini infographic extraction failed: {e}")
        return _extract_from_text_simple(text)


# ── Pillow helpers ────────────────────────────────────────────────────────────
def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _darker(rgb: tuple, factor: float = 0.55) -> tuple:
    return tuple(max(0, int(c * factor)) for c in rgb)


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
         "LiberationSans-Bold.ttf", "FreeSansBold.ttf"]
        if bold else
        ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
         "LiberationSans-Regular.ttf", "FreeSans.ttf"]
    )
    search_dirs = [
        "C:/Windows/Fonts",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype/freefont",
        "/usr/share/fonts",
    ]
    for fn in names:
        for d in search_dirs:
            path = os.path.join(d, fn)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip() if current else word
        try:
            bbox = font.getbbox(test)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * (font.size if hasattr(font, "size") else 10)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


# ── Factcard renderer ─────────────────────────────────────────────────────────
def _render_factcard(data: InfographicData, output_path: str,
                     width: int, height: int) -> str:
    """Render a visually striking gradient factcard — no chart, pure typography."""
    from PIL import Image, ImageDraw
    import io

    acc = _hex_rgb(data.accent_color)
    dark = _darker(acc, 0.45)

    # ── Gradient background ───────────────────────────────────────────────────
    try:
        import numpy as np
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        for c in range(3):
            arr[:, :, c] = np.linspace(acc[c], dark[c], height)[:, np.newaxis]
        img = Image.fromarray(arr, "RGB")
    except ImportError:
        img = Image.new("RGB", (width, height), acc)
        draw_bg = ImageDraw.Draw(img)
        for y in range(height):
            t = y / height
            col = tuple(int(acc[c] * (1 - t) + dark[c] * t) for c in range(3))
            draw_bg.line([(0, y), (width, y)], fill=col)

    draw = ImageDraw.Draw(img)

    # ── Decorative shapes ─────────────────────────────────────────────────────
    # Large translucent circle (top-right)
    cx, cy, r = int(width * 0.85), int(height * 0.18), int(height * 0.55)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse([(cx - r, cy - r), (cx + r, cy + r)],
                  fill=(*_darker(acc, 0.65), 60))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Small circle (bottom-left)
    r2 = int(height * 0.25)
    draw.ellipse(
        [(-r2 // 2, height - r2), (r2, height + r2 // 2)],
        fill=tuple(max(0, c - 15) for c in dark),
    )

    # Top accent stripe
    stripe_h = 12
    draw.rectangle([(0, 0), (width, stripe_h)], fill=(255, 255, 255, 180))

    # Bottom accent stripe
    draw.rectangle([(0, height - stripe_h), (width, height)],
                   fill=(255, 255, 255, 100))

    # ── Fonts ─────────────────────────────────────────────────────────────────
    font_title  = _load_font(38, bold=False)
    font_fact   = _load_font(76, bold=True)
    font_fact_m = _load_font(60, bold=True)   # medium fallback
    font_fact_s = _load_font(48, bold=True)   # small fallback
    font_ctx    = _load_font(30)

    white     = (255, 255, 255)
    white_dim = (220, 220, 220)

    # ── Title (top center) ────────────────────────────────────────────────────
    if data.title:
        draw.text((width // 2, 55), data.title.upper(),
                  font=font_title, fill=white_dim, anchor="mm")

    # ── Key fact (center) ─────────────────────────────────────────────────────
    fact_text = data.key_fact or data.title or "KEY FACT"
    center_y = int(height * 0.46)
    max_w = int(width * 0.80)

    # Try fitting with large font first, reduce if needed
    for fnt in (font_fact, font_fact_m, font_fact_s):
        lines = _wrap_text(fact_text, fnt, max_w)
        try:
            line_h = fnt.getbbox("Ag")[3] + 14
        except Exception:
            line_h = fnt.size + 14 if hasattr(fnt, "size") else 80
        total_h = line_h * len(lines)
        if total_h < int(height * 0.52):
            break

    # Draw text shadow
    for i, line in enumerate(lines):
        y = center_y - (len(lines) - 1) * line_h // 2 + i * line_h
        draw.text((width // 2 + 3, y + 3), line,
                  font=fnt, fill=(0, 0, 0, 80), anchor="mm")
        draw.text((width // 2, y), line,
                  font=fnt, fill=white, anchor="mm")

    # ── Context sentence (bottom area) ───────────────────────────────────────
    if data.context:
        ctx_lines = _wrap_text(data.context, font_ctx, int(width * 0.70))
        ctx_y = int(height * 0.82)
        try:
            ctx_lh = font_ctx.getbbox("Ag")[3] + 8
        except Exception:
            ctx_lh = 38
        for i, line in enumerate(ctx_lines[:3]):
            y = ctx_y + i * ctx_lh
            draw.text((width // 2, y), line,
                      font=font_ctx, fill=white_dim, anchor="mm")

    img.save(output_path, "PNG")
    return output_path


# ── QuickChart.io chart ───────────────────────────────────────────────────────
def _palette(accent: str, n: int) -> list[str]:
    base = [
        "#1565C0", "#2E7D32", "#E65100", "#6A1B9A", "#B71C1C",
        "#00695C", "#AD1457", "#283593", "#4E342E", "#00838F",
        "#F57F17", "#37474F",
    ]
    palette = [accent]
    for c in base:
        if c.upper() != accent.upper() and len(palette) < n:
            palette.append(c)
    return palette[:n]


def _build_chart_config(data: InfographicData) -> dict:
    """Build Chart.js JSON config for QuickChart.io (no Python lambdas!)."""
    colors = _palette(data.accent_color, len(data.values))
    alpha_colors = [c + "BB" for c in colors]
    unit = data.unit or ""

    if data.chart_type in ("pie", "doughnut"):
        return {
            "type": data.chart_type,
            "data": {
                "labels": data.labels,
                "datasets": [{
                    "data": data.values,
                    "backgroundColor": alpha_colors,
                    "borderColor": colors,
                    "borderWidth": 2,
                }],
            },
            "options": {
                "plugins": {
                    "legend": {
                        "position": "right",
                        "labels": {"fontSize": 18, "fontColor": "#1a1a2e", "padding": 20},
                    },
                    "datalabels": {
                        "display": True,
                        "color": "#fff",
                        "font": {"weight": "bold", "size": 18},
                        "formatter": f"(v) => v + '{unit}'",
                    },
                },
            },
        }

    if data.chart_type == "radar":
        return {
            "type": "radar",
            "data": {
                "labels": data.labels,
                "datasets": [{
                    "label": data.title,
                    "data": data.values,
                    "backgroundColor": data.accent_color + "33",
                    "borderColor": data.accent_color,
                    "borderWidth": 3,
                    "pointBackgroundColor": data.accent_color,
                    "pointRadius": 6,
                }],
            },
            "options": {
                "scale": {
                    "ticks": {"beginAtZero": True, "fontSize": 14},
                    "pointLabels": {"fontSize": 18, "fontColor": "#1a1a2e"},
                },
                "plugins": {"legend": {"display": False}},
            },
        }

    # Default: horizontal bar
    return {
        "type": "horizontalBar",
        "data": {
            "labels": data.labels,
            "datasets": [{
                "label": unit or "Value",
                "data": data.values,
                "backgroundColor": alpha_colors,
                "borderColor": colors,
                "borderWidth": 2,
            }],
        },
        "options": {
            "scales": {
                "xAxes": [{"ticks": {"beginAtZero": True, "fontSize": 16}}],
                "yAxes": [{"ticks": {"fontSize": 20, "fontColor": "#1a1a2e",
                                     "fontStyle": "bold"}}],
            },
            "plugins": {
                "legend": {"display": False},
                "datalabels": {
                    "display": True,
                    "anchor": "end",
                    "align": "right",
                    "color": "#1a1a2e",
                    "font": {"weight": "bold", "size": 16},
                    "formatter": f"(v) => v + '{unit}'",
                },
            },
        },
    }


def _fetch_quickchart(config: dict, width: int = 880, height: int = 580) -> bytes:
    chart_json = json.dumps(config, ensure_ascii=False)
    params = urllib.parse.urlencode({
        "c": chart_json,
        "w": width,
        "h": height,
        "backgroundColor": "white",
        "devicePixelRatio": "1.5",
    })
    url = f"https://quickchart.io/chart?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "YTGen/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _compose_chart_infographic(
    chart_bytes: bytes,
    data: InfographicData,
    width: int,
    height: int,
    output_path: str,
) -> str:
    """Compose 1920×1080 with light background + accent header + chart + footer."""
    from PIL import Image, ImageDraw
    import io

    bg_rgb = _hex_rgb(data.bg_color)
    acc_rgb = _hex_rgb(data.accent_color)

    img = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Header bar
    header_h = 120
    draw.rectangle([(0, 0), (width, header_h)], fill=acc_rgb)

    # Bottom corner decoration
    draw.polygon([
        (width - 280, height),
        (width, height - 180),
        (width, height),
    ], fill=_darker(acc_rgb, 0.75))

    # Bottom line
    draw.rectangle([(0, height - 8), (width, height)], fill=acc_rgb)

    # Title in header
    font_title = _load_font(46, bold=True)
    draw.text((width // 2, header_h // 2), data.title,
              font=font_title, fill=(255, 255, 255), anchor="mm")

    # Chart
    chart_img = Image.open(io.BytesIO(chart_bytes)).convert("RGBA")

    chart_area_top = header_h + 20
    chart_area_bot = (height - 140) if (data.context or data.key_fact) else (height - 30)
    max_cw = width - 160
    max_ch = chart_area_bot - chart_area_top

    cw, ch = chart_img.size
    scale = min(max_cw / cw, max_ch / ch, 1.4)
    new_cw, new_ch = int(cw * scale), int(ch * scale)
    chart_img = chart_img.resize((new_cw, new_ch), Image.LANCZOS)

    px = (width - new_cw) // 2
    py = chart_area_top + (max_ch - new_ch) // 2

    # White card behind chart
    card = Image.new("RGB", (new_cw + 24, new_ch + 24), (255, 255, 255))
    img.paste(card, (px - 12, py - 12))
    img.paste(chart_img.convert("RGB"), (px, py),
              mask=chart_img.split()[3] if chart_img.mode == "RGBA" else None)

    # Footer: key fact (left) + context (right)
    bottom_y = height - 70
    if data.key_fact:
        font_stat = _load_font(52, bold=True)
        draw.text((80, bottom_y), data.key_fact,
                  font=font_stat, fill=acc_rgb, anchor="lm")
    if data.context:
        font_ctx = _load_font(26)
        draw.text((width - 80, bottom_y), data.context[:85],
                  font=font_ctx, fill=(60, 60, 60), anchor="rm")

    img.save(output_path, "PNG")
    return output_path


def _render_matplotlib_fallback(data: InfographicData, output_path: str,
                                width: int, height: int) -> str:
    """Horizontal bar chart via matplotlib — offline fallback."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)

    acc = data.accent_color
    labels = data.labels[:5] or ["A", "B", "C"]
    values = data.values[:len(labels)] or [50, 40, 30]

    bars = ax.barh(labels, values, color=acc, edgecolor="white",
                   linewidth=1.5, height=0.6)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.02,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}{data.unit}", va="center",
                fontsize=24, fontweight="bold", color="#333")

    ax.set_title(data.title, fontsize=34, fontweight="bold", color="#1a1a2e", pad=28)
    ax.invert_yaxis()
    ax.tick_params(axis="y", labelsize=22, labelcolor="#1a1a2e")
    ax.tick_params(axis="x", labelsize=18, labelcolor="#555")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    plt.tight_layout(pad=2)
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight",
                pad_inches=0.3, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


# ── Main render ───────────────────────────────────────────────────────────────
def render_infographic(
    data: InfographicData,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Render infographic PNG: factcard or chart."""

    # ── Factcard path (no external API needed) ────────────────────────────────
    if data.infographic_type == "factcard" or not (data.labels and data.values):
        try:
            from PIL import Image
            _render_factcard(data, output_path, width, height)
            if log:
                log.info(f"Infographic rendered as factcard: {output_path}")
            return output_path
        except Exception as e:
            if log:
                log.warning(f"Factcard render failed: {e}, using matplotlib")
            _render_matplotlib_fallback(data, output_path, width, height)
            return output_path

    # ── Chart path: QuickChart.io + Pillow ────────────────────────────────────
    try:
        from PIL import Image
        config = _build_chart_config(data)
        if log:
            log.info(f"Fetching chart from QuickChart.io: type={data.chart_type}")
        chart_bytes = _fetch_quickchart(config, width=880, height=580)
        _compose_chart_infographic(chart_bytes, data, width, height, output_path)
        if log:
            log.info(f"Infographic rendered as chart: {output_path}")
        return output_path
    except Exception as e:
        if log:
            log.warning(f"QuickChart failed ({e}), matplotlib fallback")

    # ── Matplotlib fallback ───────────────────────────────────────────────────
    try:
        _render_matplotlib_fallback(data, output_path, width, height)
        return output_path
    except Exception as e2:
        raise RuntimeError(f"All infographic renderers failed: {e2}")


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
    """Convert PNG to video clip with subtle Ken-Burns zoom animation."""
    dur_frames = int(duration * fps)
    # zoompan: slow zoom from 1.0 to 1.05 over entire duration
    vf = (
        f"scale={int(width*1.06)}:{int(height*1.06)},"
        f"zoompan=z='min(1+on/{dur_frames}*0.05,1.05)':"
        f"d={dur_frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
        f"scale={width}:{height},"
        f"fps={fps}"
    )
    cmd = [
        ffmpeg_path, "-y", "-hide_banner",
        "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-video_track_timescale", "90000",
        "-an",
        output_path,
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, **_POPEN_FLAGS,
    )
    if result.returncode != 0:
        # zoompan failed (old ffmpeg) — try without animation
        vf_simple = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps}"
        )
        cmd2 = [
            ffmpeg_path, "-y", "-hide_banner",
            "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-vf", vf_simple,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-video_track_timescale", "90000",
            "-an",
            output_path,
        ]
        result2 = subprocess.run(
            cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, **_POPEN_FLAGS,
        )
        if result2.returncode != 0:
            lines = result2.stderr.splitlines()
            raise RuntimeError(f"FFmpeg infographic clip error:\n{chr(10).join(lines[-20:])}")
    return output_path


# ── Script text helpers ───────────────────────────────────────────────────────
def get_text_at_time(
    script: str,
    timestamp: float,
    audio_duration: float,
    context_chars: int = 700,
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


def plan_infographic_positions(n_clips: int,
                                min_gap: int = 5,
                                max_gap: int = 15) -> list[int]:
    positions: list[int] = []
    current = random.randint(min_gap, max_gap)
    while current < n_clips - 2:
        positions.append(current)
        current += random.randint(min_gap, max_gap)
    return positions


# ── Main entry ────────────────────────────────────────────────────────────────
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
        text = script[:700]

    try:
        data = extract_infographic_data(text, cfg)
    except Exception as e:
        if log:
            log.warning(f"extract_infographic_data failed: {e}")
        data = _extract_from_text_simple(text)

    data.accent_color = random.choice(ACCENT_COLORS)
    data.bg_color = random.choice(_BG_LIGHT)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png_path = tmp.name

    try:
        render_infographic(data, png_path, width=width, height=height)
        if log:
            log.info(
                f"Infographic: type={data.infographic_type}, "
                f"chart={data.chart_type}, labels={data.labels[:3]}"
            )
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
