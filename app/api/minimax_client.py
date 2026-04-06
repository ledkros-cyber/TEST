"""MiniMax Text-to-Audio API client."""
import os
import requests

MINIMAX_TTS_URL = "https://api.minimax.chat/v1/t2a_v2"

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
    if not api_key:
        raise RuntimeError("MiniMax API key is not set.")
    if not group_id:
        raise RuntimeError("MiniMax Group ID is not set.")

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

    url = f"{MINIMAX_TTS_URL}?GroupId={group_id}"
    resp = requests.post(url, headers=headers, json=payload, timeout=180)

    # Surface HTTP errors clearly
    try:
        resp.raise_for_status()
    except Exception:
        raise RuntimeError(
            f"MiniMax HTTP {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()
    base_resp = data.get("base_resp", {})
    status_code = base_resp.get("status_code", 0)
    if status_code != 0:
        raise RuntimeError(
            f"MiniMax API error {status_code}: "
            f"{base_resp.get('status_msg', 'Unknown error')}"
        )

    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("MiniMax returned empty audio data.")

    audio_bytes = bytes.fromhex(audio_hex)

    if not output_path:
        output_path = os.path.join(os.getcwd(), "output_audio.mp3")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    return output_path


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds based on character count."""
    # ~14 chars/sec at speed 1.0 for English
    chars = len(text)
    chars_per_sec = 14.0 * speed
    return chars / chars_per_sec
