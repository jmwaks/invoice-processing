from __future__ import annotations

import pytest

from app.tools.llm_tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_have_required_openai_shape():
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn and "description" in fn and "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_dispatch_lookup_inventory_known(seeded_db_path):
    out = dispatch_tool(
        "lookup_inventory", {"item": "WidgetA"}, db_path=seeded_db_path,
    )
    assert out["found"] is True
    assert out["item"] == "WidgetA"
    assert out["stock"] == 15


def test_dispatch_lookup_inventory_unknown(seeded_db_path):
    out = dispatch_tool(
        "lookup_inventory", {"item": "ImaginaryThing"}, db_path=seeded_db_path,
    )
    assert out["found"] is False


def test_dispatch_lookup_vendor_known(seeded_db_path):
    out = dispatch_tool(
        "lookup_vendor", {"name": "Widgets Inc."}, db_path=seeded_db_path,
    )
    assert out["found"] is True


def test_dispatch_recompute_totals():
    out = dispatch_tool(
        "recompute_totals",
        {"line_items": [{"quantity": 2, "unit_price": 100.0}, {"quantity": 1, "unit_price": 50.0}]},
        db_path=None,
    )
    assert out["computed_subtotal"] == 250.0


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError):
        dispatch_tool("nope", {}, db_path=None)
