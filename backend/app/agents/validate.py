from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from app.db.paid_invoices import lookup_paid
from app.graph.state import (
    InventoryLookupResult,
    InvoiceData,
    InvoiceState,
    ValidationIssue,
    ValidationReport,
    VendorLookupResult,
)
from app.logging_.event_emitter import EventEmitter
from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup

PRICE_TOLERANCE = 0.10  # 10%
TOTAL_TOLERANCE = 1.00  # $1
EXPECTED_CURRENCY = "USD"  # payment pipeline assumes USD; flag others for review


def _check_required_fields(inv: InvoiceData) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not inv.vendor or not inv.vendor.strip():
        issues.append(
            ValidationIssue(
                kind="missing_vendor", detail="vendor field empty/null", severity="block"
            )
        )
    if inv.total is None:
        issues.append(
            ValidationIssue(kind="missing_total", detail="total field missing", severity="block")
        )
    if not inv.line_items:
        issues.append(
            ValidationIssue(kind="no_line_items", detail="no line items", severity="block")
        )
    return issues


def _check_negative_quantities(inv: InvoiceData) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            kind="negative_qty", item=li.item,
            detail=f"quantity={li.quantity}", severity="block",
        )
        for li in inv.line_items
        if li.quantity <= 0
    ]


def _check_dates(inv: InvoiceData) -> list[ValidationIssue]:
    if inv.date and inv.due_date and inv.due_date < inv.date:
        return [ValidationIssue(
            kind="past_due_date",
            detail=f"due_date {inv.due_date} before date {inv.date}", severity="warn",
        )]
    return []


def _check_future_date(inv: InvoiceData, today: dt.date) -> list[ValidationIssue]:
    if inv.date is None or inv.date <= today:
        return []
    days = (inv.date - today).days
    return [ValidationIssue(
        kind="future_date",
        detail=f"invoice date {inv.date} is {days} day(s) in the future (today is {today})",
        severity="warn",
    )]


def _check_currency(inv: InvoiceData) -> list[ValidationIssue]:
    if not inv.currency or inv.currency.upper() == EXPECTED_CURRENCY:
        return []
    return [ValidationIssue(
        kind="currency_mismatch",
        detail=f"invoice currency {inv.currency} != expected {EXPECTED_CURRENCY} "
               f"(payment pipeline has no FX support)",
        severity="warn",
    )]


def _check_duplicate_invoice(
    inv: InvoiceData, db_path: Path, *, state_run_id: str, emitter: EventEmitter,
) -> list[ValidationIssue]:
    if not inv.invoice_number:
        return []  # no meaningful skip — invoice has bigger problems
    if not inv.vendor or not inv.vendor.strip():
        emitter.emit(
            "duplicate_check_skipped", node="validate",
            output={"reason": "missing_vendor"},
        )
        return []
    prior = lookup_paid(
        vendor=inv.vendor, invoice_number=inv.invoice_number, db_path=db_path,
    )
    if prior is None:
        return []

    issue = ValidationIssue(
        kind="duplicate_invoice",
        detail=(
            f"already paid in run {prior.run_id} for ${prior.amount:.2f} "
            f"on {prior.paid_at:%Y-%m-%d}; this submission is "
            f"${(inv.total or 0.0):.2f}"
        ),
        severity="warn",
    )

    log_dir = emitter.log_dir
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    prior_log = log_dir / f"{prior.run_id}.jsonl"

    if prior_log.exists():
        retroactive_event = {
            "kind": "duplicate_detected_retroactive",
            "ts": now_iso,
            "later_run_id": state_run_id,
            "later_amount": inv.total or 0.0,
            "later_invoice_number": inv.invoice_number,
        }
        sidecar = log_dir / "decision_updates.jsonl"
        sidecar_row = {
            "run_id": prior.run_id,
            "invoice_number": prior.invoice_number,
            "previous_outcome": "approved",
            "new_outcome": "needs_review",
            "reason": "duplicate_detected",
            "updated_at": now_iso,
            "triggered_by_run_id": state_run_id,
        }
        try:
            with prior_log.open("a") as f:
                f.write(json.dumps(retroactive_event, default=str) + "\n")
            with sidecar.open("a") as f:
                f.write(json.dumps(sidecar_row, default=str) + "\n")
        except OSError as e:
            emitter.emit(
                "duplicate_detected_retroactive_skipped", node="validate",
                output={"prior_run_id": prior.run_id, "reason": f"io_error:{e}"},
            )
    else:
        emitter.emit(
            "duplicate_detected_retroactive_skipped", node="validate",
            output={
                "prior_run_id": prior.run_id,
                "reason": "prior_log_not_found",
            },
        )

    return [issue]


def _check_total_math(inv: InvoiceData) -> list[ValidationIssue]:
    if inv.total is None or not inv.line_items:
        return []
    issues: list[ValidationIssue] = []
    computed = sum((li.quantity or 0) * (li.unit_price or 0.0) for li in inv.line_items)
    stated = inv.subtotal if inv.subtotal is not None else inv.total
    if computed > 0 and stated is not None and abs(computed - stated) > TOTAL_TOLERANCE:
        issues.append(ValidationIssue(
            kind="total_math_error",
            detail=f"computed {computed:.2f} vs stated {stated:.2f}",
            severity="warn",
        ))
    if inv.subtotal is not None:
        expected_total = inv.subtotal + (inv.tax_amount or 0.0)
        if abs(expected_total - inv.total) > TOTAL_TOLERANCE:
            issues.append(ValidationIssue(
                kind="total_math_error",
                detail=(
                    f"subtotal {inv.subtotal:.2f} + tax {(inv.tax_amount or 0.0):.2f} "
                    f"= {expected_total:.2f} vs stated total {inv.total:.2f}"
                ),
                severity="warn",
            ))
    return issues


def _check_line_items_against_inventory(
    inv: InvoiceData, db_path: Path, emitter: EventEmitter,
) -> tuple[list[ValidationIssue], list[InventoryLookupResult]]:
    issues: list[ValidationIssue] = []
    lookups: list[InventoryLookupResult] = []

    # Aggregate positive quantities per item so split-line attacks
    # (same item across many qty=1 lines) cannot bypass stock checks.
    qty_by_item: dict[str, int] = {}
    for li in inv.line_items:
        if li.quantity > 0:
            qty_by_item[li.item] = qty_by_item.get(li.item, 0) + li.quantity

    item_lookups: dict[str, InventoryLookupResult] = {}

    for li in inv.line_items:
        if li.quantity <= 0:
            continue

        if li.item not in item_lookups:
            lookup = inventory_lookup(li.item, db_path=db_path)
            item_lookups[li.item] = lookup
            lookups.append(lookup)
            emitter.emit("tool.call", node="validate", tool="inventory_lookup",
                         args={"item": li.item}, result=lookup.model_dump())
            if not lookup.found:
                issues.append(ValidationIssue(
                    kind="unknown_item", item=li.item,
                    detail="not in inventory", severity="block",
                ))
            elif lookup.stock == 0:
                issues.append(ValidationIssue(
                    kind="out_of_stock", item=li.item,
                    detail="stock is 0", severity="block",
                ))
            elif lookup.stock is not None and qty_by_item[li.item] > lookup.stock:
                issues.append(ValidationIssue(
                    kind="qty_exceeds_stock", item=li.item,
                    detail=f"requested {qty_by_item[li.item]} > stock {lookup.stock}",
                    severity="block",
                ))

        lookup = item_lookups[li.item]
        if not lookup.found or lookup.stock == 0:
            continue
        if li.unit_price is not None and lookup.unit_price and lookup.unit_price > 0:
            drift = abs(li.unit_price - lookup.unit_price) / lookup.unit_price
            if drift >= PRICE_TOLERANCE:
                issues.append(ValidationIssue(
                    kind="price_mismatch", item=li.item,
                    detail=f"invoice ${li.unit_price:.2f} vs catalog ${lookup.unit_price:.2f}",
                    severity="warn",
                ))
    return issues, lookups


def _check_vendor(
    inv: InvoiceData, db_path: Path, emitter: EventEmitter,
) -> tuple[list[ValidationIssue], VendorLookupResult | None]:
    if not inv.vendor or not inv.vendor.strip():
        return [], None
    result = vendor_lookup(inv.vendor, db_path=db_path)
    emitter.emit("tool.call", node="validate", tool="vendor_lookup",
                 args={"name": inv.vendor}, result=result.model_dump())
    if not result.found:
        return [ValidationIssue(
            kind="unknown_vendor", item=None,
            detail=f"vendor '{inv.vendor}' not in approved list", severity="warn",
        )], result
    return [], result


def run_validate(state: InvoiceState, *, db_path: Path, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="validate")
    inv = state.invoice
    if inv is None:
        state.validation = ValidationReport(issues=[], inventory_lookups=[], vendor_lookup=None)
        emitter.emit("node.complete", node="validate", output={"skipped": True})
        return state

    issues: list[ValidationIssue] = []
    issues.extend(_check_required_fields(inv))
    issues.extend(_check_negative_quantities(inv))
    issues.extend(_check_dates(inv))
    issues.extend(_check_total_math(inv))
    issues.extend(_check_currency(inv))
    issues.extend(_check_duplicate_invoice(
        inv, db_path, state_run_id=state.run_id, emitter=emitter,
    ))
    inv_issues, lookups = _check_line_items_against_inventory(inv, db_path, emitter)
    issues.extend(inv_issues)
    vendor_issues, vendor_result = _check_vendor(inv, db_path, emitter)
    issues.extend(vendor_issues)

    state.validation = ValidationReport(
        issues=issues, inventory_lookups=lookups, vendor_lookup=vendor_result,
    )
    emitter.emit("node.complete", node="validate", output={
        "issue_count": len(issues),
        "blocks": [i.kind for i in issues if i.severity == "block"],
        "warns":  [i.kind for i in issues if i.severity == "warn"],
    })
    return state
