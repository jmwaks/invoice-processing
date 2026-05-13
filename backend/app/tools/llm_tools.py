from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_inventory",
            "description": (
                "Look up a single item in the inventory database. "
                "Returns whether it exists, stock on hand, and unit price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Exact or close item name"},
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_vendor",
            "description": "Look up a vendor by name. Returns whether they are on file and their status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Vendor name as it appears on the invoice"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recompute_totals",
            "description": "Recompute subtotal from line_items as sum(quantity * unit_price). Use to verify arithmetic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"},
                            },
                            "required": ["quantity", "unit_price"],
                        },
                    },
                },
                "required": ["line_items"],
            },
        },
    },
]


def dispatch_tool(
    name: str, arguments: dict[str, object], *, db_path: Path | None,
) -> dict[str, object]:
    """Run a tool by name. Raises ValueError on unknown tool."""
    if name == "lookup_inventory":
        result = inventory_lookup(str(arguments["item"]), db_path=db_path)
        return result.model_dump()
    if name == "lookup_vendor":
        result = vendor_lookup(str(arguments["name"]), db_path=db_path)
        return result.model_dump()
    if name == "recompute_totals":
        items = arguments.get("line_items", [])
        subtotal = sum(
            float(it["quantity"]) * float(it["unit_price"])  # type: ignore[index]
            for it in items  # type: ignore[union-attr]
        )
        return {"computed_subtotal": round(subtotal, 2), "line_count": len(items)}  # type: ignore[arg-type]
    raise ValueError(f"unknown tool: {name}")


def time_dispatch(
    name: str, arguments: dict[str, object], *, db_path: Path | None,
) -> tuple[dict[str, object], int]:
    """Run a tool and return (result, elapsed_ms)."""
    t0 = perf_counter()
    out = dispatch_tool(name, arguments, db_path=db_path)
    return out, int((perf_counter() - t0) * 1000)
