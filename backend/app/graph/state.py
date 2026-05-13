from __future__ import annotations
from datetime import date
from typing import Literal
from pydantic import BaseModel


class LineItem(BaseModel):
    item: str
    quantity: int
    unit_price: float | None = None
    notes: str | None = None


class InvoiceData(BaseModel):
    invoice_number: str | None
    vendor: str | None
    date: date | None
    due_date: date | None
    line_items: list[LineItem]
    subtotal: float | None
    tax_amount: float | None
    total: float | None
    currency: str = "USD"
    payment_terms: str | None = None
    raw_text: str


class SuspicionSignal(BaseModel):
    kind: Literal[
        "urgent_language",
        "impossible_date",
        "round_number",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "other",
    ]
    detail: str
    severity: Literal["low", "medium", "high"]


class ValidationIssue(BaseModel):
    kind: Literal[
        "unknown_item",
        "out_of_stock",
        "qty_exceeds_stock",
        "price_mismatch",
        "unknown_vendor",
        "negative_qty",
        "missing_vendor",
        "missing_total",
        "no_line_items",
        "total_math_error",
        "past_due_date",
    ]
    item: str | None = None
    detail: str
    severity: Literal["info", "warn", "block"]


class InventoryLookupResult(BaseModel):
    found: bool
    item: str
    stock: int | None = None
    unit_price: float | None = None


class VendorLookupResult(BaseModel):
    found: bool
    name: str
    status: Literal["approved", "pending", "blocked"] | None = None


class ValidationReport(BaseModel):
    issues: list[ValidationIssue]
    inventory_lookups: list[InventoryLookupResult]
    vendor_lookup: VendorLookupResult | None


class Proposal(BaseModel):
    outcome: Literal["approved", "rejected", "needs_review"]
    rationale: str
    rules_applied: list[str]
    unresolved_concerns: list[str]


class Critique(BaseModel):
    agrees: bool
    objections: list[str]
    missed_signals: list[str]
    rule_misapplications: list[str]


class Decision(BaseModel):
    # Canonical fields used by downstream nodes and the UI summary.
    # They mirror final_proposal — kept top-level so callers do not have to traverse the audit trail.
    outcome: Literal["approved", "rejected", "needs_review"]
    rationale: str
    rules_applied: list[str]
    # Audit trail of the three approval passes.
    initial_proposal: Proposal
    critique: Critique
    final_proposal: Proposal


class InvoiceState(BaseModel):
    run_id: str
    source_path: str
    file_format: Literal["txt", "json", "csv", "xml", "pdf", "email"]
    invoice: InvoiceData | None = None
    suspicion_signals: list[SuspicionSignal] = []
    extraction_confidence: float | None = None
    validation: ValidationReport | None = None
    decision: Decision | None = None
    payment_receipt: dict | None = None
    error: str | None = None
    events: list[dict] = []
