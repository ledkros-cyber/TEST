import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "config.json")

DEFAULTS = {
    "youtube_api_key": "",
    "anthropic_api_key": "",
    "gemini_api_key": "",
    "gemini_api_keys": [],            # list of up to 10 Gemini API keys for rotation
    "gemini_key_index": 0,            # current active key index
    "gemini_model": "gemini-3.1-flash-preview",
    "ai_provider": "claude",          # "claude" or "gemini"
    "minimax_api_key": "",
    "minimax_group_id": "",
    "output_folder": "",
    "source_videos_folder": "",
    "quality": "1080p",
    "fps": 30,                         # GTX 1650 Ti: 30fps optimal, 60fps is very slow on CPU
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
    "subtitle_font_size": 18,
    "subtitle_font_color": "white",
    "subtitle_outline_color": "black",
    "subtitle_position": "bottom",
    "use_gpu": True,
    "parallel_workers": 2,             # i5-10300H + low free RAM: 2 is safer than 3
    "clip_min_dur": 3.0,
    "clip_max_dur": 5.0,
    "extra_seconds": 10.0,
    "voice_volume": 1.0,
    "bg_audio_volume": 0.05,
    "voice_vol_percent": 100,
    "bg_vol_percent": 5,
    "bg_music_path": "",
    "bg_music_volume": 0.12,
    "source_videos_folder": "",
    "output_folder": "",
    "min_views_filter": 100000,
    "date_filter": "all",
    "use_infographics": False,
}


LEGACY_MODELS = {
    "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b",
    "gemini-2.5-pro", "gemini-pro", "gemini-ultra",
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
    # Reset stale/deprecated model to the current default
    if data.get("gemini_model") in LEGACY_MODELS:
        data["gemini_model"] = DEFAULTS["gemini_model"]
    return data


def save_config(config: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
