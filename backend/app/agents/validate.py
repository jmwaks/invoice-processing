from __future__ import annotations

from pathlib import Path

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
    for li in inv.line_items:
        if li.quantity <= 0:
            continue
        lookup = inventory_lookup(li.item, db_path=db_path)
        lookups.append(lookup)
        emitter.emit("tool.call", node="validate", tool="inventory_lookup",
                     args={"item": li.item}, result=lookup.model_dump())
        if not lookup.found:
            issues.append(ValidationIssue(
                kind="unknown_item", item=li.item,
                detail="not in inventory", severity="block",
            ))
            continue
        if lookup.stock == 0:
            issues.append(ValidationIssue(
                kind="out_of_stock", item=li.item,
                detail="stock is 0", severity="block",
            ))
            continue
        if lookup.stock is not None and li.quantity > lookup.stock:
            issues.append(ValidationIssue(
                kind="qty_exceeds_stock", item=li.item,
                detail=f"requested {li.quantity} > stock {lookup.stock}", severity="block",
            ))
        if li.unit_price is not None and lookup.unit_price and lookup.unit_price > 0:
            drift = abs(li.unit_price - lookup.unit_price) / lookup.unit_price
            if drift > PRICE_TOLERANCE:
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
