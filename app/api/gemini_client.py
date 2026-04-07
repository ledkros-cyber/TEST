"""Google Gemini API client — uses REST API v1beta directly (no SDK required).
Dynamic model discovery via ListModels endpoint — no hardcoded model IDs.
API docs: https://ai.google.dev/api/generate-content
"""
import base64
import re
import requests

# ─────────────────────────────────────────────────────────────────────────────
# Preference order for sorting discovered models (most capable first).
# Models not in this list get appended at the end in discovery order.
# ─────────────────────────────────────────────────────────────────────────────

_MODEL_PREFERENCE = [
    # Gemini 3.1
    "gemini-3.1-pro",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash",
    "gemini-3.1-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-image-preview",
    # Gemini 3.0
    "gemini-3-pro",
    "gemini-3-pro-preview",
    "gemini-3-flash",
    "gemini-3-flash-preview",
    # Gemini 2.5
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview",
    "gemini-2.5-flash-lite",
    # Gemini 2.0
    "gemini-2.0-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    # Gemini 1.5
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

# Fallback cascade — used ONLY when ListModels API call itself fails (network error etc.)
# Listed from newest to oldest so the first working one gets used
_FALLBACK_CASCADE = [
    "gemini-3.1-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]

# Display names for known models (shown in UI)
GEMINI_MODELS = {
    "gemini-3.1-pro":               "Gemini 3.1 Pro",
    "gemini-3.1-pro-preview":       "Gemini 3.1 Pro Preview — Latest flagship",
    "gemini-3.1-flash":             "Gemini 3.1 Flash",
    "gemini-3.1-flash-preview":     "Gemini 3.1 Flash Preview — Fast & capable",
    "gemini-3.1-flash-lite":        "Gemini 3.1 Flash Lite",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash Lite Preview",
    "gemini-3-pro-preview":         "Gemini 3 Pro Preview",
    "gemini-3-flash-preview":       "Gemini 3 Flash Preview",
    "gemini-3-flash":               "Gemini 3 Flash",
    "gemini-2.5-pro":               "Gemini 2.5 Pro",
    "gemini-2.5-flash":             "Gemini 2.5 Flash",
    "gemini-2.5-flash-preview":     "Gemini 2.5 Flash Preview",
    "gemini-2.0-flash":             "Gemini 2.0 Flash",
    "gemini-1.5-pro":               "Gemini 1.5 Pro",
    "gemini-1.5-flash":             "Gemini 1.5 Flash",
}

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-preview"   # currently most widely available

MAX_GEMINI_KEYS = 10

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

SCRIPT_SYSTEM = (
    "You are a professional YouTube scriptwriter. "
    "Create unique, engaging scripts based on competitor analysis. "
    "Scripts must be 100% original, SEO-optimised, conversational, "
    "hook the viewer in the first 15 seconds, and end with a call to action."
)

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from app.utils.logger import log
except Exception:
    log = None

GEMINI_AVAILABLE = True

# ─────────────────────────────────────────────────────────────────────────────
# Session-level model discovery cache  {api_key_prefix → [model_id, ...]}
# ─────────────────────────────────────────────────────────────────────────────

_discovered_models_cache: dict[str, list[str]] = {}


def _cache_key(api_key: str) -> str:
    """Use first 12 chars of key as cache key (avoids storing full key)."""
    return (api_key or "").strip()[:12]


def _discover_models(api_key: str) -> list[str]:
    """
    Query ListModels endpoint to find all models the key can use for generateContent.
    Returns models sorted by _MODEL_PREFERENCE (most capable first).
    Falls back to _FALLBACK_CASCADE on any error.
    """
    ck = _cache_key(api_key)
    if ck in _discovered_models_cache:
        return _discovered_models_cache[ck]

    key = api_key.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        resp = requests.get(url, timeout=15)
    except Exception:
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)

    if resp.status_code != 200:
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)

    try:
        data = resp.json()
    except Exception:
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)

    models_raw = data.get("models", [])
    available: list[str] = []
    for m in models_raw:
        name = m.get("name", "")           # e.g. "models/gemini-2.5-flash"
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        # Strip "models/" prefix
        model_id = name.removeprefix("models/")
        if not model_id:
            continue
        # Skip experimental/embed/vision-only models we don't want
        skip_keywords = ("embedding", "aqa", "retrieval", "learnlm", "vision-specialist")
        if any(kw in model_id.lower() for kw in skip_keywords):
            continue
        available.append(model_id)

    if not available:
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)

    # Sort by preference: preferred models first (by position in _MODEL_PREFERENCE)
    pref_index = {m: i for i, m in enumerate(_MODEL_PREFERENCE)}
    NOT_LISTED = len(_MODEL_PREFERENCE)

    def sort_key(m: str) -> tuple:
        # Exact match first, then check prefix (handles -preview variants not in list)
        idx = pref_index.get(m, NOT_LISTED)
        return (idx, m)

    available.sort(key=sort_key)

    _discovered_models_cache[ck] = available
    return available


def clear_model_cache():
    """Clear cached model lists (called after changing API keys)."""
    _discovered_models_cache.clear()


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
    return "quota" in msg or "429" in msg or "resource_exhausted" in msg or "rate" in msg


def _is_model_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "404" in msg or "not_found" in msg or "not found" in msg
        or "not supported" in msg or "deprecated" in msg
        or ("invalid" in msg and "model" in msg)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascade + rotation dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _call_with_cascade(fn, cfg: dict, *args,
                       model_id: str = DEFAULT_GEMINI_MODEL, **kwargs):
    keys = get_active_keys(cfg)
    if not keys:
        raise RuntimeError(
            "Gemini API key is not set.\n"
            "Go to Settings tab → Gemini API Keys → add your key.\n"
            "Free key: aistudio.google.com/app/apikey"
        )

    start_key = cfg.get("gemini_key_index", 0) % len(keys)
    last_err = None

    # Try each key; for each key discover its available models and cascade through them
    for ki in range(len(keys)):
        key_idx = (start_key + ki) % len(keys)
        key = keys[key_idx]

        # Discover models available for this specific key
        models_for_key = _discover_models(key)

        # If caller specified a preferred model and it's in the list, start from it;
        # otherwise start from the beginning (most capable)
        if model_id in models_for_key:
            start_model_idx = models_for_key.index(model_id)
        else:
            start_model_idx = 0

        models_to_try = models_for_key[start_model_idx:]
        if not models_to_try:
            models_to_try = models_for_key  # safety

        key_succeeded = False
        for model in models_to_try:
            if log:
                log.info(
                    f"Gemini attempt: key #{key_idx + 1}/{len(keys)}, model={model}"
                )
            try:
                result = fn(key, *args, model_id=model, **kwargs)
                cfg["gemini_key_index"]       = key_idx
                cfg["_last_gemini_model"]     = model
                cfg["_last_gemini_key_num"]   = key_idx + 1
                cfg["_last_gemini_key_total"] = len(keys)
                if log:
                    log.api(
                        "Gemini",
                        f"{model} (key #{key_idx + 1})",
                        status=200,
                    )
                try:
                    from app.config_manager import save_config
                    save_config(cfg)
                except Exception:
                    pass
                return result
            except Exception as e:
                last_err = e
                if log:
                    log.api(
                        "Gemini",
                        f"{model} (key #{key_idx + 1})",
                        error=str(e)[:200],
                    )
                if _is_model_error(e):
                    # This model doesn't work — remove from cache and try next
                    ck = _cache_key(key)
                    cached = _discovered_models_cache.get(ck, [])
                    if model in cached:
                        cached.remove(model)
                    continue
                elif _is_quota_error(e):
                    # Quota exhausted for this key — move to next key
                    key_succeeded = False
                    break
                else:
                    raise   # auth/network error — propagate immediately

    tried_models = list({m for k in keys for m in _discover_models(k)})
    tried_str = ", ".join(tried_models[:5]) + ("..." if len(tried_models) > 5 else "")
    raise RuntimeError(
        f"All Gemini models/keys exhausted.\n"
        f"Models tried: {tried_str}\n"
        f"Keys tried: {len(keys)}\n"
        f"Last error: {last_err}\n\n"
        f"Check your key at aistudio.google.com/app/apikey"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core REST call
# ─────────────────────────────────────────────────────────────────────────────

def _post_gemini(url: str, payload: dict) -> requests.Response:
    """POST to Gemini API, handle network errors."""
    try:
        return requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Network error reaching Gemini API: {e}")
    except requests.exceptions.Timeout:
        raise RuntimeError("Gemini API request timed out (>120s).")


def _parse_response(resp: requests.Response, model_id: str) -> str:
    """Parse Gemini response → text. Raise clear errors."""
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Gemini API key rejected (HTTP {resp.status_code}).\n"
            "Verify your key at aistudio.google.com/app/apikey"
        )
    if resp.status_code == 404:
        err = resp.json().get("error", {})
        raise RuntimeError(f"404 model not found: {err.get('message', model_id)}")
    if resp.status_code == 429:
        raise RuntimeError(f"Gemini quota exceeded (429) for model {model_id}.")
    if resp.status_code == 400:
        err = resp.json().get("error", {})
        raise RuntimeError(f"Gemini 400: {err.get('message', resp.text[:300])}")
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        block_reason = data.get("promptFeedback", {}).get("blockReason", "")
        if block_reason:
            raise RuntimeError(f"Gemini blocked the request: {block_reason}")
        raise RuntimeError(f"Unexpected Gemini response: {e}\n{str(data)[:400]}")


def _generate_content_rest(api_key: str, model_id: str, payload: dict) -> str:
    """
    Try v1beta first (supports system_instruction).
    If 404 (model not on v1beta), retry on v1 with system prompt merged into contents.
    """
    key = api_key.strip()

    # ── Attempt 1: v1beta (supports system_instruction) ──────────────────
    url_beta = f"{_GEMINI_BASE}/{model_id}:generateContent?key={key}"
    resp = _post_gemini(url_beta, payload)

    if resp.status_code == 404:
        # ── Attempt 2: v1 (no system_instruction — merge into contents) ──
        payload_v1 = dict(payload)
        sys_text = ""
        if "system_instruction" in payload_v1:
            parts = payload_v1.pop("system_instruction", {}).get("parts", [])
            sys_text = "\n".join(p.get("text", "") for p in parts).strip()

        if sys_text and "contents" in payload_v1:
            first = payload_v1["contents"][0]
            old_text = first["parts"][0].get("text", "")
            first["parts"][0]["text"] = f"{sys_text}\n\n{old_text}"

        url_v1 = f"https://generativelanguage.googleapis.com/v1/models/{model_id}:generateContent?key={key}"
        resp = _post_gemini(url_v1, payload_v1)

    return _parse_response(resp, model_id)


# ─────────────────────────────────────────────────────────────────────────────
# Public API — list available models for a key
# ─────────────────────────────────────────────────────────────────────────────

def get_available_models(cfg: dict) -> list[str]:
    """
    Return list of model IDs available for the first active key.
    Used by Settings UI to populate the model selector.
    Returns fallback list if no key configured or discovery fails.
    """
    keys = get_active_keys(cfg)
    if not keys:
        return list(_FALLBACK_CASCADE)
    return _discover_models(keys[0])


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

    user_prompt = f"""{master_prompt}

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

    payload = {
        "system_instruction": {
            "parts": [{"text": SCRIPT_SYSTEM}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 8192,
        },
    }

    raw = _generate_content_rest(api_key, model_id, payload)
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
    prompts: list[str] = []

    for image_bytes, _ in thumbnail_data_list[:3]:
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt_text = (
                f"Analyse this YouTube thumbnail carefully.\n\n"
                f"Describe: layout, background, main elements, color palette, "
                f"text style, visual effects, what makes it click-worthy.\n\n"
                f"Then write a detailed image generation prompt in English for a "
                f"SIMILAR thumbnail adapted to this new video:\n"
                f"Title: {new_title}\n"
                f"Description: {new_description[:300]}\n\n"
                f"Keep the same visual style, mood and design approach.\n"
                f"Output ONLY the image generation prompt, nothing else."
            )
            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    ],
                }],
            }
            text = _generate_content_rest(api_key, model_id, payload)
            prompts.append(text.strip())
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
