from __future__ import annotations

import re
from dataclasses import dataclass

from ..parsers.document_parser import ParsedDocument


@dataclass(slots=True)
class IntelligenceExtractionResult:
    entities: dict[str, list[str]]
    obligations: list[str]
    deadlines: list[dict[str, str]]
    risks: list[str]
    action_items: list[str]
    decisions: list[str]
    renewal_or_expiry_dates: list[dict[str, str]]
    missing_information: list[str]
    policy_requirements: list[str]

    def as_payload(self) -> dict[str, object]:
        return {
            "entities": self.entities,
            "obligations": self.obligations,
            "deadlines": self.deadlines,
            "risks": self.risks,
            "action_items": self.action_items,
            "decisions": self.decisions,
            "renewal_or_expiry_dates": self.renewal_or_expiry_dates,
            "missing_information": self.missing_information,
            "policy_requirements": self.policy_requirements,
        }

    def counts(self) -> dict[str, int]:
        return {
            "entities": sum(len(values) for values in self.entities.values()),
            "obligations": len(self.obligations),
            "deadlines": len(self.deadlines),
            "risks": len(self.risks),
            "action_items": len(self.action_items),
            "decisions": len(self.decisions),
            "renewal_or_expiry_dates": len(self.renewal_or_expiry_dates),
            "missing_information": len(self.missing_information),
            "policy_requirements": len(self.policy_requirements),
        }


def extract_intelligence(parsed: ParsedDocument) -> IntelligenceExtractionResult:
    # Cap synchronous regex work. Full-document extraction should move to a worker/LLM job.
    text = (parsed.text or "")[:120_000]
    sentences = _sentences(text)

    dates = _unique(re.findall(
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
        text,
        re.I,
    ))[:50]
    amounts = _unique(re.findall(
        r"(?:[$€£]\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]*(?:\.\d{2})?\s?(?:USD|EUR|GBP)\b)",
        text,
        re.I,
    ))[:50]
    companies = _unique(re.findall(
        r"\b[A-Z][A-Za-z0-9&.,' -]{2,80}\s(?:Inc|LLC|Ltd|GmbH|SAS|SA|Corp|Corporation|Company)\b",
        text,
    ))[:30]
    people = _unique(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", text))[:25]
    projects = _unique(re.findall(r"\b(?:Project|Program|Initiative)\s+[A-Z][A-Za-z0-9_-]+\b", text))[:30]
    locations = _unique(re.findall(r"\b(?:in|at)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\b", text))[:20]

    obligations = _matching(sentences, ("shall", "must", "required to", "responsible for", "obligated"))
    risks = _matching(sentences, ("risk", "penalty", "breach", "non-compliance", "liability", "failure"))
    action_items = _matching(sentences, ("action item", "todo", "follow up", "owner:", "next step"))
    decisions = _matching(sentences, ("decided", "decision", "approved", "agreed", "resolved"))
    policy_requirements = _matching(sentences, ("policy requires", "must comply", "control", "standard", "procedure"))
    missing = _matching(sentences, ("tbd", "missing", "unknown", "to be provided", "not available"))
    deadline_sentences = _matching(sentences, ("due", "deadline", "by ", "no later than", "expires", "renewal"))

    return IntelligenceExtractionResult(
        entities={
            "people": people,
            "companies": companies,
            "dates": dates,
            "projects": projects,
            "locations": locations,
            "amounts": amounts,
        },
        obligations=obligations[:20],
        deadlines=[{"date": date, "evidence": _first_sentence_with(sentences, date)} for date in dates[:20]],
        risks=risks[:20],
        action_items=action_items[:20],
        decisions=decisions[:20],
        renewal_or_expiry_dates=[
            {"date": date, "evidence": sentence}
            for sentence in deadline_sentences
            for date in dates
            if date in sentence
        ][:20],
        missing_information=missing[:20],
        policy_requirements=policy_requirements[:20],
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 12]


def _matching(sentences: list[str], markers: tuple[str, ...]) -> list[str]:
    return [s for s in sentences if any(marker in s.lower() for marker in markers)]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _first_sentence_with(sentences: list[str], needle: str) -> str:
    return next((sentence for sentence in sentences if needle in sentence), "")

