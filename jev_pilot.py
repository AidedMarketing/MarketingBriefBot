"""Durable shadow evaluation. Never modifies recommendations or extraction status."""

import logging
import threading

from database import get_article, get_jev_evaluation, save_jev_evaluation
from jev import JevConfig, evaluate_article, evaluation_key

logger = logging.getLogger(__name__)
_evaluation_lock = threading.Lock()


def inspect_article(article, config=None):
    config = config or JevConfig.from_env()
    row = get_jev_evaluation(article["id"], evaluation_key(article, config))
    return row["result"] if row else None


def evaluate_stored_article(article, config=None):
    """Evaluate the committed public text, with caching and a retry cooldown."""
    config = config or JevConfig.from_env()
    if not config.enabled:
        return {"status": "disabled" if config.mode == "off" else "unconfigured"}
    if not _evaluation_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        # Reload after enrichment: rejected content writes must not become the state.
        stored = get_article(article["id"])
        if not stored:
            return {"status": "missing_article"}
        fingerprint = evaluation_key(stored, config)
        existing = get_jev_evaluation(stored["id"], fingerprint)
        if existing:
            result = existing["result"]
            if result.get("status") != "error" or existing["recent"]:
                return dict(result, cached=True)
        result = evaluate_article(stored, config)
        save_jev_evaluation(stored["id"], result)
        logger.info("Jev shadow evaluation article_id=%s status=%s model=%s duration_ms=%s input_tokens=%s",
                    stored["id"], result["status"], result.get("model", config.model),
                    result.get("duration_ms"), (result.get("usage") or {}).get("input_tokens"))
        return result
    except Exception as exc:
        # Database or unexpected failures must not disrupt the daily reading workflow.
        logger.warning("Jev pilot unavailable article_id=%s error_type=%s", article.get("id"), type(exc).__name__)
        return {"status": "error", "error_type": "pilot_unavailable"}
    finally:
        _evaluation_lock.release()


def format_evaluation(result):
    if not result:
        return "No evaluation for the current article text yet. Use /jev evaluate."
    status = result.get("status", "unknown")
    messages = {
        "disabled": "Jev is off. Set JEV_MODE=shadow in Railway to enable the pilot.",
        "unconfigured": "Jev needs TYPESAFE_API_KEY in Railway before live evaluation can run.",
        "busy": "Another article is being evaluated. Try /jev evaluate again shortly.",
        "missing_article": "The selected article is no longer available.",
        "skipped_empty": "Skipped: no stored article body yet. This is not an assessment of the original article.",
        "skipped_oversized": "Skipped: the stored text exceeds the pilot's conservative input limit. No text was clipped or evaluated.",
        "error": "Jev could not complete this evaluation. Reading and daily selection continue normally. Stored provider errors retry after 15 minutes.",
    }
    if status != "ok":
        return messages.get(status, "Evaluation unavailable.")
    answers = result["answers"]
    kind, topic, practical = (answers[k] for k in ("content_kind", "topic", "practical_value"))
    tokens = (result.get("usage") or {}).get("input_tokens")
    return "\n".join([
        "Shadow evaluation — it does not change your daily pick.",
        f"Content: {kind['choice']} (confidence {kind['confidence']:.2f})",
        f"Topic: {topic['choice']} (confidence {topic['confidence']:.2f})",
        f"Practical value: {practical['score']:.2f}/3 (confidence {practical['confidence']:.2f})",
        f"Concrete example probability: {answers['concrete_example']['noul']:.2f}",
        f"Access message probability: {answers['access_signal']['noul']:.2f}",
        f"Evaluated words: {result.get('word_count', 0):,}",
        f"Model: {result['model']} | Rubric: {result['rubric_version']}",
        f"Duration: {result.get('duration_ms', 0)} ms | Input tokens: {tokens if tokens is not None else 'not reported'}",
        "Judgments concern supplied text; they do not prove article completeness or factual accuracy.",
    ])
