import asyncio
import io
import os
import re
from html import escape

import httpx
from pypdf import PdfReader
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_provider import AIUnavailable, create_learning_note, discuss, guided_learning_action, reading_lens
from database import (
    add_discussion_message,
    add_reader_excerpt,
    append_import_text,
    cancel_import,
    end_discussion,
    finish_import,
    get_active_discussion,
    get_article,
    get_discussion_history,
    get_history,
    get_import_session,
    get_learning_notes,
    get_preference_summary,
    get_reader_excerpt_count,
    get_reader_excerpts,
    get_saved_articles,
    get_today_article,
    init_db,
    record_activity,
    save_learning_note,
    seed_test_article,
    start_discussion,
    start_import,
)
from importer import ingest_shared_url, source_for_url
from sources import enrich_article, refresh_sources

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def split_message(text: str, limit: int = 3800):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        candidates = [
            window.rfind("\n\n"),
            window.rfind("\n- "),
            window.rfind("\n• "),
            window.rfind(". "),
        ]
        break_at = max(candidates)
        if break_at < int(limit * 0.55):
            break_at = limit
        else:
            break_at += 1

        chunk = remaining[:break_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[break_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


async def send_long_reply(message, text: str):
    for chunk in split_message(text):
        await message.reply_text(chunk)


def diagnostic_match(article: dict, query: str):
    body = (article.get("plain_text") or "")
    needle = query.strip().lower()

    if not needle:
        return None

    pos = body.lower().find(needle)
    if pos < 0:
        return {"found": False, "position": None, "snippet": ""}

    ratio = pos / max(1, len(body))
    position = "early" if ratio < 0.33 else "middle" if ratio < 0.67 else "late"

    start = max(0, pos - 140)
    end = min(len(body), pos + len(query) + 140)
    snippet = body[start:end].replace("\n", " ").strip()

    return {"found": True, "position": position, "snippet": snippet}



def attach_reader_context(article: dict, user_id: int):
    if not article:
        return article
    enriched = dict(article)
    enriched["reader_excerpts"] = get_reader_excerpts(user_id, article["id"])
    enriched["reader_excerpt_count"] = get_reader_excerpt_count(user_id, article["id"])
    return enriched


def looks_like_reader_excerpt(text: str) -> bool:
    stripped = (text or "").strip()
    words = stripped.split()
    if len(words) >= 70:
        return True
    if stripped.lower().startswith(("excerpt:", "passage:", "quote:")):
        return True
    sentence_marks = sum(stripped.count(mark) for mark in (".", "!", "?"))
    return len(stripped) >= 420 and sentence_marks >= 3 and "?" not in stripped[-120:]


def content_label(article: dict) -> str:
    status = article.get("content_status") or "metadata_only"
    words = article.get("word_count") or 0
    excerpts = article.get("reader_excerpt_count") or 0
    extra = f" · +{excerpts} reader excerpt{'s' if excerpts != 1 else ''}" if excerpts else ""

    if status == "full":
        return f"📄 Full context · {words:,} words{extra}"
    if status == "partial":
        return f"📑 Partial context · {words:,} words{extra}"
    return f"🔐 Metadata only{extra}"


def article_keyboard(article: dict) -> InlineKeyboardMarkup:
    aid = article["id"]
    rows = [
        [InlineKeyboardButton("📖 Read Article", url=article["url"])],
        [
            InlineKeyboardButton("🔖 Save", callback_data=f"save:{aid}"),
            InlineKeyboardButton("👍 More Like This", callback_data=f"like:{aid}"),
        ],
        [
            InlineKeyboardButton("👎 Less Like This", callback_data=f"dislike:{aid}"),
            InlineKeyboardButton("💬 Discuss", callback_data=f"discuss:{aid}"),
        ],
        [InlineKeyboardButton("🧭 Reading Lens", callback_data=f"lens:{aid}")],
    ]
    if (article.get("content_status") or "metadata_only") != "full":
        rows.append([InlineKeyboardButton("📥 Import Article Context", callback_data=f"import:{aid}")])
    return InlineKeyboardMarkup(rows)


def discussion_keyboard(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧠 Key Ideas", callback_data=f"learn:keyideas:{article_id}"),
            InlineKeyboardButton("🎯 Apply It", callback_data=f"learn:apply:{article_id}"),
        ],
        [
            InlineKeyboardButton("🧪 Challenge Me", callback_data=f"learn:challenge:{article_id}"),
            InlineKeyboardButton("📝 Save Note", callback_data=f"learn:note:{article_id}"),
        ],
    ])


def format_article(article: dict, heading: str = "Today's Recommended Read") -> str:
    return (
        f"📖 <b>{escape(heading)}</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(article['publication'])}\n\n"
        f"🎯 <b>Why I picked this:</b>\n{escape(article['why_recommended'])}\n\n"
        f"🏷 {escape(article['topic'])}\n"
        f"⏱ ~{article['reading_time']} min read\n"
        f"{escape(content_label(article))}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Welcome to My Marketing Brief.\n\n"
        "/today — Next recommended read\n"
        "/saved — Saved articles\n"
        "/history — Recent recommendations\n"
        "/topics — Preference signals\n"
        "/notes — Learning notes\n"
        "/refresh — Find new articles\n"
        "/debugarticle <keyword> — Inspect latest /today article\n"
        "/debugarticle active <keyword> — Inspect active discussion\n"
        "/finishimport — Finish an article import\n"
        "/cancelimport — Cancel an article import\n"
        "/end — End an active discussion\n"
        "/help — Commands"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 Checking and reading the publications now…")
    try:
        result = await asyncio.wait_for(asyncio.to_thread(refresh_sources), timeout=20)
    except asyncio.TimeoutError:
        await msg.edit_text("⚠️ Refresh exceeded 20 seconds and was stopped. The bot is still online; /today can continue using the existing queue.")
        return
    await msg.edit_text(
        f"✅ Refresh complete.\n\n"
        f"Found {result['found']} candidates.\n"
        f"Added {result['added']} new articles.\n"
        "Discovery refresh completed. Article text will be loaded when selected by /today.\n\n"
        "Send /today for your next recommendation."
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Fast discovery only; deep-fetch just the article we are about to recommend.
    try:
        await asyncio.wait_for(asyncio.to_thread(refresh_sources, False), timeout=20)
    except asyncio.TimeoutError:
        pass

    article = get_today_article(uid)
    if not article:
        await update.message.reply_text("You've reached the end of the current queue. Try /refresh.")
        return

    if (article.get("content_status") or "metadata_only") != "full":
        try:
            await asyncio.wait_for(asyncio.to_thread(enrich_article, article), timeout=12)
            article = get_article(article["id"]) or article
        except asyncio.TimeoutError:
            pass

    article = attach_reader_context(article, uid)
    record_activity(article["id"], "delivered", uid)
    await update.message.reply_text(
        format_article(article),
        parse_mode="HTML",
        reply_markup=article_keyboard(article),
    )


async def saved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_saved_articles(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("🔖 You haven't saved any articles yet.")
        return
    text = ["🔖 <b>Your Saved Reading</b>"]
    for i, a in enumerate(rows, 1):
        text.append(
            f'{i}. <a href="{escape(a["url"], quote=True)}">{escape(a["title"])}</a>\n'
            f'   {escape(a["publication"])} · {escape(a["topic"])}'
        )
    await update.message.reply_text(
        "\n\n".join(text),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_history(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("📚 No recommendation history yet.")
        return
    text = ["📚 <b>Recent Recommendations</b>"]
    for i, a in enumerate(rows, 1):
        text.append(
            f'{i}. <a href="{escape(a["url"], quote=True)}">{escape(a["title"])}</a>\n'
            f'   {escape(a["publication"])} · {escape(a["topic"])}'
        )
    await update.message.reply_text(
        "\n\n".join(text),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_preference_summary(update.effective_user.id)
    if not rows:
        await update.message.reply_text("🧭 Use 👍 and 👎 on a few recommendations first.")
        return
    lines = ["🧭 <b>What The Brief Is Learning</b>"]
    for r in rows:
        net = r["likes"] - r["dislikes"]
        sig = "↑" if net > 0 else "↓" if net < 0 else "→"
        lines.append(
            f'{sig} <b>{escape(r["topic"])}</b> — {r["likes"]} 👍 · {r["dislikes"]} 👎'
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_learning_notes(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("📝 No learning notes yet. Start a discussion and use /note.")
        return
    lines = ["📝 <b>Learning Notes</b>"]
    for i, r in enumerate(rows, 1):
        lines.append(f'{i}. <b>{escape(r["title"])}</b>\n{escape(r["note"])}')
    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")


async def debug_article_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = list(context.args)

    # Default to the most recent /today recommendation so diagnostics track what
    # the user is currently testing. Use "/debugarticle active ..." to inspect
    # the currently active discussion instead.
    use_active = bool(args and args[0].lower() == "active")
    if use_active:
        args = args[1:]
        article = get_active_discussion(uid)
        source_label = "active discussion"
    else:
        recent = get_history(uid, 1)
        article = get_article(recent[0]["id"]) if recent else None
        source_label = "latest /today recommendation"

    if not article:
        await update.message.reply_text(
            "I couldn't find an article to inspect yet. Run /today first, or use /debugarticle active while discussing an article."
        )
        return

    article = attach_reader_context(article, uid)
    query = " ".join(args).strip()
    status = article.get("content_status") or "metadata_only"
    source_type = article.get("source_type") or "unknown"
    word_count = article.get("word_count") or 0

    lines = [
        "🧪 Article Diagnostics",
        "",
        f"Inspecting: {source_label}",
        f"Title: {article['title']}",
        f"Publication: {article['publication']}",
        f"Content status: {status}",
        f"Source type: {source_type}",
        f"Stored words: {word_count:,}",
        f"Reader excerpts: {article.get('reader_excerpt_count') or 0}",
    ]

    if query:
        result = diagnostic_match(article, query)
        lines.append(f"Query: {query}")
        lines.append(f"Found in stored text: {'yes' if result['found'] else 'no'}")
        if result["found"]:
            lines.append(f"Approximate location: {result['position']}")
            if result["snippet"]:
                lines.extend(["", "Nearby context:", result["snippet"][:500]])
    else:
        lines.extend([
            "",
            "Add a keyword or short phrase after the command to test whether it exists in stored article text."
        ])

    await update.message.reply_text("\n".join(lines))


async def end_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    end_discussion(update.effective_user.id)
    await update.message.reply_text("✅ Discussion closed.")


async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = get_active_discussion(uid)
    if not session:
        await update.message.reply_text("There isn't an active discussion. Tap 💬 Discuss first.")
        return
    session = attach_reader_context(session, uid)
    history_rows = get_discussion_history(uid, session["id"])
    if not history_rows:
        await update.message.reply_text("Talk through the article with me first, then use /note.")
        return
    try:
        note = await asyncio.to_thread(create_learning_note, session, history_rows)
    except (AIUnavailable, httpx.HTTPError):
        await update.message.reply_text("I couldn't create the note right now.")
        return
    save_learning_note(uid, session["id"], note)
    await update.message.reply_text(
        f"📝 <b>Learning Note Saved</b>\n\n{escape(note)}",
        parse_mode="HTML",
    )


async def finish_import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    article = finish_import(update.effective_user.id)
    if not article:
        await update.message.reply_text("There isn't an active article import.")
        return
    await update.message.reply_text(
        "✅ <b>Article context imported</b>\n\n"
        f"<b>{escape(article['title'])}</b>\n"
        f"{escape(content_label(article))}\n"
        f"🧾 {article.get('word_count') or 0:,} words\n\n"
        "You can now tap 💬 Discuss on this article for a grounded conversation.",
        parse_mode="HTML",
    )


async def cancel_import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel_import(update.effective_user.id)
    await update.message.reply_text("Import cancelled.")


async def article_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    action = parts[0]
    if action == "learn":
        mode = parts[1]
        aid = int(parts[2])
    else:
        aid = int(parts[1])
    uid = update.effective_user.id
    article = get_article(aid)

    if not article:
        await q.answer("Article not found.", show_alert=True)
        return

    if action == "learn":
        start_discussion(uid, aid)
        article = attach_reader_context(article, uid)
        history_rows = get_discussion_history(uid, aid)

        if mode == "note":
            if not history_rows:
                await q.answer()
                await q.message.reply_text("Talk through the article with me first, then save a learning note.")
                return
            try:
                note = await asyncio.to_thread(create_learning_note, article, history_rows)
            except Exception:
                await q.answer()
                await q.message.reply_text("I couldn't create the learning note right now.")
                return
            save_learning_note(uid, aid, note)
            await q.answer("Note saved 📝")
            await q.message.reply_text(
                f"📝 <b>Learning Note Saved</b>\n\n{escape(note)}",
                parse_mode="HTML",
            )
            return

        await q.answer()
        await q.message.chat.send_action("typing")
        try:
            answer = await asyncio.to_thread(guided_learning_action, article, history_rows, mode)
        except Exception:
            await q.message.reply_text("I couldn't run that learning action right now.")
            return

        add_discussion_message(uid, aid, "assistant", answer)
        record_activity(aid, f"learn_{mode}", uid)
        await send_long_reply(q.message, answer)
        return

    if action == "save":
        record_activity(aid, "saved", uid, True)
        await q.answer("Saved 🔖")
        return
    if action == "like":
        record_activity(aid, "liked", uid, True)
        await q.answer("More like this 👍")
        return
    if action == "dislike":
        record_activity(aid, "disliked", uid, True)
        await q.answer("Weighted down 👎")
        return
    if action == "import":
        start_import(uid, aid)
        await q.answer()
        await q.message.reply_text(
            "📥 <b>Article Import Started</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n\n"
            "Paste the article text here, or upload a text-based PDF from your subscriber access. "
            "You can send multiple text messages.\n\n"
            "When you're done, send /finishimport.\n"
            "Use /cancelimport to stop.",
            parse_mode="HTML",
        )
        return
    if action == "lens":
        article = attach_reader_context(article, uid)
        await q.answer()
        await q.message.chat.send_action("typing")
        try:
            lens = await asyncio.to_thread(reading_lens, article)
        except Exception:
            await q.message.reply_text("I couldn't build the reading lens right now.")
            return
        record_activity(aid, "reading_lens", uid)
        await send_long_reply(q.message, "🧭 Reading Lens\n\n" + lens)
        return

    if action == "discuss":
        record_activity(aid, "discussed", uid, True)
        start_discussion(uid, aid)
        await q.answer()
        article = attach_reader_context(article, uid)
        status = article.get("content_status") or "metadata_only"
        if status == "full":
            grounding = "Full context is available."
        elif status == "partial":
            grounding = (
                f"Partial context is available ({article.get('word_count') or 0:,} words). "
                "I'll answer from what I have and only ask for a passage if the missing section matters."
            )
        else:
            grounding = "I have metadata only. You can still discuss the topic or add a passage from the article."
        await q.message.reply_text(
            "💬 <b>Discussion started</b>\n\n"
            f"<b>{escape(article['title'])}</b>\n"
            f"{escape(grounding)}\n\n"
            "Send your reaction or question, or use a guided learning action below.",
            parse_mode="HTML",
            reply_markup=discussion_keyboard(aid),
        )


async def document_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = get_import_session(uid)
    if not session:
        await update.message.reply_text(
            "I received a file, but there isn't an active import. "
            "Share an HBR link or tap 📥 Import Article Context first."
        )
        return

    document = update.message.document
    tg_file = await context.bot.get_file(document.file_id)
    data = bytes(await tg_file.download_as_bytearray())
    filename = (document.file_name or "").lower()
    mime = document.mime_type or ""

    try:
        if filename.endswith(".pdf") or mime == "application/pdf":
            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n\n".join(p for p in pages if p)
            source_type = "user_pdf"
        elif filename.endswith(".txt") or mime.startswith("text/"):
            text = data.decode("utf-8", errors="replace")
            source_type = "user_file"
        else:
            await update.message.reply_text("For now I can import PDF or plain-text files.")
            return
    except Exception:
        await update.message.reply_text("I couldn't extract readable text from that file.")
        return

    if len(text.split()) < 20:
        await update.message.reply_text(
            "I couldn't find enough readable text in that file. "
            "If it's a scanned/image PDF, paste the article text instead."
        )
        return

    append_import_text(uid, text)
    article = finish_import(uid, source_type=source_type)
    await update.message.reply_text(
        "✅ <b>Article imported from file</b>\n\n"
        f"{escape(content_label(article))}\n"
        f"🧾 {article.get('word_count') or 0:,} words\n\n"
        "The Brief can now use this context during discussion.",
        parse_mode="HTML",
    )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_text = update.message.text.strip()
    if not user_text:
        return

    urls = re.findall(r"https?://[^\s<>]+", user_text)
    for raw_url in urls:
        if source_for_url(raw_url):
            try:
                article = await asyncio.to_thread(ingest_shared_url, raw_url.rstrip(".,)"))
            except Exception:
                article = None
            if article:
                status = article.get("content_status") or "metadata_only"
                if article["publication"] == "Harvard Business Review" and status != "full":
                    article = attach_reader_context(article, uid)
                    await update.message.reply_text(
                        "🔐 <b>HBR article recognized</b>\n\n"
                        f"<b>{escape(article['title'])}</b>\n"
                        f"{escape(content_label(article))}\n\n"
                        "Open it normally with your HBR subscription. If you discuss a section I don't have, "
                        "paste that passage into the active discussion and I'll add it as reader context automatically.",
                        parse_mode="HTML",
                        reply_markup=article_keyboard(article),
                    )
                else:
                    article = attach_reader_context(article, uid)
                    await update.message.reply_text(
                        "🔗 <b>Article recognized</b>\n\n"
                        f"<b>{escape(article['title'])}</b>\n"
                        f"{escape(content_label(article))}",
                        parse_mode="HTML",
                        reply_markup=article_keyboard(article),
                    )
                return

    import_session = get_import_session(uid)
    if import_session:
        append_import_text(uid, user_text)
        current_words = len(user_text.split())
        await update.message.reply_text(
            f"📥 Added {current_words:,} words to the import. "
            "Send more text or /finishimport when you're done."
        )
        return

    session = get_active_discussion(uid)
    if not session:
        return

    status = session.get("content_status") or "metadata_only"
    saved_excerpt = False
    if status in ("partial", "metadata_only") and looks_like_reader_excerpt(user_text):
        saved_excerpt = add_reader_excerpt(uid, session["id"], user_text)
        if saved_excerpt:
            await update.message.reply_text("➕ Added this passage as reader context for the active article.")

    session = attach_reader_context(session, uid)
    add_discussion_message(uid, session["id"], "user", user_text)
    history_rows = get_discussion_history(uid, session["id"])
    await update.message.chat.send_action("typing")
    try:
        answer = await asyncio.to_thread(discuss, session, history_rows[:-1], user_text)
    except Exception:
        await update.message.reply_text("I couldn't reach the discussion model right now.")
        return
    add_discussion_message(uid, session["id"], "assistant", answer)
    await send_long_reply(update.message, answer)


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    init_db()
    seed_test_article()

    app = Application.builder().token(TOKEN).build()
    for cmd, fn in [
        ("start", start),
        ("help", help_command),
        ("today", today),
        ("saved", saved),
        ("history", history),
        ("topics", topics),
        ("notes", notes),
        ("refresh", refresh_command),
        ("debugarticle", debug_article_command),
        ("end", end_command),
        ("note", note_command),
        ("finishimport", finish_import_command),
        ("cancelimport", cancel_import_command),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(article_action))
    app.add_handler(MessageHandler(filters.Document.ALL, document_import))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    print("My Marketing Brief v0.8 is running...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
