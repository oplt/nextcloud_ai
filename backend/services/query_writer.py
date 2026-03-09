from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ai.llm_client import LLMClientProtocol

# Heuristic: these patterns strongly suggest the turn references prior context.
_FOLLOW_UP_RE = re.compile(
    r"^\s*("
    r"it\b|its\b|they\b|their\b|them\b|"
    r"this\b|that\b|these\b|those\b|"
    r"the same\b|"
    r"also\b|and\b|but\b|"
    r"what about\b|how about\b|"
    r"why\b|when\b|where\b|who\b|which\b|"
    r"tell me more|explain|elaborate|"
    r"can you|could you|please\b"
    r")",
    re.IGNORECASE,
)

_SHORT_WORD_LIMIT = 10  # questions under this word-count with a follow-up opener => rewrite


def is_likely_follow_up(question: str, *, has_history: bool) -> bool:
    """Return True when the question looks like it relies on prior conversational context."""
    if not has_history:
        return False
    words = question.split()
    if len(words) <= _SHORT_WORD_LIMIT and _FOLLOW_UP_RE.search(question):
        return True
    # Very short bare questions (e.g. "why?", "and then?") are almost always follow-ups.
    if len(words) <= 4:
        return True
    return False


async def build_retrieval_query(
    *,
    question: str,
    history: list[dict[str, str]],
    llm_client: "LLMClientProtocol",
) -> tuple[str, bool]:
    """Return ``(retrieval_query, is_follow_up)``.

    When the current question is a follow-up, the LLM rewrites it into a
    fully self-contained retrieval query that incorporates relevant context
    from *history*.  The caller can use ``is_follow_up`` to decide whether
    to apply document-pinning in the retrieval stage.

    On any LLM failure the original *question* is returned unchanged so the
    system degrades gracefully rather than raising.
    """
    follow_up = is_likely_follow_up(question, has_history=bool(history))
    if not follow_up:
        return question, False

    # Use the last 4 user/assistant pairs at most to stay within context budget.
    recent_messages = history[-8:]
    history_text = "\n".join(
        f"{msg['role'].upper()}: {msg['content'][:400]}"
        for msg in recent_messages
    )

    rewrite_prompt = (
        "You are a search query rewriting assistant.\n"
        "Your ONLY job is to rewrite the LATEST USER QUESTION into a fully "
        "self-contained search query that does not depend on prior context.\n"
        "Rules:\n"
        "- Resolve all pronouns and references using the conversation history.\n"
        "- For follow-ups about sequence or comparison (after, before, next, previous), "
        "keep the person, employer, and timeframe explicit in the rewritten query.\n"
        "- Keep the query short (under 60 words).\n"
        "- Output ONLY the rewritten query. No preamble, no quotes, no explanation.\n\n"
        f"CONVERSATION HISTORY:\n{history_text}\n\n"
        f"LATEST USER QUESTION: {question}\n\n"
        "REWRITTEN SEARCH QUERY:"
    )

    try:
        rewritten = (await llm_client.generate(rewrite_prompt)).strip()
        # Sanity-check: reject empty or pathologically long rewrites.
        if not rewritten or len(rewritten) > 500:
            return question, True
        # Strip surrounding quotes that some models add.
        rewritten = rewritten.strip('"').strip("'").strip()
        return rewritten, True
    except Exception:
        # Never let a rewrite failure break the chat.
        return question, True
