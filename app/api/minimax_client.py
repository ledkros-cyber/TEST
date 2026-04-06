"""MiniMax Text-to-Audio API client.
Official docs: https://platform.minimax.io/docs/llms.txt

Authentication:
  Header: Authorization: Bearer {API_KEY}
  GroupId: required — pass as URL query param ?GroupId=XXX

Endpoint strategy:
  Chinese accounts (group_id ≥ 16 digits)  → .chat first, then .io
  International accounts (short group_id)   → .io first, then .chat
  Also tries old /v1/t2a endpoint as last resort.
"""
import os
import requests

_BASE_IO   = "https://api.minimax.io/v1/t2a_v2"
_BASE_CHAT = "https://api.minimax.chat/v1/t2a_v2"
# Fallback: older T2A endpoint (v1, non-v2)
_BASE_IO_V1   = "https://api.minimax.io/v1/t2a"
_BASE_CHAT_V1 = "https://api.minimax.chat/v1/t2a"

# Models (newest first)
MODELS = {
    "speech-02-hd":     "Speech 02 HD (best quality)",
    "speech-02-turbo":  "Speech 02 Turbo (fast)",
    "speech-01-hd":     "Speech 01 HD",
    "speech-01-turbo":  "Speech 01 Turbo",
}
DEFAULT_MODEL = "speech-02-hd"

# Full voice catalogue
VOICES = {
    # ── English ──────────────────────────────────────────────────────────
    "English_Trustful_Man":      "EN — Trustful Man",
    "English_ReliableMan":       "EN — Reliable Man",
    "English_Friendly_Female":   "EN — Friendly Female",
    "English_Deep_Voice_Man":    "EN — Deep Voice Man",
    "English_Expressive_Female": "EN — Expressive Female",
    "English_Calm_Woman":        "EN — Calm Woman",
    "English_Lively_Girl":       "EN — Lively Girl",
    "English_Patient_Man":       "EN — Patient Man",
    "English_Narrator_Male":     "EN — Narrator Male",
    "English_Narrator_Female":   "EN — Narrator Female",
    "Wise_Woman":                "EN — Wise Woman",
    "Friendly_Person":           "EN — Friendly Person",
    "Inspirational_Girl":        "EN — Inspirational Girl",
    "Deep_Voice_Man":            "EN — Deep Voice Man 2",
    "Calm_Woman":                "EN — Calm Woman 2",
    "Casual_Guy":                "EN — Casual Guy",
    "Lively_Girl":               "EN — Lively Girl 2",
    "Patient_Man":               "EN — Patient Man 2",
    "Young_Knight":              "EN — Young Knight",
    "Determined_Man":            "EN — Determined Man",
    "Lovely_Girl":               "EN — Lovely Girl",
    "Decent_Boy":                "EN — Decent Boy",
    "Imposing_Manner":           "EN — Imposing (Authoritative)",
    "Elegant_Man":               "EN — Elegant Man",
    "Sweet_Girl_2":              "EN — Sweet Girl",
    "Exuberant_Girl":            "EN — Exuberant Girl",
    # ── Russian / Multilingual ────────────────────────────────────────────
    "female-shaonv":             "RU — Young Female",
    "male-qn-qingse":            "RU — Young Male",
    "female-yujie":              "RU — Professional Female",
    "male-qn-jingying":          "RU — Business Male",
    "female-chengshu":           "RU — Mature Female",
    "audiobook_male_1":          "RU — Narrator Male",
    "audiobook_female_1":        "RU — Narrator Female",
}


def _is_chinese_account(group_id: str) -> bool:
    """Chinese MiniMax accounts have 16+ digit numeric GroupIDs."""
    return group_id.isdigit() and len(group_id) >= 16


def _build_endpoints(group_id: str) -> list[str]:
    """Return list of URLs to try, most-likely-to-work first.

    Chinese accounts  → .chat first (their region), then .io
    International     → .io first, then .chat
    Also tries old T2A v1 endpoints as last resort.
    """
    gid = group_id.strip() if group_id else ""

    if gid:
        if _is_chinese_account(gid):
            # Chinese account: .chat is the primary endpoint
            return [
                f"{_BASE_CHAT}?GroupId={gid}",   # China primary
                f"{_BASE_IO}?GroupId={gid}",      # international fallback
                f"{_BASE_CHAT_V1}?GroupId={gid}", # old v1 China
                f"{_BASE_IO_V1}?GroupId={gid}",   # old v1 international
            ]
        else:
            # International account
            return [
                f"{_BASE_IO}?GroupId={gid}",      # international primary
                f"{_BASE_CHAT}?GroupId={gid}",    # China fallback
                f"{_BASE_IO_V1}?GroupId={gid}",   # old v1
            ]
    else:
        # No GroupId — try without it on both hosts
        return [
            _BASE_IO,
            _BASE_CHAT,
        ]


def generate_audio(
    api_key: str,
    group_id: str,
    text: str,
    voice_id: str = "English_Trustful_Man",
    speed: float = 1.0,
    volume: float = 1.0,
    model: str = DEFAULT_MODEL,
    output_path: str = "",
) -> str:
    """
    Send text to MiniMax TTS API and save result as MP3.
    Returns the path to the saved audio file.
    """
    api_key  = (api_key  or "").strip()
    group_id = (group_id or "").strip()

    if not api_key:
        raise RuntimeError(
            "MiniMax API key is not set.\n"
            "Go to Settings tab and enter your MiniMax API key."
        )

    key_hint = f"...{api_key[-6:]}" if len(api_key) > 6 else "(short key?)"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
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

    endpoints = _build_endpoints(group_id)
    errors: list[str] = []
    got_auth_error = False

    for url in endpoints:
        label = url.split("?")[0].replace("https://", "")
        has_gid = "GroupId" in url

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            errors.append(f"Connection error [{label}]: {e}")
            continue
        except requests.exceptions.Timeout:
            errors.append(f"Timeout [{label}]")
            continue

        # HTTP 401 — key flat-out rejected by HTTP layer
        if resp.status_code == 401:
            got_auth_error = True
            errors.append(f"HTTP 401 [{label}] — key rejected at HTTP level")
            continue

        if resp.status_code != 200:
            errors.append(f"HTTP {resp.status_code} [{label}]: {resp.text[:150]}")
            continue

        try:
            data = resp.json()
        except Exception:
            errors.append(f"Bad JSON [{label}]: {resp.text[:150]}")
            continue

        base_resp   = data.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)
        status_msg  = base_resp.get("status_msg", "unknown")

        # ── API-level errors ──────────────────────────────────────────────
        if status_code == 2049:
            got_auth_error = True
            errors.append(
                f"Error 2049 (invalid key{', GroupId=' + group_id if has_gid else ', no GroupId'}) "
                f"[{label}]"
            )
            continue

        if status_code != 0:
            errors.append(f"API error {status_code}: {status_msg} [{label}]")
            continue

        # ── Success — decode hex audio ────────────────────────────────────
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            errors.append(f"Empty audio field [{label}]")
            continue

        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError as e:
            errors.append(f"Bad audio hex [{label}]: {e}")
            continue

        if not output_path:
            output_path = os.path.join(os.getcwd(), "output_audio.mp3")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    # ── All endpoints failed ──────────────────────────────────────────────
    attempts = "\n".join(f"  • {e}" for e in errors)

    if got_auth_error:
        is_cn = _is_chinese_account(group_id)
        gid_hint = (
            f"\n  Group ID used: {group_id} ({'Chinese account detected' if is_cn else 'international format'})"
            if group_id
            else "\n  Group ID: NOT SET — required for most accounts!"
        )
        raise RuntimeError(
            f"MiniMax authentication failed (error 2049).\n\n"
            f"Key used (last 6 chars): {key_hint}  |  length: {len(api_key)}"
            f"{gid_hint}\n\n"
            f"Most common causes:\n"
            f"  A) Wrong API key — log in to platform.minimax.io → Account → API Keys\n"
            f"     Copy the key EXACTLY (it should start with 'eyJ...')\n"
            f"  B) Key has no T2A permission — check the key's permissions\n"
            f"     on platform.minimax.io → Account → API Keys → Edit\n"
            f"  C) Group ID mismatch — Account → Group Info → copy the number\n\n"
            f"Tried all {len(endpoints)} endpoints — all rejected the key.\n"
            f"All attempts:\n{attempts}"
        )

    raise RuntimeError(
        f"MiniMax TTS failed on all endpoints.\n\n{attempts}"
    )


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds (~14 chars/sec at speed=1.0)."""
    return len(text) / (14.0 * max(speed, 0.1))
