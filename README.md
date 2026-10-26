# tg2anki

**tg2anki** is a powerful Telegram bot powered by **Google Gemini AI** that automatically extracts vocabulary, idioms, phrases, and concepts from screenshots, translator apps, images, videos, and text snippets sent via Telegram—and converts them into structured, high-quality **Anki flashcards**.

---

## Features

- **Multi-Modal AI Extraction**: Send screenshots from language learning apps (Duolingo, Babbel, dictionaries), photos of books, or text snippets. Google Gemini analyzes them and extracts the core vocabulary.
- **Smart Visual Highlights**: Automatically prioritizes text highlighted in red or visually emphasized in source screenshots.
- **Intelligent Grammar & Translation**:
  - English targets are translated into German.
  - German targets are translated into Russian (with articles, plurals, and verb conjugations).
- **AnkiConnect Integration**: Automatically syncs and adds generated flashcards directly to your local Anki deck via AnkiConnect (`http://127.0.0.1:8765`), with duplicate checking and synonym consolidation.
- **Offline Queue & Indexing**: Falls back to a local queue or indexes resources and concepts in markdown if Anki is offline.
- **Built-in Security**: Pre-configured with `.gitignore` and `gitleaks` pre-commit hooks to prevent accidental credential or API key leaks.

---

## Tech Stack

- **Python 3.10+**
- **python-telegram-bot** (Telegram Bot API v22+)
- **Google GenAI SDK** (`google-genai` with Gemini models)
- **AnkiConnect** (Local Bridge for Anki)
- **Pillow (PIL)** for image processing
- **PyYAML** for configuration

---

## Quick Start & Installation

### 1. Clone the Repository & Setup Virtual Environment
```bash
git clone https://github.com/your-username/tg2anki.git
cd tg2anki
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
Edit `.env` and add your tokens:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Setup Git Security & Pre-commit Hooks
To prevent accidentally committing your `.env` or API keys:
```bash
git init
pip install pre-commit
pre-commit install
```

### 4. Run the Bot
Make sure Anki is running locally with **AnkiConnect** installed on port `8765`, then run:
```bash
python -m src.bot
```

---

## Configuration (`config.yaml`)

You can customize model settings in `config.yaml`:
```yaml
model_name: "gemini-2.5-flash"
max_tokens: 2048
temperature: 0.1
export_dir: "data/export"
output_dir: "data/out"
```

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
