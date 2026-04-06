"""MiniMax Text-to-Audio API client."""
import os
import requests

# minimax.io  = international (most users outside China)
# minimax.chat = China region
# We try .io first, fall back to .chat
MINIMAX_URLS = [
    "https://api.minimax.io/v1/t2a_v2",
    "https://api.minimax.chat/v1/t2a_v2",
]

# Full voice catalogue — English first, then Russian/multilingual
VOICES = {
    # ── English ───────────────────────────────────────────────────────────
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
    "Abbess":                    "EN — Abbess (Female)",
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
    output_path: str = "",
) -> str:
    """Send text to MiniMax TTS and save the audio file. Returns path."""
    # Strip any accidental whitespace/newlines from credentials
    api_key  = api_key.strip()
    group_id = group_id.strip()

    if not api_key:
        raise RuntimeError("MiniMax API key is not set. Go to Settings tab.")
    if not group_id:
        raise RuntimeError("MiniMax Group ID is not set. Go to Settings tab.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "speech-01-turbo",
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": round(float(speed), 2),
            "vol":   round(float(volume), 2),
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate":     128000,
            "format":      "mp3",
            "channel":     1,
        },
    }

    # Try international endpoint first, then China region
    last_error = None
    for base_url in MINIMAX_URLS:
        url = f"{base_url}?GroupId={group_id}"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection failed to {base_url}: {e}"
            continue

        if resp.status_code == 401:
            raise RuntimeError(
                "MiniMax: invalid API key (401). "
                "Check your API key in Settings — use the 👁 button to verify it."
            )
        if resp.status_code != 200:
            last_error = f"HTTP {resp.status_code} from {base_url}: {resp.text[:300]}"
            continue

        data = resp.json()
        base_resp  = data.get("base_resp", {})
        status_code = base_resp.get("status_code", 0)

        if status_code == 2049:
            raise RuntimeError(
                "MiniMax error 2049: invalid API key.\n"
                "Fix: go to Settings tab, click 👁 next to MiniMax API Key "
                "and make sure it matches exactly what is shown on minimax.io "
                "(no extra spaces, no quotes)."
            )
        if status_code != 0:
            last_error = (
                f"MiniMax API error {status_code}: "
                f"{base_resp.get('status_msg', 'Unknown error')} "
                f"(endpoint: {base_url})"
            )
            continue

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError("MiniMax returned empty audio data.")

        # Success — decode and save
        audio_bytes = bytes.fromhex(audio_hex)
        if not output_path:
            output_path = os.path.join(os.getcwd(), "output_audio.mp3")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    raise RuntimeError(
        f"MiniMax TTS failed on all endpoints.\nLast error: {last_error}"
    )


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds based on character count."""
    # ~14 chars/sec at speed 1.0 for English
    chars = len(text)
    chars_per_sec = 14.0 * speed
    return chars / chars_per_sec
