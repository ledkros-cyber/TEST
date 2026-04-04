"""Anthropic Claude API client for script generation."""
import re

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

SCRIPT_SYSTEM = """Ты профессиональный сценарист YouTube-видео.
Ты создаёшь уникальные, захватывающие сценарии на основе анализа конкурентов.
Твои тексты:
- Полностью уникальны и не копируют источники
- Оптимизированы под алгоритмы YouTube (SEO)
- Написаны живым разговорным языком
- Удерживают внимание зрителя с первой секунды
- Структурированы: крючок → основная часть → призыв к действию
"""

def generate_script(
    api_key: str,
    source_videos: list[dict],
    master_prompt: str = "",
    target_words: int = 800,
    language: str = "ru",
) -> dict:
    """
    Generate a script based on analysed source videos.
    Returns dict with: script, title, description, tags, thumbnail_prompts
    """
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package is not installed.")

    client = anthropic.Anthropic(api_key=api_key)

    sources_text = ""
    for i, v in enumerate(source_videos, 1):
        sources_text += f"\n--- Источник {i} ---\n"
        sources_text += f"Заголовок: {v.get('title', '')}\n"
        sources_text += f"Описание: {v.get('description', '')[:1000]}\n"
        if v.get("tags"):
            sources_text += f"Теги: {', '.join(v['tags'][:20])}\n"
        if v.get("transcript"):
            sources_text += f"Субтитры (фрагмент): {v['transcript'][:2000]}\n"

    user_prompt = f"""
{master_prompt}

ИСТОЧНИКИ ДЛЯ АНАЛИЗА:
{sources_text}

ЗАДАНИЕ:
1. Напиши уникальный сценарий для YouTube-видео на РУССКОМ языке.
   - Примерная длина: {target_words} слов (±10%)
   - НЕ копируй источники — создай оригинальный контент на основе тематики
   - Начни с сильного крючка (hook) первые 15 секунд
   - В конце — призыв подписаться и включить уведомления

2. Придумай SEO-оптимизированный заголовок (до 70 символов)

3. Напиши описание для видео (150-300 слов), включи ключевые слова

4. Предложи 15-20 тегов через запятую

5. Предложи 3 разных промта для генерации превью (thumbnail) — на английском языке,
   каждый с другим визуальным стилем (реалистичный, минималистичный, яркий/кричащий)

Ответ дай СТРОГО в формате:

===СЦЕНАРИЙ===
[текст сценария]

===ЗАГОЛОВОК===
[заголовок]

===ОПИСАНИЕ===
[описание]

===ТЕГИ===
[теги через запятую]

===ПРОМТ 1===
[промт для превью 1]

===ПРОМТ 2===
[промт для превью 2]

===ПРОМТ 3===
[промт для превью 3]
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SCRIPT_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text
    return _parse_response(raw)


def _parse_response(raw: str) -> dict:
    sections = {
        "script": "",
        "title": "",
        "description": "",
        "tags": [],
        "thumbnail_prompts": [],
    }

    def extract(tag: str) -> str:
        pattern = rf"==={re.escape(tag)}===\s*(.*?)(?=====[A-ZА-Я\s\d]+===|$)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    sections["script"] = extract("СЦЕНАРИЙ")
    sections["title"] = extract("ЗАГОЛОВОК")
    sections["description"] = extract("ОПИСАНИЕ")
    tags_raw = extract("ТЕГИ")
    sections["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    prompts = []
    for i in (1, 2, 3):
        p = extract(f"ПРОМТ {i}")
        if p:
            prompts.append(p)
    sections["thumbnail_prompts"] = prompts

    return sections


def count_words(text: str) -> int:
    return len(text.split())
