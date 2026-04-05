"""Anthropic Claude API client for script generation."""
import re

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Supported languages for script generation
LANGUAGES = {
    "English":    "English",
    "Spanish":    "Spanish (Español)",
    "French":     "French (Français)",
    "German":     "German (Deutsch)",
    "Italian":    "Italian (Italiano)",
    "Portuguese": "Portuguese (Português)",
    "Russian":    "Russian (Русский)",
    "Japanese":   "Japanese (日本語)",
    "Korean":     "Korean (한국어)",
    "Chinese":    "Chinese Mandarin (中文)",
    "Arabic":     "Arabic (العربية)",
    "Hindi":      "Hindi (हिन्दी)",
    "Turkish":    "Turkish (Türkçe)",
    "Polish":     "Polish (Polski)",
    "Dutch":      "Dutch (Nederlands)",
    "Ukrainian":  "Ukrainian (Українська)",
}

SCRIPT_SYSTEM = """You are a professional YouTube video scriptwriter specializing in fitness and health content.
You create unique, engaging scripts that:
- Are completely original and do not copy source material
- Are optimized for YouTube algorithms (SEO)
- Use a conversational, engaging style
- Hook the viewer within the first 15 seconds
- Are structured: hook → main content → call-to-action
- Discuss the GENERAL benefits and science of exercise — never reference a specific exercise by name
- Can be used over any type of workout video footage
- Generate excitement and motivation in the viewer
"""


def generate_script(
    api_key: str,
    source_videos: list[dict],
    master_prompt: str = "",
    target_chars: int = 8000,
    language: str = "English",
) -> dict:
    """
    Generate a script about exercise benefits.
    source_videos is optional — used for SEO context only.
    Returns dict with: script, title, description, tags, thumbnail_prompts
    """
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package is not installed.")

    client = anthropic.Anthropic(api_key=api_key)

    # Build SEO context from source videos (optional)
    seo_context = ""
    if source_videos:
        seo_context = "\nSEO CONTEXT FROM TOP YOUTUBE VIDEOS ON THIS TOPIC:\n"
        for i, v in enumerate(source_videos[:5], 1):
            seo_context += f"\n--- Source {i} ---\n"
            seo_context += f"Title: {v.get('title', '')}\n"
            if v.get("tags"):
                seo_context += f"Tags: {', '.join(str(t) for t in v['tags'][:15])}\n"
            if v.get("description"):
                seo_context += f"Description excerpt: {v.get('description', '')[:400]}\n"

    # Build user prompt
    lang_display = language
    user_prompt = f"""
{master_prompt}

TASK:
Write a YouTube video script in {lang_display}.

STRICT RULES:
1. Write ENTIRELY in {lang_display} — every word, including the title, description, tags
2. Target length: approximately {target_chars} characters (±10%)
3. DO NOT mention any specific exercise by name (e.g., squats, push-ups, lunges, etc.)
4. Write about the GENERAL benefits, science, and motivation behind exercise/working out
5. The script must work over any workout video footage — keep it universal
6. Strong hook in the first 15 seconds
7. End with a call to subscribe and enable notifications
8. Use an energetic, motivating tone

{seo_context}

OUTPUT FORMAT (use these exact delimiters):

===SCRIPT===
[The full video script — approximately {target_chars} characters]

===TITLE===
[SEO-optimized YouTube title, max 70 characters, in {lang_display}]

===DESCRIPTION===
[YouTube description, 150-300 words, keyword-rich, in {lang_display}]

===TAGS===
[15-20 comma-separated tags in {lang_display}]

===PROMPT1===
[Thumbnail image prompt — photorealistic style, English only]

===PROMPT2===
[Thumbnail image prompt — minimalist/clean style, English only]

===PROMPT3===
[Thumbnail image prompt — bold/eye-catching style, English only]
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
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
        pattern = rf"==={re.escape(tag)}===\s*(.*?)(?=====\w|$)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    sections["script"]       = extract("SCRIPT")
    sections["title"]        = extract("TITLE")
    sections["description"]  = extract("DESCRIPTION")
    tags_raw = extract("TAGS")
    sections["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    prompts = []
    for i in (1, 2, 3):
        p = extract(f"PROMPT{i}")
        if p:
            prompts.append(p)
    sections["thumbnail_prompts"] = prompts

    return sections


def count_chars(text: str) -> int:
    return len(text)


def count_words(text: str) -> int:
    return len(text.split())
