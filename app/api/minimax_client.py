"""MiniMax Text-to-Audio V2 API client.
Based on official MiniMax MCP source: github.com/MiniMax-AI/MiniMax-MCP

Endpoints:
  Global (modern JWT key, no GroupId): https://api.minimax.io/v1/t2a_v2
  China  (modern JWT key, no GroupId): https://api.minimaxi.com/v1/t2a_v2
  Global (legacy key, with GroupId):   https://api.minimax.io/v1/t2a_v2?GroupId={id}
  China  (legacy key, with GroupId):   https://api.minimaxi.com/v1/t2a_v2?GroupId={id}

Authentication: Authorization: Bearer {API_KEY}
Modern JWT keys (~126 chars) embed the GroupId — no URL param needed.
Legacy keys require ?GroupId= query param (19-digit account number).

Text limit: MiniMax T2A V2 accepts max ~4500 chars per request.
Long texts are automatically split at sentence boundaries and audio chunks
are concatenated into a single MP3 output file.
"""
import os
import re
import subprocess
import sys
import tempfile
import requests

try:
    from app.utils.logger import log
except Exception:
    log = None

# Windows: suppress console popups
_POPEN_FLAGS: dict = {}
if sys.platform == "win32":
    _POPEN_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# Max characters per single TTS request (MiniMax T2A V2 limit)
_MAX_CHARS = 4500

# ── Official endpoints ────────────────────────────────────────────────────────
_EP_GLOBAL  = "https://api.minimax.io/v1/t2a_v2"
_EP_CHINA   = "https://api.minimaxi.com/v1/t2a_v2"       # Mainland China — note: minimaxi.com

# ── Models (from official const.py, newest first) ────────────────────────────
MODELS = {
    "speech-2.8-hd":     "Speech 2.8 HD — best quality",
    "speech-2.8-turbo":  "Speech 2.8 Turbo — fast",
    "speech-2.6-hd":     "Speech 2.6 HD",
    "speech-2.6-turbo":  "Speech 2.6 Turbo",
    "speech-02-hd":      "Speech 02 HD",
    "speech-02-turbo":   "Speech 02 Turbo",
    "speech-01-hd":      "Speech 01 HD",
    "speech-01-turbo":   "Speech 01 Turbo",
}
DEFAULT_MODEL = "speech-2.6-hd"   # default per official MCP (speech-2.6-hd)

# ── Voice catalogue (M = Male, F = Female) ───────────────────────────────────
# Only standard preset voice IDs from official MiniMax API (no custom/clone IDs)
VOICES = {
    # ── English Male (universal, work on both endpoints) ─────────────────────
    "Deep_Voice_Man":            "[M] EN — Deep Voice Man",
    "Casual_Guy":                "[M] EN — Casual Guy",
    "Young_Knight":              "[M] EN — Young Knight",
    "Determined_Man":            "[M] EN — Determined Man",
    "Decent_Boy":                "[M] EN — Decent Boy",
    "Imposing_Manner":           "[M] EN — Imposing / Authoritative",
    "Elegant_Man":               "[M] EN — Elegant Man",
    "Patient_Man":               "[M] EN — Patient Man",
    "audiobook_male_1":          "[M] EN — Audiobook Narrator Male",
    # ── English Female ────────────────────────────────────────────────────────
    "Wise_Woman":                "[F] EN — Wise Woman",
    "Inspirational_Girl":        "[F] EN — Inspirational Girl",
    "Calm_Woman":                "[F] EN — Calm Woman",
    "Lively_Girl":               "[F] EN — Lively Girl",
    "Lovely_Girl":               "[F] EN — Lovely Girl",
    "Sweet_Girl_2":              "[F] EN — Sweet Girl",
    "Exuberant_Girl":            "[F] EN — Exuberant Girl",
    "Friendly_Person":           "[F] EN — Friendly Person",
    "audiobook_female_1":        "[F] EN — Audiobook Narrator Female",
    # ── Multilingual Male ─────────────────────────────────────────────────────
    "male-qn-qingse":            "[M] Multi — Young Male",
    "male-qn-jingying":          "[M] Multi — Business Male",
    # ── Multilingual Female ───────────────────────────────────────────────────
    "female-shaonv":             "[F] Multi — Young Female",
    "female-yujie":              "[F] Multi — Professional Female",
    "female-chengshu":           "[F] Multi — Mature Female",
}


def _split_text(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split text into chunks of at most max_chars at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    # Split at sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        # If single sentence is too long, split at commas/semicolons
        if len(sentence) > max_chars:
            parts = re.split(r'(?<=[,;])\s+', sentence)
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current = (current + " " + part).strip()
                else:
                    if current:
                        chunks.append(current)
                    # If even a single part is too long, hard-cut at max_chars
                    while len(part) > max_chars:
                        chunks.append(part[:max_chars])
                        part = part[max_chars:]
                    current = part
        elif len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


def _concat_mp3_chunks(chunk_paths: list[str], output_path: str) -> str:
    """Concatenate multiple MP3 files into one using FFmpeg concat demuxer."""
    # Find ffmpeg — try local bin first, then PATH
    ffmpeg = "ffmpeg"
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "bin", "ffmpeg.exe")
    if os.path.exists(local):
        ffmpeg = local

    # Write concat list file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in chunk_paths:
            safe = p.replace("'", "\\'")
            f.write(f"file '{safe}'\n")
        list_path = f.name

    try:
        cmd = [
            ffmpeg, "-y", "-hide_banner",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-500:]}")
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass

    return output_path


def _build_endpoints(group_id: str) -> list[tuple[str, str]]:
    """
    Return list of (url, label) to try, most-likely-to-work first.

    Modern JWT keys (~126 chars) embed GroupId in the token — no URL param needed.
    Try without GroupId first (endpoints 1 & 2), then with GroupId as fallback
    for legacy keys (endpoints 3 & 4), always in the same fixed order.
    """
    gid = (group_id or "").strip()

    endpoints = [
        (_EP_GLOBAL,                          "api.minimax.io (no GroupId)"),
        (_EP_CHINA,                           "api.minimaxi.com (no GroupId)"),
    ]
    if gid:
        endpoints += [
            (f"{_EP_GLOBAL}?GroupId={gid}",  "api.minimax.io (GroupId)"),
            (f"{_EP_CHINA}?GroupId={gid}",   "api.minimaxi.com (GroupId)"),
        ]
    return endpoints


def generate_audio(
    api_key: str,
    group_id: str,
    text: str,
    voice_id: str = "Deep_Voice_Man",
    speed: float = 1.0,
    volume: float = 1.0,
    model: str = DEFAULT_MODEL,
    output_path: str = "",
    language_boost: str = "auto",
) -> str:
    """
    Send text to MiniMax T2A V2 API and save result as MP3.
    Automatically splits long texts into chunks and concatenates the audio.
    MiniMax T2A V2 limit: ~4500 chars per request.
    Returns the path to the saved audio file.
    """
    api_key  = (api_key  or "").strip()
    group_id = (group_id or "").strip()
    text     = (text     or "").strip()

    if not api_key:
        raise RuntimeError(
            "MiniMax API key is not set.\n"
            "Go to Settings tab and enter your MiniMax API key."
        )

    if not output_path:
        output_path = os.path.join(os.getcwd(), "output_audio.mp3")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # ── Split long text into chunks and process each separately ──────────────
    chunks = _split_text(text, _MAX_CHARS)
    if len(chunks) > 1:
        if log:
            log.info(
                f"MiniMax: text too long ({len(text)} chars), "
                f"splitting into {len(chunks)} chunks"
            )
        chunk_paths: list[str] = []
        try:
            for i, chunk in enumerate(chunks):
                tmp = tempfile.NamedTemporaryFile(suffix=f"_chunk{i}.mp3", delete=False)
                tmp.close()
                chunk_path = _generate_audio_single(
                    api_key=api_key, group_id=group_id, text=chunk,
                    voice_id=voice_id, speed=speed, volume=volume,
                    model=model, output_path=tmp.name,
                    language_boost=language_boost,
                )
                chunk_paths.append(chunk_path)
                if log:
                    log.info(f"MiniMax: chunk {i+1}/{len(chunks)} done ({len(chunk)} chars)")
            _concat_mp3_chunks(chunk_paths, output_path)
            if log:
                log.info(f"MiniMax TTS success (chunked {len(chunks)} parts) → {output_path}")
            return output_path
        finally:
            for p in chunk_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # Single chunk — call directly
    return _generate_audio_single(
        api_key=api_key, group_id=group_id, text=text,
        voice_id=voice_id, speed=speed, volume=volume,
        model=model, output_path=output_path,
        language_boost=language_boost,
    )


def _generate_audio_single(
    api_key: str,
    group_id: str,
    text: str,
    voice_id: str = "Deep_Voice_Man",
    speed: float = 1.0,
    volume: float = 1.0,
    model: str = DEFAULT_MODEL,
    output_path: str = "",
    language_boost: str = "auto",
) -> str:
    """Send a single text chunk (≤4500 chars) to MiniMax and save as MP3."""

    key_hint = f"...{api_key[-6:]}" if len(api_key) > 6 else "(short key?)"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    # Build payload per official MCP source (minimax_mcp/server.py)
    payload: dict = {
        "model": model,
        "text":  text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed":    round(float(speed),  2),
            "vol":      round(float(volume), 2),
            "pitch":    0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate":     128000,
            "format":      "mp3",
            "channel":     1,
        },
    }
    if language_boost and language_boost != "auto":
        payload["language_boost"] = language_boost

    endpoints = _build_endpoints(group_id)
    errors: list[str] = []
    got_auth_error = False

    if log:
        log.info(
            f"MiniMax TTS start: model={model}, voice={voice_id}, "
            f"key_len={len(api_key)}, group_id={'set' if group_id else 'not set'}, "
            f"endpoints_to_try={len(endpoints)}"
        )

    for url, label in endpoints:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            err_msg = f"Connection error [{label}]: {e}"
            errors.append(err_msg)
            if log:
                log.api("MiniMax", label, error=f"ConnectionError: {e}")
            continue
        except requests.exceptions.Timeout:
            err_msg = f"Timeout [{label}]"
            errors.append(err_msg)
            if log:
                log.api("MiniMax", label, error="Timeout")
            continue

        if resp.status_code == 401:
            got_auth_error = True
            errors.append(f"HTTP 401 [{label}] — key rejected")
            if log:
                log.api("MiniMax", label, error="HTTP 401 key rejected")
            continue

        if resp.status_code != 200:
            errors.append(f"HTTP {resp.status_code} [{label}]: {resp.text[:200]}")
            if log:
                log.api("MiniMax", label, error=f"HTTP {resp.status_code}: {resp.text[:100]}")
            continue

        if log:
            log.api("MiniMax", label, status=resp.status_code)

        try:
            data = resp.json()
        except Exception:
            errors.append(f"Bad JSON [{label}]: {resp.text[:150]}")
            if log:
                log.api("MiniMax", label, error=f"Bad JSON: {resp.text[:80]}")
            continue

        base_resp   = data.get("base_resp", {})
        status_code = base_resp.get("status_code", -1)
        status_msg  = base_resp.get("status_msg", "unknown")

        if status_code == 2049:
            got_auth_error = True
            errors.append(f"Error 2049 (auth failed) [{label}]")
            if log:
                log.api("MiniMax", label, error="API error 2049 (auth failed)")
            continue

        if status_code != 0:
            errors.append(f"API error {status_code}: {status_msg} [{label}]")
            if log:
                log.api("MiniMax", label, error=f"API error {status_code}: {status_msg}")
            continue

        # ── Success — decode hex audio (official format) ──────────────────
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            errors.append(f"Empty audio field [{label}]")
            if log:
                log.api("MiniMax", label, error="Empty audio field in response")
            continue

        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError as e:
            errors.append(f"Bad audio hex [{label}]: {e}")
            if log:
                log.api("MiniMax", label, error=f"Bad audio hex: {e}")
            continue

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        if log:
            log.info(f"MiniMax TTS success via {label}, saved to {output_path}")
        return output_path

    # ── All endpoints failed ──────────────────────────────────────────────────
    attempts = "\n".join(f"  • {e}" for e in errors)

    if log:
        log.error(f"MiniMax TTS failed on all {len(endpoints)} endpoints. Errors: {'; '.join(errors)}")

    if got_auth_error:
        gid_info = (
            f"\n  Group ID: {group_id} (provided)"
            if group_id else
            "\n  Group ID: NOT SET — get it from Account → Group Info on platform.minimax.io"
        )
        raise RuntimeError(
            f"MiniMax authentication failed (error 2049).\n\n"
            f"Key (last 6 chars): {key_hint}  |  length: {len(api_key)}"
            f"{gid_info}\n\n"
            f"How to fix:\n"
            f"  1. Open platform.minimax.io → log in\n"
            f"  2. Account → API Keys → create or copy your key\n"
            f"  3. Account → Group Info → copy the 19-digit Group ID\n"
            f"  4. Paste BOTH into Settings tab of this app\n"
            f"  5. Make sure the key has 'T2A' (Text-to-Audio) permission\n\n"
            f"Tried {len(endpoints)} endpoints:\n{attempts}"
        )

    raise RuntimeError(
        f"MiniMax TTS failed on all endpoints.\n\n{attempts}"
    )


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds (~14 chars/sec at speed=1.0)."""
    return len(text) / (14.0 * max(speed, 0.1))
