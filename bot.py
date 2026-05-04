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
        "example_form": row[5],
        "ease": row[6],
        "interval": row[7],
        "reps": row[8],
    }


def verb_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "present": row[1],
        "future": row[2],
        "past": row[3],
        "translation": row[4],
        "notes": row[5],
        "ease": row[6],
        "interval": row[7],
        "reps": row[8],
    }


async def generate_example(greek_word: str, translation: str):
    if not OPENAI_API_KEY:
        return None, None, None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"Write one short natural A2-level Greek sentence using '{greek_word}' "
                    f"(meaning: {translation}). Use a natural inflected form when possible "
                    "instead of simply repeating the dictionary form. For verbs, do not use "
                    "first-person singular unless no other form sounds natural; prefer second "
                    "person, third person, plural, future, or past forms. For nouns and "
                    "adjectives, prefer a natural case, plural, gender, or agreement form "
                    "when possible. "
                    "Then give the Russian translation and the exact Greek form used from "
                    "that word family. Format exactly: "
                    "<Greek sentence> | <Russian translation> | <Greek form used>. No extra text."
                ),
            }],
            max_tokens=120,
        )
        text = resp.choices[0].message.content.strip()
        if "|" in text:
            parts = [part.strip() for part in text.split("|")]
            if len(parts) >= 3:
                return parts[0], parts[1], parts[2]
    except Exception as e:
        logging.warning(f"OpenAI error: {e}")
    return None, None, None


async def ensure_word_example(word: dict):
    if word["example_gr"] or not OPENAI_API_KEY:
        return word["example_gr"], word["example_ru"], word.get("example_form")

    gr, ru, form = await generate_example(word["greek"], word["translation"])
    if gr:
        db.save_example(word["id"], gr, ru, form or word["greek"])
        word["example_gr"] = gr
        word["example_ru"] = ru
        word["example_form"] = form or word["greek"]
    return gr, ru, form


def schedule_example_generation(word: dict, context: ContextTypes.DEFAULT_TYPE):
    if word["example_gr"] or not OPENAI_API_KEY:
        return

    tasks = context.application.bot_data.setdefault("example_tasks", {})
    word_id = word["id"]
    task = tasks.get(word_id)
    if task and not task.done():
        return

    async def run():
        try:
            return await ensure_word_example(word)
        finally:
            tasks.pop(word_id, None)

    tasks[word_id] = context.application.create_task(run())


async def get_example(word: dict, context: ContextTypes.DEFAULT_TYPE):
    if word["example_gr"] or not OPENAI_API_KEY:
        return word["example_gr"], word["example_ru"], word.get("example_form")

    tasks = context.application.bot_data.setdefault("example_tasks", {})
    task = tasks.get(word["id"])
    if task and not task.done():
        gr, ru, form = await task
        if gr:
            word["example_gr"] = gr
            word["example_ru"] = ru
            word["example_form"] = form or word["greek"]
        return gr, ru, form

    return await ensure_word_example(word)


def format_example_text(greek: str | None, russian: str | None, form: str | None):
    if not greek:
        return ""

    return f"\n\n📝 _{greek}_\n_{russian}_"


def format_word_verb_forms(greek_word: str):
    forms = db.get_verb_forms_by_present(greek_word)
    if not forms:
        return ""

    future, past = forms
    return f"\n\n🔮 Future: *{future}*\n🕰 Past: *{past}*"


async def show_word_answer(query, word: dict, idx: int, total: int, context: ContextTypes.DEFAULT_TYPE):
    verb_forms_text = format_word_verb_forms(word["greek"])

    example_text = ""
    if word["example_gr"]:
        example_text = format_example_text(
            word["example_gr"], word["example_ru"], word.get("example_form")
        )
    elif OPENAI_API_KEY:
        await query.edit_message_text("⏳ Finishing example…")
        gr, ru, form = await get_example(word, context)
        if gr:
            example_text = format_example_text(gr, ru, form)

    text = (
        f"*{idx + 1}/{total}*\n\n"
        f"🇬🇷 *{word['greek']}*\n"
        f"🇷🇺 {word['translation']}"
        f"{verb_forms_text}"
        f"{example_text}\n\n"
        f"How well did you know it?"
    )
    keyboard = [
        [
            InlineKeyboardButton("🔄 Regenerate example", callback_data=f"regen:{word['id']}"),
            InlineKeyboardButton("🚫 Know it - don't show", callback_data=f"hide:{word['id']}"),
        ],
        [
            InlineKeyboardButton("✅ Easy", callback_data=f"rate:{word['id']}:5"),
            InlineKeyboardButton("🤔 Hard", callback_data=f"rate:{word['id']}:3"),
            InlineKeyboardButton("❌ No idea", callback_data=f"rate:{word['id']}:0"),
        ],
    ]
    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


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
    schedule_example_generation(word, context)
    total = len(session)
    label = "🔁 Review" if word["reps"] > 0 else "🆕 New"
    text = f"*{idx + 1}/{total}* {label}\n\n🇬🇷 *{word['greek']}*"
    keyboard = [[InlineKeyboardButton("👁 Show translation", callback_data=f"show:{word['id']}")]]
    await reply_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def send_verb_card(reply_fn, context: ContextTypes.DEFAULT_TYPE):
    session: list = context.user_data.get("verb_session", [])
    idx: int = context.user_data.get("verb_idx", 0)

    if idx >= len(session):
        await reply_fn(
            "🎉 *Verb session complete!*\n\nUse /verbs for another session or /stats to see your progress.",
            parse_mode="Markdown",
        )
        return

    verb = session[idx]
    total = len(session)
    label = "🔁 Review" if verb["reps"] > 0 else "🆕 New"
    text = (
        f"*{idx + 1}/{total}* {label}\n\n"
        f"🇬🇷 *{verb['present']}*\n"
        f"🇷🇺 {verb['translation']}"
    )
    keyboard = [[InlineKeyboardButton("👁 Show future/past", callback_data=f"vshow:{verb['id']}")]]
    await reply_fn(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇬🇷 *Greek A2 Trainer*\n\n"
        "*/study* — start a flashcard session\n"
        "*/verbs* — practice future and past verb forms\n"
        "*/stats* — see your progress\n\n"
        "Each session gives you up to 30 due reviews + 15 new words.\n"
        "Rate each card: ✅ Easy · 🤔 Hard · ❌ Don't know\n"
        "Use 🚫 Know it - don't show for words you already know too well.",
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


async def cmd_verbs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = db.get_verb_session(user_id, max_reviews=15, max_new=10)
    if not rows:
        await update.message.reply_text(
            "✅ No verb forms due right now — come back tomorrow!\nUse /stats to see your progress."
        )
        return

    context.user_data["verb_session"] = [verb_to_dict(r) for r in rows]
    context.user_data["verb_idx"] = 0
    await send_verb_card(update.message.reply_text, context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_stats(user_id)
    vs = db.get_verb_stats(user_id)
    pct = round(s["seen"] / s["total"] * 100) if s["total"] else 0
    verb_pct = round(vs["seen"] / vs["total"] * 100) if vs["total"] else 0
    await update.message.reply_text(
        f"📊 *Your progress*\n\n"
        f"*Words*\n"
        f"Total: {s['total']}\n"
        f"Seen: {s['seen']} ({pct}%) · New left: {s['unseen']}\n"
        f"Learning: {s['learning']} · Mature: {s['known']}\n"
        f"Don't show again: {s['hidden']}\n"
        f"Due: today {s['due']} · tomorrow {s['due_tomorrow']} · 7d {s['due_week']}\n"
        f"Examples saved: {s['examples']}/{s['total']}\n"
        f"Avg ease: {s['avg_ease']:.2f}\n\n"
        f"*Verb forms*\n"
        f"Total: {vs['total']}\n"
        f"Seen: {vs['seen']} ({verb_pct}%) · New left: {vs['unseen']}\n"
        f"Learning: {vs['learning']} · Mature: {vs['known']}\n"
        f"Due: today {vs['due']} · tomorrow {vs['due_tomorrow']} · 7d {vs['due_week']}\n"
        f"Avg ease: {vs['avg_ease']:.2f}",
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

        await show_word_answer(query, word, idx, len(session), context)

    elif data.startswith("regen:"):
        word_id = int(data.split(":")[1])
        session: list = context.user_data.get("session", [])
        idx: int = context.user_data.get("idx", 0)
        word = next((w for w in session if w["id"] == word_id), None)
        if not word:
            await query.edit_message_text("Session expired. Use /study to start again.")
            return
        if not OPENAI_API_KEY:
            await query.edit_message_text("OpenAI API key is not configured.")
            return

        await query.edit_message_text("⏳ Regenerating example…")
        gr, ru, form = await generate_example(word["greek"], word["translation"])
        if gr:
            db.save_example(word["id"], gr, ru, form or word["greek"])
            word["example_gr"] = gr
            word["example_ru"] = ru
            word["example_form"] = form or word["greek"]

        await show_word_answer(query, word, idx, len(session), context)

    elif data.startswith("hide:"):
        word_id = int(data.split(":")[1])
        user_id = update.effective_user.id
        db.hide_word(user_id, word_id)

        await query.edit_message_reply_markup(reply_markup=None)

        context.user_data["idx"] = context.user_data.get("idx", 0) + 1
        await send_card(query.message.reply_text, context)

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

        await query.edit_message_reply_markup(reply_markup=None)

        context.user_data["idx"] = context.user_data.get("idx", 0) + 1
        await send_card(query.message.reply_text, context)

    elif data.startswith("vshow:"):
        verb_id = int(data.split(":")[1])
        session: list = context.user_data.get("verb_session", [])
        idx: int = context.user_data.get("verb_idx", 0)
        verb = next((v for v in session if v["id"] == verb_id), None)
        if not verb:
            await query.edit_message_text("Verb session expired. Use /verbs to start again.")
            return

        total = len(session)
        notes = f"\n_{verb['notes']}_" if verb["notes"] else ""
        text = (
            f"*{idx + 1}/{total}*\n\n"
            f"🇬🇷 *{verb['present']}*\n"
            f"🔮 Future: *{verb['future']}*\n"
            f"🕰 Past: *{verb['past']}*\n"
            f"🇷🇺 {verb['translation']}"
            f"{notes}\n\n"
            f"How well did you know these forms?"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Know it", callback_data=f"vrate:{verb_id}:5"),
            InlineKeyboardButton("🤔 Hard",    callback_data=f"vrate:{verb_id}:3"),
            InlineKeyboardButton("❌ No idea", callback_data=f"vrate:{verb_id}:0"),
        ]]
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("vrate:"):
        _, verb_id_str, quality_str = data.split(":")
        verb_id = int(verb_id_str)
        quality = int(quality_str)
        user_id = update.effective_user.id

        session: list = context.user_data.get("verb_session", [])
        verb = next((v for v in session if v["id"] == verb_id), None)
        if verb:
            ef, interval, reps, next_review = srs.sm2(
                verb["ease"], verb["interval"], verb["reps"], quality
            )
            db.update_verb_progress(user_id, verb_id, ef, interval, reps, next_review)

        await query.edit_message_reply_markup(reply_markup=None)

        context.user_data["verb_idx"] = context.user_data.get("verb_idx", 0) + 1
        await send_verb_card(query.message.reply_text, context)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_TOKEN not set in .env")

    db.init_db()
    db.load_words()
    db.load_verb_forms()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("study", cmd_study))
    app.add_handler(CommandHandler("verbs", cmd_verbs))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_callback))

    print("✅ Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
