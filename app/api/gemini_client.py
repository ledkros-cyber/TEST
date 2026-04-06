"""Google Gemini API client — uses new google-genai SDK (v1 API, not v1beta).
Install: pip install google-genai
Docs: https://ai.google.dev/gemini-api/docs
"""
import io
import re

# ── New SDK (google-genai, v1 API) ────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
    GEMINI_SDK = "new"
except ImportError:
    GEMINI_AVAILABLE = False
    GEMINI_SDK = "none"

# ── Pillow for Vision ─────────────────────────────────────────────────────────
try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────────────────────────

# Cascade order: most capable → least capable
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
    msg = str(e).lower()
    return (
        "404" in msg
        or "not found" in msg
        or "not supported" in msg
        or "deprecated" in msg
        or ("invalid" in msg and "model" in msg)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascade + rotation dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _call_with_cascade(fn, cfg: dict, *args,
                       model_id: str = DEFAULT_GEMINI_MODEL, **kwargs):
    """
    Try models from most→least capable, rotating keys on quota errors.
    - Quota error  → rotate to next key (same model)
    - Model 404    → skip to next model (try all keys first)
    - Other error  → raise immediately
    """
    keys = get_active_keys(cfg)
    if not keys:
        raise RuntimeError(
            "Gemini API key is not set.\n"
            "Go to Settings tab → enter your Gemini key.\n"
            "Free key: aistudio.google.com/app/apikey"
        )

    start_idx = (
        GEMINI_MODEL_CASCADE.index(model_id)
        if model_id in GEMINI_MODEL_CASCADE else 0
    )
    models_to_try = GEMINI_MODEL_CASCADE[start_idx:]
    start_key = cfg.get("gemini_key_index", 0) % len(keys)
    last_err = None

    for model in models_to_try:
        for ki in range(len(keys)):
            key_idx = (start_key + ki) % len(keys)
            key = keys[key_idx]
            try:
                result = fn(key, *args, model_id=model, **kwargs)
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
                    break        # model unavailable — skip all keys, try next model
                elif _is_quota_error(e):
                    continue     # quota — try next key
                else:
                    raise        # auth error, network, etc. — propagate

    tried = ", ".join(models_to_try)
    raise RuntimeError(
        f"All Gemini models/keys exhausted.\n"
        f"Models tried: {tried}\n"
        f"Keys tried: {len(keys)}\n"
        f"Last error: {last_err}\n\n"
        f"Tip: verify your key at aistudio.google.com/app/apikey"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal — build a client (new SDK uses v1 REST API, not v1beta)
# ─────────────────────────────────────────────────────────────────────────────

def _client(api_key: str):
    if not GEMINI_AVAILABLE:
        raise RuntimeError(
            "google-genai is not installed.\n"
            "Run: pip install google-genai\n"
            "Or re-run SETUP.bat to update dependencies."
        )
    return genai.Client(api_key=api_key.strip())


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
    client = _client(api_key)

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

    seen: set[str] = set()
    unique_tags: list[str] = []
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

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=SCRIPT_SYSTEM,
            temperature=0.85,
            max_output_tokens=8192,
        ),
    )

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
    client = _client(api_key)

    prompts: list[str] = []
    for image_bytes, _ in thumbnail_data_list[:3]:
        try:
            image_part = genai_types.Part.from_bytes(
                data=image_bytes, mime_type="image/jpeg"
            )
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
            resp = client.models.generate_content(
                model=model_id,
                contents=[prompt_text, image_part],
            )
            prompts.append(resp.text.strip())
        except Exception as e:
            prompts.append(f"[Thumbnail analysis failed: {e}]")

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
