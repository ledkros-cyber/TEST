"""MiniMax Text-to-Audio API client.
Based on official docs: https://platform.minimax.io/docs/llms.txt
"""
import os
import requests

# International endpoint (minimax.io) — no GroupId needed
# China endpoint (minimax.chat)        — requires ?GroupId=
_ENDPOINTS = [
    ("https://api.minimax.io/v1/t2a_v2",   False),   # (url, needs_group_id)
    ("https://api.minimax.chat/v1/t2a_v2", True),
]

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


def generate_audio(
    api_key: str,
    group_id: str,       # optional — only needed for minimax.chat
    text: str,
    voice_id: str = "English_Trustful_Man",
    speed: float = 1.0,
    volume: float = 1.0,
    model: str = DEFAULT_MODEL,
    output_path: str = "",
) -> str:
    """
    Send text to MiniMax TTS and save as MP3.
    Tries api.minimax.io first (no GroupId), then api.minimax.chat (with GroupId).
    Returns path to saved audio file.
    """
    api_key  = (api_key  or "").strip()
    group_id = (group_id or "").strip()

    if not api_key:
        raise RuntimeError(
            "MiniMax API key is not set.\n"
            "Go to Settings tab and enter your MiniMax API key."
        )

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

    errors = []

    for base_url, needs_group in _ENDPOINTS:
        # Build URL — only append GroupId for .chat endpoint
        if needs_group:
            if not group_id:
                errors.append(f"Skipped {base_url} — Group ID not set")
                continue
            url = f"{base_url}?GroupId={group_id}"
        else:
            url = base_url

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            errors.append(f"Connection error [{base_url}]: {e}")
            continue

        # 401 = definitely wrong key
        if resp.status_code == 401:
            raise RuntimeError(
                "MiniMax: HTTP 401 — API key is rejected.\n"
                "Open Settings, click 👁 next to MiniMax API Key "
                "and verify it matches exactly what is on platform.minimax.io."
            )

        if resp.status_code != 200:
            errors.append(f"HTTP {resp.status_code} [{base_url}]: {resp.text[:200]}")
            continue

        try:
            data = resp.json()
        except Exception:
            errors.append(f"Invalid JSON from {base_url}: {resp.text[:200]}")
            continue

        base_resp   = data.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)

        if status_code == 2049:
            raise RuntimeError(
                "MiniMax error 2049: invalid API key.\n"
                "Verify your key at platform.minimax.io — "
                "copy it again carefully, no spaces or quotes."
            )

        if status_code != 0:
            errors.append(
                f"API error {status_code}: {base_resp.get('status_msg','?')} [{base_url}]"
            )
            continue

        # Extract audio (hex-encoded per API spec)
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            errors.append(f"Empty audio data returned from {base_url}")
            continue

        audio_bytes = bytes.fromhex(audio_hex)

        if not output_path:
            output_path = os.path.join(os.getcwd(), "output_audio.mp3")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    raise RuntimeError(
        "MiniMax TTS failed on all endpoints.\n\n"
        + "\n".join(errors)
    )


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds (~14 chars/sec at speed=1.0)."""
    return len(text) / (14.0 * max(speed, 0.1))
