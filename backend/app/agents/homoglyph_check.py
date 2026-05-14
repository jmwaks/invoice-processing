from __future__ import annotations

import re

from app.graph.state import InvoiceData, SuspicionSignal

HOMOGLYPH_MAP: dict[str, str] = {
    "O": "0",
    "I": "1",
    "l": "1",
    "B": "8",
    "S": "5",
    "Z": "2",
}

_HEADER_MANGLINGS: tuple[str, ...] = (
    "INV0ICE", "1NVOICE", "INV01CE", "INVO1CE", "1NV0ICE",
)

_DATE_SHAPED_RE = re.compile(r"\b\d{4}-[\dA-Z]{2}-[\dA-Z]{2}\b")


def _has_homoglyph(token: str) -> bool:
    return any(c in HOMOGLYPH_MAP for c in token)


def _invoice_number_id_part(invoice_number: str) -> str:
    if "-" not in invoice_number:
        return invoice_number
    return invoice_number.split("-", 1)[1]


def detect_homoglyphs(inv: InvoiceData) -> list[SuspicionSignal]:
    signals: list[SuspicionSignal] = []
    seen: set[str] = set()

    def _emit(text_match: str, detail: str) -> None:
        if text_match in seen:
            return
        seen.add(text_match)
        signals.append(SuspicionSignal(
            kind="homoglyph_corruption",
            detail=detail,
            severity="medium",
            text_match=text_match,
        ))

    if inv.invoice_number:
        id_part = _invoice_number_id_part(inv.invoice_number)
        if _has_homoglyph(id_part):
            _emit(
                inv.invoice_number,
                f"invoice_number {inv.invoice_number!r} contains characters that "
                f"visually resemble digits (homoglyphs): "
                f"{sorted(set(c for c in id_part if c in HOMOGLYPH_MAP))}",
            )

    raw = inv.raw_text or ""
    for token in _HEADER_MANGLINGS:
        if token in raw:
            _emit(
                token,
                f"document header contains {token!r}, a homoglyph-mangled "
                f"version of 'INVOICE'",
            )

    for match in _DATE_SHAPED_RE.finditer(raw):
        token = match.group(0)
        if _has_homoglyph(token):
            _emit(
                token,
                f"date-shaped token {token!r} contains characters that visually "
                f"resemble digits (homoglyphs)",
            )

    return signals
