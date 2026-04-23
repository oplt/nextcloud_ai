from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.ai.follow_up_classifier import FollowUpClassification, classify_follow_up

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

_SHORT_WORD_LIMIT = 10


def is_likely_follow_up(question: str, *, has_history: bool) -> bool:
    """Backward-compatible coarse follow-up flag."""
    return classify_follow_up(question, has_history=has_history).is_follow_up


@dataclass(slots=True)
class RetrievalQueryPlan:
    retrieval_query: str
    is_follow_up: bool
    follow_up: FollowUpClassification


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
    legacy_signal = (
        len(question.split()) <= _SHORT_WORD_LIMIT and _FOLLOW_UP_RE.search(question)
    )
    eligible = structured.is_follow_up or (
        bool(history) and legacy_signal and structured.confidence >= 0.35
    )
    if not eligible:
        return RetrievalQueryPlan(
            retrieval_query=question,
            is_follow_up=False,
            follow_up=structured,
        )

    recent_messages = history[-8:]
    history_text = "\n".join(
        f"{msg['role'].upper()}: {msg['content'][:400]}" for msg in recent_messages
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
        if not rewritten or len(rewritten) > 500:
            return RetrievalQueryPlan(
                retrieval_query=question,
                is_follow_up=structured.confidence >= 0.55,
                follow_up=structured,
            )
        rewritten = rewritten.strip('"').strip("'").strip()
        is_follow_up = structured.confidence >= 0.55
        return RetrievalQueryPlan(
            retrieval_query=rewritten,
            is_follow_up=is_follow_up,
            follow_up=structured,
        )
    except Exception:
        return RetrievalQueryPlan(
            retrieval_query=question,
            is_follow_up=structured.confidence >= 0.55,
            follow_up=structured,
        )
