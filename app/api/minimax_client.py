"""MiniMax Text-to-Audio API client."""
import os
import requests

MINIMAX_TTS_URL   = "https://api.minimax.chat/v1/t2a_v2"
MINIMAX_VOICE_URL = "https://api.minimax.chat/v1/get_voice_list"

# Full list of known MiniMax voices (static fallback)
VOICES: dict[str, str] = {
    # ── Female ───────────────────────────────────────────────────────────────
    "female-shaonv":        "Female — Young/Bright (EN/ZH)",
    "female-yujie":         "Female — Professional (EN/ZH)",
    "female-chengshu":      "Female — Mature/Elegant (EN/ZH)",
    "female-tianmei":       "Female — Sweet (ZH)",
    "Ava_multilingual":     "Ava — Multilingual Female",
    "Serena_multilingual":  "Serena — Multilingual Female",
    "audiobook_female_1":   "Female — Audiobook Narrator",
    "audiobook_female_2":   "Female — Audiobook Narrator 2",
    # ── Male ─────────────────────────────────────────────────────────────────
    "male-qn-qingse":       "Male — Young/Casual (EN/ZH)",
    "male-qn-jingying":     "Male — Business/Formal (EN/ZH)",
    "male-qn-badao":        "Male — Bold/Powerful (ZH)",
    "male-qn-daxuesheng":   "Male — Student/Friendly (ZH)",
    "Bowen_multilingual":   "Bowen — Multilingual Male",
    "Adam_multilingual":    "Adam — Multilingual Male",
    "audiobook_male_1":     "Male — Audiobook Narrator",
    "audiobook_male_2":     "Male — Audiobook Narrator 2",
    # ── English specialist ────────────────────────────────────────────────────
    "English_Trustful_Man": "English — Trustful Man",
    "English_ReliableMan":  "English — Reliable Man",
    "English_CalmWoman":    "English — Calm Woman",
    "English_EmotionalFemale": "English — Emotional Female",
    "English_WarmAunty":    "English — Warm Aunty",
    # ── Multilingual ─────────────────────────────────────────────────────────
    "Spanish_SentimentalF": "Spanish — Sentimental Female",
    "Spanish_ExpressiveM":  "Spanish — Expressive Male",
    "French_FriendlyF":     "French — Friendly Female",
    "French_CharmingM":     "French — Charming Male",
    "German_ReliableM":     "German — Reliable Male",
    "Portuguese_CalmF":     "Portuguese — Calm Female",
    "Russian_CalmF":        "Russian — Calm Female",
    "Japanese_FriendlyF":   "Japanese — Friendly Female",
    "Korean_WarmF":         "Korean — Warm Female",
}


def fetch_voices(api_key: str, group_id: str) -> dict[str, str]:
    """
    Fetch the full voice list from MiniMax API.
    Returns dict of {voice_id: display_name}.
    Falls back to the static VOICES dict on any error.
    """
    if not api_key or not group_id:
        return VOICES

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{MINIMAX_VOICE_URL}?GroupId={group_id}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, str] = {}
        # MiniMax returns voice list under different possible keys
        voice_list = (
            data.get("voice_list")
            or data.get("voices")
            or data.get("data", {}).get("voice_list")
            or []
        )
        for v in voice_list:
            vid   = v.get("voice_id") or v.get("id") or ""
            label = v.get("name") or v.get("display_name") or vid
            if vid:
                result[vid] = label

        return result if result else VOICES
    except Exception:
        return VOICES


def generate_audio(
    api_key: str,
    group_id: str,
    text: str,
    voice_id: str = "female-shaonv",
    speed: float = 1.0,
    volume: float = 1.0,
    output_path: str = "",
) -> str:
    """
    Send text to MiniMax TTS and save the audio file.
    Returns path to saved audio file.
    """
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
            "speed":    round(speed, 2),
            "vol":      round(volume, 2),
            "pitch":    0,
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
    resp.raise_for_status()

    data = resp.json()

    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(
            f"MiniMax API error {base_resp.get('status_code')}: "
            f"{base_resp.get('status_msg', 'Unknown error')}"
        )

    audio_data = data.get("data", {}).get("audio", "")
    if not audio_data:
        raise RuntimeError("MiniMax returned empty audio data.")

    audio_bytes = bytes.fromhex(audio_data)

    if not output_path:
        output_path = os.path.join(os.getcwd(), "output_audio.mp3")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    return output_path


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds based on character count."""
    # ~5 chars per word, ~140 wpm at speed 1.0
    words = len(text.split())
    wpm = 140 * speed
    return (words / wpm) * 60
