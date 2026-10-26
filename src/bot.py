import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from telegram.request import HTTPXRequest
from google import genai

from src.vision import analyze_text, analyze_image, analyze_video
from src.anki import (
    add_or_update_card, update_card_fields, delete_card_list,
    sync_queue, is_anki_reachable, save_to_queue, clean_entire_deck_duplicates
)
from src.config import GEMINI_API_KEY, CONFIG

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
STATE_FILE = Path("data/bot_state.json")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

IMAGE_BUFFER = {}
BUFFER_DELAY = 3.0

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

bot_state = load_state()

def extract_cards_from_response(res) -> list:
    if isinstance(res, list):
        return res
    elif isinstance(res, dict):
        if isinstance(res.get("cards"), list):
            return res["cards"]
        elif res.get("card"):
            return [res["card"]]
    return []

async def auto_sync_queue_task(app):
    while True:
        try:
            if is_anki_reachable():
                processed = sync_queue()
                for entry in processed:
                    item = entry["item"]
                    res = entry["result"]

                    chat_id = item.get("chat_id") if isinstance(item, dict) else None
                    msg_id = item.get("msg_id") if isinstance(item, dict) else None
                    card = item.get("card", item) if isinstance(item, dict) else item

                    expr = card.get("Expression", "")

                    if chat_id and msg_id:
                        try:
                            if res.get("status") == "duplicate":
                                await app.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=int(msg_id),
                                    text=f"⚠️ **Word/Phrase already exists!**\n\n**'{expr}'** is already present in your Anki deck.",
                                    parse_mode="Markdown"
                                )
                            elif res.get("status") == "updated":
                                await app.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=int(msg_id),
                                    text=f"🔄 **Flashcards updated!**\n\nAdditional information added to both cards for **'{expr}'**.",
                                    parse_mode="Markdown"
                                )
                            elif res.get("status") == "success":
                                primary = card.get("PrimaryMeaning", "")
                                meanings = card.get("Meanings", "")
                                grammar = card.get("Grammar", "")
                                example = card.get("ExampleSentence", "")
                                note = card.get("PersonalNote", "")

                                meaning_str = primary if primary else "*(No translation)*"
                                if meanings:
                                    meaning_str += f" | {meanings}"

                                details = [f"📌 **Word:** {expr}", f"💡 **Meaning:** {meaning_str}"]
                                if grammar:
                                    details.append(f"📖 **Grammar:** {grammar}")
                                if example:
                                    details.append(f"💬 **Example:** {example}")
                                if note:
                                    details.append(f"ℹ️ **Note:** {note}")

                                text = "✅ 2 Cards added to Anki!\n\n" + "\n".join(details) + "\n\n_Reply to this message to edit or delete both cards._"
                                await app.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=int(msg_id),
                                    text=text,
                                    parse_mode="Markdown"
                                )

                                if res.get("note_ids"):
                                    bot_state[str(msg_id)] = {
                                        "note_ids": res["note_ids"],
                                        "card": card
                                    }
                                    save_state(bot_state)
                        except Exception as e:
                            print(f"[Auto-Sync Edit Error] {e}")

                if processed:
                    print(f"[Auto-Sync] Successfully pushed {len(processed)} queued cards to Anki!")
        except Exception as e:
            print(f"[Auto-Sync Task Error] {e}")

        await asyncio.sleep(10)

async def process_and_send_cards(msg, cards_list):
    if not cards_list:
        await msg.reply_text("ℹ️ No vocabulary or idioms extracted.")
        return

    for card in cards_list:
        expr = card.get("Expression", "").strip()
        if not expr:
            continue

        anki_res = add_or_update_card(card)

        if anki_res.get("status") == "duplicate":
            await msg.reply_text(f"⚠️ **Word/Phrase already exists!**\n\n**'{expr}'** is already present in your Anki deck.", parse_mode="Markdown")
            await asyncio.sleep(0.3)
            continue

        if anki_res.get("status") == "updated":
            await msg.reply_text(f"🔄 **Flashcards updated!**\n\nAdditional information added to both cards for **'{expr}'**.", parse_mode="Markdown")
            await asyncio.sleep(0.3)
            continue

        primary = card.get("PrimaryMeaning", "")
        meanings = card.get("Meanings", "")
        grammar = card.get("Grammar", "")
        example = card.get("ExampleSentence", "")
        note = card.get("PersonalNote", "")

        is_success = anki_res.get("status") == "success"
        status = "✅ 2 Cards added to Anki!" if is_success else "📥 Saved to offline queue (Anki closed)."

        meaning_str = primary if primary else "*(No translation)*"
        if meanings:
            meaning_str += f" | {meanings}"

        details = [f"📌 **Word:** {expr}", f"💡 **Meaning:** {meaning_str}"]
        if grammar:
            details.append(f"📖 **Grammar:** {grammar}")
        if example:
            details.append(f"💬 **Example:** {example}")
        if note:
            details.append(f"ℹ️️ **Note:** {note}")

        response_text = f"{status}\n\n" + "\n".join(details) + "\n\n_Reply to this message to edit or delete both cards._"

        reply_msg = await msg.reply_text(response_text, parse_mode="Markdown")

        if is_success and anki_res.get("note_ids"):
            bot_state[str(reply_msg.message_id)] = {
                "note_ids": anki_res["note_ids"],
                "card": card
            }
            save_state(bot_state)
        elif not is_success:
            save_to_queue(card, msg_id=str(reply_msg.message_id), chat_id=msg.chat_id)

        await asyncio.sleep(0.4)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.message
    caption = msg.caption

    # Check text caption first for instant response
    if caption and len(caption.strip()) > 3:
        try:
            res = analyze_text(caption)
            cards = extract_cards_from_response(res)
            if cards:
                await process_and_send_cards(msg, cards)
                return
        except Exception:
            pass

    video_obj = msg.video or msg.animation or msg.video_note
    if not video_obj:
        return

    # Check Telegram API 20MB file limit
    if video_obj.file_size and video_obj.file_size > 20 * 1024 * 1024:
        await msg.reply_text("⚠️ **Video zu groß!** Telegram-Bots können Dateien über 20 MB nicht herunterladen.")
        return

    status_msg = await msg.reply_text("🎬 Video wird verarbeitet...")

    try:
        file = await video_obj.get_file()
        temp_dir = Path("data/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        video_path = temp_dir / f"{video_obj.file_unique_id}.mp4"
        await file.download_to_drive(custom_path=video_path)

        # Run blocking video upload & processing in a thread pool
        res = await asyncio.to_thread(analyze_video, str(video_path), caption)
        cards = extract_cards_from_response(res)
        await status_msg.delete()
        await process_and_send_cards(msg, cards)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Fehler bei der Videoverarbeitung: {e}")
    finally:
        if 'video_path' in locals() and video_path.exists():
            video_path.unlink()

async def process_buffered_images(chat_id, context):
    await asyncio.sleep(BUFFER_DELAY)
    if chat_id not in IMAGE_BUFFER:
        return

    buffer_data = IMAGE_BUFFER.pop(chat_id)
    image_paths = buffer_data["paths"]
    msg = buffer_data["msg"]
    caption = buffer_data.get("caption")

    try:
        for path in image_paths:
            res = analyze_image(path, user_caption=caption)
            cards = extract_cards_from_response(res)
            await process_and_send_cards(msg, cards)
            await asyncio.sleep(0.5)
    except Exception as e:
        await msg.reply_text(f"⚠️ Error processing buffered images: {e}")
    finally:
        for p in image_paths:
            path_obj = Path(p)
            if path_obj.exists():
                path_obj.unlink()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.message
    photo = msg.photo[-1]
    file = await photo.get_file()

    temp_dir = Path("data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    img_path = temp_dir / f"{photo.file_unique_id}.jpg"
    await file.download_to_drive(custom_path=img_path)

    chat_id = msg.chat_id

    if chat_id not in IMAGE_BUFFER:
        IMAGE_BUFFER[chat_id] = {
            "paths": [str(img_path)],
            "msg": msg,
            "caption": msg.caption,
            "task": asyncio.create_task(process_buffered_images(chat_id, context))
        }
    else:
        IMAGE_BUFFER[chat_id]["paths"].append(str(img_path))
        if msg.caption and not IMAGE_BUFFER[chat_id]["caption"]:
            IMAGE_BUFFER[chat_id]["caption"] = msg.caption

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.message

    if msg.reply_to_message:
        await handle_reply(update, context)
        return

    try:
        res = analyze_text(msg.text)
        cards = extract_cards_from_response(res)
        await process_and_send_cards(msg, cards)
    except Exception as e:
        await msg.reply_text(f"⚠️ Error processing text: {e}")

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.message
    parent_id = str(msg.reply_to_message.message_id)

    if parent_id not in bot_state:
        await msg.reply_text("⚠️ No active Anki card linked to this message.")
        return

    card_info = bot_state[parent_id]
    note_ids = card_info.get("note_ids", [])
    if not note_ids and card_info.get("note_id"):
        note_ids = [card_info["note_id"]]

    try:
        prompt = f"Analyze edit instruction: '{msg.text}'. Return JSON: {{\"action\": \"DELETE\"|\"UPDATE\", \"fields\": {{\"Front\": \"text or null\", \"Back\": \"text or null\"}}}}"
        response = client.models.generate_content(
            model=CONFIG.get("model_name", "gemini-3.5-flash-lite"),
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        command = json.loads(response.text)
        action = command.get("action")

        if action == "DELETE":
            if delete_card_list(note_ids):
                await msg.reply_text("🗑️ Both connected flashcards deleted from Anki!")
                del bot_state[parent_id]
                save_state(bot_state)
            else:
                await msg.reply_text("⚠️ Could not delete cards from Anki.")

        elif action == "UPDATE":
            updated_fields = {k: v for k, v in command.get("fields", {}).items() if v is not None}
            success = False
            for n_id in note_ids:
                if update_card_fields(n_id, updated_fields):
                    success = True
            if success:
                await msg.reply_text("✏️ Connected flashcards updated successfully!")
            else:
                await msg.reply_text("⚠️ No changes applied or Anki update failed.")

    except Exception as e:
        await msg.reply_text(f"⚠️ Error processing command: {e}")

async def handle_dedupe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.message
    await msg.reply_text("🔍 Checking Anki deck for duplicate pairs...")

    deleted_count = clean_entire_deck_duplicates()
    if deleted_count > 0:
        await msg.reply_text(f"🧹 Cleaned up {deleted_count} duplicate card(s) from your Anki deck!")
    else:
        await msg.reply_text("✅ No duplicate cards found in your deck.")

async def post_init(app):
    if is_anki_reachable():
        processed = sync_queue()
        if processed:
            print(f"[Start Sync] Imported {len(processed)} queued items to Anki.")

        deleted = clean_entire_deck_duplicates()
        if deleted > 0:
            print(f"[Start Dedupe] Cleaned {deleted} duplicate cards from Anki deck!")

    asyncio.create_task(auto_sync_queue_task(app))

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(request).post_init(post_init).build()

    app.add_handler(CommandHandler("dedupe", handle_dedupe_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.ANIMATION | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    print("Bot is running with Non-Blocking Video Extractor active...")
    app.run_polling()

if __name__ == "__main__":
    main()
