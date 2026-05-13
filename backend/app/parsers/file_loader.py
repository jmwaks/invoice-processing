from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FileFormat = Literal["txt", "json", "csv", "xml", "pdf", "email"]


@dataclass
class LoadedFile:
    text: str
    format: FileFormat
    source_path: Path


def _looks_like_email(text: str) -> bool:
    head = text[:200].lower()
    return head.lstrip().startswith("from:") and "subject:" in head


def _load_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages]
            text = "\n".join(pages).strip()
            if text:
                return text
    except Exception:  # noqa: BLE001 — fallback path
        pass
    import fitz  # PyMuPDF
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc).strip()


class EmptyExtractionError(ValueError):
    """Raised when a PDF (or other file) yields no extractable text — likely a scan."""


def load_invoice_file(path: Path) -> LoadedFile:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        text = _load_pdf(path)
        if not text.strip():
            raise EmptyExtractionError(
                f"PDF {path.name} has no extractable text (likely scanned). "
                "OCR is not configured in this prototype."
            )
        return LoadedFile(text=text, format="pdf", source_path=path)
    if suffix in {"txt", "json", "csv", "xml"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        fmt: FileFormat = "email" if suffix == "txt" and _looks_like_email(text) else suffix  # type: ignore[assignment]
        return LoadedFile(text=text, format=fmt, source_path=path)
    raise ValueError(f"Unsupported file extension: {path.suffix}")
