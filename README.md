# <Project name>: Research Assistant Telegram Bot (SSRLLM)

A Telegram bot with a built-in AI agent. It answers simple questions instantly
and turns complex ones into structured research reports.

![demo](docs/demo.gif)  <!-- screenshot or short GIF of the bot -->

## Features

- **Fast answers** for simple questions
- **Deep research**: the bot splits a complex question into subtopics,
  lets you choose which ones to cover, then writes a detailed report
- **Sources**: web search, Wikipedia and arXiv
- **PDF Q&A**: upload a PDF and ask questions about it or use it to create more precise answers
- **Answer modes**: Auto / Fast only / Deep always (`/mode`)
- **Daily limit** for deep research (`/limit` shows what is left)

## How it works

```
Telegram user ──> aiogram handlers (bot/) ──> LangGraph agent (src/)
                                                 ├─ fast track
                                                 └─ deep research (human-in-the-loop:
                                                    the user picks subtopics)
```

- `bot/`: Telegram layer (aiogram 3): handlers, inline keyboards
- `src/`: LangGraph agent, tools, prompts, PDF indexing, usage limits
- `DB/`: local SQLite files (created automatically, not committed)

## Quick start

**Requirements:** Python <version>, a Telegram bot token from [@BotFather](https://t.me/BotFather),
API keys for <LLM provider> and <search provider>.

```bash
git clone https://github.com/La3euka04/SSRLLM.git
cd <repo>
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # Windows: copy .env.example .env
# fill in the values in .env

python main.py
```

