"""MiniMax Text-to-Audio API client.
Based on official docs: https://platform.minimax.io/docs/llms.txt
"""
import os
import requests

# All endpoint combinations to try, in order:
#   (url_template, needs_group_id_in_url)
# We try:
#   1. api.minimax.io  WITHOUT GroupId  (recommended for international)
#   2. api.minimax.io  WITH    GroupId  (some accounts need it even on .io)
#   3. api.minimax.chat WITH   GroupId  (China endpoint)
_ENDPOINTS = [
    ("https://api.minimax.io/v1/t2a_v2",   False),
    ("https://api.minimax.io/v1/t2a_v2",   True),    # .io + GroupId
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
    group_id: str,
    text: str,
    voice_id: str = "English_Trustful_Man",
    speed: float = 1.0,
    volume: float = 1.0,
    model: str = DEFAULT_MODEL,
    output_path: str = "",
) -> str:
    """
    Send text to MiniMax TTS and save as MP3.
    Tries multiple endpoint + GroupId combinations automatically.
    Returns path to saved audio file.
    """
    api_key  = (api_key  or "").strip()
    group_id = (group_id or "").strip()

    if not api_key:
        raise RuntimeError(
            "MiniMax API key is not set.\n"
            "Go to Settings tab and enter your MiniMax API key."
        )

    key_hint = f"...{api_key[-6:]}" if len(api_key) > 6 else "(short key)"

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

    errors: list[str] = []
    got_auth_error = False

    for base_url, needs_group in _ENDPOINTS:
        # Skip GroupId variants if no GroupId was given
        if needs_group and not group_id:
            continue

        url = f"{base_url}?GroupId={group_id}" if needs_group else base_url
        label = f"{base_url} {'(+GroupId)' if needs_group else '(no GroupId)'}"

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.ConnectionError as e:
            errors.append(f"Connection error [{label}]: {e}")
            continue
        except requests.exceptions.Timeout:
            errors.append(f"Timeout [{label}]")
            continue

        if resp.status_code == 401:
            got_auth_error = True
            errors.append(f"HTTP 401 [{label}] — key rejected")
            continue

        if resp.status_code != 200:
            errors.append(f"HTTP {resp.status_code} [{label}]: {resp.text[:120]}")
            continue

        try:
            data = resp.json()
        except Exception:
            errors.append(f"Invalid JSON [{label}]: {resp.text[:120]}")
            continue

        base_resp   = data.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)
        status_msg  = base_resp.get("status_msg", "?")

        if status_code == 2049:
            got_auth_error = True
            errors.append(f"Error 2049 (invalid key) [{label}]")
            continue    # try other endpoint combinations before giving up

        if status_code == 2013:
            errors.append(f"Error 2013 (no GroupId required) [{label}]")
            continue

        if status_code != 0:
            errors.append(f"API error {status_code}: {status_msg} [{label}]")
            continue

        # ── Success ──────────────────────────────────────────────────────
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            errors.append(f"Empty audio data [{label}]")
            continue

        audio_bytes = bytes.fromhex(audio_hex)
        if not output_path:
            output_path = os.path.join(os.getcwd(), "output_audio.mp3")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    # ── All endpoints failed ──────────────────────────────────────────────────
    if got_auth_error:
        raise RuntimeError(
            f"MiniMax: authentication failed (error 2049).\n\n"
            f"Key used: {key_hint} (length {len(api_key)})\n\n"
            f"What to check:\n"
            f"  1. Go to platform.minimax.io → Account → API Keys\n"
            f"  2. Create a NEW key and copy it completely\n"
            f"  3. In Settings tab click 👁 to reveal the saved key and compare\n"
            f"  4. Make sure you are using the key from platform.minimax.io\n"
            f"     (international), NOT from minimax.chat (China platform)\n"
            f"  5. If you have a Group ID, enter it in Settings too\n\n"
            f"Attempts made:\n" + "\n".join(f"  • {e}" for e in errors)
        )

    raise RuntimeError(
        "MiniMax TTS failed on all endpoints.\n\n"
        + "\n".join(f"  • {e}" for e in errors)
    )


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds (~14 chars/sec at speed=1.0)."""
    return len(text) / (14.0 * max(speed, 0.1))
