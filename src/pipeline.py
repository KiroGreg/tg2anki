from pathlib import Path
from src.vision import analyze_image

class NoCardError(Exception):
    pass

def process_file(image_path: str, user_caption: str = None) -> dict:
    result = analyze_image(image_path, user_caption)
    content_type = result.get("type")

    if content_type == "vocabulary" and result.get("card"):
        return result["card"]
    elif content_type in ["resource", "concept"]:
        index_file = Path("data/index.md")
        info = result.get("resource_info") or image_path
        with open(index_file, "a", encoding="utf-8") as f:
            f.write(f"- [{content_type.upper()}] {info} (File: {Path(image_path).name})\n")
        raise NoCardError(f"Saved as {content_type} in index.md.")
    else:
        raise NoCardError("Classified as irrelevant.")
