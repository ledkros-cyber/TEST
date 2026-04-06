"""Anthropic Claude API — script generation + thumbnail vision analysis."""
import base64
import re

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

SCRIPT_SYSTEM = """You are a professional YouTube scriptwriter.
You create unique, engaging video scripts based on competitor analysis.
Your scripts:
- Are 100% original and do not copy sources
- Are SEO-optimized for YouTube
- Use natural conversational language
- Hook the viewer in the first 15 seconds
- Follow structure: hook -> main content -> call to action
"""


def _client(api_key: str):
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package is not installed.")
    return anthropic.Anthropic(api_key=api_key)


def generate_script(
    api_key: str,
    source_videos: list[dict],
    master_prompt: str = "",
    target_chars: int = 3000,
    language: str = "ru",
) -> dict:
    """
    Generate script, title, description, tags (real + generated), thumbnail prompts.
    Returns: {script, title, description, tags, thumbnail_prompts, thumbnail_urls}
    """
    client = _client(api_key)

    # Collect real tags from source videos
    all_real_tags: list[str] = []
    sources_text = ""
    thumbnail_urls: list[str] = []

    for i, v in enumerate(source_videos, 1):
        sources_text += f"\n--- Source {i} ---\n"
        sources_text += f"Title: {v.get('title', '')}\n"
        sources_text += f"Description: {v.get('description', '')[:1200]}\n"
        vtags = v.get("tags", [])
        if vtags:
            sources_text += f"Tags: {', '.join(vtags[:30])}\n"
            all_real_tags.extend(vtags[:30])
        if v.get("transcript"):
            sources_text += f"Transcript (excerpt): {v['transcript'][:2500]}\n"
        if v.get("thumbnail"):
            thumbnail_urls.append(v["thumbnail"])

    # Deduplicate real tags, keep up to 40
    seen = set()
    unique_real_tags = []
    for t in all_real_tags:
        tl = t.lower().strip()
        if tl and tl not in seen:
            seen.add(tl)
            unique_real_tags.append(t.strip())
    unique_real_tags = unique_real_tags[:40]

    user_prompt = f"""{master_prompt}

COMPETITOR SOURCES TO ANALYSE:
{sources_text}

REAL TAGS EXTRACTED FROM SOURCE VIDEOS (use these as a base, add relevant ones):
{', '.join(unique_real_tags)}

TASK — write in {'Russian' if language == 'ru' else 'English'} language:

1. UNIQUE SCRIPT for a YouTube video.
   - Target length: {target_chars} characters (±10%)
   - Do NOT copy sources — create original content on the same topic
   - Start with a powerful hook (first 15 seconds)
   - End with a call to subscribe and enable notifications
   - Natural, conversational tone

2. SEO-OPTIMISED TITLE (max 70 characters)

3. VIDEO DESCRIPTION (150-300 words with keywords)

4. TAGS — use the real tags above as a base and supplement with relevant ones.
   Provide 20-30 tags separated by commas.

Reply STRICTLY in this format (keep the === markers exactly):

===SCRIPT===
[script text]

===TITLE===
[title]

===DESCRIPTION===
[description]

===TAGS===
[tags, separated by commas]
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=6000,
        system=SCRIPT_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text
    parsed = _parse_response(raw)
    parsed["thumbnail_urls"] = thumbnail_urls
    return parsed


def analyze_thumbnails(
    api_key: str,
    thumbnail_data_list: list[tuple[bytes, str]],   # [(image_bytes, source_title), ...]
    new_title: str,
    new_description: str,
) -> list[str]:
    """
    Analyse competitor thumbnail images and return image-generation prompts
    adapted to the new video title/description.

    Returns list of prompt strings (one per thumbnail, max 3).
    """
    client = _client(api_key)
    prompts = []

    for image_bytes, source_title in thumbnail_data_list[:3]:
        try:
            b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
            # Detect format
            media_type = "image/jpeg"
            if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                media_type = "image/png"
            elif image_bytes[:4] == b"RIFF":
                media_type = "image/webp"

            message = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=800,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"""Analyse this YouTube thumbnail image carefully and then write an image generation prompt.

Step 1 — Analyse the thumbnail:
- Overall layout and composition
- Background (color, texture, scene)
- Main visual elements (person, objects, text, graphics)
- Color palette and mood
- Text overlays (font style, size, color, placement)
- Visual effects (glow, shadows, contrasts, shapes)
- What makes it click-worthy / eye-catching

Step 2 — Write a detailed image generation prompt in English for a SIMILAR thumbnail but adapted to this NEW video:
Title: {new_title}
Description: {new_description[:300]}

Rules for the prompt:
- Keep the same visual style, layout, mood, and design approach as the analysed thumbnail
- Replace the topic/content with what matches the new title
- Make it maximally click-worthy and engaging
- Include specific details: colors, fonts, lighting, composition, style
- Output ONLY the image generation prompt, nothing else."""
                        }
                    ],
                }],
            )
            prompts.append(message.content[0].text.strip())
        except Exception as e:
            prompts.append(f"[Thumbnail analysis failed: {e}]")

    # If fewer than 3 thumbnails, add style variations
    styles = ["photorealistic dramatic", "bold minimalist", "vibrant neon pop-art"]
    while len(prompts) < 3:
        idx = len(prompts)
        prompts.append(
            f"{styles[idx % len(styles)]} YouTube thumbnail for video titled '{new_title}', "
            f"high contrast, attention-grabbing text overlay, professional design"
        )

    return prompts[:3]


def _parse_response(raw: str) -> dict:
    sections = {"script": "", "title": "", "description": "", "tags": [],
                "thumbnail_prompts": [], "thumbnail_urls": []}

    def extract(tag: str) -> str:
        pattern = rf"==={re.escape(tag)}===\s*(.*?)(?=====[A-ZА-Яa-zа-я\s\d]+===|$)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    sections["script"] = extract("SCRIPT")
    sections["title"] = extract("TITLE")
    sections["description"] = extract("DESCRIPTION")
    tags_raw = extract("TAGS")
    sections["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return sections


def count_chars(text: str) -> int:
    return len(text)


def count_words(text: str) -> int:
    return len(text.split())
