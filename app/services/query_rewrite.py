"""Lightweight conversational query rewriting for follow-up questions."""

from __future__ import annotations

import logging
import os
import re

from openai import OpenAI

from app.infra.cache.chat_memory import ChatTurn

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
SHORT_FOLLOW_UP_RE = re.compile(
    r"^(what about|how about)\s+(.+)\??$",
    re.IGNORECASE,
)


def _heuristic_rewrite(query: str, history: list[ChatTurn]) -> str | None:
    if not history:
        return None
    last = history[-1]
    stripped = query.strip()

    match = SHORT_FOLLOW_UP_RE.match(stripped)
    if match:
        topic = match.group(2).strip(" ?")
        # e.g. "What about Vault?" + prior startup validation question
        return f"{topic} in the context of: {last.query}"

    if len(stripped.split()) <= 6 and stripped.lower().startswith(("and ", "also ")):
        return f"{stripped} (follow-up to: {last.query})"

    if stripped.endswith("?") and len(stripped.split()) <= 5:
        return f"{stripped} — continuing discussion about: {last.query}"

    return None


def _llm_rewrite(query: str, history: list[ChatTurn], client: OpenAI, model: str) -> str | None:
    if not history:
        return None
    lines = []
    for turn in history[-4:]:
        lines.append(f"User: {turn.query}")
        lines.append(f"Assistant: {turn.answer[:500]}")
    conversation = "\n".join(lines)
    prompt = (
        "Rewrite the latest user message as a standalone search query for documentation retrieval.\n"
        "Resolve pronouns and follow-ups using conversation history.\n"
        "Output ONLY the rewritten query, no quotes.\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest user message: {query}\n\n"
        "Standalone query:"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=120,
        )
        rewritten = (response.choices[0].message.content or "").strip()
        return rewritten if rewritten else None
    except Exception as exc:
        logger.warning("query_rewrite_failed", extra={"error": str(exc)})
        return None


def rewrite_query(
    query: str,
    history: list[ChatTurn],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> tuple[str, bool]:
    """
    Return (standalone_query, was_rewritten).
  Falls back to original query on failure.
    """
    if not history:
        return query, False

    heuristic = _heuristic_rewrite(query, history)
    if heuristic:
        logger.info("query_rewritten", extra={"method": "heuristic", "rewritten": heuristic[:200]})
        return heuristic, True

    if client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return query, False
        client = OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL", GROQ_BASE_URL))

    model = model or os.environ.get("RAG_MODEL", "llama-3.1-8b-instant")
    llm_result = _llm_rewrite(query, history, client, model)
    if llm_result:
        logger.info("query_rewritten", extra={"method": "llm", "rewritten": llm_result[:200]})
        return llm_result, True

    return query, False
