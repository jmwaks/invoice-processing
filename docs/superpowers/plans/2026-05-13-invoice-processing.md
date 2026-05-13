# Invoice Processing Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end multi-agent invoice processing prototype: CLI + FastAPI + React UI, driven by a LangGraph state machine that ingests, validates, approves (with a propose-critique-finalize loop), and pays / logs invoices.

**Architecture:** Python 3.11 backend with LangGraph orchestrating four agent nodes. xAI Grok via OpenAI-compatible API does LLM extraction and approval reasoning. Deterministic SQLite validation. FastAPI exposes the graph as SSE-streamed runs. React + Tailwind + Zustand frontend renders four live panels (timeline, batch queue, DB inspector, critique view).

**Tech Stack:** Python 3.11+, LangGraph, FastAPI, Pydantic v2, pdfplumber/PyMuPDF, SQLite, OpenAI SDK (pointed at api.x.ai); Vite + React 18 + TypeScript + Tailwind + Zustand + React Query.

**Source spec:** `docs/superpowers/specs/2026-05-13-invoice-processing-design.md` — refer to it whenever a Pydantic schema, prompt, or rule is described in shorthand below.

---

## File structure

```
invoice-processing/
  backend/
    pyproject.toml
    .env.example
    Makefile
    app/
      __init__.py
      main.py                    # CLI entry: python -m app.main --invoice_path=...
      config.py                  # env loading, model name, paths
      graph/
        __init__.py
        state.py                 # InvoiceState + all Pydantic models from spec §5
        builder.py               # LangGraph construction
      agents/
        __init__.py
        ingest.py
        validate.py
        approve.py
        pay.py
        log_node.py
      llm/
        __init__.py
        grok_client.py           # OpenAI-compatible client + retry wrapper
        structured_output.py     # Pydantic structured-output helper
      tools/
        __init__.py
        inventory_tool.py
        vendor_tool.py
        payment_tool.py
      rules/
        __init__.py
        engine.py
        rules.yaml
      parsers/
        __init__.py
        file_loader.py           # PDF/text loading + format detect
      logging_/
        __init__.py
        event_emitter.py         # NOTE: directory name `logging_` to avoid stdlib clash
      api/
        __init__.py
        app.py                   # FastAPI factory
        routes.py
        sse.py
        runs.py                  # in-memory run registry
      db/
        __init__.py
        init_db.py
        seed.yaml
    data/
      invoices/                  # copied from galatiq-case-invoices/data/invoices
      inventory.db               # generated; gitignored
      adversarial/               # authored INV-9001..9005
    logs/                        # per-run jsonl traces; gitignored
    tests/
      __init__.py
      conftest.py
      expected_outcomes.yaml
      fixtures/grok/             # recorded Grok responses; gitignored except for committed canonical set
      test_file_loader.py
      test_validate.py
      test_rules_engine.py
      test_vendor_normalization.py
      test_event_emitter.py
      test_pay_tool.py
      test_integration.py
      test_live_smoke.py
    scripts/
      record_fixtures.py
  frontend/
    package.json
    vite.config.ts
    tsconfig.json
    tailwind.config.js
    index.html
    src/
      main.tsx
      App.tsx
      api/
        client.ts
        sse.ts
      store/
        runStore.ts
      types/
        events.ts                # SSE event union type from spec §10
        state.ts                 # InvoiceState mirror
      components/
        UploadZone.tsx
        BatchQueue.tsx
        Timeline.tsx
        SourceAndExtraction.tsx
        CritiquePanel.tsx
        DBInspector.tsx
        StatusBadge.tsx          # shared
      pages/
        Dashboard.tsx
  docs/
  README.md
```

**Note:** the events directory is named `logging_` (with trailing underscore) to avoid colliding with Python's stdlib `logging` module when imported as `from app.logging_ import event_emitter`.

---

## Phase 0 — Project bootstrap

### Task 0.1: Set up Python backend skeleton

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/Makefile`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/config.py`
- Create: `.gitignore` (extend root file)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "invoice-processing-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "langgraph>=0.2.0",
  "langchain-core>=0.3.0",
  "openai>=1.40.0",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.0.0",
  "pdfplumber>=0.11.0",
  "pymupdf>=1.24.0",
  "fastapi>=0.110.0",
  "uvicorn[standard]>=0.30.0",
  "python-multipart>=0.0.9",
  "sse-starlette>=2.1.0",
  "pyyaml>=6.0",
  "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0.0",
  "pytest-asyncio>=0.23.0",
  "ruff>=0.5.0",
  "mypy>=1.10.0",
  "httpx>=0.27.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.mypy]
strict = true
files = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`**

```
XAI_API_KEY=
XAI_MODEL=grok-4
XAI_BASE_URL=https://api.x.ai/v1
INVOICE_PROCESSING_LOG_DIR=./logs
INVOICE_PROCESSING_INVOICES_DIR=./data/invoices
INVOICE_PROCESSING_DB_PATH=./data/inventory.db
RUN_LIVE_TESTS=0
```

- [ ] **Step 3: Write `app/config.py`**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    xai_api_key: str = ""
    xai_model: str = "grok-4"
    xai_base_url: str = "https://api.x.ai/v1"

    invoice_processing_log_dir: Path = Path("./logs")
    invoice_processing_invoices_dir: Path = Path("./data/invoices")
    invoice_processing_db_path: Path = Path("./data/inventory.db")

    run_live_tests: bool = False


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write `Makefile`**

```makefile
.PHONY: install dev test seed record-fixtures demo lint typecheck

install:
	cd backend && pip install -e ".[dev]"

seed:
	cd backend && python -m app.db.init_db --reset

dev:
	cd backend && uvicorn app.api.app:app --reload --port 8000

test:
	cd backend && pytest -v

record-fixtures:
	cd backend && python scripts/record_fixtures.py

demo:
	cd backend && python -m app.main --batch

lint:
	cd backend && ruff check app tests

typecheck:
	cd backend && mypy app
```

- [ ] **Step 5: Extend root `.gitignore`**

Append to existing `.gitignore`:
```
# project-specific
backend/data/inventory.db
backend/logs/
backend/data/*.db-journal
frontend/node_modules
frontend/dist
.env
```

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/Makefile backend/app/__init__.py backend/app/config.py .gitignore
git commit -m "chore: bootstrap python backend skeleton"
```

---

### Task 0.2: Copy sample invoices into the repo

**Files:**
- Create: `backend/data/invoices/` populated from `/Users/mwakichako/repos/galatiq-case-invoices/data/invoices/`

- [ ] **Step 1: Copy invoice files**

```bash
mkdir -p backend/data/invoices
cp /Users/mwakichako/repos/galatiq-case-invoices/data/invoices/*.txt backend/data/invoices/
cp /Users/mwakichako/repos/galatiq-case-invoices/data/invoices/*.json backend/data/invoices/
cp /Users/mwakichako/repos/galatiq-case-invoices/data/invoices/*.csv backend/data/invoices/
cp /Users/mwakichako/repos/galatiq-case-invoices/data/invoices/*.xml backend/data/invoices/
cp /Users/mwakichako/repos/galatiq-case-invoices/data/invoices/*.pdf backend/data/invoices/
```

- [ ] **Step 2: Verify**

Run: `ls backend/data/invoices/ | wc -l`
Expected: `20` (16 invoice files + counts include _revised + .txt versions for PDFs — confirm via `ls`).

- [ ] **Step 3: Commit**

```bash
git add backend/data/invoices/
git commit -m "data: copy sample invoices from case repo"
```

---

### Task 0.3: Verify dependencies install

- [ ] **Step 1: Create venv and install**

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 2: Confirm imports work**

```bash
python -c "import langgraph, openai, pydantic, fastapi, pdfplumber, fitz, yaml; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Verify the configured xAI model is reachable and supports `json_object` response format**

The exact xAI model name and JSON-mode support are the load-bearing risks before fixture recording. Confirm now rather than discovering after wiring all four nodes.

```bash
XAI_API_KEY=... XAI_MODEL=grok-4 python -c "
import os
from openai import OpenAI
c = OpenAI(api_key=os.environ['XAI_API_KEY'], base_url='https://api.x.ai/v1')
resp = c.chat.completions.create(
    model=os.environ['XAI_MODEL'],
    messages=[{'role':'user','content':'Return JSON {\"ok\": true}'}],
    response_format={'type': 'json_object'},
)
print('model_ok:', resp.model)
print('content:', resp.choices[0].message.content)
"
```
Expected: `model_ok: <model name>` and a JSON object in `content`. If 4xx with "model not found", try `grok-3`, `grok-3-mini`, or `grok-beta` and update `.env`/`config.py` default accordingly. If 4xx on `response_format`, JSON mode isn't supported on that model — pick a different model that does, since structured extraction depends on it.

- [ ] **Step 4: No commit needed** (setup verification, not code)

---

## Phase 1 — Domain models, DB, rules engine

### Task 1.1: Pydantic state models (`graph/state.py`)

**Files:**
- Create: `backend/app/graph/__init__.py` (empty)
- Create: `backend/app/graph/state.py`
- Create: `backend/tests/test_state_models.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_state_models.py`:
```python
from datetime import date
from app.graph.state import (
    InvoiceData, LineItem, SuspicionSignal, ValidationIssue,
    ValidationReport, Proposal, Critique, Decision, InvoiceState,
)


def test_invoice_data_accepts_nullable_fields():
    inv = InvoiceData(
        invoice_number=None, vendor=None, date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=None,
        raw_text="",
    )
    assert inv.currency == "USD"


def test_line_item_requires_quantity():
    item = LineItem(item="WidgetA", quantity=3)
    assert item.unit_price is None
    assert item.quantity == 3


def test_validation_issue_kinds_constrained():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ValidationIssue(kind="not_a_real_kind", detail="x", severity="warn")


def test_decision_round_trips_to_json():
    p = Proposal(outcome="approved", rationale="ok", rules_applied=["r1"], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    d = Decision(
        outcome="approved", rationale="ok", rules_applied=["r1"],
        initial_proposal=p, critique=c, final_proposal=p,
    )
    payload = d.model_dump_json()
    Decision.model_validate_json(payload)


def test_invoice_state_serialises():
    s = InvoiceState(run_id="r1", source_path="x", file_format="txt")
    assert s.invoice is None
    assert s.events == []
```

- [ ] **Step 2: Run — expect ImportError**

Run: `cd backend && pytest tests/test_state_models.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.graph.state'`)

- [ ] **Step 3: Implement `graph/state.py`**

```python
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
    payment_terms: str | None
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


class ValidationReport(BaseModel):
    issues: list[ValidationIssue]
    inventory_lookups: list[dict]
    vendor_lookup: dict | None


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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd backend && pytest tests/test_state_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/__init__.py backend/app/graph/state.py backend/tests/test_state_models.py
git commit -m "feat: pydantic state and contract models"
```

---

### Task 1.2: DB init + seed (`db/init_db.py`)

**Files:**
- Create: `backend/app/db/__init__.py` (empty)
- Create: `backend/app/db/seed.yaml`
- Create: `backend/app/db/init_db.py`
- Create: `backend/tests/test_db_init.py`

- [ ] **Step 1: Write `seed.yaml`**

```yaml
inventory:
  - { item: WidgetA, stock: 15, unit_price: 250.00 }
  - { item: WidgetB, stock: 10, unit_price: 500.00 }
  - { item: GadgetX, stock: 5,  unit_price: 750.00 }
  - { item: FakeItem, stock: 0,  unit_price: 0.00 }

vendors:
  - "Widgets Inc."
  - "Gadgets Co."
  - "Precision Parts Ltd."
  - "Global Supply Chain Partners"
  - "Acme Industrial Supplies"
  - "MegaWidgets Corp"
  - "Consolidated Materials Group"
  - "Summit Manufacturing Co."
  - "QuickShip Distributers"
  - "Atlas Industrial Supply"
  - "TechParts International"
  - "Reliable Components Inc."
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_db_init.py`:
```python
import sqlite3
from pathlib import Path
from app.db.init_db import init_db, normalize_vendor


def test_init_db_creates_tables_and_seeds(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT item, stock, unit_price FROM inventory ORDER BY item").fetchall()
    assert ("FakeItem", 0, 0.0) in rows
    assert ("WidgetA", 15, 250.0) in rows
    v = conn.execute("SELECT name, status FROM vendors WHERE display_name='Widgets Inc.'").fetchone()
    assert v == ("widgets", "approved")  # normalized form


def test_init_db_is_idempotent(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=False)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    assert n == 4


def test_normalize_vendor():
    assert normalize_vendor("Widgets Inc.") == "widgets"
    assert normalize_vendor("Acme Industrial Supplies") == "acme industrial supplies"
    assert normalize_vendor("Summit Manufacturing Co.") == "summit manufacturing"
    assert normalize_vendor("Fraudster LLC") == "fraudster"
```

- [ ] **Step 3: Run — expect failure**

Run: `cd backend && pytest tests/test_db_init.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: Implement `app/db/init_db.py`**

```python
from __future__ import annotations
import argparse
import re
import sqlite3
from pathlib import Path
import yaml

INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    item       TEXT PRIMARY KEY,
    stock      INTEGER NOT NULL,
    unit_price REAL    NOT NULL
);
"""

VENDORS_DDL = """
CREATE TABLE IF NOT EXISTS vendors (
    name         TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('approved','pending','blocked'))
);
"""

_SUFFIX_RE = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company)\b\.?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_vendor(name: str) -> str:
    s = name.lower()
    s = _PUNCT_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    return " ".join(s.split())


def init_db(db_path: Path, seed_path: Path, reset: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(INVENTORY_DDL + VENDORS_DDL)
        with seed_path.open() as f:
            seed = yaml.safe_load(f)
        for row in seed["inventory"]:
            conn.execute(
                "INSERT OR REPLACE INTO inventory(item, stock, unit_price) VALUES (?,?,?)",
                (row["item"], row["stock"], row["unit_price"]),
            )
        for display in seed["vendors"]:
            conn.execute(
                "INSERT OR REPLACE INTO vendors(name, display_name, status) VALUES (?,?,?)",
                (normalize_vendor(display), display, "approved"),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--db", type=Path, default=Path("data/inventory.db"))
    ap.add_argument("--seed", type=Path, default=Path("app/db/seed.yaml"))
    args = ap.parse_args()
    init_db(args.db, args.seed, reset=args.reset)
    print(f"DB initialized at {args.db}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_db_init.py -v`
Expected: 3 passed

- [ ] **Step 6: Seed the real DB**

```bash
cd backend && python -m app.db.init_db --reset
```
Expected: `DB initialized at data/inventory.db`

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/ backend/tests/test_db_init.py
git commit -m "feat: sqlite schema and seed data"
```

---

### Task 1.3: Rules engine (`rules/engine.py`)

**Files:**
- Create: `backend/app/rules/__init__.py` (empty)
- Create: `backend/app/rules/rules.yaml` (from spec §8)
- Create: `backend/app/rules/engine.py`
- Create: `backend/tests/test_rules_engine.py`

- [ ] **Step 1: Write `rules.yaml`**

```yaml
hard_blocks:
  - missing_vendor
  - missing_total
  - no_line_items
  - negative_qty
  - unknown_item
  - out_of_stock
  - qty_exceeds_stock

auto_approve_when:
  - total_usd_lte: 10000
  - validation_clean: true
  - max_suspicion_severity: low
  - extraction_confidence_gte: 0.8

scrutiny_required_when:
  - total_usd_gt: 10000
  - any_warn_issue: true
  - max_suspicion_severity_gte: medium
  - extraction_confidence_lt: 0.8
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_rules_engine.py`:
```python
from app.graph.state import (
    InvoiceState, InvoiceData, ValidationReport, ValidationIssue, SuspicionSignal
)
from app.rules.engine import evaluate_rules, RuleEvaluation


def _state(total=1000.0, issues=None, signals=None, confidence=0.95) -> InvoiceState:
    return InvoiceState(
        run_id="r1", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-1", vendor="Widgets Inc.", date=None, due_date=None,
            line_items=[], subtotal=total, tax_amount=0.0, total=total, raw_text="",
        ),
        suspicion_signals=signals or [],
        extraction_confidence=confidence,
        validation=ValidationReport(issues=issues or [], inventory_lookups=[], vendor_lookup=None),
    )


def test_auto_approve_when_clean_and_small():
    r = evaluate_rules(_state(total=1000.0))
    assert r.hard_blocks == []
    assert r.auto_approve is True
    assert r.scrutiny is False


def test_scrutiny_above_10k():
    r = evaluate_rules(_state(total=15000.0))
    assert r.auto_approve is False
    assert r.scrutiny is True


def test_hard_block_qty_exceeds_stock():
    issue = ValidationIssue(kind="qty_exceeds_stock", item="GadgetX", detail="20>5", severity="block")
    r = evaluate_rules(_state(issues=[issue]))
    assert "qty_exceeds_stock" in r.hard_blocks
    assert r.auto_approve is False


def test_warn_triggers_scrutiny():
    issue = ValidationIssue(kind="price_mismatch", item="WidgetA", detail="", severity="warn")
    r = evaluate_rules(_state(issues=[issue]))
    assert r.scrutiny is True
    assert r.hard_blocks == []


def test_medium_suspicion_triggers_scrutiny():
    sig = SuspicionSignal(kind="urgent_language", detail="urgent", severity="medium")
    r = evaluate_rules(_state(signals=[sig]))
    assert r.scrutiny is True


def test_low_confidence_triggers_scrutiny():
    r = evaluate_rules(_state(confidence=0.6))
    assert r.scrutiny is True
    assert r.auto_approve is False
```

- [ ] **Step 3: Run — expect failure**

Run: `cd backend && pytest tests/test_rules_engine.py -v`
Expected: FAIL

- [ ] **Step 4: Implement `app/rules/engine.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from app.graph.state import InvoiceState

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class RuleEvaluation:
    hard_blocks: list[str] = field(default_factory=list)
    auto_approve: bool = False
    scrutiny: bool = False
    summary: str = ""


def _load_rules(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def evaluate_rules(state: InvoiceState, rules_path: Path | None = None) -> RuleEvaluation:
    if rules_path is None:
        rules_path = Path(__file__).parent / "rules.yaml"
    rules = _load_rules(rules_path)
    hard_kinds = set(rules["hard_blocks"])

    issues = state.validation.issues if state.validation else []
    hard_blocks = [i.kind for i in issues if i.kind in hard_kinds]

    total = state.invoice.total if state.invoice and state.invoice.total is not None else 0.0
    confidence = state.extraction_confidence or 0.0
    max_sev = max(
        (SEVERITY_RANK[s.severity] for s in state.suspicion_signals), default=-1
    )
    has_warn = any(i.severity == "warn" for i in issues)
    has_block = bool(hard_blocks)

    auto_approve = (
        not has_block
        and total <= 10_000
        and not has_warn
        and max_sev <= SEVERITY_RANK["low"]
        and confidence >= 0.8
    )
    scrutiny = (
        has_block  # always scrutinize before rejecting
        or total > 10_000
        or has_warn
        or max_sev >= SEVERITY_RANK["medium"]
        or confidence < 0.8
    )
    summary_parts = []
    if hard_blocks:
        summary_parts.append(f"hard_blocks={hard_blocks}")
    if total > 10_000:
        summary_parts.append(f"total>${10_000}: ${total:.2f}")
    if has_warn:
        summary_parts.append("validation_warn")
    if max_sev >= SEVERITY_RANK["medium"]:
        summary_parts.append("suspicion_medium+")
    if confidence < 0.8:
        summary_parts.append(f"low_confidence={confidence:.2f}")
    return RuleEvaluation(
        hard_blocks=hard_blocks,
        auto_approve=auto_approve,
        scrutiny=scrutiny,
        summary="; ".join(summary_parts) or "clean",
    )
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_rules_engine.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/rules/ backend/tests/test_rules_engine.py
git commit -m "feat: rule engine with hard blocks and scrutiny gates"
```

---

### Task 1.4: Event emitter (`logging_/event_emitter.py`)

**Files:**
- Create: `backend/app/logging_/__init__.py` (empty)
- Create: `backend/app/logging_/event_emitter.py`
- Create: `backend/tests/test_event_emitter.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_event_emitter.py`:
```python
import json
from pathlib import Path
from app.logging_.event_emitter import EventEmitter


def test_emitter_writes_to_state_and_file(tmp_path: Path):
    log_dir = tmp_path / "logs"
    state_events: list[dict] = []
    emitter = EventEmitter(run_id="r1", state_events=state_events, log_dir=log_dir)
    emitter.emit("node.start", node="ingest")
    emitter.emit("node.complete", node="ingest", output={"x": 1})
    assert len(state_events) == 2
    assert state_events[0]["kind"] == "node.start"
    assert "ts" in state_events[0]
    log_file = log_dir / "r1.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["kind"] == "node.complete"


def test_emitter_queue_receives(tmp_path: Path):
    import asyncio

    async def _run():
        q: asyncio.Queue = asyncio.Queue()
        emitter = EventEmitter(run_id="r2", state_events=[], log_dir=tmp_path / "logs", queue=q)
        emitter.emit("node.start", node="ingest")
        event = await asyncio.wait_for(q.get(), timeout=0.5)
        assert event["kind"] == "node.start"

    asyncio.run(_run())
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_event_emitter.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement `event_emitter.py`**

```python
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventEmitter:
    def __init__(
        self,
        run_id: str,
        state_events: list[dict],
        log_dir: Path,
        queue: asyncio.Queue | None = None,
    ) -> None:
        self.run_id = run_id
        self.state_events = state_events
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{run_id}.jsonl"
        self.queue = queue

    def emit(self, kind: str, **payload: Any) -> dict:
        event: dict[str, Any] = {
            "kind": kind,
            "ts": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self.state_events.append(event)
        with self.log_path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        if self.queue is not None:
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_event_emitter.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/logging_/ backend/tests/test_event_emitter.py
git commit -m "feat: event emitter (state + jsonl + sse queue)"
```

---

## Phase 2 — LLM client and ingestion

### Task 2.1: Grok client wrapper

**Files:**
- Create: `backend/app/llm/__init__.py`
- Create: `backend/app/llm/grok_client.py`
- Create: `backend/app/llm/structured_output.py`
- Create: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_grok_client.py`:
```python
from unittest.mock import MagicMock
from pydantic import BaseModel
from app.llm.grok_client import GrokClient


class Toy(BaseModel):
    a: int
    b: str


def test_grok_client_parses_structured_output():
    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))
    ]
    mock_sdk.chat.completions.create.return_value.usage = MagicMock(
        prompt_tokens=10, completion_tokens=5
    )
    client = GrokClient(model="grok-4", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract", user="data", schema=Toy
    )
    assert parsed == Toy(a=7, b="hi")
    assert meta.tokens_in == 10
    assert meta.tokens_out == 5
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_grok_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/llm/grok_client.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallMeta:
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


class GrokClient:
    def __init__(self, *, api_key: str = "", base_url: str = "https://api.x.ai/v1",
                 model: str = "grok-4", sdk: OpenAI | None = None) -> None:
        self.model = model
        self.sdk = sdk or OpenAI(api_key=api_key, base_url=base_url)

    def structured_complete(
        self, *, system: str, user: str, schema: Type[T], max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        """One LLM call with one retry on Pydantic validation failure."""
        attempts = 0
        last_error: str | None = None
        while True:
            attempts += 1
            t0 = perf_counter()
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            if last_error is not None:
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous output failed validation with this error:\n"
                        f"{last_error}\nReturn corrected JSON only."
                    ),
                })
            resp = self.sdk.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            elapsed_ms = int((perf_counter() - t0) * 1000)
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            try:
                parsed = schema.model_validate(json.loads(content))
                meta = CallMeta(
                    tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                    tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                    latency_ms=elapsed_ms,
                    model=self.model,
                )
                return parsed, meta
            except (ValidationError, json.JSONDecodeError) as e:
                last_error = str(e)
                if attempts > max_retries:
                    raise
```

- [ ] **Step 4: Write a minimal `structured_output.py` placeholder**

```python
"""Reserved for any future structured-output helpers we don't need yet."""
```

(YAGNI — the helper currently lives inside GrokClient.)

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_grok_client.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/ backend/tests/test_grok_client.py
git commit -m "feat: grok client with structured output + retry"
```

---

### Task 2.2: File loader (`parsers/file_loader.py`)

**Files:**
- Create: `backend/app/parsers/__init__.py`
- Create: `backend/app/parsers/file_loader.py`
- Create: `backend/tests/test_file_loader.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_file_loader.py`:
```python
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
    p = Path("data/invoices/invoice_1011.pdf")
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
    # Simulate both extractors returning blank — represents a scanned/image PDF.
    import pytest
    from app.parsers import file_loader
    from app.parsers.file_loader import EmptyExtractionError

    monkeypatch.setattr(file_loader, "_load_pdf", lambda _p: "")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-fake")
    with pytest.raises(EmptyExtractionError):
        load_invoice_file(pdf)
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_file_loader.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `parsers/file_loader.py`**

```python
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
    doc = fitz.open(path)
    return "\n".join(page.get_text() for page in doc).strip()


class EmptyExtractionError(ValueError):
    """Raised when a PDF (or other file) yields no extractable text — likely a scan."""


def load_invoice_file(path: Path) -> LoadedFile:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        text = _load_pdf(path)
        if not text.strip():
            # Both pdfplumber and PyMuPDF returned nothing — almost certainly a
            # scanned image PDF. We do not ship an OCR fallback (would require
            # a system-level tesseract binary that the case data does not need).
            # Fail loudly so the graph routes to `unprocessable` rather than
            # feeding the LLM an empty document.
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
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_file_loader.py -v`
Expected: 5 passed (or 4 + 1 skipped if PDF not present)

- [ ] **Step 5: Commit**

```bash
git add backend/app/parsers/ backend/tests/test_file_loader.py
git commit -m "feat: file loader for txt/json/csv/xml/pdf/email"
```

---

### Task 2.3: Ingestion agent (`agents/ingest.py`)

**Files:**
- Create: `backend/app/agents/__init__.py` (empty)
- Create: `backend/app/agents/ingest.py`
- Create: `backend/tests/test_ingest_agent.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_ingest_agent.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
from app.graph.state import InvoiceState
from app.agents.ingest import run_ingest
from app.logging_.event_emitter import EventEmitter


def _mk_state(path: str, fmt: str = "txt") -> InvoiceState:
    return InvoiceState(run_id="r", source_path=path, file_format=fmt)


def test_ingest_populates_state_when_llm_returns_valid(tmp_path: Path):
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("INVOICE\nVendor: Widgets Inc.\nTotal: $1000\n")

    fake_meta = MagicMock(tokens_in=100, tokens_out=50, latency_ms=200, model="grok-4")
    llm = MagicMock()
    llm.structured_complete.return_value = (
        MagicMock(  # parsed IngestResponse
            invoice=MagicMock(model_dump=lambda: {
                "invoice_number": "INV-1", "vendor": "Widgets Inc.",
                "date": None, "due_date": None, "line_items": [],
                "subtotal": 1000.0, "tax_amount": 0.0, "total": 1000.0,
                "currency": "USD", "payment_terms": None, "raw_text": "...",
            }),
            suspicion_signals=[],
            extraction_confidence=0.95,
        ),
        fake_meta,
    )

    state = _mk_state(str(inv_file))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)
    assert out.invoice is not None
    assert out.invoice.vendor == "Widgets Inc."
    assert out.extraction_confidence == 0.95
    assert any(e["kind"] == "ingest.complete" for e in out.events)
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_ingest_agent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `agents/ingest.py`**

```python
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel
from app.graph.state import InvoiceData, InvoiceState, SuspicionSignal
from app.llm.grok_client import GrokClient
from app.logging_.event_emitter import EventEmitter
from app.parsers.file_loader import load_invoice_file


class IngestResponse(BaseModel):
    invoice: InvoiceData
    suspicion_signals: list[SuspicionSignal] = []
    extraction_confidence: float


SYSTEM_PROMPT = """You are an invoice extractor. Convert the provided invoice text into a structured JSON object.

Rules:
- Extract values verbatim from the source. Do not invent values.
- If a field is missing or unreadable, return null. Do not guess.
- Dates use YYYY-MM-DD. If the source says "yesterday" or another relative term, return null and note it as a suspicion signal.
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * dates in the past or expressed as "yesterday"
  * round-number totals on otherwise odd line items
  * generic or alarming vendor names
  * unknown / made-up looking item names
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": { invoice_number, vendor, date, due_date, line_items:[{item, quantity, unit_price, notes}], subtotal, tax_amount, total, currency, payment_terms, raw_text },
  "suspicion_signals": [{ kind, detail, severity }],
  "extraction_confidence": number
}
The raw_text field should echo the input text exactly.
"""


def run_ingest(state: InvoiceState, *, llm: GrokClient, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="ingest")
    path = Path(state.source_path)

    try:
        loaded = load_invoice_file(path)
        state.file_format = loaded.format  # type: ignore[assignment]
    except Exception as e:
        # EmptyExtractionError (scanned PDF, no OCR) and any other load failure
        # land here. The graph's conditional edge after `ingest` routes to `log`
        # when state.error is set.
        state.error = f"unprocessable: {e}"
        emitter.emit("node.complete", node="ingest", output={"error": state.error})
        return state

    user = f"Source format: {loaded.format}\n\nInvoice content:\n{loaded.text}"
    try:
        parsed, meta = llm.structured_complete(
            system=SYSTEM_PROMPT, user=user, schema=IngestResponse, max_retries=1,
        )
    except Exception as e:
        state.error = f"unprocessable: extraction failed ({e})"
        emitter.emit("ingest.retry", node="ingest", reason="pydantic validation exhausted")
        emitter.emit("node.complete", node="ingest", output={"error": state.error})
        return state

    emitter.emit(
        "llm.call", node="ingest",
        tokens_in=meta.tokens_in, tokens_out=meta.tokens_out,
        latency_ms=meta.latency_ms, model=meta.model,
        prompt_chars=len(user), response_chars=0,
    )
    state.invoice = parsed.invoice
    state.invoice.raw_text = loaded.text  # ensure raw_text is from source, not echoed
    state.suspicion_signals = parsed.suspicion_signals
    state.extraction_confidence = parsed.extraction_confidence
    emitter.emit("node.complete", node="ingest", output={
        "vendor": state.invoice.vendor,
        "total": state.invoice.total,
        "confidence": parsed.extraction_confidence,
        "suspicion_count": len(parsed.suspicion_signals),
    })
    return state
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_ingest_agent.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/ backend/tests/test_ingest_agent.py
git commit -m "feat: ingestion agent with grok extraction"
```

---

### Task 2.4: Live-LLM smoke test for ingestion (opt-in)

**Files:**
- Create: `backend/tests/test_live_smoke.py`

- [ ] **Step 1: Write the conditional test**

```python
import os
from pathlib import Path
import pytest
from app.config import get_settings
from app.llm.grok_client import GrokClient
from app.graph.state import InvoiceState
from app.agents.ingest import run_ingest
from app.logging_.event_emitter import EventEmitter

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to run"
)


def test_live_ingest_inv_1001(tmp_path: Path):
    settings = get_settings()
    assert settings.xai_api_key, "Set XAI_API_KEY in .env"
    llm = GrokClient(
        api_key=settings.xai_api_key, base_url=settings.xai_base_url, model=settings.xai_model,
    )
    state = InvoiceState(
        run_id="live-1", source_path="data/invoices/invoice_1001.txt", file_format="txt",
    )
    emitter = EventEmitter("live-1", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)
    assert out.invoice is not None
    assert out.invoice.vendor and "widgets" in out.invoice.vendor.lower()
    assert out.invoice.total == 5000.0 or out.invoice.subtotal == 5000.0
```

- [ ] **Step 2: Run with live flag (manual confirmation)**

```bash
cd backend && RUN_LIVE_TESTS=1 pytest tests/test_live_smoke.py -v
```
Expected: 1 passed. (If failed, debug the prompt or model name; this is the first real-LLM signal.)

- [ ] **Step 3: Run without the flag — confirm skipped**

```bash
cd backend && pytest tests/test_live_smoke.py -v
```
Expected: 1 skipped

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_live_smoke.py
git commit -m "test: live grok smoke test for ingestion"
```

---

## Phase 3 — Validation and tools

### Task 3.1: Inventory and vendor tools

**Files:**
- Create: `backend/app/tools/__init__.py`
- Create: `backend/app/tools/inventory_tool.py`
- Create: `backend/app/tools/vendor_tool.py`
- Create: `backend/tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tools.py`:
```python
import sqlite3
from pathlib import Path
from app.db.init_db import init_db
from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup


def _seeded(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    return db


def test_inventory_lookup_found(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("WidgetA", db_path=db)
    assert r == {"found": True, "item": "WidgetA", "stock": 15, "unit_price": 250.0}


def test_inventory_lookup_not_found(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("SuperGizmo", db_path=db)
    assert r == {"found": False, "item": "SuperGizmo", "stock": None, "unit_price": None}


def test_inventory_lookup_normalizes_widget_spacing(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("Widget A", db_path=db)
    assert r["found"] is True
    assert r["stock"] == 15


def test_vendor_lookup_match_via_normalization(tmp_path: Path):
    db = _seeded(tmp_path)
    r = vendor_lookup("widgets inc.", db_path=db)
    assert r["found"] is True
    assert r["status"] == "approved"


def test_vendor_lookup_unknown(tmp_path: Path):
    db = _seeded(tmp_path)
    r = vendor_lookup("Fraudster LLC", db_path=db)
    assert r["found"] is False
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `tools/inventory_tool.py`**

```python
from __future__ import annotations
import sqlite3
from pathlib import Path
from app.db.init_db import normalize_vendor  # reused for general normalization
from app.config import get_settings


def _norm_item(s: str) -> str:
    return "".join(s.split()).lower()


def inventory_lookup(item: str, db_path: Path | None = None) -> dict:
    db_path = db_path or get_settings().invoice_processing_db_path
    conn = sqlite3.connect(db_path)
    try:
        target = _norm_item(item)
        cur = conn.execute("SELECT item, stock, unit_price FROM inventory")
        for row_item, stock, unit_price in cur.fetchall():
            if _norm_item(row_item) == target:
                return {
                    "found": True, "item": row_item,
                    "stock": int(stock), "unit_price": float(unit_price),
                }
        return {"found": False, "item": item, "stock": None, "unit_price": None}
    finally:
        conn.close()
```

- [ ] **Step 4: Implement `tools/vendor_tool.py`**

```python
from __future__ import annotations
import sqlite3
from pathlib import Path
from app.db.init_db import normalize_vendor
from app.config import get_settings


def vendor_lookup(name: str, db_path: Path | None = None) -> dict:
    if not name or not name.strip():
        return {"found": False, "name": name, "status": None}
    db_path = db_path or get_settings().invoice_processing_db_path
    conn = sqlite3.connect(db_path)
    try:
        normalized = normalize_vendor(name)
        row = conn.execute(
            "SELECT display_name, status FROM vendors WHERE name = ?", (normalized,),
        ).fetchone()
        if row:
            return {"found": True, "name": row[0], "status": row[1]}
        return {"found": False, "name": name, "status": None}
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_tools.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools/ backend/tests/test_tools.py
git commit -m "feat: inventory and vendor lookup tools"
```

---

### Task 3.2: Validation agent (`agents/validate.py`)

**Files:**
- Create: `backend/app/agents/validate.py`
- Create: `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_validate_agent.py`:
```python
from pathlib import Path
from app.db.init_db import init_db
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.agents.validate import run_validate
from app.logging_.event_emitter import EventEmitter


def _seeded(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    return db


def _state(invoice: InvoiceData) -> InvoiceState:
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt", invoice=invoice,
    )


def _inv(**kw) -> InvoiceData:
    base = dict(
        invoice_number="INV-X", vendor="Widgets Inc.", date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=None, raw_text="",
    )
    base.update(kw)
    return InvoiceData(**base)


def test_unknown_item_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="SuperGizmo", quantity=2, unit_price=400.0)],
        total=800.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "unknown_item" in kinds


def test_qty_exceeds_stock_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="GadgetX", quantity=20, unit_price=750.0)],
        total=15000.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "qty_exceeds_stock" in kinds


def test_out_of_stock_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="FakeItem", quantity=1, unit_price=1000.0)],
        total=1000.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "out_of_stock" in kinds


def test_missing_vendor_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(vendor=None, line_items=[LineItem(item="WidgetA", quantity=1)]))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "missing_vendor" in kinds


def test_negative_qty_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(line_items=[LineItem(item="WidgetA", quantity=-5)]))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "negative_qty" in kinds


def test_price_mismatch_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=100.0)],  # 60% off
        total=400.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "price_mismatch" in kinds


def test_unknown_vendor_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        vendor="Fraudster LLC",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "unknown_vendor" in kinds


def test_records_lookups_for_ui(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    assert len(out.validation.inventory_lookups) == 1
    assert out.validation.vendor_lookup is not None
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_validate_agent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `agents/validate.py`**

```python
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
            continue  # already flagged
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
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_validate_agent.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/validate.py backend/tests/test_validate_agent.py
git commit -m "feat: validation agent with inventory/vendor/price checks"
```

---

### Task 3.3: Vendor name normalization edge cases

**Files:**
- Create: `backend/tests/test_vendor_normalization.py`

- [ ] **Step 1: Write tests for tricky vendor names**

```python
import pytest
from app.db.init_db import normalize_vendor


@pytest.mark.parametrize("input_name,expected", [
    ("Widgets Inc.", "widgets"),
    ("widgets, inc.", "widgets"),
    ("WIDGETS INC", "widgets"),
    ("Atlas Industrial Supply", "atlas industrial supply"),
    ("Acme Co.", "acme"),
    ("Acme Corporation", "acme"),
    ("  Acme   Corp  ", "acme"),
    ("Reliable Components Inc.", "reliable components"),
])
def test_normalization_table(input_name, expected):
    assert normalize_vendor(input_name) == expected
```

- [ ] **Step 2: Run — many should pass already, fix the ones that don't**

Run: `cd backend && pytest tests/test_vendor_normalization.py -v`
Fix `normalize_vendor` if any fail (e.g., comma handling, double space collapse already covered).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_vendor_normalization.py
# (and `backend/app/db/init_db.py` if you adjusted normalize_vendor)
git commit -m "test: vendor normalization edge cases"
```

---

## Phase 4 — Approval node

### Task 4.1: Proposal/Critique/Finalize prompts and pass schemas

**Files:**
- Create: `backend/app/agents/approve.py`
- Create: `backend/tests/test_approve_agent.py`

This task implements the three-pass approver from spec §8. We unit-test each pass with a mocked GrokClient.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_approve_agent.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
from app.graph.state import (
    InvoiceData, InvoiceState, ValidationIssue, ValidationReport, LineItem,
    Proposal, Critique,
)
from app.agents.approve import run_approve
from app.logging_.event_emitter import EventEmitter


def _state(total=1000.0, issues=None, vendor="Widgets Inc.") -> InvoiceState:
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-1", vendor=vendor, date=None, due_date=None,
            line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
            subtotal=total, tax_amount=0.0, total=total, raw_text="raw",
        ),
        extraction_confidence=0.95,
        validation=ValidationReport(issues=issues or [], inventory_lookups=[], vendor_lookup=None),
    )


def _fake_meta():
    return MagicMock(tokens_in=10, tokens_out=10, latency_ms=50, model="grok-4")


def test_approve_hard_block_forces_reject_regardless_of_llm(tmp_path: Path):
    issue = ValidationIssue(kind="qty_exceeds_stock", item="GadgetX", detail="", severity="block")
    state = _state(total=15000.0, issues=[issue])

    llm = MagicMock()
    # LLM optimistically suggests approve; engine must override.
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="seems fine", rules_applied=[], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="approved", rationale="confirmed", rules_applied=[], unresolved_concerns=[]), _fake_meta()),
    ]

    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision is not None
    assert out.decision.outcome == "rejected"
    assert "qty_exceeds_stock" in out.decision.rules_applied[0]


def test_approve_clean_invoice_approves(tmp_path: Path):
    state = _state(total=1000.0)
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="clean", rules_applied=["auto_approve"], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="approved", rationale="clean", rules_applied=["auto_approve"], unresolved_concerns=[]), _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "approved"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.critique.agrees is True


def test_approve_critic_revises_initial(tmp_path: Path):
    state = _state(total=12000.0)  # scrutiny territory
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="passed checks", rules_applied=["scrutiny"], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=False, objections=["missed risk"], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="needs_review", rationale="critic raised concern", rules_applied=["scrutiny"], unresolved_concerns=["missed risk"]), _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "needs_review"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.final_proposal.outcome == "needs_review"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_approve_agent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `agents/approve.py`**

```python
from __future__ import annotations
import json
from app.graph.state import (
    Critique, Decision, InvoiceState, Proposal,
)
from app.llm.grok_client import GrokClient
from app.logging_.event_emitter import EventEmitter
from app.rules.engine import RuleEvaluation, evaluate_rules

PROPOSE_SYSTEM = """You are an accounts payable approver at Acme Corp.

Given the invoice data, validation report, suspicion signals, extraction confidence, and rule-engine evaluation, decide: approved | rejected | needs_review.

Rules to apply (verbatim):
- If the rule engine reports any hard_blocks, the outcome MUST be 'rejected' — explain which blocks and why.
- If auto_approve is true (all gates green), approve and cite "auto_approve".
- If scrutiny is required, weigh the validation warnings and suspicion signals; rejected only for clear cause, needs_review for genuine ambiguity, approved only with explicit reasoning.

Cite every rule you apply by name. Be concise — 2-4 sentences of rationale max.

Return JSON: { "outcome": "...", "rationale": "...", "rules_applied": [...], "unresolved_concerns": [...] }
"""

CRITIQUE_SYSTEM = """You are an adversarial reviewer of an AP approver's decision.

Look for:
- Missed red flags in suspicion_signals or raw invoice text
- Rules cited but applied incorrectly
- Low extraction confidence the approver glossed over
- Unwarranted approval of borderline cases
- Unwarranted rejection where the data supports approval

If you agree, say so plainly — do not manufacture objections.

Return JSON: { "agrees": bool, "objections": [...], "missed_signals": [...], "rule_misapplications": [...] }
"""

FINALIZE_SYSTEM = """You are the AP approver finalizing your decision after a peer critique.

If the critique raises valid points, revise. If not, explain why you stand by the original.

Return JSON: { "outcome": "...", "rationale": "...", "rules_applied": [...], "unresolved_concerns": [...] }
"""


def _emit_llm(emitter: EventEmitter, sub: str, meta) -> None:
    emitter.emit(
        "llm.call", node="approve",
        sub=sub, tokens_in=meta.tokens_in, tokens_out=meta.tokens_out,
        latency_ms=meta.latency_ms, model=meta.model,
        prompt_chars=0, response_chars=0,
    )


def _context_block(state: InvoiceState, evaluation: RuleEvaluation) -> str:
    inv = state.invoice.model_dump() if state.invoice else {}
    val = state.validation.model_dump() if state.validation else {}
    return json.dumps({
        "invoice": inv,
        "validation": val,
        "suspicion_signals": [s.model_dump() for s in state.suspicion_signals],
        "extraction_confidence": state.extraction_confidence,
        "rule_evaluation": {
            "hard_blocks": evaluation.hard_blocks,
            "auto_approve": evaluation.auto_approve,
            "scrutiny": evaluation.scrutiny,
            "summary": evaluation.summary,
        },
    }, default=str, indent=2)


def run_approve(state: InvoiceState, *, llm: GrokClient, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="approve")
    evaluation = evaluate_rules(state)
    emitter.emit("approve.rules_evaluated", node="approve", evaluation={
        "hard_blocks": evaluation.hard_blocks,
        "auto_approve": evaluation.auto_approve,
        "scrutiny": evaluation.scrutiny,
        "summary": evaluation.summary,
    })

    context = _context_block(state, evaluation)

    # Pass 1: propose
    emitter.emit("approve.propose.start", node="approve")
    proposal, meta1 = llm.structured_complete(
        system=PROPOSE_SYSTEM, user=context, schema=Proposal,
    )
    _emit_llm(emitter, "propose", meta1)
    emitter.emit("approve.propose.complete", node="approve", output=proposal.model_dump())

    # Pass 2: critique
    critique_user = context + "\n\nApprover proposal:\n" + proposal.model_dump_json(indent=2)
    if state.invoice and state.invoice.raw_text:
        critique_user += "\n\nRaw invoice text:\n" + state.invoice.raw_text
    emitter.emit("approve.critique.start", node="approve")
    try:
        critique, meta2 = llm.structured_complete(
            system=CRITIQUE_SYSTEM, user=critique_user, schema=Critique,
        )
        _emit_llm(emitter, "critique", meta2)
        emitter.emit("approve.critique.complete", node="approve", output=critique.model_dump())
    except Exception as e:
        emitter.emit("approve.critique.complete", node="approve", output={"error": str(e)})
        critique = Critique(agrees=False, objections=[f"critique pass failed: {e}"],
                            missed_signals=[], rule_misapplications=[])
        forced_review = True
    else:
        forced_review = False

    # Pass 3: finalize
    finalize_user = (
        context
        + "\n\nInitial proposal:\n" + proposal.model_dump_json(indent=2)
        + "\n\nCritique:\n" + critique.model_dump_json(indent=2)
    )
    emitter.emit("approve.finalize.start", node="approve")
    final_proposal, meta3 = llm.structured_complete(
        system=FINALIZE_SYSTEM, user=finalize_user, schema=Proposal,
    )
    _emit_llm(emitter, "finalize", meta3)
    emitter.emit("approve.finalize.complete", node="approve", output=final_proposal.model_dump())

    outcome = final_proposal.outcome
    rules_applied = list(final_proposal.rules_applied)
    rationale = final_proposal.rationale

    # Hard-block override: rule engine has final authority
    if evaluation.hard_blocks:
        outcome = "rejected"
        rules_applied = [f"hard_block:{kind}" for kind in evaluation.hard_blocks] + rules_applied
        rationale = (
            f"Hard-block rules forced rejection: {', '.join(evaluation.hard_blocks)}. "
            f"Model rationale: {rationale}"
        )

    if forced_review and outcome == "approved":
        outcome = "needs_review"
        rationale = "Critique pass failed — escalated to needs_review. " + rationale

    state.decision = Decision(
        outcome=outcome,
        rationale=rationale,
        rules_applied=rules_applied,
        initial_proposal=proposal,
        critique=critique,
        final_proposal=final_proposal,
    )
    emitter.emit("approve.decision", node="approve", output=state.decision.model_dump())
    emitter.emit("node.complete", node="approve", output={"outcome": outcome})
    return state
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_approve_agent.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/approve.py backend/tests/test_approve_agent.py
git commit -m "feat: approval agent with propose/critique/finalize loop"
```

---

### Task 4.2: Approval routing helper

This is small but worth a dedicated unit so the graph builder stays clean.

**Files:**
- Modify: `backend/app/agents/approve.py` (add `route_after_approve`)
- Modify: `backend/tests/test_approve_agent.py`

- [ ] **Step 1: Add the test**

Append to `test_approve_agent.py`:
```python
from app.agents.approve import route_after_approve
from app.graph.state import Decision, Proposal, Critique


def _dec(outcome):
    p = Proposal(outcome=outcome, rationale="", rules_applied=[], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return Decision(outcome=outcome, rationale="", rules_applied=[],
                    initial_proposal=p, critique=c, final_proposal=p)


def test_route_after_approve_approved_goes_to_pay():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("approved")
    assert route_after_approve(state) == "pay"


def test_route_after_approve_rejected_goes_to_log():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("rejected")
    assert route_after_approve(state) == "log"


def test_route_after_approve_needs_review_goes_to_log():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("needs_review")
    assert route_after_approve(state) == "log"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_approve_agent.py::test_route_after_approve_approved_goes_to_pay -v`
Expected: FAIL

- [ ] **Step 3: Add `route_after_approve` to `approve.py`**

```python
def route_after_approve(state: InvoiceState) -> str:
    if state.decision is None:
        return "log"
    return "pay" if state.decision.outcome == "approved" else "log"
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_approve_agent.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/approve.py backend/tests/test_approve_agent.py
git commit -m "feat: approve→pay/log routing helper"
```

---

## Phase 5 — Payment, log, graph, CLI

### Task 5.1: Payment tool and node

**Files:**
- Create: `backend/app/tools/payment_tool.py`
- Create: `backend/app/agents/pay.py`
- Create: `backend/tests/test_pay.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pay.py`:
```python
from pathlib import Path
from app.graph.state import InvoiceData, InvoiceState, Decision, Proposal, Critique
from app.agents.pay import run_pay, reset_paid_invoices
from app.logging_.event_emitter import EventEmitter


def _state(inv_num="INV-1", total=500.0) -> InvoiceState:
    p = Proposal(outcome="approved", rationale="ok", rules_applied=[], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number=inv_num, vendor="Widgets Inc.", date=None, due_date=None,
            line_items=[], subtotal=total, tax_amount=0.0, total=total, raw_text="",
        ),
        decision=Decision(outcome="approved", rationale="", rules_applied=[],
                          initial_proposal=p, critique=c, final_proposal=p),
    )


def test_pay_returns_success_and_records_receipt(tmp_path: Path):
    reset_paid_invoices()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_pay(state, emitter=emitter)
    assert out.payment_receipt is not None
    assert out.payment_receipt["status"] == "success"
    assert out.payment_receipt["vendor"] == "Widgets Inc."
    assert out.payment_receipt["amount"] == 500.0


def test_pay_idempotent(tmp_path: Path):
    reset_paid_invoices()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    run_pay(state, emitter=emitter)
    state2 = _state()
    emitter2 = EventEmitter("r2", state2.events, tmp_path / "logs")
    out = run_pay(state2, emitter=emitter2)
    assert any(e["kind"] == "pay.skipped_duplicate" for e in out.events)
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_pay.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `tools/payment_tool.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone


def mock_payment(*, vendor: str, amount: float, invoice_number: str, run_id: str) -> dict:
    return {
        "status": "success",
        "transaction_id": f"TXN-{run_id[:8]}",
        "vendor": vendor,
        "amount": amount,
        "invoice_number": invoice_number,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Implement `agents/pay.py`**

```python
from __future__ import annotations
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter
from app.tools.payment_tool import mock_payment

_PAID_INVOICES: set[str] = set()


def reset_paid_invoices() -> None:
    _PAID_INVOICES.clear()


def run_pay(state: InvoiceState, *, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="pay")
    inv = state.invoice
    if inv is None or inv.invoice_number is None or inv.total is None or not inv.vendor:
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "missing fields"})
        return state
    if inv.invoice_number in _PAID_INVOICES:
        emitter.emit("pay.skipped_duplicate", node="pay",
                     output={"invoice_number": inv.invoice_number})
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "duplicate"})
        return state
    receipt = mock_payment(
        vendor=inv.vendor, amount=inv.total,
        invoice_number=inv.invoice_number, run_id=state.run_id,
    )
    _PAID_INVOICES.add(inv.invoice_number)
    state.payment_receipt = receipt
    emitter.emit("tool.call", node="pay", tool="mock_payment",
                 args={"vendor": inv.vendor, "amount": inv.total}, result=receipt)
    emitter.emit("node.complete", node="pay", output=receipt)
    return state
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_pay.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/pay.py backend/app/tools/payment_tool.py backend/tests/test_pay.py
git commit -m "feat: payment tool and pay node with idempotency"
```

---

### Task 5.2: Rejection/unprocessable log node

**Files:**
- Create: `backend/app/agents/log_node.py`
- Create: `backend/tests/test_log_node.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_log_node.py`:
```python
import json
from pathlib import Path
from app.graph.state import (
    InvoiceData, InvoiceState, Decision, Proposal, Critique,
    ValidationReport, ValidationIssue,
)
from app.agents.log_node import run_log
from app.logging_.event_emitter import EventEmitter


def _rejected_state(tmp_path: Path) -> InvoiceState:
    p = Proposal(outcome="rejected", rationale="bad", rules_applied=["hard_block:out_of_stock"], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return InvoiceState(
        run_id="r-rej", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-X", vendor="Fraudster LLC", date=None, due_date=None,
            line_items=[], subtotal=100.0, tax_amount=0.0, total=100.0, raw_text="",
        ),
        decision=Decision(outcome="rejected", rationale="bad", rules_applied=["hard_block:out_of_stock"],
                          initial_proposal=p, critique=c, final_proposal=p),
        validation=ValidationReport(issues=[], inventory_lookups=[], vendor_lookup=None),
    )


def test_log_writes_rejection_record(tmp_path: Path):
    state = _rejected_state(tmp_path)
    emitter = EventEmitter("r-rej", state.events, tmp_path / "logs")
    rejections_file = tmp_path / "logs" / "rejections.jsonl"
    out = run_log(state, emitter=emitter, rejections_file=rejections_file)
    assert rejections_file.exists()
    record = json.loads(rejections_file.read_text().splitlines()[-1])
    assert record["outcome"] == "rejected"
    assert record["vendor"] == "Fraudster LLC"


def test_log_writes_unprocessable_record(tmp_path: Path):
    state = InvoiceState(run_id="r-bad", source_path="x", file_format="txt", error="unprocessable: foo")
    emitter = EventEmitter("r-bad", state.events, tmp_path / "logs")
    rejections_file = tmp_path / "logs" / "rejections.jsonl"
    out = run_log(state, emitter=emitter, rejections_file=rejections_file)
    record = json.loads(rejections_file.read_text().splitlines()[-1])
    assert record["outcome"] == "unprocessable"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_log_node.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `agents/log_node.py`**

```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter


def run_log(
    state: InvoiceState, *, emitter: EventEmitter, rejections_file: Path | None = None,
) -> InvoiceState:
    emitter.emit("node.start", node="log")
    rejections_file = rejections_file or emitter.log_dir / "rejections.jsonl"
    rejections_file.parent.mkdir(parents=True, exist_ok=True)

    if state.error and state.invoice is None:
        record = {
            "run_id": state.run_id,
            "invoice_number": None,
            "vendor": None,
            "outcome": "unprocessable",
            "rationale": state.error,
            "rules_applied": [],
            "validation_issues": [],
            "suspicion_signals": [],
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }
        emitter.emit("log.unprocessable_written", node="log", output=record)
    else:
        inv = state.invoice
        decision = state.decision
        record = {
            "run_id": state.run_id,
            "invoice_number": inv.invoice_number if inv else None,
            "vendor": inv.vendor if inv else None,
            "outcome": decision.outcome if decision else "rejected",
            "rationale": decision.rationale if decision else "",
            "rules_applied": decision.rules_applied if decision else [],
            "validation_issues": [i.model_dump() for i in (state.validation.issues if state.validation else [])],
            "suspicion_signals": [s.model_dump() for s in state.suspicion_signals],
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }
        emitter.emit("log.rejection_written", node="log", output=record)

    with rejections_file.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    emitter.emit("node.complete", node="log", output={"written": True})
    return state
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_log_node.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/log_node.py backend/tests/test_log_node.py
git commit -m "feat: rejection/unprocessable log node"
```

---

### Task 5.3: Wire the LangGraph (`graph/builder.py`)

**Files:**
- Create: `backend/app/graph/builder.py`
- Create: `backend/tests/test_graph_builder.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_graph_builder.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
from app.db.init_db import init_db
from app.graph.state import InvoiceState, Proposal, Critique
from app.graph.builder import build_graph
from app.logging_.event_emitter import EventEmitter


def test_graph_compiles_and_runs_approved_path(tmp_path: Path):
    db = tmp_path / "t.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)

    # Fake LLM that produces a valid extraction and unanimous approve.
    llm = MagicMock()
    # ingest pass
    ingest_response = MagicMock()
    ingest_response.invoice = MagicMock()
    ingest_response.invoice.model_dump = lambda: {
        "invoice_number": "INV-1001", "vendor": "Widgets Inc.",
        "date": "2026-01-15", "due_date": "2026-02-01",
        "line_items": [{"item": "WidgetA", "quantity": 1, "unit_price": 250.0}],
        "subtotal": 250.0, "tax_amount": 0.0, "total": 250.0,
        "currency": "USD", "payment_terms": "Net 15", "raw_text": "",
    }
    from app.graph.state import InvoiceData, SuspicionSignal
    ingest_inv = InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms="Net 15", raw_text="",
    )
    ingest_inv.line_items = []
    from app.agents.ingest import IngestResponse
    ingest_resp = IngestResponse(
        invoice=ingest_inv, suspicion_signals=[], extraction_confidence=0.95,
    )
    meta = MagicMock(tokens_in=10, tokens_out=10, latency_ms=10, model="grok-4")

    proposal = Proposal(outcome="approved", rationale="ok", rules_applied=["auto_approve"], unresolved_concerns=[])
    critique = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    llm.structured_complete.side_effect = [
        (ingest_resp, meta),  # ingest
        (proposal, meta),     # propose
        (critique, meta),     # critique
        (proposal, meta),     # finalize
    ]

    graph = build_graph(llm=llm, db_path=db, log_dir=tmp_path / "logs")
    init_state = InvoiceState(
        run_id="r-graph",
        source_path=str(Path("data/invoices/invoice_1001.txt").resolve()),
        file_format="txt",
    )
    out = graph.invoke(init_state)
    assert out["decision"].outcome == "approved"
    assert out["payment_receipt"] is not None
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_graph_builder.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `graph/builder.py`**

```python
from __future__ import annotations
from pathlib import Path
from langgraph.graph import StateGraph, END
from app.agents.approve import route_after_approve, run_approve
from app.agents.ingest import run_ingest
from app.agents.log_node import run_log
from app.agents.pay import run_pay
from app.agents.validate import run_validate
from app.graph.state import InvoiceState
from app.llm.grok_client import GrokClient
from app.logging_.event_emitter import EventEmitter


def _emitter_for(state: InvoiceState, log_dir: Path) -> EventEmitter:
    return EventEmitter(state.run_id, state.events, log_dir)


def build_graph(*, llm: GrokClient, db_path: Path, log_dir: Path):
    graph = StateGraph(InvoiceState)

    def ingest_node(state: InvoiceState) -> InvoiceState:
        return run_ingest(state, llm=llm, emitter=_emitter_for(state, log_dir))

    def validate_node(state: InvoiceState) -> InvoiceState:
        return run_validate(state, db_path=db_path, emitter=_emitter_for(state, log_dir))

    def approve_node(state: InvoiceState) -> InvoiceState:
        return run_approve(state, llm=llm, emitter=_emitter_for(state, log_dir))

    def pay_node(state: InvoiceState) -> InvoiceState:
        return run_pay(state, emitter=_emitter_for(state, log_dir))

    def log_node_fn(state: InvoiceState) -> InvoiceState:
        return run_log(state, emitter=_emitter_for(state, log_dir))

    graph.add_node("ingest", ingest_node)
    graph.add_node("validate", validate_node)
    graph.add_node("approve", approve_node)
    graph.add_node("pay", pay_node)
    graph.add_node("log", log_node_fn)

    graph.set_entry_point("ingest")
    # ingest → validate, unless unprocessable → log
    graph.add_conditional_edges(
        "ingest",
        lambda s: "log" if s.error else "validate",
        {"validate": "validate", "log": "log"},
    )
    graph.add_edge("validate", "approve")
    graph.add_conditional_edges(
        "approve", route_after_approve, {"pay": "pay", "log": "log"},
    )
    graph.add_edge("pay", END)
    graph.add_edge("log", END)
    return graph.compile()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_graph_builder.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/builder.py backend/tests/test_graph_builder.py
git commit -m "feat: langgraph builder wiring all five nodes"
```

---

### Task 5.4: CLI entry point (`main.py`)

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_cli.py`:
```python
import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.skipif(not Path("backend/data/inventory.db").exists() and
                    not Path("data/inventory.db").exists(),
                    reason="run `make seed` first")
def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"],
        capture_output=True, text=True, cwd="backend",
    )
    assert result.returncode == 0
    assert "--invoice_path" in result.stdout
```

- [ ] **Step 2: Implement `app/main.py`**

```python
from __future__ import annotations
import argparse
import json
import sys
import uuid
from pathlib import Path
from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.llm.grok_client import GrokClient
from app.parsers.file_loader import load_invoice_file


def _format_summary(final: dict) -> str:
    state = final
    decision = state.get("decision")
    receipt = state.get("payment_receipt")
    inv = state.get("invoice") or {}
    lines = [
        f"Run:        {state.get('run_id')}",
        f"File:       {state.get('source_path')}",
        f"Vendor:     {inv.get('vendor')}",
        f"Amount:     ${inv.get('total')}" if inv.get("total") is not None else "Amount:     —",
        f"Outcome:    {decision.outcome if decision else state.get('error', 'unknown')}",
    ]
    if decision:
        lines.append(f"Rules:      {', '.join(decision.rules_applied) or '—'}")
        lines.append("Rationale:")
        for line in decision.rationale.splitlines():
            lines.append(f"  {line}")
    if receipt:
        lines.append(f"Receipt:    {receipt['transaction_id']} at {receipt['paid_at']}")
    return "\n".join(lines)


def run_one(invoice_path: Path, *, settings) -> dict:
    db = settings.invoice_processing_db_path
    if not db.exists():
        init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    llm = GrokClient(
        api_key=settings.xai_api_key,
        base_url=settings.xai_base_url,
        model=settings.xai_model,
    )
    graph = build_graph(llm=llm, db_path=db, log_dir=settings.invoice_processing_log_dir)
    loaded = load_invoice_file(invoice_path)
    state = InvoiceState(
        run_id=uuid.uuid4().hex,
        source_path=str(invoice_path.resolve()),
        file_format=loaded.format,  # type: ignore[arg-type]
    )
    final = graph.invoke(state)
    return final


def main() -> int:
    ap = argparse.ArgumentParser(prog="invoice-processor")
    ap.add_argument("--invoice_path", type=Path, help="Path to a single invoice file")
    ap.add_argument("--batch", action="store_true",
                    help="Run all invoices in INVOICE_PROCESSING_INVOICES_DIR")
    ap.add_argument("--json", action="store_true", help="Print final state as JSON")
    args = ap.parse_args()
    settings = get_settings()

    if args.batch:
        paths = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                       if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
        for p in paths:
            print(f"\n=== {p.name} ===")
            final = run_one(p, settings=settings)
            print(_format_summary(final))
        return 0

    if args.invoice_path is None:
        ap.error("--invoice_path is required unless --batch is set")
    final = run_one(args.invoice_path, settings=settings)
    if args.json:
        print(json.dumps(final, default=str, indent=2))
    else:
        print(_format_summary(final))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run tests**

Run: `cd backend && pytest tests/test_cli.py -v`
Expected: 1 passed

- [ ] **Step 4: Smoke-test against a sample invoice with live LLM (manual)**

```bash
cd backend && python -m app.main --invoice_path=data/invoices/invoice_1001.txt
```
Expected: prints a summary block with `Outcome: approved`. (If it fails, debug.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_cli.py
git commit -m "feat: CLI entry point with single-run and batch modes"
```

---

## Phase 6 — Golden fixtures and integration tests

### Task 6.1: Mock-LLM client for tests

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/fixture_helpers.py`

- [ ] **Step 1: Write `tests/fixture_helpers.py`**

```python
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Type, TypeVar
from pydantic import BaseModel
from app.llm.grok_client import CallMeta, GrokClient

T = TypeVar("T", bound=BaseModel)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "grok"


def _key(system: str, user: str) -> str:
    h = hashlib.sha256()
    h.update(system.encode())
    h.update(b"|")
    h.update(user.encode())
    return h.hexdigest()[:16]


class MockGrokClient(GrokClient):
    """Returns recorded responses keyed by prompt hash."""

    def __init__(self) -> None:
        self.model = "grok-mock"

    def structured_complete(
        self, *, system: str, user: str, schema: Type[T], max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        key = _key(system, user)
        path = FIXTURES_DIR / f"{key}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No fixture for prompt hash {key}. Re-record with scripts/record_fixtures.py."
            )
        payload = json.loads(path.read_text())
        return (
            schema.model_validate(payload["response"]),
            CallMeta(tokens_in=payload.get("tokens_in", 0),
                     tokens_out=payload.get("tokens_out", 0),
                     latency_ms=payload.get("latency_ms", 0),
                     model="grok-mock"),
        )

    @staticmethod
    def record(system: str, user: str, response: BaseModel, *, tokens_in: int = 0, tokens_out: int = 0) -> Path:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        key = _key(system, user)
        path = FIXTURES_DIR / f"{key}.json"
        path.write_text(json.dumps({
            "system_preview": system[:200],
            "user_preview": user[:500],
            "response": response.model_dump(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }, indent=2))
        return path
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
from pathlib import Path
import pytest
from app.db.init_db import init_db


@pytest.fixture(scope="session")
def session_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("dbs") / "session.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    return db
```

- [ ] **Step 3: No test for these yet — they exist to support Task 6.2.**

- [ ] **Step 4: Commit**

```bash
git add backend/tests/conftest.py backend/tests/fixture_helpers.py
git commit -m "test: mock grok client + session-scoped seeded db"
```

---

### Task 6.2: Record fixtures script

**Files:**
- Create: `backend/scripts/record_fixtures.py`

This script runs every sample invoice end-to-end against the real Grok API once and records every LLM exchange into `tests/fixtures/grok/`. Run it manually with `make record-fixtures`.

- [ ] **Step 1: Implement `scripts/record_fixtures.py`**

```python
"""Record Grok responses for every sample invoice for use as test fixtures.

Run once after setting XAI_API_KEY. Run again when prompts change.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Allow running as: python scripts/record_fixtures.py
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.llm.grok_client import CallMeta, GrokClient
from app.parsers.file_loader import load_invoice_file
from tests.fixture_helpers import MockGrokClient


class RecordingClient(GrokClient):
    def __init__(self, base: GrokClient):
        self.base = base
        self.model = base.model

    def structured_complete(self, *, system, user, schema, max_retries=1):
        result, meta = self.base.structured_complete(
            system=system, user=user, schema=schema, max_retries=max_retries,
        )
        MockGrokClient.record(system, user, result,
                              tokens_in=meta.tokens_in, tokens_out=meta.tokens_out)
        return result, meta


def main():
    settings = get_settings()
    assert settings.xai_api_key, "Set XAI_API_KEY"
    db = settings.invoice_processing_db_path
    if not db.exists():
        init_db(db, seed_path=ROOT / "app" / "db" / "seed.yaml", reset=True)
    real = GrokClient(
        api_key=settings.xai_api_key,
        base_url=settings.xai_base_url,
        model=settings.xai_model,
    )
    recorder = RecordingClient(real)
    graph = build_graph(llm=recorder, db_path=db, log_dir=settings.invoice_processing_log_dir)

    invoices = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                      if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
    for p in invoices:
        loaded = load_invoice_file(p)
        state = InvoiceState(
            run_id=f"rec-{p.stem}", source_path=str(p.resolve()), file_format=loaded.format,  # type: ignore[arg-type]
        )
        try:
            final = graph.invoke(state)
            outcome = final.get("decision").outcome if final.get("decision") else final.get("error")
            print(f"recorded {p.name}: {outcome}")
        except Exception as e:
            print(f"FAILED  {p.name}: {e}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it once** (manual, requires API key)

```bash
cd backend && python scripts/record_fixtures.py
```
Expected: ~50-60 JSON files written to `backend/tests/fixtures/grok/` (one per LLM call across 16-20 invoices × 4 calls each, minus dedup by prompt hash).

- [ ] **Step 3: Commit the fixtures**

```bash
git add backend/scripts/record_fixtures.py backend/tests/fixtures/grok/
git commit -m "test: record grok fixtures for all sample invoices"
```

---

### Task 6.3: End-to-end integration test against all invoices

**Files:**
- Create: `backend/tests/expected_outcomes.yaml`
- Create: `backend/tests/test_integration.py`

- [ ] **Step 1: Write `expected_outcomes.yaml`**

```yaml
INV-1001: { outcome: approved }
INV-1002: { outcome: rejected, requires: [qty_exceeds_stock] }
INV-1003: { outcome: rejected, requires: [out_of_stock] }
INV-1004: { outcome: approved }
INV-1004-R1: { outcome: approved }   # invoice_1004_revised.json
INV-1005: { outcome: approved }       # crosses $10K → needs_review or approved acceptable
INV-1006: { outcome: approved }
INV-1007: { outcome: approved }       # $15.5K, crosses $10K threshold
INV-1008: { outcome: rejected, requires: [unknown_item] }
INV-1009: { outcome: rejected, requires_any_of: [missing_vendor, negative_qty] }
INV-1010: { outcome: approved }
INV-1011: { outcome: approved }
INV-1012: { outcome: approved }       # OCR-style typos but valid
INV-1013: { outcome: approved }       # total math error → warn
INV-1014: { outcome: approved }       # EUR currency
INV-1015: { outcome: approved }
INV-1016: { outcome: rejected, requires: [unknown_item] }   # WidgetC unknown

# Some invoices may land in needs_review depending on LLM judgment.
# Add explicit "acceptable_outcomes" when ambiguity is real.
```

- [ ] **Step 2: Write the integration test**

`backend/tests/test_integration.py`:
```python
from pathlib import Path
import pytest
import yaml
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.parsers.file_loader import load_invoice_file
from app.agents.pay import reset_paid_invoices
from tests.fixture_helpers import MockGrokClient

EXPECTED = yaml.safe_load(Path("tests/expected_outcomes.yaml").read_text())
INVOICES_DIR = Path("data/invoices")


def _invoice_key(p: Path) -> str:
    stem = p.stem  # invoice_1004_revised
    parts = stem.split("_")
    if len(parts) >= 3 and parts[-1] == "revised":
        return f"INV-{parts[1]}-R1"
    return f"INV-{parts[1]}"


@pytest.fixture(scope="module")
def graph_and_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("intdb") / "i.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    log_dir = tmp_path_factory.mktemp("ilogs")
    llm = MockGrokClient()
    return build_graph(llm=llm, db_path=db, log_dir=log_dir), db


@pytest.mark.parametrize("path", sorted(
    p for p in INVOICES_DIR.iterdir()
    if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"}
))
def test_invoice_end_to_end(path: Path, graph_and_db):
    graph, _ = graph_and_db
    reset_paid_invoices()
    loaded = load_invoice_file(path)
    state = InvoiceState(
        run_id=f"it-{path.stem}", source_path=str(path.resolve()), file_format=loaded.format,  # type: ignore[arg-type]
    )
    final = graph.invoke(state)
    key = _invoice_key(path)
    expected = EXPECTED.get(key)
    if expected is None:
        pytest.skip(f"no expectation registered for {key}")
    decision = final.get("decision")
    error = final.get("error")
    actual_outcome = decision.outcome if decision else ("unprocessable" if error else "unknown")
    assert actual_outcome == expected["outcome"], (
        f"{key}: expected {expected['outcome']}, got {actual_outcome}; rationale={(decision.rationale if decision else error)!r}"
    )
    if "requires" in expected:
        rules = " ".join(decision.rules_applied) if decision else ""
        for required in expected["requires"]:
            assert required in rules, f"{key}: required rule '{required}' not in {decision.rules_applied}"
    if "requires_any_of" in expected:
        rules = " ".join(decision.rules_applied) if decision else ""
        assert any(r in rules for r in expected["requires_any_of"]), (
            f"{key}: none of {expected['requires_any_of']} found in {decision.rules_applied}"
        )
```

- [ ] **Step 3: Run integration tests**

Run: `cd backend && pytest tests/test_integration.py -v`
Expected: all 16+ parametrized cases pass (or some skip if expectations missing). If a case fails, decide: adjust the `expected_outcomes.yaml` (LLM made a defensible call) or fix prompts/rules (LLM is wrong).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/expected_outcomes.yaml backend/tests/test_integration.py
git commit -m "test: end-to-end integration tests across all sample invoices"
```

---

### Task 6.4: Trace replay tool

**Files:**
- Create: `backend/app/tools/replay.py`
- Create: `backend/tests/test_replay.py`

Per spec §13: `python -m app.tools.replay --run_id=...` reads a jsonl trace and prints a final summary.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_replay.py`:
```python
import json
from pathlib import Path
from app.tools.replay import replay_trace


def test_replay_summarises_final_state(tmp_path: Path, capsys):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "test-run"
    events = [
        {"kind": "node.start", "node": "ingest", "ts": "t1"},
        {"kind": "llm.call", "node": "ingest", "tokens_in": 100, "tokens_out": 50, "latency_ms": 200, "model": "grok-4"},
        {"kind": "node.complete", "node": "ingest", "ts": "t2", "output": {"vendor": "X"}},
        {"kind": "approve.decision", "node": "approve", "output": {
            "outcome": "approved", "rationale": "ok", "rules_applied": ["auto_approve"],
        }},
        {"kind": "run.complete", "ts": "t9", "final_state": {}},
    ]
    (log_dir / f"{run_id}.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    summary = replay_trace(run_id, log_dir=log_dir)
    assert summary["events"] == 5
    assert summary["llm_calls"] == 1
    assert summary["tokens_in"] == 100
    assert summary["tokens_out"] == 50
    assert summary["decision"]["outcome"] == "approved"
    out = capsys.readouterr().out
    assert "approved" in out
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_replay.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/tools/replay.py`**

```python
from __future__ import annotations
import argparse
import json
from pathlib import Path
from app.config import get_settings


def replay_trace(run_id: str, *, log_dir: Path) -> dict:
    path = log_dir / f"{run_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No trace at {path}")
    events = [json.loads(line) for line in path.read_text().splitlines() if line]
    llm = [e for e in events if e.get("kind") == "llm.call"]
    tokens_in = sum(e.get("tokens_in", 0) for e in llm)
    tokens_out = sum(e.get("tokens_out", 0) for e in llm)
    latency_ms = sum(e.get("latency_ms", 0) for e in llm)
    tools = [e for e in events if e.get("kind") == "tool.call"]
    decision = next(
        (e["output"] for e in events if e.get("kind") == "approve.decision"), None,
    )
    summary = {
        "run_id": run_id,
        "events": len(events),
        "llm_calls": len(llm),
        "tool_calls": len(tools),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "decision": decision,
    }
    print(f"Run:      {run_id}")
    print(f"Events:   {len(events)}")
    print(f"LLM:      {len(llm)} calls, {tokens_in} in / {tokens_out} out, {latency_ms}ms total")
    print(f"Tools:    {len(tools)}")
    if decision:
        print(f"Outcome:  {decision.get('outcome')}")
        print(f"Rules:    {', '.join(decision.get('rules_applied', []))}")
        print(f"Rationale:\n  {decision.get('rationale')}")
    else:
        print("Outcome:  (no decision recorded)")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run_id", required=True)
    args = ap.parse_args()
    settings = get_settings()
    replay_trace(args.run_id, log_dir=settings.invoice_processing_log_dir)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_replay.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/replay.py backend/tests/test_replay.py
git commit -m "feat: trace replay tool for post-hoc inspection"
```

---

## Phase 7 — FastAPI + SSE

### Task 7.1: Run registry

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/runs.py`
- Create: `backend/tests/test_runs_registry.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_runs_registry.py`:
```python
import asyncio
from pathlib import Path
from app.api.runs import RunRegistry


def test_registry_creates_and_lists(tmp_path: Path):
    async def _run():
        reg = RunRegistry(log_dir=tmp_path)
        run = reg.create(source_path=str(tmp_path / "x.txt"), file_format="txt")
        assert run.run_id in reg.list_ids()
        assert reg.get(run.run_id) is run
    asyncio.run(_run())


def test_registry_subscribe_receives_events(tmp_path: Path):
    async def _run():
        reg = RunRegistry(log_dir=tmp_path)
        run = reg.create(source_path="x", file_format="txt")
        q = reg.subscribe(run.run_id)
        run.emitter.emit("node.start", node="ingest")
        ev = await asyncio.wait_for(q.get(), timeout=0.5)
        assert ev["kind"] == "node.start"
    asyncio.run(_run())
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_runs_registry.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/api/runs.py`**

```python
from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter


@dataclass
class Run:
    run_id: str
    state: InvoiceState
    emitter: EventEmitter
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: bool = False


class RunRegistry:
    def __init__(self, *, log_dir: Path):
        self.log_dir = log_dir
        self._runs: dict[str, Run] = {}

    def create(self, *, source_path: str, file_format: str) -> Run:
        run_id = uuid.uuid4().hex
        state = InvoiceState(run_id=run_id, source_path=source_path, file_format=file_format)  # type: ignore[arg-type]
        run = Run(run_id=run_id, state=state, emitter=_FanoutEmitter(run_id, state.events, self.log_dir))
        run.emitter._run = run  # type: ignore[attr-defined]
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_ids(self) -> list[str]:
        return list(self._runs.keys())

    def subscribe(self, run_id: str) -> asyncio.Queue:
        run = self._runs[run_id]
        q: asyncio.Queue = asyncio.Queue()
        # replay existing events
        for e in run.state.events:
            q.put_nowait(e)
        run.subscribers.append(q)
        return q

    def mark_done(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.done = True
            for q in run.subscribers:
                q.put_nowait({"kind": "run.complete", "ts": "", "final_state": run.state.model_dump(mode="json")})


class _FanoutEmitter(EventEmitter):
    """Emitter that fans out to every subscriber on its parent Run."""
    _run: Run | None = None

    def emit(self, kind: str, **payload):
        event = super().emit(kind, **payload)
        if self._run is not None:
            for q in self._run.subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        return event
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_runs_registry.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/runs.py backend/tests/test_runs_registry.py
git commit -m "feat: in-memory run registry with SSE subscriber fan-out"
```

---

### Task 7.2: FastAPI app and routes

**Files:**
- Create: `backend/app/api/app.py`
- Create: `backend/app/api/routes.py`
- Create: `backend/app/api/sse.py`
- Create: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py`:
```python
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from tests.fixture_helpers import MockGrokClient
from app.db.init_db import init_db


@pytest.fixture()
def client(tmp_path: Path):
    db = tmp_path / "api.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    app = create_app(llm=MockGrokClient(), db_path=db, log_dir=tmp_path / "logs")
    return TestClient(app)


def test_inventory_endpoint(client):
    resp = client.get("/api/inventory")
    assert resp.status_code == 200
    body = resp.json()
    assert "inventory" in body and "vendors" in body
    items = {row["item"] for row in body["inventory"]}
    assert {"WidgetA", "WidgetB", "GadgetX", "FakeItem"} <= items


def test_create_run_uploads_and_returns_id(client):
    sample = Path("data/invoices/invoice_1001.txt")
    with sample.open("rb") as f:
        resp = client.post("/api/runs", files={"file": (sample.name, f, "text/plain")})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body


def test_list_runs(client):
    sample = Path("data/invoices/invoice_1001.txt")
    with sample.open("rb") as f:
        client.post("/api/runs", files={"file": (sample.name, f, "text/plain")})
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `app/api/sse.py`**

```python
from __future__ import annotations
import asyncio
import json
from sse_starlette.sse import EventSourceResponse


async def event_stream(queue: asyncio.Queue):
    while True:
        event = await queue.get()
        yield {"data": json.dumps(event, default=str)}
        if event.get("kind") == "run.complete" or event.get("kind") == "run.error":
            break


def sse_response(queue: asyncio.Queue):
    return EventSourceResponse(event_stream(queue))
```

- [ ] **Step 4: Implement `app/api/routes.py`**

```python
from __future__ import annotations
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.api.runs import RunRegistry
from app.api.sse import sse_response
from app.graph.builder import build_graph
from app.parsers.file_loader import load_invoice_file


def build_router(*, registry: RunRegistry, db_path: Path, graph) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def _run_graph(run_id: str) -> None:
        run = registry.get(run_id)
        if run is None:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, graph.invoke, run.state)
        except Exception as e:  # noqa: BLE001
            run.emitter.emit("run.error", error=str(e))
        finally:
            registry.mark_done(run_id)

    @router.post("/runs")
    async def create_run(file: UploadFile = File(...)) -> dict[str, str]:
        suffix = Path(file.filename or "upload").suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(await file.read())
            tmp_path = Path(tf.name)
        loaded = load_invoice_file(tmp_path)
        run = registry.create(source_path=str(tmp_path), file_format=loaded.format)
        asyncio.create_task(_run_graph(run.run_id))
        return {"run_id": run.run_id}

    @router.get("/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request):
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        q = registry.subscribe(run_id)
        return sse_response(q)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        return run.state.model_dump(mode="json")

    @router.get("/runs")
    async def list_runs() -> list[dict]:
        return [_summary(registry.get(rid).state) for rid in registry.list_ids()]

    @router.get("/runs/{run_id}/source")
    async def get_source(run_id: str) -> dict[str, str]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        text = Path(run.state.source_path).read_text(encoding="utf-8", errors="replace")
        return {"text": text, "format": run.state.file_format}

    @router.post("/runs/batch")
    async def run_batch() -> dict:
        from app.config import get_settings
        settings = get_settings()
        invoices = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                          if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
        run_ids: list[str] = []
        sem = asyncio.Semaphore(4)

        async def _one(path: Path):
            async with sem:
                loaded = load_invoice_file(path)
                run = registry.create(source_path=str(path), file_format=loaded.format)
                run_ids.append(run.run_id)
                await _run_graph(run.run_id)

        for p in invoices:
            asyncio.create_task(_one(p))
        return {"run_ids": run_ids, "total": len(invoices)}

    @router.get("/inventory")
    async def inventory() -> dict:
        conn = sqlite3.connect(db_path)
        try:
            inv = [
                {"item": row[0], "stock": row[1], "unit_price": row[2]}
                for row in conn.execute("SELECT item, stock, unit_price FROM inventory ORDER BY item")
            ]
            vendors = [
                {"name": row[0], "display_name": row[1], "status": row[2]}
                for row in conn.execute("SELECT name, display_name, status FROM vendors ORDER BY display_name")
            ]
        finally:
            conn.close()
        return {"inventory": inv, "vendors": vendors}

    return router


def _summary(state) -> dict:
    decision = state.decision
    inv = state.invoice
    return {
        "run_id": state.run_id,
        "source_path": state.source_path,
        "invoice_number": inv.invoice_number if inv else None,
        "vendor": inv.vendor if inv else None,
        "total": inv.total if inv else None,
        "outcome": (decision.outcome if decision else ("unprocessable" if state.error else "running")),
        "error": state.error,
    }
```

- [ ] **Step 5: Implement `app/api/app.py`**

```python
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import build_router
from app.api.runs import RunRegistry
from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.llm.grok_client import GrokClient


def create_app(*, llm: GrokClient | None = None, db_path: Path | None = None, log_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    db_path = db_path or settings.invoice_processing_db_path
    log_dir = log_dir or settings.invoice_processing_log_dir
    if not db_path.exists():
        init_db(db_path, seed_path=Path("app/db/seed.yaml"), reset=True)
    llm = llm or GrokClient(
        api_key=settings.xai_api_key, base_url=settings.xai_base_url, model=settings.xai_model,
    )
    registry = RunRegistry(log_dir=log_dir)
    graph = build_graph(llm=llm, db_path=db_path, log_dir=log_dir)
    app = FastAPI(title="Invoice Processing")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(build_router(registry=registry, db_path=db_path, graph=graph))
    return app


app = create_app()
```

- [ ] **Step 6: Run tests**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: 3 passed

- [ ] **Step 7: Manual smoke test**

```bash
cd backend && uvicorn app.api.app:app --port 8000 &
sleep 2
curl -s http://localhost:8000/api/inventory | head
kill %1
```
Expected: JSON with inventory + vendors arrays.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/ backend/tests/test_api.py
git commit -m "feat: fastapi app with run, batch, sse, inventory endpoints"
```

---

## Phase 8 — Frontend scaffold + upload + timeline

### Task 8.1: Vite + React + Tailwind + TS scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`

- [ ] **Step 1: Create the directory and `package.json`**

```bash
mkdir -p frontend/src/{api,store,types,components,pages}
```

`frontend/package.json`:
```json
{
  "name": "invoice-processing-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "zustand": "^4.5.0",
    "@tanstack/react-query": "^5.50.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0"
  }
}
```

- [ ] **Step 2: Write the standard config files**

`frontend/vite.config.ts`:
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

`frontend/tailwind.config.js`:
```javascript
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

`frontend/postcss.config.js`:
```javascript
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Acme AP</title>
  </head>
  <body class="bg-slate-50 text-slate-900">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`frontend/src/main.tsx`:
```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App.tsx";
import "./index.css";

const qc = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
```

`frontend/src/App.tsx`:
```typescript
import Dashboard from "./pages/Dashboard.tsx";
export default function App() { return <Dashboard />; }
```

- [ ] **Step 3: Install dependencies**

```bash
cd frontend && npm install
```

- [ ] **Step 4: Verify dev server boots (manual)**

```bash
cd frontend && npm run dev
```
Open `http://localhost:5173`. Expected: blank page (no errors in console). Stop the server.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/tailwind.config.js frontend/postcss.config.js frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(frontend): vite + react + tailwind scaffold"
```

---

### Task 8.2: TypeScript types mirroring backend contracts

**Files:**
- Create: `frontend/src/types/state.ts`
- Create: `frontend/src/types/events.ts`

- [ ] **Step 1: Write `types/state.ts`**

```typescript
export type Severity = "info" | "warn" | "block";
export type SuspicionSeverity = "low" | "medium" | "high";
export type Outcome = "approved" | "rejected" | "needs_review";

export interface LineItem {
  item: string;
  quantity: number;
  unit_price: number | null;
  notes: string | null;
}

export interface InvoiceData {
  invoice_number: string | null;
  vendor: string | null;
  date: string | null;
  due_date: string | null;
  line_items: LineItem[];
  subtotal: number | null;
  tax_amount: number | null;
  total: number | null;
  currency: string;
  payment_terms: string | null;
  raw_text: string;
}

export interface SuspicionSignal {
  kind: string;
  detail: string;
  severity: SuspicionSeverity;
}

export interface ValidationIssue {
  kind: string;
  item: string | null;
  detail: string;
  severity: Severity;
}

export interface InventoryLookupRow {
  found: boolean;
  item: string;
  stock: number | null;
  unit_price: number | null;
}

export interface ValidationReport {
  issues: ValidationIssue[];
  inventory_lookups: InventoryLookupRow[];
  vendor_lookup: { found: boolean; name: string; status: string | null } | null;
}

export interface Proposal {
  outcome: Outcome;
  rationale: string;
  rules_applied: string[];
  unresolved_concerns: string[];
}

export interface Critique {
  agrees: boolean;
  objections: string[];
  missed_signals: string[];
  rule_misapplications: string[];
}

export interface Decision {
  outcome: Outcome;
  rationale: string;
  rules_applied: string[];
  initial_proposal: Proposal;
  critique: Critique;
  final_proposal: Proposal;
}

export interface InvoiceState {
  run_id: string;
  source_path: string;
  file_format: "txt" | "json" | "csv" | "xml" | "pdf" | "email";
  invoice: InvoiceData | null;
  suspicion_signals: SuspicionSignal[];
  extraction_confidence: number | null;
  validation: ValidationReport | null;
  decision: Decision | null;
  payment_receipt: Record<string, unknown> | null;
  error: string | null;
}
```

- [ ] **Step 2: Write `types/events.ts`**

```typescript
import type { Decision, InvoiceState } from "./state.ts";

export type NodeName = "ingest" | "validate" | "approve" | "pay" | "log";

export type RunEvent =
  | { kind: "node.start"; node: NodeName; ts: string }
  | { kind: "node.complete"; node: NodeName; ts: string; output?: any }
  | { kind: "llm.call"; node: NodeName; ts: string; sub?: string; tokens_in: number; tokens_out: number; latency_ms: number; model: string }
  | { kind: "tool.call"; node: NodeName; ts: string; tool: string; args: any; result: any }
  | { kind: "approve.rules_evaluated"; node: NodeName; ts: string; evaluation: any }
  | { kind: "approve.propose.start"; node: NodeName; ts: string }
  | { kind: "approve.propose.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.critique.start"; node: NodeName; ts: string }
  | { kind: "approve.critique.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.finalize.start"; node: NodeName; ts: string }
  | { kind: "approve.finalize.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.decision"; node: NodeName; ts: string; output: Decision }
  | { kind: "pay.skipped_duplicate"; node: NodeName; ts: string; output: any }
  | { kind: "log.rejection_written"; node: NodeName; ts: string; output: any }
  | { kind: "log.unprocessable_written"; node: NodeName; ts: string; output: any }
  | { kind: "run.complete"; ts: string; final_state: InvoiceState }
  | { kind: "run.error"; ts: string; error: string };
```

- [ ] **Step 3: No tests for plain types**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/
git commit -m "feat(frontend): typescript types mirroring backend"
```

---

### Task 8.3: API client + SSE hook

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/sse.ts`

- [ ] **Step 1: Write `api/client.ts`**

```typescript
import type { InvoiceState } from "../types/state.ts";

export async function uploadInvoice(file: File): Promise<{ run_id: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch("/api/runs", { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`upload failed: ${resp.status}`);
  return resp.json();
}

export async function getInventory(): Promise<{
  inventory: { item: string; stock: number; unit_price: number }[];
  vendors: { name: string; display_name: string; status: string }[];
}> {
  const resp = await fetch("/api/inventory");
  if (!resp.ok) throw new Error("inventory fetch failed");
  return resp.json();
}

export async function listRuns(): Promise<Array<{
  run_id: string;
  source_path: string;
  invoice_number: string | null;
  vendor: string | null;
  total: number | null;
  outcome: string;
  error: string | null;
}>> {
  const resp = await fetch("/api/runs");
  if (!resp.ok) throw new Error("list runs failed");
  return resp.json();
}

export async function getRun(runId: string): Promise<InvoiceState> {
  const resp = await fetch(`/api/runs/${runId}`);
  if (!resp.ok) throw new Error("run fetch failed");
  return resp.json();
}

export async function getSource(runId: string): Promise<{ text: string; format: string }> {
  const resp = await fetch(`/api/runs/${runId}/source`);
  if (!resp.ok) throw new Error("source fetch failed");
  return resp.json();
}

export async function runBatch(): Promise<{ run_ids: string[]; total: number }> {
  const resp = await fetch("/api/runs/batch", { method: "POST" });
  if (!resp.ok) throw new Error("batch failed");
  return resp.json();
}
```

- [ ] **Step 2: Write `api/sse.ts`**

```typescript
import type { RunEvent } from "../types/events.ts";

export function subscribeToRun(runId: string, onEvent: (e: RunEvent) => void): () => void {
  const es = new EventSource(`/api/runs/${runId}/events`);
  es.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as RunEvent;
      onEvent(data);
      if (data.kind === "run.complete" || data.kind === "run.error") {
        es.close();
      }
    } catch (e) {
      console.error("bad event", e, msg.data);
    }
  };
  es.onerror = () => es.close();
  return () => es.close();
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/
git commit -m "feat(frontend): rest client and sse subscriber"
```

---

### Task 8.4: Run store (Zustand) + Dashboard + UploadZone + Timeline

**Files:**
- Create: `frontend/src/store/runStore.ts`
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/components/UploadZone.tsx`
- Create: `frontend/src/components/Timeline.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`

- [ ] **Step 1: Write `store/runStore.ts`**

```typescript
import { create } from "zustand";
import type { RunEvent } from "../types/events.ts";
import type { Decision, InvoiceState } from "../types/state.ts";

type NodeStatus = "pending" | "running" | "complete" | "error";

interface NodeStageView {
  status: NodeStatus;
  startedAt?: string;
  completedAt?: string;
  summary?: any;
}

interface ApproveSubStages {
  propose: NodeStatus;
  critique: NodeStatus;
  finalize: NodeStatus;
}

export interface ActiveRunView {
  runId: string;
  events: RunEvent[];
  stages: Record<"ingest" | "validate" | "approve" | "pay" | "log", NodeStageView>;
  approveSubStages: ApproveSubStages;
  state: Partial<InvoiceState>;
  done: boolean;
}

interface Store {
  activeRunId: string | null;
  runs: Record<string, ActiveRunView>;
  selectRun: (runId: string) => void;
  appendEvent: (runId: string, e: RunEvent) => void;
  initializeRun: (runId: string) => void;
}

const emptyStages = (): ActiveRunView["stages"] => ({
  ingest: { status: "pending" },
  validate: { status: "pending" },
  approve: { status: "pending" },
  pay: { status: "pending" },
  log: { status: "pending" },
});

export const useRunStore = create<Store>((set, get) => ({
  activeRunId: null,
  runs: {},
  selectRun: (runId) => set({ activeRunId: runId }),
  initializeRun: (runId) =>
    set((s) => ({
      activeRunId: runId,
      runs: {
        ...s.runs,
        [runId]: {
          runId,
          events: [],
          stages: emptyStages(),
          approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
          state: { run_id: runId },
          done: false,
        },
      },
    })),
  appendEvent: (runId, e) => {
    const current = get().runs[runId];
    if (!current) {
      get().initializeRun(runId);
    }
    set((s) => {
      const r = { ...(s.runs[runId] ?? { runId, events: [], stages: emptyStages(),
        approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
        state: { run_id: runId }, done: false }) };
      r.events = [...r.events, e];
      if (e.kind === "node.start") r.stages[e.node].status = "running";
      if (e.kind === "node.complete") {
        r.stages[e.node].status = "complete";
        r.stages[e.node].summary = e.output;
      }
      if (e.kind === "approve.propose.start") r.approveSubStages.propose = "running";
      if (e.kind === "approve.propose.complete") r.approveSubStages.propose = "complete";
      if (e.kind === "approve.critique.start") r.approveSubStages.critique = "running";
      if (e.kind === "approve.critique.complete") r.approveSubStages.critique = "complete";
      if (e.kind === "approve.finalize.start") r.approveSubStages.finalize = "running";
      if (e.kind === "approve.finalize.complete") r.approveSubStages.finalize = "complete";
      if (e.kind === "approve.decision") r.state.decision = e.output as Decision;
      if (e.kind === "run.complete") {
        r.state = e.final_state;
        r.done = true;
      }
      if (e.kind === "run.error") r.done = true;
      return { runs: { ...s.runs, [runId]: r } };
    });
  },
}));
```

- [ ] **Step 2: Write `components/StatusBadge.tsx`**

```typescript
type Status = "pending" | "running" | "complete" | "error";

const COLORS: Record<Status, string> = {
  pending: "text-slate-400 border-slate-300",
  running: "text-amber-700 border-amber-400 animate-pulse",
  complete: "text-emerald-700 border-emerald-400",
  error: "text-rose-700 border-rose-400",
};

const ICONS: Record<Status, string> = {
  pending: "○", running: "◐", complete: "●", error: "✗",
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`inline-block w-5 text-center font-mono ${COLORS[status]}`}>{ICONS[status]}</span>;
}
```

- [ ] **Step 3: Write `components/UploadZone.tsx`**

```typescript
import { useCallback, useState } from "react";
import { uploadInvoice } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { useRunStore } from "../store/runStore.ts";

export function UploadZone() {
  const [drag, setDrag] = useState(false);
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);

  const onFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    const { run_id } = await uploadInvoice(file);
    initializeRun(run_id);
    subscribeToRun(run_id, (e) => appendEvent(run_id, e));
  }, [initializeRun, appendEvent]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
      className={`border-2 border-dashed rounded p-6 text-center text-sm cursor-pointer transition
        ${drag ? "border-amber-400 bg-amber-50" : "border-slate-300 bg-white"}`}
      onClick={() => document.getElementById("file-input")?.click()}
    >
      <input id="file-input" type="file" hidden onChange={(e) => onFiles(e.target.files)} />
      Drag an invoice here or click to upload
    </div>
  );
}
```

- [ ] **Step 4: Write `components/Timeline.tsx`**

```typescript
import { useRunStore } from "../store/runStore.ts";
import { StatusBadge } from "./StatusBadge.tsx";

const STAGES = ["ingest", "validate", "approve", "pay", "log"] as const;

export function Timeline() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  if (!run) {
    return <div className="text-slate-400 text-sm p-4">No active run. Upload an invoice to start.</div>;
  }
  return (
    <div className="bg-white border rounded p-4 space-y-2">
      <h2 className="font-semibold">Timeline · {run.runId.slice(0, 8)}</h2>
      <ul className="space-y-1">
        {STAGES.map((s) => {
          const stage = run.stages[s];
          return (
            <li key={s}>
              <div className="flex items-center gap-2 text-sm">
                <StatusBadge status={stage.status} />
                <span className="font-mono uppercase w-20">{s}</span>
                {stage.summary && (
                  <span className="text-slate-500 truncate">
                    {JSON.stringify(stage.summary).slice(0, 80)}
                  </span>
                )}
              </div>
              {s === "approve" && stage.status !== "pending" && (
                <ul className="ml-8 mt-1 space-y-1">
                  {(["propose", "critique", "finalize"] as const).map((sub) => (
                    <li key={sub} className="flex items-center gap-2 text-xs">
                      <StatusBadge status={run.approveSubStages[sub]} />
                      <span className="font-mono">{sub}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Write `pages/Dashboard.tsx`**

```typescript
import { UploadZone } from "../components/UploadZone.tsx";
import { Timeline } from "../components/Timeline.tsx";

export default function Dashboard() {
  return (
    <div className="max-w-5xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Acme AP</h1>
      </header>
      <UploadZone />
      <Timeline />
    </div>
  );
}
```

- [ ] **Step 6: Smoke test (manual)**

In one terminal:
```bash
cd backend && uvicorn app.api.app:app --port 8000
```
In another:
```bash
cd frontend && npm run dev
```
Open `http://localhost:5173`. Drop `data/invoices/invoice_1001.txt`. Watch timeline progress through stages.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/store/ frontend/src/components/UploadZone.tsx frontend/src/components/Timeline.tsx frontend/src/components/StatusBadge.tsx frontend/src/pages/
git commit -m "feat(frontend): run store, upload zone, live timeline"
```

---

## Phase 9 — Remaining UI panels

### Task 9.1: SourceAndExtraction panel

**Files:**
- Create: `frontend/src/components/SourceAndExtraction.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write `SourceAndExtraction.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useRunStore } from "../store/runStore.ts";
import { getSource } from "../api/client.ts";

export function SourceAndExtraction() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const [source, setSource] = useState<string>("");

  useEffect(() => {
    if (!activeId) return;
    getSource(activeId).then((s) => setSource(s.text)).catch(() => setSource(""));
  }, [activeId]);

  if (!run) return null;
  const inv = run.state.invoice;
  const signals = run.state.suspicion_signals ?? [];

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Raw</h3>
        <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-80 overflow-auto">{source || "—"}</pre>
      </div>
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Extracted</h3>
        {inv ? (
          <pre className="text-xs font-mono whitespace-pre-wrap max-h-80 overflow-auto">
            {JSON.stringify(inv, null, 2)}
          </pre>
        ) : <div className="text-slate-400 text-sm">Pending…</div>}
        {signals.length > 0 && (
          <div className="mt-2 space-x-1">
            {signals.map((s, i) => (
              <span key={i} className="inline-block text-xs px-2 py-0.5 rounded bg-rose-100 text-rose-800" title={s.detail}>
                {s.kind} ({s.severity})
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Modify `Dashboard.tsx`**

```typescript
import { UploadZone } from "../components/UploadZone.tsx";
import { Timeline } from "../components/Timeline.tsx";
import { SourceAndExtraction } from "../components/SourceAndExtraction.tsx";

export default function Dashboard() {
  return (
    <div className="max-w-6xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Acme AP</h1>
      </header>
      <UploadZone />
      <Timeline />
      <SourceAndExtraction />
    </div>
  );
}
```

- [ ] **Step 3: Verify in browser (manual)**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SourceAndExtraction.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): source + extraction panel with suspicion chips"
```

---

### Task 9.2: CritiquePanel

**Files:**
- Create: `frontend/src/components/CritiquePanel.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write `CritiquePanel.tsx`**

```typescript
import { useRunStore } from "../store/runStore.ts";

const OUTCOME_COLORS: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-900",
  rejected: "bg-rose-100 text-rose-900",
  needs_review: "bg-amber-100 text-amber-900",
};

export function CritiquePanel() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const decision = run?.state.decision;
  if (!run) return null;
  if (!decision) {
    return <div className="bg-white border rounded p-3 text-slate-400 text-sm">Approval not started yet.</div>;
  }
  const initial = decision.initial_proposal;
  const critique = decision.critique;
  const final = decision.final_proposal;
  return (
    <div className="grid grid-cols-3 gap-3">
      <Cell title="Initial proposal" outcome={initial.outcome} body={initial.rationale} extras={initial.rules_applied} />
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm">Critique</h3>
        <p className="text-xs mt-1">{critique.agrees ? "Agrees" : "Disagrees"}</p>
        {critique.objections.length > 0 && <List label="Objections" items={critique.objections} />}
        {critique.missed_signals.length > 0 && <List label="Missed signals" items={critique.missed_signals} />}
        {critique.rule_misapplications.length > 0 && <List label="Rule issues" items={critique.rule_misapplications} />}
      </div>
      <Cell title="Final" outcome={final.outcome} body={final.rationale} extras={final.rules_applied}
            changed={initial.outcome !== final.outcome} />
    </div>
  );
}

function Cell({ title, outcome, body, extras, changed }: {
  title: string; outcome: string; body: string; extras: string[]; changed?: boolean;
}) {
  return (
    <div className={`bg-white border rounded p-3 ${changed ? "ring-2 ring-amber-300" : ""}`}>
      <h3 className="font-semibold text-sm flex justify-between">
        <span>{title}</span>
        <span className={`text-xs px-2 py-0.5 rounded ${OUTCOME_COLORS[outcome] ?? ""}`}>{outcome}</span>
      </h3>
      <p className="text-xs mt-2 whitespace-pre-wrap">{body}</p>
      {extras.length > 0 && (
        <div className="mt-2 space-x-1">
          {extras.map((r, i) => <span key={i} className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-slate-100">{r}</span>)}
        </div>
      )}
    </div>
  );
}

function List({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="mt-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <ul className="list-disc list-inside text-xs">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}
```

- [ ] **Step 2: Add to Dashboard**

In `pages/Dashboard.tsx`, import `CritiquePanel` and render after `SourceAndExtraction`.

- [ ] **Step 3: Verify (manual)**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CritiquePanel.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): critique side-by-side panel"
```

---

### Task 9.3: DBInspector

**Files:**
- Create: `frontend/src/components/DBInspector.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write `DBInspector.tsx`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { getInventory } from "../api/client.ts";
import { useRunStore } from "../store/runStore.ts";

export function DBInspector() {
  const { data } = useQuery({ queryKey: ["inventory"], queryFn: getInventory });
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const lookups = run?.state.validation?.inventory_lookups ?? [];
  const looked = new Set(lookups.map((l) => l.item));

  if (!data) return <div className="text-slate-400 text-sm">Loading DB…</div>;
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Inventory</h3>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500"><th>Item</th><th>Stock</th><th>Price</th><th></th></tr>
          </thead>
          <tbody>
            {data.inventory.map((row) => (
              <tr key={row.item} className={looked.has(row.item) ? "bg-amber-50" : ""}>
                <td className="font-mono">{row.item}</td>
                <td>{row.stock}</td>
                <td>${row.unit_price.toFixed(2)}</td>
                <td>{looked.has(row.item) && <span className="text-[10px] text-amber-700">looked up</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Vendors</h3>
        <ul className="text-xs space-y-1 max-h-60 overflow-auto">
          {data.vendors.map((v) => (
            <li key={v.name} className="flex justify-between">
              <span>{v.display_name}</span>
              <span className="text-slate-500">{v.status}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add to Dashboard**

- [ ] **Step 3: Verify (manual)**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/DBInspector.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): db inspector with looked-up row highlights"
```

---

### Task 9.4: BatchQueue + "Run all 16" button

**Files:**
- Create: `frontend/src/components/BatchQueue.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/store/runStore.ts` (small extension)

- [ ] **Step 1: Write `BatchQueue.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRuns, runBatch } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { useRunStore } from "../store/runStore.ts";

export function BatchQueue() {
  const { data, refetch } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });
  const selectRun = useRunStore((s) => s.selectRun);
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);
  const activeId = useRunStore((s) => s.activeRunId);
  const [running, setRunning] = useState(false);

  // NOTE: We deliberately do NOT open an SSE connection for every run in a
  // batch. HTTP/1.1 caps at ~6 concurrent connections per origin, so 16 streams
  // would queue and stall. Instead, the batch endpoint triggers all runs
  // server-side; this queue refreshes every 1.5s via `listRuns` polling for
  // outcome updates. SSE only opens lazily for the currently selected run
  // (handled in the row onClick below).
  const handleBatch = async () => {
    setRunning(true);
    await runBatch();
    setRunning(false);
    refetch();
  };

  return (
    <div className="bg-white border rounded p-3 h-full">
      <div className="flex justify-between items-center mb-2">
        <h3 className="font-semibold text-sm">Runs</h3>
        <button
          onClick={handleBatch}
          disabled={running}
          className="text-xs px-2 py-1 rounded bg-slate-900 text-white disabled:opacity-50"
        >
          {running ? "Starting…" : "Run all 16"}
        </button>
      </div>
      <ul className="text-xs space-y-1 max-h-[70vh] overflow-auto">
        {(data ?? []).map((r) => (
          <li
            key={r.run_id}
            onClick={() => selectRun(r.run_id)}
            className={`cursor-pointer flex justify-between gap-2 p-1 rounded
              ${activeId === r.run_id ? "bg-slate-100" : "hover:bg-slate-50"}`}
          >
            <span className="font-mono truncate max-w-[110px]">{r.invoice_number ?? r.run_id.slice(0, 8)}</span>
            <span className="truncate max-w-[80px] text-slate-500">{r.vendor ?? "—"}</span>
            <OutcomeChip outcome={r.outcome} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function OutcomeChip({ outcome }: { outcome: string }) {
  const cls =
    outcome === "approved" ? "bg-emerald-100 text-emerald-800" :
    outcome === "rejected" ? "bg-rose-100 text-rose-800" :
    outcome === "needs_review" ? "bg-amber-100 text-amber-800" :
    outcome === "unprocessable" ? "bg-slate-200 text-slate-700" :
    "bg-slate-100 text-slate-500";
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{outcome}</span>;
}
```

- [ ] **Step 2: Update `Dashboard.tsx` to a two-column layout**

```typescript
import { UploadZone } from "../components/UploadZone.tsx";
import { Timeline } from "../components/Timeline.tsx";
import { SourceAndExtraction } from "../components/SourceAndExtraction.tsx";
import { CritiquePanel } from "../components/CritiquePanel.tsx";
import { DBInspector } from "../components/DBInspector.tsx";
import { BatchQueue } from "../components/BatchQueue.tsx";

export default function Dashboard() {
  return (
    <div className="max-w-7xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Acme AP</h1>
      </header>
      <div className="grid grid-cols-[260px_1fr] gap-4">
        <BatchQueue />
        <div className="space-y-4">
          <UploadZone />
          <Timeline />
          <SourceAndExtraction />
          <CritiquePanel />
          <DBInspector />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Selecting a run from the queue should subscribe to its events**

In `BatchQueue.tsx`, update `onClick` to lazily open the SSE connection (only when the user picks a row) and always switch the active run. This is the consumer side of the "no fan-out subscriptions" rule from `handleBatch`:

```typescript
const runs = useRunStore((s) => s.runs);

// inside the li:
onClick={() => {
  if (!runs[r.run_id]) {
    initializeRun(r.run_id);
    subscribeToRun(r.run_id, (e) => appendEvent(r.run_id, e));
  }
  selectRun(r.run_id);
}}
```

Because the run's events are appended into state.events on the server (via the event emitter) before any SSE subscriber connects, the registry replays them on connect (`RunRegistry.subscribe` already does this). So opening SSE late still produces a fully-populated timeline.

- [ ] **Step 4: Smoke test full flow (manual)**

Reload the browser. Click "Run all 16" — queue populates, click each to inspect. Watch timeline, critique, and DB inspector update for each.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BatchQueue.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): batch queue with run-all-16"
```

---

## Phase 10 — Adversarial invoices, README, polish

### Task 10.1: Author 5 adversarial invoices

**Files:**
- Create: `backend/data/adversarial/invoice_9001.txt` through `invoice_9005.txt`
- Modify: `backend/tests/expected_outcomes.yaml`

Each invoice is a small text/JSON file targeting one edge of behavior. Author them as instructed in spec §13.

- [ ] **Step 1: Create `invoice_9001.txt`** — extraction confidence boundary

```
INV0ICE   <-- "I" replaced with zero in header

Vendor: Atlas Industrial Supply
Invoice Number: INV-9OO1   <-- letter O in two places
Date: 2026-O2-O3
Due Date: 2026-03-03

Items:
  Widget A    qty: 5     unit price: $250

Total: $1,250

Payment Terms: Net 30
```

- [ ] **Step 2: Create `invoice_9002.txt`** — duplicate invoice number with different amount

```
INVOICE

Vendor: Widgets Inc.
Invoice Number: INV-1001
Date: 2026-02-15
Due Date: 2026-03-01

Items:
  WidgetA    qty: 5    unit price: $250.00

Total Amount: $1,250.00

Payment Terms: Net 15
Notes: Submitted again with different amount than original.
```

- [ ] **Step 3: Create `invoice_9003.json`** — subtotal/total math off

```json
{
  "invoice_number": "INV-9003",
  "vendor": { "name": "Precision Parts Ltd." },
  "date": "2026-02-10",
  "due_date": "2026-03-10",
  "line_items": [
    {"item": "WidgetA", "quantity": 4, "unit_price": 250.00}
  ],
  "subtotal": 1000.00,
  "tax_rate": 0.05,
  "tax_amount": 50.00,
  "total": 1500.00,
  "currency": "USD",
  "payment_terms": "Net 30"
}
```

- [ ] **Step 4: Create `invoice_9004.xml`** — EUR multi-currency

```xml
<?xml version="1.0" encoding="UTF-8"?>
<invoice>
  <header>
    <invoice_number>INV-9004</invoice_number>
    <vendor>TechParts International</vendor>
    <date>2026-02-08</date>
    <due_date>2026-03-08</due_date>
    <currency>EUR</currency>
  </header>
  <line_items>
    <item><name>WidgetA</name><quantity>4</quantity><unit_price>225.00</unit_price></item>
  </line_items>
  <totals><total>900.00</total></totals>
</invoice>
```

- [ ] **Step 5: Create `invoice_9005.txt`** — 50 line items

Generate programmatically:
```bash
cat > backend/data/adversarial/invoice_9005.txt <<'EOF'
INVOICE
Vendor: Atlas Industrial Supply
Invoice Number: INV-9005
Date: 2026-02-12
Due Date: 2026-04-12

Items:
EOF
for i in $(seq 1 50); do
  echo "  WidgetA    qty: 1    unit price: \$250.00" >> backend/data/adversarial/invoice_9005.txt
done
echo "" >> backend/data/adversarial/invoice_9005.txt
echo "Total Amount: \$12,500.00" >> backend/data/adversarial/invoice_9005.txt
echo "Payment Terms: Net 60" >> backend/data/adversarial/invoice_9005.txt
```

- [ ] **Step 6: Copy adversarial invoices into the main invoices dir**

The batch endpoint and CLI `--batch` mode both iterate `INVOICE_PROCESSING_INVOICES_DIR`. Copy (not symlink, so the originals remain in `adversarial/` for clarity in version control):

```bash
cp backend/data/adversarial/invoice_9001.txt backend/data/invoices/
cp backend/data/adversarial/invoice_9002.txt backend/data/invoices/
cp backend/data/adversarial/invoice_9003.json backend/data/invoices/
cp backend/data/adversarial/invoice_9004.xml backend/data/invoices/
cp backend/data/adversarial/invoice_9005.txt backend/data/invoices/
```

- [ ] **Step 7: Append expectations to `expected_outcomes.yaml`**

```yaml
INV-9001: { outcome: needs_review }       # OCR-style ambiguity
INV-9002: { outcome: approved }            # duplicate not enforced (documented gap)
INV-9003: { outcome: approved, requires: [total_math_error] }
INV-9004: { outcome: needs_review }       # EUR; insufficient info to convert
INV-9005: { outcome: rejected, requires: [qty_exceeds_stock] }  # 50 > 15 stock
```

- [ ] **Step 8: Re-record fixtures (live LLM) and run integration tests**

```bash
cd backend && make record-fixtures && make test
```

- [ ] **Step 9: Commit**

```bash
git add backend/data/adversarial/ backend/data/invoices/ backend/tests/expected_outcomes.yaml backend/tests/fixtures/grok/
git commit -m "test: 5 adversarial invoices covering edge cases"
```

---

### Task 10.2: README + demo script

**Files:**
- Modify: `README.md` (currently a stub)

- [ ] **Step 1: Write the README**

Replace `README.md` content with:

```markdown
# Acme AP — Invoice Processing Automation

A working multi-agent prototype that ingests invoices in six formats (PDF, TXT, JSON, CSV, XML, email), validates them against an inventory database, runs an approver with a peer-critique loop, and pays approved invoices or logs rejections — end-to-end in seconds, with the full reasoning trace visible in a web UI.

## Why this matters

Acme Corp's manual workflow loses $2M/year:

- **30% error rate.** Six classes of error are now caught automatically: missing vendors, negative quantities, unknown items, out-of-stock items, overstock requests, and price drift. A propose-critique-finalize loop catches what a single LLM pass would miss.
- **5-day delays.** Each invoice resolves in seconds; the "Run all 16" button processes the entire sample backlog while you watch.
- **Frustrated stakeholders.** Every decision carries a written rationale tied to named rules. AP, vendors, and the VP see the same story.

## Quick start

```bash
make install           # one-time
export XAI_API_KEY=... # see .env.example
make seed              # creates data/inventory.db from seed.yaml
make demo              # runs all 16 sample invoices via CLI
```

For the UI:

```bash
make dev               # FastAPI on :8000
cd frontend && npm install && npm run dev    # React on :5173
```

Open `http://localhost:5173`, drop any file from `data/invoices/`, watch the agents work.

## Architecture

LangGraph state machine with four agent nodes:

```
ingest → validate → approve → pay   (or → log on reject/needs_review)
```

- **Ingest** — one Grok call per invoice with Pydantic structured output; retries once on validation failure.
- **Validate** — deterministic SQL checks against inventory and approved-vendors tables. Eight failure modes.
- **Approve** — three sequential Grok calls: proposer, adversarial critic, finalizer. A rule engine (`rules.yaml`) provides hard blocks and gate thresholds; the LLM cannot override hard blocks.
- **Pay / Log** — mock payment API or structured rejection log.

Full design: [`docs/superpowers/specs/2026-05-13-invoice-processing-design.md`](docs/superpowers/specs/2026-05-13-invoice-processing-design.md).

## What's in the UI

- **Timeline** — live agent status with per-pass detail in the approver
- **Source / Extracted** — original file alongside the structured extraction; suspicion signals as red chips
- **Critique view** — initial proposal vs. critic vs. final, with changes highlighted
- **DB Inspector** — inventory and vendor tables; rows touched by the current run are highlighted
- **Batch queue** — every run with outcome chips, one click to inspect

## Demo script (3 minutes)

1. **INV-1001** (clean approve). Drop the file. Show: timeline fills in green; critique agrees; payment receipt appears. The whole run took ~5s.
2. **INV-1003** (fraud). Show: suspicion chips light up (urgency, wire-transfer demand, "yesterday" due date); validator flags `out_of_stock` + `unknown_vendor`; rule engine forces rejection; rationale cites all three rules.
3. **INV-1012** (OCR typos). Show: extraction succeeds despite "Widget A" vs "WidgetA", `26-Jan-2O26`, `$3,500.O0`. The validator still finds the right inventory rows because we normalize.
4. **"Run all 16"**. Watch the queue fill in seconds. Click through to a couple to highlight different outcomes.

## Testing

```bash
make test                        # unit + golden integration (mocked LLM, deterministic)
RUN_LIVE_TESTS=1 make test       # also runs the live-LLM smoke test
```

Fixtures are recorded with `make record-fixtures` (requires an API key) and committed.

## Repository

```
backend/  — python + langgraph + fastapi
frontend/ — vite + react + tailwind + zustand
docs/     — design spec + this plan
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: project readme with business framing + demo script"
```

---

### Task 10.3: Lint, typecheck, final pass

- [ ] **Step 1: Run lint**

```bash
cd backend && make lint
```
Fix any reported issues.

- [ ] **Step 2: Run typecheck**

```bash
cd backend && make typecheck
```
Fix any reported issues. `mypy --strict` will be strict — annotate where needed.

- [ ] **Step 3: Run full test suite**

```bash
cd backend && make test
```
All tests must pass (live smoke can skip if no API key).

- [ ] **Step 4: Build frontend**

```bash
cd frontend && npm run build
```
Should succeed without TS errors.

- [ ] **Step 5: Final manual run**

End-to-end: `make dev`, `npm run dev`, demo each scenario from the README demo script.

- [ ] **Step 6: Commit any lint/type fixes**

```bash
git add -A
git commit -m "chore: lint, typecheck, polish"
```

---

## Done

At this point the system passes all checkpoints from spec §15 (Evaluation-criterion crosswalk). What's shipped:

- CLI matching the README contract
- 4-stage LangGraph with hard-block enforcement and propose-critique-finalize
- 21 sample + adversarial invoices, deterministic golden tests, opt-in live smoke
- FastAPI + SSE backend with batch and replay-capable trace files
- React UI with four panels and a working batch demo
- README that leads with business framing and a 3-minute demo script
