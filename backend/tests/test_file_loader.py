from pathlib import Path
from app.parsers.file_loader import load_invoice_file, FileFormat


def test_load_txt_file(tmp_path: Path):
    p = tmp_path / "inv.txt"
    p.write_text("INVOICE\nVendor: X\n")
    result = load_invoice_file(p)
    assert result.format == "txt"
    assert "INVOICE" in result.text


def test_load_email_when_starts_with_from(tmp_path: Path):
    p = tmp_path / "inv.txt"
    p.write_text("From: a@b\nTo: c@d\nSubject: x\n\nbody")
    result = load_invoice_file(p)
    assert result.format == "email"


def test_load_json(tmp_path: Path):
    p = tmp_path / "inv.json"
    p.write_text('{"x": 1}')
    result = load_invoice_file(p)
    assert result.format == "json"
    assert "x" in result.text


def test_load_pdf_real_sample():
    p = Path(__file__).resolve().parents[1] / "data" / "invoices" / "invoice_1011.pdf"
    if not p.exists():
        import pytest; pytest.skip("sample PDF not present")
    result = load_invoice_file(p)
    assert result.format == "pdf"
    assert "INVOICE" in result.text.upper() or "Summit" in result.text


def test_unsupported_extension_raises(tmp_path: Path):
    import pytest
    p = tmp_path / "x.docx"
    p.write_bytes(b"x")
    with pytest.raises(ValueError):
        load_invoice_file(p)


def test_empty_pdf_raises_empty_extraction(tmp_path: Path, monkeypatch):
    import pytest
    from app.parsers import file_loader
    from app.parsers.file_loader import EmptyExtractionError

    monkeypatch.setattr(file_loader, "_load_pdf", lambda _p: "")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-fake")
    with pytest.raises(EmptyExtractionError):
        load_invoice_file(pdf)
