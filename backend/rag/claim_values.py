"""Structured values used by grounded-claim verification."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MONEY_RE = re.compile(
    r"(?:€|\$|£|\b(?:eur|euro|usd|gbp)\b)\s*\d[\d.,]*"
    r"|\d[\d.,]*\s*(?:€|\$|£|\b(?:eur|euro|usd|gbp)\b)",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def money_supported(value: str, evidence: str) -> bool:
    expected = _money_value(value)
    if expected is None:
        return False
    currency, amount = expected
    for found in MONEY_RE.findall(evidence):
        actual = _money_value(found)
        if actual is not None and actual == (currency, amount):
            return True
    # Tables often put currency in the header and the value in a later row.
    return _currency_present(currency, evidence) and _number_present(amount, evidence)


def _money_value(value: str) -> tuple[str, Decimal] | None:
    lowered = value.lower()
    currency = (
        "eur"
        if "€" in value or "eur" in lowered or "euro" in lowered
        else "usd"
        if "$" in value or "usd" in lowered
        else "gbp"
        if "£" in value or "gbp" in lowered
        else ""
    )
    raw = re.sub(r"[^0-9.,]", "", value)
    if not currency or not raw:
        return None
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in raw or "." in raw:
        separator = "," if "," in raw else "."
        tail = raw.rsplit(separator, 1)[1]
        raw = raw.replace(separator, "." if len(tail) == 2 else "")
    try:
        return currency, Decimal(raw)
    except InvalidOperation:
        return None


def _currency_present(currency: str, evidence: str) -> bool:
    lowered = evidence.lower()
    aliases = {"eur": ("eur", "euro", "€"), "usd": ("usd", "$"), "gbp": ("gbp", "£")}
    return any(alias in lowered for alias in aliases[currency])


def _number_present(amount: Decimal, evidence: str) -> bool:
    for raw in re.findall(r"\d[\d.,]*", evidence):
        parsed = _money_value(f"EUR {raw}")
        if parsed is not None and parsed[1] == amount:
            return True
    return False
