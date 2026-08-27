import os
from typing import Iterable

import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_URL = "https://api.openai.com/v1/responses"


class AIUnavailable(RuntimeError):
    pass


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    pieces = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _article_context(article: dict) -> str:
    status = article.get("content_status") or "metadata_only"
    description = (article.get("meta_description") or article.get("summary") or "").strip()
    body = (article.get("plain_text") or "").strip()

    if status == "full":
        context_rule = "FULL CONTEXT: You may attribute claims to the article when supported by the supplied text."
    elif status == "partial":
        context_rule = (
            "PARTIAL CONTEXT: Only attribute claims that appear in the supplied excerpt/metadata. "
            "Do not present inferred themes as the article's argument."
        )
    else:
        context_rule = (
            "METADATA ONLY: Do not say 'the article argues', 'the article says', 'the core lesson is', "
            "or otherwise attribute substantive claims to the article. You may discuss the topic generally, "
            "but label that clearly as topic-level analysis. Ask for an excerpt/import when article-specific analysis is requested."
        )

    # Keep prompts economical while still supplying a substantial article context.
    body_for_model = body[:30000]

    return (
        f"Title: {article['title']}\n"
        f"Publication: {article['publication']}\n"
        f"Topic: {article['topic']}\n"
        f"URL: {article['url']}\n"
        f"Content status: {status}\n"
        f"Grounding rule: {context_rule}\n"
        f"Description: {description or '(none)'}\n"
        f"Article text/excerpt:\n{body_for_model or '(none)'}"
    )


def _history_text(history: Iterable[dict]) -> str:
    lines = []
    for message in history:
        role = "User" if message["role"] == "user" else "The Brief"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines[-12:])


def _call_openai(instructions: str, prompt: str, max_output_tokens: int = 700) -> str:
    if not OPENAI_API_KEY:
        raise AIUnavailable("OPENAI_API_KEY is not configured.")

    response = httpx.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        },
        timeout=45.0,
    )
    response.raise_for_status()
    text = _extract_output_text(response.json())
    if not text:
        raise AIUnavailable("The AI provider returned no text.")
    return text


def discuss(article: dict, history: list[dict], user_message: str) -> str:
    instructions = (
        "You are The Brief, a thoughtful professional-reading discussion partner. "
        "Help the user learn business, marketing, strategy, leadership, and technology through the selected article. "
        "Be concise but substantive. Test assumptions, explain unfamiliar concepts, and connect ideas to practical work. "
        "Ground article-specific claims only in the supplied context. "
        "If context is partial or metadata-only, explicitly distinguish article-grounded observations from general topic analysis. "
        "Never invent an article's thesis, examples, evidence, or conclusions. "
        "If deeper article-specific analysis requires missing text, ask the user to import or paste the relevant passage. "
        "Do not reproduce long copyrighted passages."
    )
    prompt = (
        f"ARTICLE\n{_article_context(article)}\n\n"
        f"RECENT DISCUSSION\n{_history_text(history) or '(none yet)'}\n\n"
        f"USER MESSAGE\n{user_message}"
    )
    return _call_openai(instructions, prompt)


def create_learning_note(article: dict, history: list[dict]) -> str:
    instructions = (
        "Create a compact learning note from a professional-reading discussion. "
        "Use exactly three short sections: Key idea, My takeaway, Application. "
        "Base article-specific claims only on supplied article context and the user's discussion. "
        "If the article context is partial, preserve that uncertainty. Do not invent claims."
    )
    prompt = (
        f"ARTICLE\n{_article_context(article)}\n\n"
        f"DISCUSSION\n{_history_text(history)}"
    )
    return _call_openai(instructions, prompt, max_output_tokens=400)
