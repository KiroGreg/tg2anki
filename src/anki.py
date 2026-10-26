import json
import requests
from pathlib import Path

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
QUEUE_FILE = Path("data/queue.json")
DEFAULT_DECK = "Telegram-DE-Test"

def invoke_anki(action: str, **params):
    payload = {"action": action, "version": 6, "params": params}
    try:
        response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
        response.raise_for_status()
        res = response.json()
        if res.get("error"):
            return None
        return res.get("result")
    except Exception:
        return None

def is_anki_reachable() -> bool:
    try:
        res = requests.get(ANKI_CONNECT_URL, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

def find_existing_notes(expression: str, deck_name: str = DEFAULT_DECK) -> list:
    """Finds all connected notes (both directions) for a given expression."""
    if not is_anki_reachable() or not expression:
        return []

    clean_expr = expression.strip()
    query = f'"deck:{deck_name}" ("Front:{clean_expr}" or "Front:{clean_expr}*" or "Back:*{clean_expr}*")'

    notes = invoke_anki("findNotes", query=query)
    if not notes:
        return []

    info = invoke_anki("notesInfo", notes=notes)
    return info if info else []

def safe_str(value) -> str:
    """Helper to ensure None is safely converted to an empty string before stripping."""
    if value is None:
        return ""
    return str(value).strip()

def add_or_update_card(card_data: dict, deck_name: str = DEFAULT_DECK) -> dict:
    expr = safe_str(card_data.get("Expression"))
    primary = safe_str(card_data.get("PrimaryMeaning"))
    meanings = safe_str(card_data.get("Meanings"))

    if not expr:
        return {"status": "error", "message": "Missing expression."}

    full_translation = primary
    if meanings:
        full_translation += f" ({meanings})"

    if not is_anki_reachable():
        save_to_queue(card_data)
        return {"status": "queued", "message": "Anki not reachable. Saved to queue."}

    # Search for existing cards in both directions
    existing_notes = find_existing_notes(expr, deck_name=deck_name)

    if existing_notes:
        for note in existing_notes:
            fields = note.get("fields", {})
            back_val = fields.get("Back", {}).get("value", "")
            front_val = fields.get("Front", {}).get("value", "")

            if primary and (primary in back_val or primary in front_val):
                return {"status": "duplicate", "note_ids": [n["noteId"] for n in existing_notes], "message": f"Word '{expr}' already exists!"}

        updated_ids = []
        for note in existing_notes:
            n_id = note["noteId"]
            fields = note.get("fields", {})
            curr_back = fields.get("Back", {}).get("value", "")

            append_html = f"<br><hr><b>Addition:</b> {full_translation}"
            if card_data.get('ExampleSentence'):
                append_html += f"<br><i>{card_data.get('ExampleSentence')}</i>"
            if card_data.get('PersonalNote'):
                append_html += f"<br><small>{card_data.get('PersonalNote')}</small>"

            if update_card_fields(n_id, {"Back": curr_back + append_html}):
                updated_ids.append(n_id)

        return {"status": "updated", "note_ids": updated_ids, "message": f"Updated connected cards for '{expr}'!"}

    details_html = ""
    if card_data.get('Grammar'):
        details_html += f"<br><small><b>Grammar:</b> {card_data.get('Grammar')}</small>"
    if card_data.get('ExampleSentence'):
        details_html += f"<br><br><i>{card_data.get('ExampleSentence')}</i>"
    if card_data.get('PersonalNote'):
        details_html += f"<br><small><b>Note:</b> {card_data.get('PersonalNote')}</small>"

    pair_tag = f"pair_{expr.replace(' ', '_').lower()}"

    # CARD 1: Standard Direction (DE -> RU / EN -> DE)
    card1_note = {
        "deckName": deck_name,
        "modelName": "Basic",
        "fields": {
            "Front": expr,
            "Back": f"<b>{full_translation}</b>{details_html}"
        },
        "tags": [card_data.get("Tags", "Vocabulary"), pair_tag]
    }

    # CARD 2: Reversed Direction
    card2_note = {
        "deckName": deck_name,
        "modelName": "Basic",
        "fields": {
            "Front": full_translation,
            "Back": f"<b>{expr}</b>{details_html}"
        },
        "tags": [card_data.get("Tags", "Vocabulary"), pair_tag]
    }

    id1 = invoke_anki("addNote", note=card1_note)
    id2 = invoke_anki("addNote", note=card2_note)

    # Force Card 2 to sit directly next to Card 1 in the new queue
    if id1 and id2:
        try:
            cards_1 = invoke_anki("findCards", query=f"nid:{id1}")
            cards_2 = invoke_anki("findCards", query=f"nid:{id2}")
            if cards_1 and cards_2:
                invoke_anki("repositionCards", cards=cards_2, start=cards_1[0] + 1, step=1, shift=True)
        except Exception:
            pass

    if id1 and id2:
        return {"status": "success", "note_ids": [id1, id2]}
    elif id1 or id2:
        return {"status": "success", "note_ids": [i for i in [id1, id2] if i]}
    else:
        save_to_queue(card_data)
        return {"status": "queued", "message": "Saved to queue."}

def update_card_fields(note_id: int, fields: dict) -> bool:
    res = invoke_anki("updateNoteFields", note={"id": note_id, "fields": fields})
    return res is not None

def delete_card_list(note_ids: list) -> bool:
    if not note_ids:
        return False
    res = invoke_anki("deleteNotes", notes=note_ids)
    return res is not None

def delete_card(note_id: int) -> bool:
    return delete_card_list([note_id])

def clean_entire_deck_duplicates(deck_name: str = DEFAULT_DECK) -> int:
    if not is_anki_reachable():
        return 0

    note_ids = invoke_anki("findNotes", query=f'"deck:{deck_name}"')
    if not note_ids:
        return 0

    notes_info = invoke_anki("notesInfo", notes=note_ids)
    if not notes_info:
        return 0

    seen_expressions = {}
    duplicates_to_delete = []

    for note in notes_info:
        n_id = note.get("noteId")
        front_val = safe_str(note.get("fields", {}).get("Front", {}).get("value")).lower()

        if not front_val:
            continue

        if front_val in seen_expressions:
            duplicates_to_delete.append(n_id)
        else:
            seen_expressions[front_val] = n_id

    if duplicates_to_delete:
        delete_card_list(duplicates_to_delete)

    return len(duplicates_to_delete)

def save_to_queue(card_data: dict, msg_id: str = None, chat_id: int = None):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    queue = []
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception:
            queue = []

    item = {"card": card_data, "msg_id": msg_id, "chat_id": chat_id}
    queue.append(item)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def sync_queue() -> list:
    if not QUEUE_FILE.exists() or not is_anki_reachable():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
    except Exception:
        return []
    if not queue:
        return []

    processed_items = []
    remaining_queue = []

    for item in queue:
        card_data = item.get("card", item) if isinstance(item, dict) and "card" in item else item
        res = add_or_update_card(card_data)

        if res.get("status") in ["success", "duplicate", "updated"]:
            processed_items.append({"item": item, "result": res})
        else:
            remaining_queue.append(item)

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining_queue, f, ensure_ascii=False, indent=2)

    return processed_items
