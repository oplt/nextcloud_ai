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


@dataclass(frozen=True, slots=True)
class WeightedRule:
    label: str
    patterns: tuple[tuple[str, float], ...]


TYPE_RULES: tuple[WeightedRule, ...] = (
    WeightedRule("invoice_finance", (
        (r"\binvoice\b", 3.5), (r"\breceipt\b", 2.5), (r"\bpayment due\b", 3.0),
        (r"\bvat\b", 2.0), (r"\btax\b", 1.0), (r"\btotal amount\b", 2.5),
        (r"\bpurchase order\b|\bpo[-\s]?\d+\b", 2.8),
    )),
    WeightedRule("contract", (
        (r"\bagreement\b", 3.0), (r"\bcontract\b", 3.0), (r"\bparty\b|\bparties\b", 1.8),
        (r"\bterm\b", 1.2), (r"\btermination\b", 2.0), (r"\bconfidentiality\b", 2.2),
        (r"\bmsa\b|\bnda\b|\bdpa\b", 3.2),
    )),
    WeightedRule("legal", (
        (r"\blegal\b", 2.2), (r"\blitigation\b", 3.0), (r"\bcounsel\b", 2.5),
        (r"\bclaim\b", 2.0), (r"\bliability\b", 2.0), (r"\bcourt\b", 2.2),
    )),
    WeightedRule("compliance", (
        (r"\bgdpr\b|\biso\s?27001\b|\bsoc\s?2\b", 3.5), (r"\baudit\b", 2.5),
        (r"\bcompliance\b", 3.0), (r"\bregulation\b", 2.0), (r"\bpolicy\b", 1.5),
        (r"\bcontrol\b", 1.7), (r"\brisk assessment\b", 2.6),
    )),
    WeightedRule("meeting_notes", (
        (r"\bmeeting minutes\b|\bminutes\b", 3.4), (r"\bmeeting notes\b", 3.4),
        (r"\battendees\b", 2.0), (r"\bagenda\b", 2.0), (r"\baction items?\b", 2.6),
        (r"\bdecisions?\b", 2.0),
    )),
    WeightedRule("technical_documentation", (
        (r"\bapi\b", 2.2), (r"\bendpoint\b", 2.5), (r"\binstallation\b", 2.6),
        (r"\bconfiguration\b", 2.0), (r"\btechnical\b", 2.0), (r"\bmanual\b", 2.4),
        (r"\bspecification\b|\bspec\b", 2.5), (r"\bdatasheet\b", 3.0),
    )),
    WeightedRule("hr", (
        (r"\bemployee\b", 2.4), (r"\bonboarding\b", 2.6), (r"\bpayroll\b", 3.0),
        (r"\bleave policy\b", 2.8), (r"\bcv\b|\bresume\b", 3.0), (r"\bbenefits\b", 1.6),
    )),
    WeightedRule("sales_proposal", (
        (r"\bproposal\b", 3.2), (r"\bquote\b|\bquotation\b", 3.0), (r"\brfp\b", 3.0),
        (r"\boffer\b", 2.2), (r"\bpricing\b", 1.8), (r"\bclient\b", 1.3),
    )),
    WeightedRule("project_document", (
        (r"\bproject plan\b", 3.2), (r"\broadmap\b", 2.6), (r"\brequirements\b", 2.2),
        (r"\bsprint\b", 2.0), (r"\bmilestone\b", 2.0), (r"\bokr\b", 1.8),
    )),
    WeightedRule("support_operations", (
        (r"\brunbook\b", 3.2), (r"\bincident\b", 2.8), (r"\bticket\b", 2.4),
        (r"\bsla\b", 2.5), (r"\bsupport\b", 2.0), (r"\bpostmortem\b", 2.8),
    )),
)

DOMAIN_RULES: tuple[WeightedRule, ...] = (
    WeightedRule("legal", ((r"\blegal\b|\bagreement\b|\bcontract\b|\bnda\b|\blitigation\b", 3.0),)),
    WeightedRule("finance", ((r"\binvoice\b|\bpayment\b|\breceipt\b|\bbudget\b|\bvat\b|\baccounting\b", 3.0),)),
    WeightedRule("hr", ((r"\bemployee\b|\bpayroll\b|\bonboarding\b|\bleave\b|\bresume\b|\bcv\b", 3.0),)),
    WeightedRule("engineering", ((r"\bapi\b|\btechnical\b|\bspec\b|\binstallation\b|\bdeployment\b|\bendpoint\b", 3.0),)),
    WeightedRule("operations", ((r"\brunbook\b|\bincident\b|\bprocess\b|\bprocedure\b|\boperations\b", 3.0),)),
    WeightedRule("sales", ((r"\bproposal\b|\bclient\b|\bquote\b|\brfp\b|\bsales\b|\boffer\b", 3.0),)),
    WeightedRule("procurement", ((r"\bsupplier\b|\bvendor\b|\bpurchase order\b|\bprocurement\b|\bpo[-\s]?\d+\b", 3.0),)),
    WeightedRule("compliance", ((r"\bcompliance\b|\bgdpr\b|\biso\s?27001\b|\baudit\b|\bpolicy\b|\bcontrol\b", 3.0),)),
    WeightedRule("customer_support", ((r"\bsupport\b|\bticket\b|\bcustomer\b|\bsla\b", 3.0),)),
    WeightedRule("management", ((r"\bboard\b|\bstrategy\b|\bokr\b|\bkpi\b|\bmanagement\b", 3.0),)),
)


class DocumentClassifier:
    def __init__(self, llm_client: LLMClientProtocol | None = None) -> None:
        self.llm_client = llm_client if llm_client is not None else LLMClientFactory.create()

    async def classify(self, *, document: Document, parsed: ParsedDocument) -> ClassificationResult:
        if document.manual_category_override:
            return ClassificationResult(
                document_type=document.document_type or "unclassified",
                document_type_confidence=document.document_type_confidence or 1.0,
                document_type_reason=document.document_type_reason or "Manual override.",
                document_type_source="manual",
                business_domain=document.business_domain or "unknown",
                business_domain_confidence=document.business_domain_confidence or 1.0,
                business_domain_reason=document.business_domain_reason or "Manual override.",
                business_domain_source="manual",
            )

        rule_result = rule_classify(document=document, parsed=parsed)

        # Fast path: trust precise rules. This removes most unnecessary LLM calls.
        if (
                rule_result.document_type_confidence >= 0.78
                and rule_result.business_domain_confidence >= 0.72
                and rule_result.document_type != "unclassified"
        ):
            return rule_result

        llm_result = await self._classify_with_llm(document=document, parsed=parsed, fallback=rule_result)
        if llm_result is None:
            return rule_result

        # Do not allow a low-confidence LLM answer to replace stronger deterministic evidence.
        if llm_result.document_type_confidence + 0.10 < rule_result.document_type_confidence:
            return rule_result

        return llm_result

    async def _classify_with_llm(
            self, *, document: Document, parsed: ParsedDocument, fallback: ClassificationResult
    ) -> ClassificationResult | None:
        if isinstance(self.llm_client, StubGroundedLLMClient):
            return None

        sample = _classification_sample(parsed.text)
        headings = _headings(parsed.text)[:15]
        prompt = (
            "You classify enterprise documents for ingestion. Return strict JSON only with these keys: "
            "document_type, document_type_confidence, document_type_reason, "
            "business_domain, business_domain_confidence, business_domain_reason. "
            f"Allowed document_type values: {DOCUMENT_TYPES}. "
            f"Allowed business_domain values: {BUSINESS_DOMAINS}. "
            "Use unclassified and unknown when evidence is weak. Confidence must be 0.0 to 1.0. "
            "Prefer exact document purpose over generic words.\n\n"
            f"File path: {document.file_path}\n"
            f"File name: {document.file_name}\n"
            f"MIME: {document.mime_type}\n"
            f"Rule fallback: {fallback.document_type}/{fallback.business_domain}\n"
            f"Headings: {headings}\n"
            f"Text sample:\n{sample}"
        )

        try:
            raw = await self.llm_client.generate(prompt)
            data = json.loads(_json_object(raw))
        except Exception:
            return None

        doc_type = str(data.get("document_type") or "unclassified")
        domain = str(data.get("business_domain") or "unknown")
        if doc_type not in DOCUMENT_TYPES:
            doc_type = "unclassified"
        if domain not in BUSINESS_DOMAINS:
            domain = "unknown"

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
    doc_type, type_score, type_terms, type_margin = _best_match(haystack, TYPE_RULES)
    domain, domain_score, domain_terms, domain_margin = _best_match(haystack, DOMAIN_RULES)

    if doc_type is None or type_score < 2.3:
        doc_type = "unclassified"
        type_confidence = 0.25
        type_reason = "No strong taxonomy signal matched filename, path, headings, or text sample."
        type_source = "fallback"
    else:
        type_confidence = _score_to_confidence(type_score, type_margin)
        type_reason = f"Matched weighted evidence: {', '.join(type_terms[:5])}."
        type_source = "rule"

    if domain is None or domain_score < 2.3:
        domain = "unknown"
        domain_confidence = 0.25
        domain_reason = "No strong business-domain signal matched filename, path, headings, or text sample."
        domain_source = "fallback"
    else:
        domain_confidence = _score_to_confidence(domain_score, domain_margin)
        domain_reason = f"Matched weighted evidence: {', '.join(domain_terms[:5])}."
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
    ext = Path(document.file_name or "").suffix.lower()
    headings = " ".join(_headings(parsed.text or "")[:25])
    path_boost = " ".join(Path(document.file_path or "").parts[-4:])
    text_sample = _classification_sample(parsed.text or "")
    return _normalize(f"{document.file_name} {path_boost} {ext} {document.mime_type or ''} {headings} {text_sample}")


def _classification_sample(text: str, limit: int = 9000) -> str:
    if not text:
        return ""
    head = text[: limit // 2]
    tail = text[-limit // 2 :] if len(text) > limit else ""
    return f"{head}\n{tail}"


def _best_match(haystack: str, rules: tuple[WeightedRule, ...]) -> tuple[str | None, float, list[str], float]:
    scored: list[tuple[str, float, list[str]]] = []
    for rule in rules:
        score = 0.0
        matched: list[str] = []
        for pattern, weight in rule.patterns:
            if re.search(pattern, haystack, flags=re.I):
                score += weight
                matched.append(pattern)
        if score:
            scored.append((rule.label, score, matched))

    if not scored:
        return None, 0.0, [], 0.0

    scored.sort(key=lambda item: item[1], reverse=True)
    best = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    margin = best[1] - second_score
    return best[0], best[1], best[2], margin


def _score_to_confidence(score: float, margin: float) -> float:
    base = min(0.93, 0.35 + score * 0.09)
    if margin >= 2.5:
        base += 0.08
    elif margin < 1.0:
        base -= 0.10
    return max(0.30, min(0.95, base))


def _headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
        elif 3 <= len(stripped) <= 90 and stripped[:1].isupper() and not stripped.endswith("."):
            headings.append(stripped)
    return headings


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).lower()


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