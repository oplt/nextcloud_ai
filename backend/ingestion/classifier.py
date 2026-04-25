from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..ai.llm_client import LLMClientFactory, LLMClientProtocol, StubGroundedLLMClient
from ..db.models import Document
from ..parsers.document_parser import ParsedDocument
from .taxonomy import BUSINESS_DOMAINS, DOCUMENT_TYPES


@dataclass(slots=True)
class ClassificationResult:
    document_type: str
    document_type_confidence: float
    document_type_reason: str
    document_type_source: str
    business_domain: str
    business_domain_confidence: float
    business_domain_reason: str
    business_domain_source: str


TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("contract", ("agreement", "contract", "terms", "msa", "nda")),
    ("invoice_finance", ("invoice", "receipt", "payment", "purchase order", " po ", "po-")),
    ("compliance", ("gdpr", "iso", "audit", "safety", "compliance", "regulation")),
    ("meeting_notes", ("minutes", "meeting", "transcript", "notes", "decision log")),
    ("technical_documentation", ("manual", "installation", "specification", "technical", "datasheet")),
    ("hr", ("cv", "resume", "employee", "onboarding", "leave", "payroll")),
    ("sales_proposal", ("proposal", "offer", "quote", "rfp", "sales")),
    ("project_document", ("roadmap", "requirements", "sprint", "project plan")),
    ("support_operations", ("runbook", "incident", "support", "ticket", "sla")),
    ("legal", ("legal", "litigation", "counsel", "claim")),
]

DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("legal", ("legal", "agreement", "contract", "terms", "nda", "litigation")),
    ("finance", ("finance", "accounting", "invoice", "payment", "receipt", "budget")),
    ("engineering", ("engineering", "technical", "spec", "manual", "installation", "api")),
    ("sales", ("sales", "proposal", "client", "quote", "rfp", "offer")),
    ("procurement", ("procurement", "supplier", "vendor", "purchase order", "po")),
    ("hr", ("hr", "employee", "payroll", "onboarding", "leave", "resume")),
    ("operations", ("operations", "procedure", "runbook", "incident", "process")),
    ("compliance", ("compliance", "gdpr", "iso", "audit", "regulation", "policy")),
    ("customer_support", ("support", "ticket", "customer", "sla")),
    ("management", ("management", "board", "strategy", "okr", "kpi")),
]


class DocumentClassifier:
    def __init__(self, llm_client: LLMClientProtocol | None = None) -> None:
        self.llm_client = llm_client if llm_client is not None else LLMClientFactory.create()

    async def classify(self, *, document: Document, parsed: ParsedDocument) -> ClassificationResult:
        if document.manual_category_override:
            return ClassificationResult(
                document_type=document.document_type,
                document_type_confidence=document.document_type_confidence or 1.0,
                document_type_reason=document.document_type_reason or "Manual override.",
                document_type_source="manual",
                business_domain=document.business_domain,
                business_domain_confidence=document.business_domain_confidence or 1.0,
                business_domain_reason=document.business_domain_reason or "Manual override.",
                business_domain_source="manual",
            )

        rule_result = rule_classify(document=document, parsed=parsed)
        llm_result = await self._classify_with_llm(document=document, parsed=parsed, fallback=rule_result)
        return llm_result or rule_result

    async def _classify_with_llm(
        self, *, document: Document, parsed: ParsedDocument, fallback: ClassificationResult
    ) -> ClassificationResult | None:
        if isinstance(self.llm_client, StubGroundedLLMClient):
            return None
        headings = _headings(parsed.text)[:20]
        prompt = (
            "Classify document. Return strict JSON only. "
            f"Allowed document_type: {DOCUMENT_TYPES}. "
            f"Allowed business_domain: {BUSINESS_DOMAINS}. "
            "Use unclassified/unknown with low confidence if unsure. "
            f"File: {document.file_path}\n"
            f"MIME: {document.mime_type}\n"
            f"Headings: {headings}\n"
            f"Text: {parsed.text[:5000]}"
        )
        try:
            raw = await self.llm_client.generate(prompt)
            data = json.loads(_json_object(raw))
        except Exception:
            return None

        doc_type = str(data.get("document_type") or "")
        domain = str(data.get("business_domain") or "")
        if doc_type not in DOCUMENT_TYPES or domain not in BUSINESS_DOMAINS:
            return None
        return ClassificationResult(
            document_type=doc_type,
            document_type_confidence=_confidence(data.get("document_type_confidence"), fallback.document_type_confidence),
            document_type_reason=str(data.get("document_type_reason") or "LLM classification."),
            document_type_source="llm",
            business_domain=domain,
            business_domain_confidence=_confidence(data.get("business_domain_confidence"), fallback.business_domain_confidence),
            business_domain_reason=str(data.get("business_domain_reason") or "LLM classification."),
            business_domain_source="llm",
        )


def rule_classify(*, document: Document, parsed: ParsedDocument) -> ClassificationResult:
    haystack = _haystack(document=document, parsed=parsed)
    doc_type, type_score, type_terms = _best_match(haystack, TYPE_RULES)
    domain, domain_score, domain_terms = _best_match(haystack, DOMAIN_RULES)

    if doc_type is None:
        doc_type = "unclassified"
        type_confidence = 0.25
        type_reason = "No taxonomy rule matched path, filename, headings, or body preview."
        type_source = "fallback"
    else:
        type_confidence = min(0.95, 0.45 + type_score * 0.12)
        type_reason = f"Matched {', '.join(type_terms[:4])}."
        type_source = "rule"

    if domain is None:
        domain = "unknown"
        domain_confidence = 0.25
        domain_reason = "No business domain rule matched path, filename, headings, or body preview."
        domain_source = "fallback"
    else:
        domain_confidence = min(0.95, 0.45 + domain_score * 0.12)
        domain_reason = f"Matched {', '.join(domain_terms[:4])}."
        domain_source = "rule"

    return ClassificationResult(
        document_type=doc_type,
        document_type_confidence=type_confidence,
        document_type_reason=type_reason,
        document_type_source=type_source,
        business_domain=domain,
        business_domain_confidence=domain_confidence,
        business_domain_reason=domain_reason,
        business_domain_source=domain_source,
    )


def _haystack(*, document: Document, parsed: ParsedDocument) -> str:
    ext = Path(document.file_name).suffix.lower()
    headings = " ".join(_headings(parsed.text)[:30])
    return f" {document.file_name} {document.file_path} {ext} {document.mime_type or ''} {headings} {parsed.text[:8000]} ".lower()


def _best_match(haystack: str, rules: list[tuple[str, tuple[str, ...]]]) -> tuple[str | None, int, list[str]]:
    best: tuple[str | None, int, list[str]] = (None, 0, [])
    for category, terms in rules:
        matched = [term.strip() for term in terms if term in haystack]
        score = len(matched)
        if score > best[1]:
            best = (category, score, matched)
    return best


def _headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
        elif 3 <= len(stripped) <= 90 and stripped[:1].isupper() and not stripped.endswith("."):
            headings.append(stripped)
    return headings


def _json_object(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return raw[start : end + 1]


def _confidence(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))

