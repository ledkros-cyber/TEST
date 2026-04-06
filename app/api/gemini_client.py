"""Google Gemini API client — drop-in alternative to claude_client.py.
Docs: https://ai.google.dev/gemini-api/docs
"""
import io
import re

try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────────────────────────

# Ordered from most capable → least capable (used for automatic cascade)
GEMINI_MODEL_CASCADE = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

GEMINI_MODELS = {
    "gemini-2.5-pro-preview-05-06": "Gemini 2.5 Pro (best quality)",
    "gemini-2.0-flash":             "Gemini 2.0 Flash (recommended)",
    "gemini-1.5-pro":               "Gemini 1.5 Pro",
    "gemini-1.5-flash":             "Gemini 1.5 Flash (fast)",
}
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

MAX_GEMINI_KEYS = 10

# Relax safety filters so creative/marketing content isn't blocked
_SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:       HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
} if GEMINI_AVAILABLE else {}

SCRIPT_SYSTEM = (
    "You are a professional YouTube scriptwriter. "
    "Create unique, engaging scripts based on competitor analysis. "
    "Scripts must be 100% original, SEO-optimised, conversational, "
    "hook the viewer in the first 15 seconds, and end with a call to action."
)


# ─────────────────────────────────────────────────────────────────────────────
# Key helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_active_keys(cfg: dict) -> list[str]:
    """Return all non-empty Gemini API keys from config."""
    keys = []
    for k in cfg.get("gemini_api_keys", []):
        k = (k or "").strip()
        if k:
            keys.append(k)
    if not keys:
        single = (cfg.get("gemini_api_key") or "").strip()
        if single:
            keys.append(single)
    return keys


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "quota" in msg or "429" in msg or "resource_exhausted" in msg


def _is_model_error(e: Exception) -> bool:
    """404 / model not found / not supported for this API version."""
    msg = str(e).lower()
    return (
        "404" in msg
        or "not found" in msg
        or "not supported" in msg
        or "deprecated" in msg
        or "invalid" in msg and "model" in msg
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascade + rotation dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _call_with_cascade(fn, cfg: dict, *args, model_id: str = DEFAULT_GEMINI_MODEL, **kwargs):
    """
    Call fn(api_key, *args, model_id=model, **kwargs) with automatic:
      • Model cascade  — if a model returns 404/unavailable, tries next less-capable model
      • Key rotation   — if a key returns quota error, rotates to the next key
    Cascade starts at `model_id` (the user's preferred model), falling back in order.
    Stores successful model + key index back into cfg.
    """
    keys = get_active_keys(cfg)
    if not keys:
        raise RuntimeError(
            "Gemini API key is not set.\n"
            "Go to Settings tab and enter your Google Gemini API key.\n"
            "Get a free key at: aistudio.google.com/app/apikey"
        )

    # Build model list starting at the configured model
    if model_id in GEMINI_MODEL_CASCADE:
        start_model_idx = GEMINI_MODEL_CASCADE.index(model_id)
    else:
        start_model_idx = 0
    models_to_try = GEMINI_MODEL_CASCADE[start_model_idx:]

    start_key = cfg.get("gemini_key_index", 0) % len(keys)
    last_err = None

    for model in models_to_try:
        for ki in range(len(keys)):
            key_idx = (start_key + ki) % len(keys)
            key = keys[key_idx]
            try:
                result = fn(key, *args, model_id=model, **kwargs)
                # Persist which model/key worked
                cfg["gemini_key_index"]       = key_idx
                cfg["_last_gemini_model"]     = model
                cfg["_last_gemini_key_num"]   = key_idx + 1
                cfg["_last_gemini_key_total"] = len(keys)
                try:
                    from app.config_manager import save_config
                    save_config(cfg)
                except Exception:
                    pass
                return result
            except Exception as e:
                last_err = e
                if _is_model_error(e):
                    # This model is unavailable — skip all remaining keys for it
                    break
                elif _is_quota_error(e):
                    # Quota on this key — try next key with same model
                    continue
                else:
                    # Real error (auth, network, etc.) — propagate immediately
                    raise

    tried = ", ".join(models_to_try)
    raise RuntimeError(
        f"All Gemini models/keys exhausted.\n"
        f"Models tried: {tried}\n"
        f"Keys tried: {len(keys)}\n"
        f"Last error: {last_err}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal model factory
# ─────────────────────────────────────────────────────────────────────────────

def _model(api_key: str, model_id: str):
    if not GEMINI_AVAILABLE:
        raise RuntimeError(
            "google-generativeai is not installed.\n"
            "Run: pip install google-generativeai"
        )
    genai.configure(api_key=api_key.strip())
    return genai.GenerativeModel(
        model_name=model_id,
        system_instruction=SCRIPT_SYSTEM,
        safety_settings=_SAFETY,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API — script generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_script(
    api_key: str,
    source_videos: list[dict],
    master_prompt: str = "",
    target_chars: int = 3000,
    language: str = "ru",
    model_id: str = DEFAULT_GEMINI_MODEL,
    cfg: dict | None = None,
) -> dict:
    """Generate script via Gemini (same return format as claude_client).
    If cfg is provided, model cascade + key rotation run automatically."""
    if cfg is not None:
        return _call_with_cascade(
            _generate_script_with_key, cfg,
            source_videos, master_prompt, target_chars, language,
            model_id=model_id,
        )
    return _generate_script_with_key(
        api_key, source_videos, master_prompt, target_chars, language,
        model_id=model_id,
    )


def _generate_script_with_key(
    api_key: str,
    source_videos: list[dict],
    master_prompt: str = "",
    target_chars: int = 3000,
    language: str = "ru",
    model_id: str = DEFAULT_GEMINI_MODEL,
) -> dict:
    m = _model(api_key, model_id)

    all_real_tags: list[str] = []
    sources_text = ""
    thumbnail_urls: list[str] = []

    for i, v in enumerate(source_videos, 1):
        sources_text += f"\n--- Source {i} ---\n"
        sources_text += f"Title: {v.get('title', '')}\n"
        sources_text += f"Description: {v.get('description', '')[:1200]}\n"
        vtags = v.get("tags", [])
        if vtags:
            sources_text += f"Tags: {', '.join(vtags[:30])}\n"
            all_real_tags.extend(vtags[:30])
        if v.get("transcript"):
            sources_text += f"Transcript excerpt: {v['transcript'][:2500]}\n"
        if v.get("thumbnail"):
            thumbnail_urls.append(v["thumbnail"])

    seen = set()
    unique_tags = []
    for t in all_real_tags:
        tl = t.lower().strip()
        if tl and tl not in seen:
            seen.add(tl)
            unique_tags.append(t.strip())
    unique_tags = unique_tags[:40]

    prompt = f"""{master_prompt}

COMPETITOR SOURCES TO ANALYSE:
{sources_text}

REAL TAGS FROM SOURCE VIDEOS (use as base, add relevant ones):
{', '.join(unique_tags)}

TASK — write in {'Russian' if language == 'ru' else 'English'}:

1. UNIQUE SCRIPT (~{target_chars} characters ±10%)
   - 100% original, not copied from sources
   - Powerful hook first 15 seconds
   - Conversational tone
   - End with call to subscribe

2. SEO TITLE (max 70 characters)

3. VIDEO DESCRIPTION (150-300 words with keywords)

4. TAGS — use the real tags above as base, supplement. 20-30 tags, comma-separated.

Reply STRICTLY in this format:

===SCRIPT===
[script]

===TITLE===
[title]

===DESCRIPTION===
[description]

===TAGS===
[tags]
"""

    response = m.generate_content(prompt)
    raw = response.text
    parsed = _parse(raw)
    parsed["thumbnail_urls"] = thumbnail_urls
    parsed["_used_model"] = model_id
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# Public API — thumbnail analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_thumbnails(
    api_key: str,
    thumbnail_data_list: list[tuple[bytes, str]],
    new_title: str,
    new_description: str,
    model_id: str = DEFAULT_GEMINI_MODEL,
    cfg: dict | None = None,
) -> list[str]:
    """Analyse competitor thumbnails with Gemini Vision → image-gen prompts."""
    if cfg is not None:
        return _call_with_cascade(
            _analyze_thumbnails_with_key, cfg,
            thumbnail_data_list, new_title, new_description,
            model_id=model_id,
        )
    return _analyze_thumbnails_with_key(
        api_key, thumbnail_data_list, new_title, new_description,
        model_id=model_id,
    )


def _analyze_thumbnails_with_key(
    api_key: str,
    thumbnail_data_list: list[tuple[bytes, str]],
    new_title: str,
    new_description: str,
    model_id: str = DEFAULT_GEMINI_MODEL,
) -> list[str]:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is not installed. Run: pip install Pillow")

    genai.configure(api_key=api_key.strip())
    vision_model = genai.GenerativeModel(
        model_name=model_id,
        safety_settings=_SAFETY,
    )

    prompts = []
    for image_bytes, _ in thumbnail_data_list[:3]:
        try:
            pil_img = PILImage.open(io.BytesIO(image_bytes))
            prompt_text = (
                f"Analyse this YouTube thumbnail carefully.\n\n"
                f"Describe: layout, background, main elements, color palette, "
                f"text style, visual effects, what makes it click-worthy.\n\n"
                f"Then write a detailed image generation prompt in English for a "
                f"SIMILAR thumbnail but adapted to this new video:\n"
                f"Title: {new_title}\n"
                f"Description: {new_description[:300]}\n\n"
                f"Keep the same visual style, mood and design approach.\n"
                f"Output ONLY the image generation prompt, nothing else."
            )
            resp = vision_model.generate_content([prompt_text, pil_img])
            prompts.append(resp.text.strip())
        except Exception as e:
            prompts.append(f"[Gemini thumbnail analysis failed: {e}]")

    styles = ["photorealistic dramatic", "bold minimalist", "vibrant neon pop-art"]
    while len(prompts) < 3:
        idx = len(prompts)
        prompts.append(
            f"{styles[idx % len(styles)]} YouTube thumbnail for '{new_title}', "
            f"high contrast, attention-grabbing, professional design"
        )
    return prompts[:3]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse(raw: str) -> dict:
    def extract(tag: str) -> str:
        m = re.search(
            rf"==={re.escape(tag)}===\s*(.*?)(?=====[A-ZА-Яa-zа-я\s\d]+===|$)",
            raw, re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    tags_raw = extract("TAGS")
    return {
        "script":            extract("SCRIPT"),
        "title":             extract("TITLE"),
        "description":       extract("DESCRIPTION"),
        "tags":              [t.strip() for t in tags_raw.split(",") if t.strip()],
        "thumbnail_prompts": [],
        "thumbnail_urls":    [],
    }


def count_chars(text: str) -> int:
    return len(text)
