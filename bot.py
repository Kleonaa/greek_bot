import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import db
import srs

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ── helpers ──────────────────────────────────────────────────────────────────

def word_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "greek": row[1],
        "translation": row[2],
        "example_gr": row[3],
        "example_ru": row[4],
        "ease": row[5],
        "interval": row[6],
        "reps": row[7],
    }


async def generate_example(greek_word: str, translation: str):
    if not OPENAI_API_KEY:
        return None, None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"Write one short A2-level Greek sentence using the word '{greek_word}' "
                    f"(meaning: {translation}), then its Russian translation. "
                    "Format exactly: <Greek sentence> | <Russian translation>. No extra text."
                ),
            }],
            max_tokens=120,
        )
        text = resp.choices[0].message.content.strip()
        if "|" in text:
            gr, ru = text.split("|", 1)
            return gr.strip(), ru.strip()
    except Exception as e:
        logging.warning(f"OpenAI error: {e}")
    return None, None


async def send_card(reply_fn, context: ContextTypes.DEFAULT_TYPE):
    session: list = context.user_data.get("session", [])
    idx: int = context.user_data.get("idx", 0)

    if idx >= len(session):
        await reply_fn(
            "🎉 *Session complete!*\n\nUse /study for another session or /stats to see your progress.",
            parse_mode="Markdown",
        )
        return

    word = session[idx]
    total = len(session)
    label = "🔁 Review" if word["reps"] > 0 else "🆕 New"
    text = f"*{idx + 1}/{total}* {label}\n\n🇬🇷 *{word['greek']}*"
    keyboard = [[InlineKeyboardButton("👁 Show translation", callback_data=f"show:{word['id']}")]]
    await reply_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇬🇷 *Greek A2 Trainer*\n\n"
        "*/study* — start a flashcard session\n"
        "*/stats* — see your progress\n\n"
        "Each session gives you up to 30 due reviews + 15 new words.\n"
        "Rate each card: ✅ Know it · 🤔 Hard · ❌ Don't know",
        parse_mode="Markdown",
    )


async def cmd_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = db.get_session_words(user_id, max_reviews=30, max_new=15)
    if not rows:
        await update.message.reply_text(
            "✅ Nothing due right now — come back tomorrow!\nUse /stats to see your progress."
        )
        return

    context.user_data["session"] = [word_to_dict(r) for r in rows]
    context.user_data["idx"] = 0
    await send_card(update.message.reply_text, context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_stats(user_id)
    pct = round(s["seen"] / s["total"] * 100) if s["total"] else 0
    await update.message.reply_text(
        f"📊 *Your progress*\n\n"
        f"Total words: {s['total']}\n"
        f"Seen: {s['seen']} ({pct}%)\n"
        f"Well-learned (interval ≥ 21d): {s['known']}\n"
        f"Due today: {s['due']}",
        parse_mode="Markdown",
    )


# ── callback handler ──────────────────────────────────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("show:"):
        word_id = int(data.split(":")[1])
        session: list = context.user_data.get("session", [])
        idx: int = context.user_data.get("idx", 0)
        word = next((w for w in session if w["id"] == word_id), None)
        if not word:
            await query.edit_message_text("Session expired. Use /study to start again.")
            return

        # Fetch / generate example
        example_text = ""
        if word["example_gr"]:
            example_text = f"\n\n📝 _{word['example_gr']}_\n_{word['example_ru']}_"
        elif OPENAI_API_KEY:
            await query.edit_message_text("⏳ Generating example…")
            gr, ru = await generate_example(word["greek"], word["translation"])
            if gr:
                db.save_example(word_id, gr, ru)
                word["example_gr"] = gr
                word["example_ru"] = ru
                example_text = f"\n\n📝 _{gr}_\n_{ru}_"

        total = len(session)
        text = (
            f"*{idx + 1}/{total}*\n\n"
            f"🇬🇷 *{word['greek']}*\n"
            f"🇷🇺 {word['translation']}"
            f"{example_text}\n\n"
            f"How well did you know it?"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Know it", callback_data=f"rate:{word_id}:5"),
            InlineKeyboardButton("🤔 Hard",    callback_data=f"rate:{word_id}:3"),
            InlineKeyboardButton("❌ No idea", callback_data=f"rate:{word_id}:0"),
        ]]
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("rate:"):
        _, word_id_str, quality_str = data.split(":")
        word_id = int(word_id_str)
        quality = int(quality_str)
        user_id = update.effective_user.id

        session: list = context.user_data.get("session", [])
        word = next((w for w in session if w["id"] == word_id), None)
        if word:
            ef, interval, reps, next_review = srs.sm2(
                word["ease"], word["interval"], word["reps"], quality
            )
            db.update_progress(user_id, word_id, ef, interval, reps, next_review)

        # Remove buttons from rated card
        labels = {5: "✅ Know it", 3: "🤔 Hard", 0: "❌ No idea"}
        await query.edit_message_reply_markup(reply_markup=None)

        context.user_data["idx"] = context.user_data.get("idx", 0) + 1
        await send_card(query.message.reply_text, context)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_TOKEN not set in .env")

    db.init_db()
    db.load_words()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("study", cmd_study))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_callback))

    print("✅ Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
