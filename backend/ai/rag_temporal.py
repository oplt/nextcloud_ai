"""Shared year / employment / temporal heuristics for retrieval ranking and answer verification."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from backend.db.models import DocumentChunk

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(
    r"\b(?:[A-Za-z]{3,9}\s+)?(?P<start>(?:19|20)\d{2})\b"
    r"\s*(?:-|–|—|to|through|until)\s*"
    r"(?:(?:[A-Za-z]{3,9}\s+)?(?P<end>(?:19|20)\d{2})|(?P<open>present|current|now))",
    flags=re.IGNORECASE,
)
_EMPLOYMENT_HINT_RE = re.compile(
    r"\b(?:work experience|employment history|worked|employed|employment|job|role|position|"
    r"developer|engineer|analyst|researcher|manager|officer|consultant|specialist|intern)\b",
    flags=re.IGNORECASE,
)
_EDUCATION_HINT_RE = re.compile(
    r"\b(?:education|qualifications|qualification|phd|master(?:'s)?|bachelor(?:'s)?|student|"
    r"thesis|degree|diploma)\b",
    flags=re.IGNORECASE,
)


def extract_question_years(question: str) -> list[str]:
    return list(dict.fromkeys(_YEAR_RE.findall(question)))


def is_year_token(candidate: str) -> bool:
    c = candidate.strip()
    return bool(re.fullmatch(r"(?:19|20)\d{2}", c)) if c else False


def year_literal_present(text: str) -> bool:
    return bool(_YEAR_RE.search(text))


def employment_markers_present(text: str) -> bool:
    return bool(_EMPLOYMENT_HINT_RE.search(text))


def education_markers_present(text: str) -> bool:
    return bool(_EDUCATION_HINT_RE.search(text))


def extract_year_ranges(
    text: str,
    *,
    open_end_policy: Literal["start_year", "current_year"] = "start_year",
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    now_year = datetime.now(timezone.utc).year
    for match in _YEAR_RANGE_RE.finditer(text):
        start_year = int(match.group("start"))
        if match.group("end"):
            end_year = int(match.group("end"))
        elif match.group("open"):
            end_year = now_year if open_end_policy == "current_year" else start_year
        else:
            end_year = start_year
        if end_year < start_year:
            start_year, end_year = end_year, start_year
        ranges.append((start_year, end_year))
    return ranges


def text_supports_year(
    text: str,
    year: str,
    *,
    open_end_policy: Literal["start_year", "current_year"] = "start_year",
) -> bool:
    if re.search(rf"\b{re.escape(str(year))}\b", text):
        return True
    year_value = int(year)
    return any(
        start_year <= year_value <= end_year
        for start_year, end_year in extract_year_ranges(text, open_end_policy=open_end_policy)
    )


def looks_like_employment_question(question: str) -> bool:
    lowered = f" {question.lower()} "
    return any(
        term in lowered
        for term in (
            " work ",
            " worked ",
            " employer ",
            " employed ",
            " employment ",
            " company ",
            " job ",
            " role ",
        )
    )


def looks_like_relative_employment_question(question: str) -> bool:
    if not looks_like_employment_question(question):
        return False
    lowered = f" {question.lower()} "
    return any(
        marker in lowered
        for marker in (
            " after ",
            " before ",
            " next ",
            " previous ",
            " then ",
            " later ",
            " following ",
            " subsequent ",
            " prior ",
        )
    )


def chunk_haystack(chunk: DocumentChunk) -> str:
    document = chunk.document
    return " ".join(
        part.lower()
        for part in [
            document.file_name if document else "",
            document.file_path if document else "",
            chunk.section_title or "",
            chunk.content,
        ]
        if part
    )


def contextual_score_for_chunk(
    *,
    chunk: DocumentChunk,
    question: str,
    chunk_year_open_end_policy: Literal["start_year", "current_year"] = "start_year",
) -> float:
    haystack = chunk_haystack(chunk)
    if not haystack:
        return 0.0
    years = extract_question_years(question)
    employment_question = looks_like_employment_question(question)
    score = 0.0
    if years:
        if all(
            text_supports_year(haystack, year, open_end_policy=chunk_year_open_end_policy)
            for year in years
        ):
            score += 0.22
        elif _YEAR_RE.search(haystack):
            score -= 0.40
    has_employment_markers = bool(_EMPLOYMENT_HINT_RE.search(haystack))
    has_education_markers = bool(_EDUCATION_HINT_RE.search(haystack))
    if employment_question:
        if has_employment_markers:
            score += 0.18
        if has_education_markers and not has_employment_markers:
            score -= 0.45
        if (
            years
            and has_employment_markers
            and all(
                text_supports_year(haystack, year, open_end_policy=chunk_year_open_end_policy)
                for year in years
            )
        ):
            score += 0.08
    return score


def question_needs_multi_evidence(question: str) -> bool:
    lowered = question.lower()
    patterns = (
        "compare",
        "contrast",
        "difference",
        "differences",
        "timeline",
        "before and after",
        "pros and cons",
        "how many",
        "list all",
        "enumerate",
        "both",
        "versus",
        " vs ",
        "trade-off",
        "summarize all",
    )
    return any(p in lowered for p in patterns)
