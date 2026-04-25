from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

from ..rag.answer import build_source_block
from ..schemas.chat_schema import ChatSource

GROUNDED_PROMPT_VERSION = "2"
DEFAULT_DOMAIN_PROFILE = "default"


@dataclass(frozen=True, slots=True)
class DomainPromptProfile:
    name: str
    description: str
    rules: tuple[str, ...]


_DOMAIN_PROFILES: dict[str, DomainPromptProfile] = {
    "default": DomainPromptProfile(
        name="default",
        description="Domain-neutral private knowledge assistant behavior.",
        rules=(
            "Answer only from the provided sources.",
            "Treat the sources as the only allowed evidence.",
            "Do not infer missing facts beyond what the sources explicitly support.",
            "Do not use background knowledge to fill gaps.",
            "If a fact is not explicitly supported by a cited source excerpt, say that you could not verify it from the indexed sources.",
            "Absence of evidence is not evidence of absence; do not make negative claims merely because the retrieved sources are silent.",
            "For time-bound questions, an explicit date range in a source supports every point inside that range, but not dates outside it.",
            "If the user challenges a prior answer, re-check the provided sources and correct the answer if needed.",
            "State the direct answer in the first sentence when the evidence supports one.",
            "Cite source numbers inline, for example [1] or [1][2].",
            "Every supported factual statement must include at least one inline citation.",
            "Never cite a source that does not directly support the sentence it is attached to.",
        ),
    ),
    "employment_cv": DomainPromptProfile(
        name="employment_cv",
        description="CV/resume/employment-history verification behavior.",
        rules=(
            "For questions about whether a person worked at an employer, answer yes or no only if a source excerpt explicitly supports that claim.",
            "Do not answer that a person did not work somewhere unless a source explicitly says that.",
            "Do not treat education entries, degrees, student status, or training as employment unless the source explicitly describes a job, role, internship, contract, or work assignment.",
            "Preserve distinctions between employer, client, project, school, certification body, and location.",
        ),
    ),
    "contract_review": DomainPromptProfile(
        name="contract_review",
        description="Contract, policy, obligation, deadline, and clause-review behavior.",
        rules=(
            "Distinguish obligations, permissions, prohibitions, rights, deadlines, renewal terms, termination terms, penalties, and exceptions.",
            "Do not infer legal effect beyond the cited clause text.",
            "When the evidence is partial, identify the clause or excerpt that is available and state what remains unverified.",
        ),
    ),
    "technical_manual": DomainPromptProfile(
        name="technical_manual",
        description="Technical documentation, procedures, configuration, and operations behavior.",
        rules=(
            "Preserve exact component names, commands, configuration keys, versions, error codes, and procedural order from the sources.",
            "Do not invent missing steps or parameters.",
            "If a procedure is incomplete in the sources, say which required step or parameter is not verified.",
        ),
    ),
    "compliance_policy": DomainPromptProfile(
        name="compliance_policy",
        description="Compliance, internal policy, audit, and governance behavior.",
        rules=(
            "Distinguish mandatory requirements from recommendations and examples.",
            "Preserve policy scope, applicability, exceptions, effective dates, and responsible roles when cited.",
            "Do not claim compliance or non-compliance unless the cited evidence directly supports it.",
        ),
    ),
    "meeting_notes": DomainPromptProfile(
        name="meeting_notes",
        description="Meeting notes, decisions, action items, and discussion-summary behavior.",
        rules=(
            "Distinguish decisions, proposals, action items, owners, deadlines, and unresolved questions.",
            "Do not convert discussion or suggestions into confirmed decisions unless the source explicitly does so.",
            "When summarizing, keep attribution and dates if available in the sources.",
        ),
    ),
}


def available_domain_profiles() -> tuple[str, ...]:
    return tuple(_DOMAIN_PROFILES.keys())


def get_domain_profile(profile_name: str | None) -> DomainPromptProfile:
    if not profile_name:
        return _DOMAIN_PROFILES[DEFAULT_DOMAIN_PROFILE]
    return _DOMAIN_PROFILES.get(profile_name, _DOMAIN_PROFILES[DEFAULT_DOMAIN_PROFILE])


def _write_rules(buffer: io.StringIO, rules: Iterable[str]) -> None:
    for rule in rules:
        cleaned = " ".join(rule.split())
        if cleaned:
            buffer.write(f"- {cleaned}\n")


def _write_history(buffer: io.StringIO, history: list[dict[str, str]]) -> None:
    recent = history[-6:]
    buffer.write("\nCONVERSATION HISTORY (for conversational continuity only; sources remain the only evidence):\n")
    for msg in recent:
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        role_label = "USER" if role == "user" else "ASSISTANT"
        content = " ".join((msg.get("content") or "").split())
        if len(content) > 600:
            content = content[:597].rstrip() + "..."
        if content:
            buffer.write(f"{role_label}: {content}\n")


def build_grounded_prompt(
        question: str,
        sources: list[ChatSource],
        *,
        history: list[dict[str, str]] | None = None,
        memory_block: str | None = None,
        domain_profile: str | None = None,
        extra_rules: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Build a grounded answer prompt.

    Default behavior is domain-neutral. Domain-specific rules are opt-in through
    ``domain_profile`` so the generic product does not overfit to one document type.
    Existing callers remain compatible because all new arguments are keyword-only and
    optional.
    """
    profile = get_domain_profile(domain_profile)
    buffer = io.StringIO()

    buffer.write("You are a private company knowledge assistant.\n")
    buffer.write("Your job is to answer from retrieved indexed sources with strict citations.\n")

    buffer.write("\nBASE GROUNDING RULES:\n")
    _write_rules(buffer, _DOMAIN_PROFILES[DEFAULT_DOMAIN_PROFILE].rules)

    if profile.name != DEFAULT_DOMAIN_PROFILE:
        buffer.write(f"\nDOMAIN-SPECIFIC RULES ({profile.name}):\n")
        _write_rules(buffer, profile.rules)

    if extra_rules:
        buffer.write("\nADDITIONAL CALL-SITE RULES:\n")
        _write_rules(buffer, extra_rules)

    if memory_block:
        buffer.write("\nMEMORY CONTEXT (not evidence unless also supported by sources):\n")
        buffer.write(memory_block.strip())
        buffer.write("\n")

    if history:
        _write_history(buffer, history)

    buffer.write("\nQUESTION:\n")
    buffer.write(question)
    buffer.write("\n\nSOURCES:\n")
    buffer.write(build_source_block(sources))
    buffer.write("\n")

    buffer.write(
        "\nFINAL ANSWER RULES:\n"
        "- Use only the sources above as evidence.\n"
        "- If the sources are insufficient, say so clearly and do not make a positive or negative claim.\n"
        "- If no retrieved source directly answers the question, answer exactly: "
        '"I could not verify this from the retrieved indexed sources. The available evidence is insufficient to answer without guessing."\n'
        "- Do not repeat or restate the user question at the start of the answer.\n"
        "- Keep the answer concise and factual.\n"
        "- Include inline citations for every supported factual statement.\n"
        "- Do not include a citation on unsupported or insufficiency statements.\n\n"
        "FINAL ANSWER:\n"
    )
    return buffer.getvalue()