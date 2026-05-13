from __future__ import annotations
from pathlib import Path
from app.graph.state import InvoiceState, ValidationIssue, ValidationReport
from app.logging_.event_emitter import EventEmitter
from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup

PRICE_TOLERANCE = 0.10  # 10%
TOTAL_TOLERANCE = 1.00  # $1


def run_validate(state: InvoiceState, *, db_path: Path, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="validate")
    issues: list[ValidationIssue] = []
    lookups: list[dict] = []
    vendor_result: dict | None = None
    inv = state.invoice
    if inv is None:
        state.validation = ValidationReport(issues=[], inventory_lookups=[], vendor_lookup=None)
        emitter.emit("node.complete", node="validate", output={"skipped": True})
        return state

    # 1. required fields
    if not inv.vendor or not inv.vendor.strip():
        issues.append(ValidationIssue(kind="missing_vendor", detail="vendor field empty/null", severity="block"))
    if inv.total is None:
        issues.append(ValidationIssue(kind="missing_total", detail="total field missing", severity="block"))
    if not inv.line_items:
        issues.append(ValidationIssue(kind="no_line_items", detail="no line items", severity="block"))

    # 2. negative qty
    for li in inv.line_items:
        if li.quantity <= 0:
            issues.append(ValidationIssue(
                kind="negative_qty", item=li.item,
                detail=f"quantity={li.quantity}", severity="block",
            ))

    # 3. past due
    if inv.date and inv.due_date and inv.due_date < inv.date:
        issues.append(ValidationIssue(
            kind="past_due_date",
            detail=f"due_date {inv.due_date} before date {inv.date}", severity="warn",
        ))

    # 4. total math
    if inv.total is not None and inv.line_items:
        computed = sum((li.quantity or 0) * (li.unit_price or 0.0) for li in inv.line_items)
        if computed > 0 and abs(computed - (inv.subtotal or inv.total or 0.0)) > TOTAL_TOLERANCE:
            issues.append(ValidationIssue(
                kind="total_math_error",
                detail=f"computed {computed:.2f} vs stated {(inv.subtotal or inv.total):.2f}",
                severity="warn",
            ))

    # 5. inventory lookups
    for li in inv.line_items:
        if li.quantity <= 0:
            continue
        lookup = inventory_lookup(li.item, db_path=db_path)
        lookups.append(lookup)
        emitter.emit("tool.call", node="validate", tool="inventory_lookup",
                     args={"item": li.item}, result=lookup)
        if not lookup["found"]:
            issues.append(ValidationIssue(
                kind="unknown_item", item=li.item,
                detail="not in inventory", severity="block",
            ))
            continue
        if lookup["stock"] == 0:
            issues.append(ValidationIssue(
                kind="out_of_stock", item=li.item,
                detail="stock is 0", severity="block",
            ))
            continue
        if li.quantity > lookup["stock"]:
            issues.append(ValidationIssue(
                kind="qty_exceeds_stock", item=li.item,
                detail=f"requested {li.quantity} > stock {lookup['stock']}", severity="block",
            ))
        if li.unit_price is not None and lookup["unit_price"] > 0:
            drift = abs(li.unit_price - lookup["unit_price"]) / lookup["unit_price"]
            if drift > PRICE_TOLERANCE:
                issues.append(ValidationIssue(
                    kind="price_mismatch", item=li.item,
                    detail=f"invoice ${li.unit_price:.2f} vs catalog ${lookup['unit_price']:.2f}",
                    severity="warn",
                ))

    # 6. vendor lookup
    if inv.vendor and inv.vendor.strip():
        vendor_result = vendor_lookup(inv.vendor, db_path=db_path)
        emitter.emit("tool.call", node="validate", tool="vendor_lookup",
                     args={"name": inv.vendor}, result=vendor_result)
        if not vendor_result["found"]:
            issues.append(ValidationIssue(
                kind="unknown_vendor", item=None,
                detail=f"vendor '{inv.vendor}' not in approved list", severity="warn",
            ))

    state.validation = ValidationReport(
        issues=issues, inventory_lookups=lookups, vendor_lookup=vendor_result,
    )
    emitter.emit("node.complete", node="validate", output={
        "issue_count": len(issues),
        "blocks": [i.kind for i in issues if i.severity == "block"],
        "warns":  [i.kind for i in issues if i.severity == "warn"],
    })
    return state
