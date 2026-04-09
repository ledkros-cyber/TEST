import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "config.json")

DEFAULTS = {
    "youtube_api_key": "AIzaSyB-3w_DiRP02WuLCbWSkk3yZjcR8vswe7o",
    "anthropic_api_key": "",
    "gemini_api_key": "AIzaSyD2TxtDZmpxfiU_l-mAtbK02tlHY2rm0mk",
    "gemini_api_keys": ["AIzaSyD2TxtDZmpxfiU_l-mAtbK02tlHY2rm0mk"],
    "gemini_key_index": 0,            # current active key index
    "gemini_model": "gemini-2.5-pro",
    "ai_provider": "gemini",
    "minimax_api_key": "sk-api-9KrhYMFovNR1Q4d3j4gj_l8ekHBQoQ3RDl56JJNtqDy-50t_pRaNxddJMclyPUQMJPKFfpXayjE95r_ApEvAn6sKMk3OgMkzKeAIntC4s8HYtrHx45t8qEE",
    "minimax_group_id": "1947674643892540352",
    "output_folder": "",
    "source_videos_folder": "",
    "quality": "1080p",
    "fps": 30,                         # GTX 1650 Ti: 30fps optimal, 60fps is very slow on CPU
    "bg_audio_volume": 0.05,
    "voice_id": "Deep_Voice_Man",
    "voice_speed": 1.0,
    "voice_volume": 1.0,
    "script_length": 800,
    "master_prompt": (
        "Перепиши мне этот сценарий на АНГЛИЙСКОМ языке, длина 18000 символов, "
        "сделай его интересным, динамичным, с полезными занимательными фактами, "
        "сильным хуком вначале сценария вовлекающим читателя дочитать его до конца, "
        "и удерживать на протяжении всего сценария. "
        "Стиль повествования такой же как в исходнике! Обязательно! "
        "Проверь себя после написания на количество символов что бы оно было "
        "в пределах того что я прописал в ТЗ выше. "
        "Текст должен быть сразу готов к озвучиванию без заголовков и подзаголовков, "
        "только голый текст для озвучки искусственным интелектом."
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
    "extra_seconds": 6.0,
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
    "gemini-pro", "gemini-ultra",
    # gemini-3.1-* models never existed — reset to real default
    "gemini-3.1-pro", "gemini-3.1-pro-preview",
    "gemini-3.1-flash", "gemini-3.1-flash-preview", "gemini-3.1-flash-lite-preview",
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
