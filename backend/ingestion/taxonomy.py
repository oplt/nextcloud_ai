from __future__ import annotations

from typing import Literal

DOCUMENT_TYPES = [
    "contract",
    "invoice_finance",
    "legal",
    "compliance",
    "meeting_notes",
    "technical_documentation",
    "hr",
    "sales_proposal",
    "project_document",
    "support_operations",
    "general_knowledge",
    "unclassified",
]

BUSINESS_DOMAINS = [
    "legal",
    "finance",
    "hr",
    "engineering",
    "operations",
    "sales",
    "procurement",
    "compliance",
    "customer_support",
    "management",
    "unknown",
]

CLASSIFICATION_SOURCES = ["rule", "llm", "manual", "fallback"]
PARSE_STATUSES = [
    "pending",
    "parsing",
    "parsed",
    "partially_parsed",
    "failed",
    "needs_ocr",
    "unsupported_type",
    "indexed",
]
CHUNK_TYPES = ["text", "table", "image_ocr", "metadata"]
EMBEDDING_STATUSES = ["pending", "embedded", "failed", "skipped"]

DocumentType = Literal[
    "contract",
    "invoice_finance",
    "legal",
    "compliance",
    "meeting_notes",
    "technical_documentation",
    "hr",
    "sales_proposal",
    "project_document",
    "support_operations",
    "general_knowledge",
    "unclassified",
]

BusinessDomain = Literal[
    "legal",
    "finance",
    "hr",
    "engineering",
    "operations",
    "sales",
    "procurement",
    "compliance",
    "customer_support",
    "management",
    "unknown",
]

