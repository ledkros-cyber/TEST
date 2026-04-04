"""MiniMax Text-to-Audio API client."""
import base64
import json
import os

import requests

MINIMAX_TTS_URL = "https://api.minimax.chat/v1/t2a_v2"

VOICES = {
    "female-shaonv": "Женский — Молодой (RU)",
    "male-qn-qingse": "Мужской — Молодой (RU)",
    "female-yujie": "Женский — Профессиональный (RU)",
    "male-qn-jingying": "Мужской — Деловой (RU)",
    "female-chengshu": "Женский — Зрелый (RU)",
    "audiobook_male_1": "Мужской — Рассказчик",
    "audiobook_female_1": "Женский — Рассказчик",
    "English_Trustful_Man": "Мужской — English",
    "English_ReliableMan": "Мужской — English 2",
}


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
            "speed": round(speed, 2),
            "vol": round(volume, 2),
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }

    url = f"{MINIMAX_TTS_URL}?GroupId={group_id}"
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()

    data = resp.json()

    # Check for API-level errors
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(
            f"MiniMax API error {base_resp.get('status_code')}: "
            f"{base_resp.get('status_msg', 'Unknown error')}"
        )

    audio_data = data.get("data", {}).get("audio", "")
    if not audio_data:
        raise RuntimeError("MiniMax returned empty audio data.")

    # audio is hex-encoded
    audio_bytes = bytes.fromhex(audio_data)

    if not output_path:
        output_path = os.path.join(os.getcwd(), "output_audio.mp3")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    return output_path


def get_audio_duration_estimate(text: str, speed: float = 1.0) -> float:
    """Estimate audio duration in seconds based on word count."""
    words = len(text.split())
    # Average speaking rate ~140 words/min at speed=1.0
    wpm = 140 * speed
    return (words / wpm) * 60
