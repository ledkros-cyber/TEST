"""Infographic generator — real visual charts via QuickChart.io + Pillow composition.

Pipeline:
  script text → Gemini (extract numerical data + chart type)
  → QuickChart.io API (free, no key) → chart PNG
  → Pillow compose 1920×1080 frame (background + title + chart + context)
  → FFmpeg → video clip (5-8 s)

QuickChart.io: https://quickchart.io  — free, no API key, 1M charts/month
Fallback: matplotlib simple chart when QuickChart is unreachable
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

# ── Windows: suppress console popups ─────────────────────────────────────────
_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# ── Color palettes ────────────────────────────────────────────────────────────
ACCENT_COLORS = [
    "#2196F3", "#4CAF50", "#FF9800", "#9C27B0",
    "#F44336", "#00BCD4", "#FF5722", "#3F51B5",
    "#009688", "#E91E63",
]

_BG_LIGHT = [
    "#FFFFFF", "#F8F9FA", "#FFF8E1", "#E8F5E9",
    "#E3F2FD", "#F3E5F5", "#FBE9E7", "#E0F7FA",
]

CHART_TYPES = ["bar", "doughnut", "radar", "gauge", "pie", "polarArea"]


# ── Data structure ────────────────────────────────────────────────────────────
@dataclass
class InfographicData:
    title: str
    chart_type: str = "bar"           # bar | doughnut | radar | gauge | pie | polarArea
    labels: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    unit: str = ""                    # %, km, people, $, etc.
    key_stat: str = ""                # large callout number/text
    context: str = ""                 # 1-2 sentence supporting text
    accent_color: str = "#2196F3"
    bg_color: str = "#FFFFFF"


# ── Gemini extraction ─────────────────────────────────────────────────────────
def _extract_with_key(api_key: str, text: str, model_id: str = None) -> InfographicData:
    from app.api.gemini_client import _generate_with_sdk, DEFAULT_GEMINI_MODEL
    if model_id is None:
        model_id = DEFAULT_GEMINI_MODEL

    prompt = (
        "You are a data visualization designer. Analyze this script excerpt "
        "and extract data for a VISUAL CHART infographic — real numbers and stats.\n"
        "Return ONLY valid JSON (no markdown, no code blocks):\n"
        "{\n"
        '  "title": "short chart title, max 50 chars",\n'
        '  "chart_type": "bar OR doughnut OR radar OR gauge OR pie OR polarArea",\n'
        '  "labels": ["label1", "label2", "label3"],\n'
        '  "values": [45.0, 30.0, 25.0],\n'
        '  "unit": "% or km or $ or people or empty string",\n'
        '  "key_stat": "single most impressive number/fact from the text, max 30 chars",\n'
        '  "context": "1 sentence explaining the chart, max 100 chars"\n'
        "}\n\n"
        "Chart type guide:\n"
        "  bar — ranked comparisons, quantities (e.g. Top 5 armies by size)\n"
        "  doughnut — percentages that sum to 100 (e.g. fleet composition)\n"
        "  pie — distribution of parts (e.g. budget allocation)\n"
        "  radar — multi-dimension scoring (e.g. country capabilities: navy, air, ground)\n"
        "  gauge — single percentage/score (e.g. 73% control achieved)\n"
        "  polarArea — multiple categories with area emphasis\n\n"
        "IMPORTANT: values must be REAL numbers from the text or reasonable estimates.\n"
        "labels: 3-6 items max. values: matching length array of numbers.\n"
        "For gauge: labels=['metric name'], values=[single 0-100 number].\n\n"
        f"Script excerpt:\n{text[:800]}"
    )

    raw = _generate_with_sdk(api_key=api_key, model_id=model_id, user_prompt=prompt)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

    d = json.loads(raw)

    chart_type = d.get("chart_type", "bar")
    if chart_type not in CHART_TYPES:
        chart_type = "bar"

    labels = [str(l)[:40] for l in d.get("labels", []) if l][:6]
    values_raw = d.get("values", [])
    values = []
    for v in values_raw:
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            values.append(0.0)
    values = values[:len(labels)]

    if not labels or not values:
        raise ValueError("No chart data returned by Gemini")

    return InfographicData(
        title=str(d.get("title", ""))[:55],
        chart_type=chart_type,
        labels=labels,
        values=values,
        unit=str(d.get("unit", ""))[:10],
        key_stat=str(d.get("key_stat", ""))[:35],
        context=str(d.get("context", ""))[:100],
        accent_color=random.choice(ACCENT_COLORS),
        bg_color=random.choice(_BG_LIGHT),
    )


def _extract_from_text_simple(text: str) -> InfographicData:
    """Fallback: extract numbers from text for a simple bar chart."""
    # Find numbers with context
    matches = re.findall(r'(\d+[\.,]?\d*)\s*(%|km|miles?|people|soldiers?|aircraft|ships?)?', text)
    labels, values = [], []
    words = text.split()
    for i, (num_str, unit) in enumerate(matches[:5]):
        try:
            val = float(num_str.replace(",", "."))
        except ValueError:
            continue
        # Find word before number as label
        idx = next((j for j, w in enumerate(words) if num_str in w), -1)
        label = words[idx - 1].strip(".,!?") if idx > 0 else f"Item {i+1}"
        labels.append(label[:20])
        values.append(val)

    if not labels:
        # Generic fallback
        labels = ["Factor 1", "Factor 2", "Factor 3"]
        values = [random.randint(40, 90), random.randint(30, 80), random.randint(20, 70)]

    return InfographicData(
        title=text.split(".")[0][:50],
        chart_type="bar",
        labels=labels,
        values=values,
        accent_color=random.choice(ACCENT_COLORS),
        bg_color=random.choice(_BG_LIGHT),
    )


def extract_infographic_data(text: str, cfg: dict) -> InfographicData:
    from app.api.gemini_client import _call_with_cascade, DEFAULT_GEMINI_MODEL
    try:
        return _call_with_cascade(_extract_with_key, cfg, text, model_id=DEFAULT_GEMINI_MODEL)
    except Exception as e:
        if log:
            log.warning(f"Gemini infographic extraction failed: {e}")
        return _extract_from_text_simple(text)


# ── QuickChart.io chart generator ─────────────────────────────────────────────
def _palette(accent: str, n: int) -> list[str]:
    """Generate n colors based on accent."""
    base_colors = [
        "#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336",
        "#00BCD4", "#FF5722", "#3F51B5", "#009688", "#E91E63",
        "#FFC107", "#607D8B", "#795548", "#8BC34A", "#03A9F4",
    ]
    # Put accent first, then fill with others
    palette = [accent]
    for c in base_colors:
        if c.upper() != accent.upper() and len(palette) < n:
            palette.append(c)
    return palette[:n]


def _build_chart_config(data: InfographicData) -> dict:
    """Build Chart.js config for QuickChart.io."""
    colors = _palette(data.accent_color, len(data.values))
    alpha_colors = [c + "CC" for c in colors]  # 80% opacity

    if data.chart_type == "gauge":
        value = data.values[0] if data.values else 50
        label = data.labels[0] if data.labels else data.title
        return {
            "type": "gauge",
            "data": {
                "datasets": [{
                    "value": min(100, max(0, value)),
                    "data": [25, 25, 25, 25],
                    "backgroundColor": ["#F44336", "#FF9800", "#FFC107", "#4CAF50"],
                    "borderWidth": 2,
                }]
            },
            "options": {
                "needle": {
                    "radiusPercentage": 2,
                    "widthPercentage": 3.2,
                    "lengthPercentage": 80,
                    "color": "rgba(0,0,0,0.9)",
                },
                "valueLabel": {
                    "display": True,
                    "formatter": lambda v: f"{v}%",
                    "fontSize": 28,
                    "color": "#1a1a2e",
                    "backgroundColor": "transparent",
                },
                "plugins": {
                    "title": {
                        "display": True,
                        "text": label,
                        "fontSize": 24,
                        "fontColor": "#1a1a2e",
                    }
                }
            }
        }

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
                }]
            },
            "options": {
                "plugins": {
                    "legend": {
                        "position": "right",
                        "labels": {
                            "fontSize": 18,
                            "fontColor": "#1a1a2e",
                            "padding": 16,
                        }
                    },
                    "datalabels": {
                        "display": True,
                        "formatter": "(value, ctx) => { return value + '" + (data.unit or "") + "'; }",
                        "color": "#fff",
                        "font": {"weight": "bold", "size": 16},
                    }
                }
            }
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
                }]
            },
            "options": {
                "scale": {
                    "ticks": {
                        "beginAtZero": True,
                        "fontSize": 14,
                        "fontColor": "#555",
                    },
                    "gridLines": {"color": "rgba(0,0,0,0.1)"},
                    "pointLabels": {"fontSize": 18, "fontColor": "#1a1a2e"},
                },
                "plugins": {
                    "legend": {"display": False}
                }
            }
        }

    if data.chart_type == "polarArea":
        return {
            "type": "polarArea",
            "data": {
                "labels": data.labels,
                "datasets": [{
                    "data": data.values,
                    "backgroundColor": alpha_colors,
                    "borderColor": colors,
                    "borderWidth": 2,
                }]
            },
            "options": {
                "plugins": {
                    "legend": {
                        "position": "right",
                        "labels": {"fontSize": 16, "fontColor": "#1a1a2e"},
                    }
                }
            }
        }

    # Default: horizontal bar chart
    return {
        "type": "horizontalBar",
        "data": {
            "labels": data.labels,
            "datasets": [{
                "label": data.unit or "Value",
                "data": data.values,
                "backgroundColor": alpha_colors,
                "borderColor": colors,
                "borderWidth": 2,
            }]
        },
        "options": {
            "scales": {
                "xAxes": [{"ticks": {"beginAtZero": True, "fontSize": 16, "fontColor": "#333"}}],
                "yAxes": [{"ticks": {"fontSize": 18, "fontColor": "#1a1a2e", "fontStyle": "bold"}}],
            },
            "plugins": {
                "legend": {"display": False},
                "datalabels": {
                    "display": True,
                    "anchor": "end",
                    "align": "right",
                    "color": "#1a1a2e",
                    "font": {"weight": "bold", "size": 16},
                    "formatter": "(value) => value + '" + (data.unit or "") + "'",
                }
            }
        }
    }


def _fetch_quickchart(config: dict, width: int = 860, height: int = 560) -> bytes:
    """Fetch chart PNG from QuickChart.io (free, no API key)."""
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


# ── Pillow composition ────────────────────────────────────────────────────────
def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _compose_infographic(
    chart_bytes: bytes,
    data: InfographicData,
    width: int,
    height: int,
    output_path: str,
) -> str:
    """Compose final 1920×1080 image: background + title + chart + context."""
    from PIL import Image, ImageDraw, ImageFont
    import io

    bg_rgb = _hex_rgb(data.bg_color)
    acc_rgb = _hex_rgb(data.accent_color)

    # Base image
    img = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Top accent header bar
    header_h = 130
    draw.rectangle([(0, 0), (width, header_h)], fill=acc_rgb)

    # Diagonal accent accent shape (bottom-right decoration)
    draw.polygon([
        (width - 300, height),
        (width, height - 200),
        (width, height),
    ], fill=tuple(max(0, c - 30) for c in acc_rgb))

    # Bottom thin accent line
    draw.rectangle([(0, height - 8), (width, height)], fill=acc_rgb)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        font_names = (
            ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
            else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
        )
        for fn in font_names:
            for search_dir in [
                "C:/Windows/Fonts",
                "/usr/share/fonts/truetype/dejavu",
                "/usr/share/fonts/truetype/liberation",
                "/usr/share/fonts",
            ]:
                path = os.path.join(search_dir, fn)
                if os.path.exists(path):
                    try:
                        return ImageFont.truetype(path, size)
                    except Exception:
                        continue
        return ImageFont.load_default()

    font_title  = _load_font(48, bold=True)
    font_stat   = _load_font(80, bold=True)
    font_ctx    = _load_font(28)
    font_credit = _load_font(22)

    # ── Title in header ───────────────────────────────────────────────────────
    title_color = (255, 255, 255)
    draw.text((width // 2, header_h // 2), data.title,
              font=font_title, fill=title_color, anchor="mm")

    # ── Chart image ───────────────────────────────────────────────────────────
    chart_img = Image.open(io.BytesIO(chart_bytes)).convert("RGBA")

    # Target chart area: full width minus margins, below header
    chart_area_top = header_h + 20
    chart_area_bot = height - 160 if data.context or data.key_stat else height - 40

    max_chart_w = width - 200
    max_chart_h = chart_area_bot - chart_area_top

    # Scale keeping aspect ratio
    cw, ch = chart_img.size
    scale = min(max_chart_w / cw, max_chart_h / ch, 1.5)
    new_cw = int(cw * scale)
    new_ch = int(ch * scale)
    chart_img = chart_img.resize((new_cw, new_ch), Image.LANCZOS)

    # Paste centered
    paste_x = (width - new_cw) // 2
    paste_y = chart_area_top + (max_chart_h - new_ch) // 2
    # White background behind chart (chart might have transparency)
    chart_bg = Image.new("RGBA", (new_cw + 20, new_ch + 20), (255, 255, 255, 230))
    img.paste(chart_bg.convert("RGB"), (paste_x - 10, paste_y - 10))
    img.paste(chart_img.convert("RGB"), (paste_x, paste_y),
              mask=chart_img.split()[3] if chart_img.mode == "RGBA" else None)

    # ── Key stat (bottom left) ────────────────────────────────────────────────
    bottom_y = height - 120
    if data.key_stat:
        draw.text((80, bottom_y), data.key_stat,
                  font=font_stat, fill=acc_rgb, anchor="lm")

    # ── Context text (bottom right) ───────────────────────────────────────────
    if data.context:
        ctx_x = width - 80
        draw.text((ctx_x, bottom_y), data.context[:90],
                  font=font_ctx, fill=(80, 80, 80), anchor="rm")

    img.save(output_path, "PNG", quality=95)
    return output_path


# ── Matplotlib fallback ───────────────────────────────────────────────────────
def _render_matplotlib_fallback(data: InfographicData, output_path: str,
                                 width: int, height: int) -> str:
    """Simple bar chart via matplotlib when QuickChart is unavailable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "DejaVu Sans"
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(data.bg_color)
    ax.set_facecolor(data.bg_color)

    acc = data.accent_color
    labels = data.labels[:6] or ["A", "B", "C"]
    values = data.values[:len(labels)] or [50, 40, 30]

    colors = [acc] * len(labels)
    bars = ax.barh(labels, values, color=colors, edgecolor="white", linewidth=1.5, height=0.6)

    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}{data.unit}", va="center", fontsize=24, fontweight="bold", color="#333")

    ax.set_title(data.title, fontsize=36, fontweight="bold", color="#1a1a2e", pad=30)
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
    """Render infographic: QuickChart chart + Pillow composition → PNG."""

    # Try QuickChart.io + Pillow
    try:
        from PIL import Image
        config = _build_chart_config(data)
        if log:
            log.info(f"Fetching chart from QuickChart.io: type={data.chart_type}")
        chart_bytes = _fetch_quickchart(config, width=860, height=560)
        _compose_infographic(chart_bytes, data, width, height, output_path)
        if log:
            log.info(f"Infographic rendered via QuickChart: {output_path}")
        return output_path
    except Exception as e:
        if log:
            log.warning(f"QuickChart failed ({e}), using matplotlib fallback")

    # Fallback: matplotlib
    try:
        _render_matplotlib_fallback(data, output_path, width, height)
        return output_path
    except Exception as e2:
        raise RuntimeError(f"Infographic render failed: QuickChart error + matplotlib: {e2}")


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
        raise RuntimeError(f"FFmpeg infographic clip error:\n{chr(10).join(lines[-20:])}")
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

    data.accent_color = random.choice(ACCENT_COLORS)
    data.bg_color = random.choice(_BG_LIGHT)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png_path = tmp.name

    try:
        render_infographic(data, png_path, width=width, height=height)
        if log:
            log.info(
                f"Infographic: chart_type={data.chart_type}, "
                f"labels={data.labels[:3]}, values={data.values[:3]}"
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
