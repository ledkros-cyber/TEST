import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "config.json")

DEFAULTS = {
    "youtube_api_key": "",
    "anthropic_api_key": "",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.0-flash",
    "ai_provider": "claude",          # "claude" or "gemini"
    "minimax_api_key": "",
    "minimax_group_id": "",
    "output_folder": "",
    "source_videos_folder": "",
    "quality": "1080p",
    "fps": 60,
    "bg_audio_volume": 0.05,
    "voice_id": "female-shaonv",
    "voice_speed": 1.0,
    "voice_volume": 1.0,
    "script_length": 800,
    "master_prompt": (
        "Ты профессиональный сценарист YouTube-видео. "
        "Пиши уникальный, увлекательный сценарий на русском языке, "
        "оптимизированный под алгоритмы YouTube. "
        "Используй разговорный стиль, держи зрителя вовлечённым."
    ),
    "noise_intensity": 8,
    "subtitle_font_size": 32,
    "subtitle_font_color": "white",
    "subtitle_outline_color": "black",
    "subtitle_position": "bottom",
    "use_gpu": True,
    "min_views_filter": 100000,
    "date_filter": "all",
}


def load_config() -> dict:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULTS.copy())
        return DEFAULTS.copy()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # merge missing defaults
    for k, v in DEFAULTS.items():
        if k not in data:
            data[k] = v
    return data


def save_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
