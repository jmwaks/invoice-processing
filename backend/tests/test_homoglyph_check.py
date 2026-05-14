from app.agents.homoglyph_check import detect_homoglyphs
from app.graph.state import InvoiceData, LineItem


def _inv(**kw: object) -> InvoiceData:
    base: dict[str, object] = dict(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None, line_items=[],
        subtotal=None, tax_amount=None, total=None,
        currency="USD", payment_terms=None, raw_text="",
    )
    base.update(kw)
    return InvoiceData(**base)  # type: ignore[arg-type]


def test_clean_invoice_emits_no_signal() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-02-03\n",
    )
    assert detect_homoglyphs(inv) == []


def test_invoice_number_with_O_for_0_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-9OO1",
        raw_text="INVOICE\nInvoice Number: INV-9OO1\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and "INV-9OO1" in (s.text_match or "")
        for s in signals
    )


def test_header_INV0ICE_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INV0ICE\nInvoice Number: INV-1001\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and (s.text_match or "") == "INV0ICE"
        for s in signals
    )


def test_date_with_O_in_raw_text_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-O2-O3\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and "2026-O2-O3" in (s.text_match or "")
        for s in signals
    )


def test_date_without_homoglyph_is_not_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-02-03\nDue: 2026-03-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert not any(s.kind == "homoglyph_corruption" for s in signals)


def test_legitimate_O_in_vendor_address_not_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        vendor="OAKWOOD HOLDINGS LLC",
        raw_text=(
            "INVOICE\nInvoice Number: INV-1001\n"
            "Vendor: OAKWOOD HOLDINGS LLC\nAddress: 100 OAK ROAD\n"
            "Date: 2026-02-03\n"
        ),
    )
    assert detect_homoglyphs(inv) == []


def test_dedup_by_text_match_does_not_double_emit() -> None:
    inv = _inv(
        invoice_number="INV-1OO1",
        raw_text="INVOICE\nInvoice Number: INV-1OO1\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    text_matches = [s.text_match for s in signals if s.kind == "homoglyph_corruption"]
    assert len(text_matches) == len(set(text_matches))
