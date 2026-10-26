import json
import time
from google import genai
from PIL import Image
from src.config import GEMINI_API_KEY, CONFIG

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_PROMPT = """You are an expert at extracting vocabulary, idioms, and phrases from screenshots, translator apps, text snippets, and videos to create structured Anki flashcards.

STRICT DUPLICATE & SYNONYM CONSOLIDATION RULE (CRITICAL):
- Avoid creating multiple separate flashcards for synonyms, variants, or similar table entries shown in a single screenshot/text.
- ALWAYS combine closely related words into a SINGLE card:
  - Expression: "второпях / впопыхах"
  - PrimaryMeaning: "in größter / großer Hast"
- If entries are distinct, pick ONLY the most relevant primary term instead of spamming multiple cards.

ABSOLUTE TOP PRIORITY RULE (VISUAL HIGHLIGHTS / RED MARKINGS):
- FIRST AND FOREMOST: Check if any part of the image/video/text is visually highlighted or marked in RED.
- Whatever text or word is highlighted or emphasized is the PRIMARY TARGET TO EXTRACT.

SINGLE TEXT WORD HANDLING:
- If the user types a single word (e.g. "hast", "Hast", "abbrechen"), DO NOT DISCARD IT.
- Check if it can be a Noun (e.g., "hast" -> "die Hast"). Always include the correct German article for nouns!

LANGUAGE & TRANSLATION RULES:
1. ENGLISH TARGETS:
   - Translate strictly into GERMAN ONLY ("PrimaryMeaning").
2. GERMAN TARGETS:
   - Translate into RUSSIAN ("PrimaryMeaning").

REQUIRED FIELDS FOR ALL CARDS:
1. EXAMPLE SENTENCE: At least one clear, natural example sentence MUST be provided.
2. NOUN & VERB DETAILS: Include articles, plural forms, or verb conjugations in Grammar.

RETURN ONLY VALID JSON:
{
  "type": "vocabulary" | "resource" | "irrelevant",
  "cards": [
    {
      "Expression": "Target word/expression or combined synonyms",
      "PrimaryMeaning": "Translation",
      "Meanings": "Secondary meanings or nuances",
      "ExampleSentence": "Clear example sentence",
      "Grammar": "Part of speech, noun article/plural, or verb forms",
      "CEFR": "B2/C1",
      "SynonymsAntonyms": null,
      "PersonalNote": "Additional context",
      "Source": "Telegram",
      "WordType": "Adverb / Noun / Verb / Idiom",
      "Tags": "Vocabulary::German",
      "Confidence": "high"
    }
  ]
}
"""

def analyze_input(contents, user_caption: str = None) -> dict:
    prompt = SYSTEM_PROMPT
    if user_caption:
        prompt += f"\n\nADDITIONAL USER INPUT / CAPTION:\n\"{user_caption}\""

    full_contents = contents + [prompt]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=CONFIG.get("model_name", "gemini-3.5-flash-lite"),
                contents=full_contents,
                config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            err_msg = str(e)
            if ("503" in err_msg or "429" in err_msg) and attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                raise e

def analyze_image(image_path: str, user_caption: str = None) -> dict:
    img = Image.open(image_path)
    return analyze_input([img], user_caption=user_caption)

def analyze_multiple_images(image_paths: list, user_caption: str = None) -> dict:
    images = [Image.open(p) for p in image_paths]
    return analyze_input(images, user_caption=user_caption)

def analyze_text(text: str) -> dict:
    return analyze_input([f"TEXT TO PROCESS:\n{text}"], user_caption=None)

def analyze_video(video_path: str, user_caption: str = None) -> dict:
    video_file = client.files.upload(file=video_path)

    # Wait with timeout (max 45 seconds)
    max_wait = 45
    waited = 0
    while video_file.state.name == "PROCESSING" and waited < max_wait:
        time.sleep(3)
        waited += 3
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        client.files.delete(name=video_file.name)
        raise RuntimeError("Video processing failed on Gemini server.")

    try:
        res = analyze_input([video_file], user_caption=user_caption)
        return res
    finally:
        try:
            client.files.delete(name=video_file.name)
        except Exception:
            pass
