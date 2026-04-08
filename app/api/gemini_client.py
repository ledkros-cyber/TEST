"""Google Gemini API client — uses the official Google Gen AI SDK (google-genai).
Dynamic model discovery via client.models.list() — Pro models only, flash/lite excluded.
SDK docs: https://googleapis.github.io/python-genai/
"""
import base64
import re

# ─────────────────────────────────────────────────────────────────────────────
# SDK import with fallback
# ─────────────────────────────────────────────────────────────────────────────

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_SDK_AVAILABLE = True
except ImportError:
    GEMINI_SDK_AVAILABLE = False
    genai = None
    genai_types = None

# ─────────────────────────────────────────────────────────────────────────────
# Logger (optional — app may not always provide one)
# ─────────────────────────────────────────────────────────────────────────────

try:
    from app.utils.logger import log
except Exception:
    log = None

# ─────────────────────────────────────────────────────────────────────────────
# Model constants — keep ALL for UI compatibility
# ─────────────────────────────────────────────────────────────────────────────

# User-configured preferred models (shown in UI selector)
# Only pro/thinking models — fast/flash models are hidden from the UI selector
# (they may still be used as fallback in the cascade if pro models hit quota)
GEMINI_MODELS = {
    "gemini-2.5-pro":                  "Gemini 2.5 Pro — Флагман (лучшее качество)",
    "gemini-2.5-pro-preview-03-25":    "Gemini 2.5 Pro Preview",
    "gemini-2.5-flash":                "Gemini 2.5 Flash",
    "gemini-2.5-flash-preview-04-17":  "Gemini 2.5 Flash Preview",
    "gemini-2.0-flash":                "Gemini 2.0 Flash",
    "gemini-1.5-pro":                  "Gemini 1.5 Pro — Большой контекст",
    "gemini-1.5-flash":                "Gemini 1.5 Flash",
}

DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"  # best available pro model

MAX_GEMINI_KEYS = 10

# ─────────────────────────────────────────────────────────────────────────────
# Model preference order — used for cascade + dynamic discovery sorting
# ─────────────────────────────────────────────────────────────────────────────

_MODEL_PREFERENCE = [
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview-03-25",
    "gemini-2.5-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.5-flash-preview",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-1.5-pro",
    "gemini-1.5-pro-001",
    "gemini-1.5-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-8b",
]

# Fallback cascade — used ONLY when model discovery itself fails (auth/network error)
# Pro/thinking models first, flash as last resort
_FALLBACK_CASCADE = [
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview-03-25",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

# ─────────────────────────────────────────────────────────────────────────────
# System instruction used for all script generation calls
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_SYSTEM = (
    "You are a professional YouTube scriptwriter. "
    "Create unique, engaging scripts based on competitor analysis. "
    "Scripts must be 100% original, SEO-optimised, conversational, "
    "hook the viewer in the first 15 seconds, and end with a call to action. "
    "If the script language is English, the title and description MUST also be in English."
)

# ─────────────────────────────────────────────────────────────────────────────
# Default generation config (shared base — overridden per-call via config arg)
# Temperature 0.75: balance creativity and logical narrative (per user requirements)
# max_output_tokens 8192: scripts are long texts
# ─────────────────────────────────────────────────────────────────────────────

# Note: system_instruction is set per-call, not here
_GEN_CONFIG_DEFAULTS = dict(
    temperature=0.75,
    max_output_tokens=8192,
)

GEMINI_AVAILABLE = True  # kept for backward compat

# ─────────────────────────────────────────────────────────────────────────────
# Session-level token usage counter
# ─────────────────────────────────────────────────────────────────────────────

_session_tokens: dict = {"input": 0, "output": 0, "total": 0, "requests": 0}


def get_session_token_stats() -> dict:
    """Return copy of session token usage statistics."""
    return dict(_session_tokens)


def reset_session_tokens() -> None:
    """Reset session token counters."""
    _session_tokens.update({"input": 0, "output": 0, "total": 0, "requests": 0})

# ─────────────────────────────────────────────────────────────────────────────
# SDK client factory
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(api_key: str) -> "genai.Client":
    """Create and return a google-genai Client for the given API key."""
    return genai.Client(api_key=api_key.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Session-level model discovery cache  {api_key_prefix → [model_id, ...]}
# ─────────────────────────────────────────────────────────────────────────────

_discovered_models_cache: dict[str, list[str]] = {}


def _cache_key(api_key: str) -> str:
    """Use first 12 chars of key as cache key (avoids storing the full key)."""
    return (api_key or "").strip()[:12]


def _discover_models(api_key: str) -> list[str]:
    """
    Query available models via SDK client.models.list().
    Returns model IDs that support generateContent, sorted by _MODEL_PREFERENCE.
    Falls back to _FALLBACK_CASCADE on any error.
    """
    ck = _cache_key(api_key)
    if ck in _discovered_models_cache:
        return _discovered_models_cache[ck]

    if not GEMINI_SDK_AVAILABLE:
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)

    try:
        client = _make_client(api_key)
        available: list[str] = []

        for model in client.models.list():
            name: str = getattr(model, "name", "") or ""
            # Strip "models/" prefix that the API returns
            model_id = name.removeprefix("models/") if name.startswith("models/") else name
            if not model_id:
                continue

            # Filter to only models that support content generation
            methods = getattr(model, "supported_generation_methods", None) or []
            if "generateContent" not in methods:
                continue

            mid_lower = model_id.lower()

            # Skip embedding, retrieval and other non-generation models
            skip_keywords = ("embedding", "aqa", "retrieval", "learnlm", "vision-specialist")
            if any(kw in mid_lower for kw in skip_keywords):
                continue

            # STRICT: only Pro models allowed — flash and lite are too weak for scripts
            banned_keywords = ("flash", "lite")
            if any(kw in mid_lower for kw in banned_keywords):
                continue

            # Must contain "pro" to be a quality model
            if "pro" not in mid_lower:
                continue

            available.append(model_id)

        if not available:
            _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
            return list(_FALLBACK_CASCADE)

        # Sort by preference: preferred models first (by position in _MODEL_PREFERENCE)
        pref_index = {m: i for i, m in enumerate(_MODEL_PREFERENCE)}
        not_listed = len(_MODEL_PREFERENCE)

        def sort_key(m: str) -> tuple:
            # Exact match first, then preserve discovery order for unknown models
            return (pref_index.get(m, not_listed), m)

        available.sort(key=sort_key)

        _discovered_models_cache[ck] = available
        return available

    except Exception as exc:
        if log:
            log.info(f"Gemini model discovery failed, using fallback cascade: {exc}")
        _discovered_models_cache[ck] = list(_FALLBACK_CASCADE)
        return list(_FALLBACK_CASCADE)


def clear_model_cache() -> None:
    """Clear cached model lists (call after changing API keys)."""
    _discovered_models_cache.clear()


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Validate a Gemini API key by calling models.list().
    Returns (ok: bool, message: str).
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "Ключ не введён."
    if not GEMINI_SDK_AVAILABLE:
        return False, "google-genai не установлен. Запустите: pip install google-genai"
    try:
        client = _make_client(api_key)
        models_found = []
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            mid = name.removeprefix("models/")
            methods = getattr(m, "supported_generation_methods", None) or []
            if "generateContent" in methods and "pro" in mid.lower():
                models_found.append(mid)
            if len(models_found) >= 3:
                break
        if models_found:
            return True, f"Ключ рабочий. Pro-модели: {', '.join(models_found[:3])}"
        return True, "Ключ рабочий (Pro-модели не найдены, возможно нет доступа)."
    except Exception as exc:
        e_str = str(exc)
        if "leaked" in e_str.lower() or "reported" in e_str.lower():
            return False, "Ключ скомпрометирован (leaked). Создайте новый на aistudio.google.com/app/apikey"
        if "expired" in e_str.lower():
            return False, "Ключ истёк. Создайте новый на aistudio.google.com/app/apikey"
        if "api key" in e_str.lower() or "invalid" in e_str.lower() or "400" in e_str or "403" in e_str:
            return False, "Неверный API-ключ. Проверьте ключ на aistudio.google.com/app/apikey"
        if "429" in e_str or "quota" in e_str.lower():
            return True, "Ключ рабочий, но квота исчерпана (лимит запросов)."
        return False, f"Ошибка: {e_str[:150]}"


# ─────────────────────────────────────────────────────────────────────────────
# Core SDK call — replaces _post_gemini / _parse_response / _generate_content_rest
# ─────────────────────────────────────────────────────────────────────────────

def _generate_with_sdk(
    api_key: str,
    model_id: str,
    user_prompt: str,
    system_instruction: str = "",
    image_data_list: list[tuple[bytes, str]] | None = None,
) -> str:
    """
    Send a request to Gemini using the official SDK.

    Supports:
    - Text-only prompts
    - Multi-modal (text + images via inline_data)
    - System instructions
    - Per-call generation config (temperature=0.75, max_output_tokens=8192)

    Error handling:
    - 404 errors → raise RuntimeError with "404" in message (triggers model cascade)
    - 429 / quota errors → raise RuntimeError with "quota" in message (triggers key rotation)
    - Auth errors → raise RuntimeError with HTTP code in message
    - Other errors → re-raise with clear message
    """
    if not GEMINI_SDK_AVAILABLE:
        raise RuntimeError(
            "google-genai not installed. Run: pip install google-genai"
        )

    client = _make_client(api_key)

    # Build the parts list: images first (if any), then the text prompt
    types = genai_types
    parts = []
    if image_data_list:
        for img_bytes, mime_type in image_data_list:
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))
    parts.append(types.Part.from_text(text=user_prompt))

    contents = [types.Content(role="user", parts=parts)]

    # Per-call config — system_instruction included when provided
    config = types.GenerateContentConfig(
        system_instruction=system_instruction if system_instruction else None,
        temperature=0.75,
        max_output_tokens=8192,
    )

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
        )
    except Exception as exc:
        # Map SDK errors to messages our cascade understands
        e_str = str(exc)
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)

        if code == 404 or "404" in e_str or "not found" in e_str.lower():
            raise RuntimeError(
                f"404 model not found: {model_id} — {e_str[:200]}"
            )
        if (
            code == 429
            or "429" in e_str
            or "quota" in e_str.lower()
            or "resource_exhausted" in e_str.lower()
        ):
            raise RuntimeError(
                f"Gemini quota exceeded (429) for model {model_id}.\n\n"
                f"Бесплатный лимит Gemini Pro: 50 запросов в день / 2 в минуту.\n"
                f"Подождите минуту или добавьте другой API-ключ в Настройках."
            )
        if (
            code in (401, 403)
            or "api key" in e_str.lower()
            or "invalid" in e_str.lower()
        ):
            raise RuntimeError(
                f"Gemini API key rejected (HTTP {code}): {e_str[:200]}"
            )
        raise RuntimeError(f"Gemini SDK error: {e_str[:300]}")

    # Track token usage from usageMetadata
    try:
        meta = getattr(response, "usage_metadata", None)
        if meta:
            inp = getattr(meta, "prompt_token_count", 0) or 0
            out = getattr(meta, "candidates_token_count", 0) or 0
            tot = getattr(meta, "total_token_count", 0) or (inp + out)
            _session_tokens["input"]    += inp
            _session_tokens["output"]   += out
            _session_tokens["total"]    += tot
            _session_tokens["requests"] += 1
    except Exception:
        pass

    # Extract text from the response
    try:
        return response.text
    except Exception:
        # Check whether the request was blocked
        feedback = getattr(response, "prompt_feedback", None)
        if feedback and getattr(feedback, "block_reason", None):
            raise RuntimeError(f"Gemini blocked: {feedback.block_reason}")
        raise RuntimeError(f"Empty Gemini response for model {model_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Key helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_active_keys(cfg: dict) -> list[str]:
    """Return a list of non-empty Gemini API keys from the config dict."""
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
    """Return True if the exception looks like a quota / rate-limit error."""
    msg = str(e).lower()
    return "quota" in msg or "429" in msg or "resource_exhausted" in msg or "rate" in msg


def _is_key_invalid_error(e: Exception) -> bool:
    """Return True if the key itself is invalid/expired/revoked — try next key."""
    msg = str(e).lower()
    return (
        "expired" in msg
        or "leaked" in msg
        or "api_key_invalid" in msg
        or "key rejected" in msg
        or ("400" in msg and ("invalid" in msg or "expired" in msg))
        or ("403" in msg and "key" in msg)
        or "permission_denied" in msg
    )


def _is_model_error(e: Exception) -> bool:
    """Return True if the exception indicates the model is unavailable / not found."""
    msg = str(e).lower()
    return (
        "404" in msg or "not_found" in msg or "not found" in msg
        or "not supported" in msg or "deprecated" in msg
        or ("invalid" in msg and "model" in msg)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascade + key-rotation dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _call_with_cascade(fn, cfg: dict, *args,
                       model_id: str = DEFAULT_GEMINI_MODEL, **kwargs):
    """
    Call fn(api_key, *args, model_id=..., **kwargs) with automatic:
    - Key rotation (cycles through all configured keys)
    - Model cascade (falls through discovered models on 404)
    - Quota handling (moves to next key on 429)

    fn must accept (api_key: str, ..., model_id: str) as its signature.
    """
    keys = get_active_keys(cfg)
    if not keys:
        raise RuntimeError(
            "Gemini API key не задан.\n"
            "Перейди в Настройки → Gemini API Keys → добавь ключ.\n"
            "Бесплатный ключ: aistudio.google.com/app/apikey"
        )

    start_key = cfg.get("gemini_key_index", 0) % len(keys)
    last_err = None
    quota_exhausted_keys: list[int] = []   # key indices that hit quota

    if log:
        log.info(f"Gemini start: {len(keys)} key(s) available, starting from key #{start_key + 1}")

    # Try each key; for each key discover its available models and cascade through them
    for ki in range(len(keys)):
        key_idx = (start_key + ki) % len(keys)
        key = keys[key_idx]

        # Discover models available for this specific key
        models_for_key = _discover_models(key)

        # If the caller specified a preferred model and it's available, start from it;
        # otherwise start from the beginning (most capable)
        if model_id in models_for_key:
            start_model_idx = models_for_key.index(model_id)
        else:
            start_model_idx = 0

        models_to_try = models_for_key[start_model_idx:]
        if not models_to_try:
            models_to_try = models_for_key  # safety fallback

        for model in models_to_try:
            if log:
                log.info(
                    f"Gemini attempt: key #{key_idx + 1}/{len(keys)}, model={model}"
                )
            try:
                result = fn(key, *args, model_id=model, **kwargs)
                # Persist successful key index and metadata
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
                    # This model doesn't work — evict from cache and try the next one
                    ck = _cache_key(key)
                    cached = _discovered_models_cache.get(ck, [])
                    if model in cached:
                        cached.remove(model)
                    continue
                elif _is_quota_error(e):
                    # Quota exhausted for this key — switch to next key
                    quota_exhausted_keys.append(key_idx + 1)
                    next_key_num = ((key_idx + 1) % len(keys)) + 1
                    if log:
                        remaining = len(keys) - len(quota_exhausted_keys)
                        if remaining > 0:
                            log.info(
                                f"Ключ #{key_idx + 1} — квота исчерпана. "
                                f"Переключаюсь на ключ #{next_key_num} "
                                f"(осталось ключей: {remaining})"
                            )
                        else:
                            log.info(
                                f"Ключ #{key_idx + 1} — квота исчерпана. "
                                f"Все {len(keys)} ключ(а/ей) исчерпаны."
                            )
                    break
                elif _is_key_invalid_error(e):
                    # Key is expired/revoked/leaked — skip to next key
                    if log:
                        log.info(
                            f"Ключ #{key_idx + 1} — недействителен (истёк/отозван). "
                            f"Переключаюсь на следующий ключ."
                        )
                    break
                else:
                    raise  # network errors — propagate immediately

    # Build a clear final error message
    if quota_exhausted_keys and len(quota_exhausted_keys) == len(keys):
        raise RuntimeError(
            f"Квота исчерпана на всех {len(keys)} ключ(а/ей).\n\n"
            f"Бесплатный лимит Gemini Pro: 50 запросов в день / 2 в минуту.\n"
            f"Добавь ещё ключи в Настройках или подожди до завтра.\n"
            f"Новый ключ: aistudio.google.com/app/apikey"
        )
    last_err_str = str(last_err).lower()
    if "expired" in last_err_str or "invalid" in last_err_str or "leaked" in last_err_str:
        raise RuntimeError(
            f"Все {len(keys)} Gemini API ключ(а/ей) недействительны.\n\n"
            f"Причина: ключи истекли, отозваны или скомпрометированы.\n\n"
            f"Создай новые ключи на: aistudio.google.com/app/apikey\n"
            f"Затем добавь их в Настройки → Gemini API Keys."
        )
    tried_models = list({m for k in keys for m in _discover_models(k)})
    tried_str = ", ".join(tried_models[:5]) + ("..." if len(tried_models) > 5 else "")
    raise RuntimeError(
        f"Не удалось получить ответ от Gemini.\n"
        f"Проверено ключей: {len(keys)}, моделей: {tried_str}\n"
        f"Последняя ошибка: {last_err}\n\n"
        f"Проверь ключи на aistudio.google.com/app/apikey"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API — list available models for a key
# ─────────────────────────────────────────────────────────────────────────────

def get_available_models(cfg: dict) -> list[str]:
    """
    Return list of model IDs available for the first active key.
    Used by Settings UI to populate the model selector.
    Returns fallback list if no key is configured or discovery fails.
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
    """
    Generate a YouTube script from competitor source videos.

    When cfg is provided, uses key rotation + model cascade via _call_with_cascade.
    Otherwise calls directly with api_key (useful for single-key usage).
    """
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
    """Internal: generate a script using a specific key and model."""
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

    # Deduplicate tags preserving order
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

    raw = _generate_with_sdk(
        api_key=api_key,
        model_id=model_id,
        user_prompt=user_prompt,
        system_instruction=SCRIPT_SYSTEM,
    )
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
    """
    Analyse competitor thumbnails and generate image-generation prompts.

    Returns a list of up to 3 image-generation prompt strings.
    When cfg is provided, uses key rotation + model cascade.
    """
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
    """Internal: analyse thumbnails using a specific key and model via SDK."""
    prompts: list[str] = []

    for image_bytes, mime_type in thumbnail_data_list[:3]:
        try:
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
            text = _generate_with_sdk(
                api_key=api_key,
                model_id=model_id,
                user_prompt=prompt_text,
                image_data_list=[(image_bytes, mime_type)],
            )
            prompts.append(text.strip())
        except Exception as e:
            prompts.append(f"[Thumbnail analysis failed: {e}]")

    # Pad to 3 prompts with generic fallbacks if we received fewer images
    styles = ["photorealistic dramatic", "bold minimalist", "vibrant neon pop-art"]
    while len(prompts) < 3:
        idx = len(prompts)
        prompts.append(
            f"{styles[idx % len(styles)]} YouTube thumbnail for '{new_title}', "
            f"high contrast, attention-grabbing, professional design"
        )
    return prompts[:3]


# ─────────────────────────────────────────────────────────────────────────────
# Script parsing helper
# ─────────────────────────────────────────────────────────────────────────────

def _parse(raw: str) -> dict:
    """
    Parse the structured ===SECTION=== response format produced by the LLM.
    Returns a dict with keys: script, title, description, tags,
    thumbnail_prompts, thumbnail_urls.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────

def count_chars(text: str) -> int:
    """Return character count of text."""
    return len(text)
