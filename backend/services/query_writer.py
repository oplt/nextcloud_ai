from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..ai.follow_up_classifier import (
    FollowUpClassification,
    classify_follow_up,
    has_contextual_reference,
    is_challenge_turn,
)

if TYPE_CHECKING:
    from ai.llm_client import LLMClientProtocol

_CITATION_TAIL_RE = re.compile(r"\s*\[\d+\](?:\s*\[\d+\])*\s*$")
_MAX_HISTORY_MESSAGES = 8
_MAX_HISTORY_MESSAGE_CHARS = 420
_MAX_REWRITE_CHARS = 500
_MAX_REWRITE_WORDS = 70
_STRICT_CONTEXT_REFERENCE_RE = re.compile(
    r"\b(it|its|they|them|this|these|those|same|previous|prior|next|above|below|there|here)\b|^\s*(what|how)\s+about\b",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class RetrievalQueryPlan:
    retrieval_query: str
    is_follow_up: bool
    follow_up: FollowUpClassification


def is_likely_follow_up(question: str, *, has_history: bool) -> bool:
    """Backward-compatible coarse follow-up flag."""
    return classify_follow_up(question, has_history=has_history).is_follow_up


def _strip_citation_tail(text: str) -> str:
    return _CITATION_TAIL_RE.sub("", text).strip()


def _compress_whitespace(text: str) -> str:
    return " ".join(text.split())


def _clean_history_content(content: str, *, limit: int = _MAX_HISTORY_MESSAGE_CHARS) -> str:
    content = _compress_whitespace(_strip_citation_tail(content or ""))
    if len(content) > limit:
        return content[: limit - 3].rstrip() + "..."
    return content


def _recent_user_context(history: list[dict[str, str]], *, max_items: int = 3) -> list[str]:
    """Return recent user turns only.

    Fallback retrieval queries should not use prior assistant answers as factual evidence,
    because a challenged answer may be wrong. User turns are safer context anchors.
    """
    user_turns: list[str] = []
    for message in reversed(history[-_MAX_HISTORY_MESSAGES:]):
        if message.get("role") != "user":
            continue
        content = _clean_history_content(message.get("content", ""), limit=180)
        if content:
            user_turns.append(content)
        if len(user_turns) >= max_items:
            break
    return list(reversed(user_turns))


def _format_history_for_rewrite(history: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in history[-_MAX_HISTORY_MESSAGES:]:
        role = (message.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clean_history_content(message.get("content", ""))
        if not content:
            continue
        # Keep assistant turns for reference resolution, but the rewrite prompt makes clear
        # that assistant statements are not evidence for final answering.
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)


def _build_contextual_follow_up_query(
        *,
        question: str,
        history: list[dict[str, str]],
) -> str:
    """Conservative fallback when the rewrite LLM fails or returns an unsafe rewrite."""
    prior_user_turns = _recent_user_context(history)
    if not prior_user_turns:
        return question

    rewritten = f"{question} Context from prior user turns: {' '.join(prior_user_turns)}"
    return _compress_whitespace(rewritten)[:_MAX_REWRITE_CHARS]


def _looks_like_bad_rewrite(*, original_question: str, rewritten: str) -> bool:
    if not rewritten:
        return True
    if len(rewritten) > _MAX_REWRITE_CHARS:
        return True
    if len(rewritten.split()) > _MAX_REWRITE_WORDS:
        return True
    if rewritten.casefold() in {
        "i don't know",
        "i cannot answer",
        "cannot answer",
        "not enough information",
    }:
        return True
    if rewritten.startswith(("- ", "* ", "1.")):
        return True
    if "\n" in rewritten:
        return True
    # For a context-dependent original question, an identical rewrite usually means the
    # model failed to resolve references.
    if has_contextual_reference(original_question) and rewritten.casefold() == original_question.casefold():
        return True
    return False


def _has_strict_context_reference(question: str) -> bool:
    return bool(_STRICT_CONTEXT_REFERENCE_RE.search(question))


async def build_retrieval_query(
        *,
        question: str,
        history: list[dict[str, str]],
        llm_client: "LLMClientProtocol",
) -> tuple[str, bool]:
    """Return ``(retrieval_query, is_follow_up)`` for pinning and logging."""
    plan = await plan_retrieval_query(question=question, history=history, llm_client=llm_client)
    return plan.retrieval_query, plan.is_follow_up


async def plan_retrieval_query(
        *,
        question: str,
        history: list[dict[str, str]],
        llm_client: "LLMClientProtocol",
) -> RetrievalQueryPlan:
    structured = classify_follow_up(question, has_history=bool(history))
    contextual_signal = bool(history) and (
            _has_strict_context_reference(question) or is_challenge_turn(question)
    )

    if not contextual_signal:
        return RetrievalQueryPlan(
            retrieval_query=question,
            is_follow_up=False,
            follow_up=structured,
        )

    is_follow_up = True

    history_text = _format_history_for_rewrite(history)
    if not history_text:
        return RetrievalQueryPlan(
            retrieval_query=question,
            is_follow_up=False,
            follow_up=structured,
        )

    rewrite_prompt = (
        "You are a search query rewriting assistant for a retrieval system.\n"
        "Your only task is to rewrite the latest user question into one concise, "
        "self-contained search query.\n"
        "Use the conversation history only to resolve references. Do not treat prior "
        "assistant answers as factual evidence.\n\n"
        "Rules:\n"
        "- Resolve pronouns, demonstratives, ellipsis, and vague references.\n"
        "- Preserve the relevant entities, dates, document names, section names, identifiers, "
        "locations, and timeframes.\n"
        "- For comparison or sequence follow-ups, preserve both sides of the comparison or "
        "the relevant before/after anchor.\n"
        "- For challenge turns such as 'are you sure?' or 'check again', rewrite the query "
        "to re-check the original factual issue, not the assistant's wording.\n"
        "- Keep the query under 60 words.\n"
        "- Output only the rewritten query. No preamble, quotes, bullets, or explanation.\n\n"
        f"CONVERSATION HISTORY:\n{history_text}\n\n"
        f"LATEST USER QUESTION: {question}\n\n"
        "REWRITTEN SEARCH QUERY:"
    )

    fallback_query = _build_contextual_follow_up_query(question=question, history=history)

    try:
        rewritten = (await llm_client.generate(rewrite_prompt)).strip()
        rewritten = rewritten.strip('"').strip("'").strip()
        rewritten = _compress_whitespace(rewritten)
        if _looks_like_bad_rewrite(original_question=question, rewritten=rewritten):
            rewritten = fallback_query
        return RetrievalQueryPlan(
            retrieval_query=rewritten,
            is_follow_up=is_follow_up,
            follow_up=structured,
        )
    except Exception:
        return RetrievalQueryPlan(
            retrieval_query=fallback_query,
            is_follow_up=is_follow_up,
            follow_up=structured,
        )