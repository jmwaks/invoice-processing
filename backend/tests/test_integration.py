from pathlib import Path
import pytest
import yaml
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.parsers.file_loader import load_invoice_file
from tests.fixture_helpers import MockGrokClient, FIXTURES_DIR

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED = BACKEND_DIR / "app" / "db" / "seed.yaml"
INVOICES_DIR = BACKEND_DIR / "data" / "invoices"
EXPECTED_FILE = Path(__file__).parent / "expected_outcomes.yaml"
EXPECTED = yaml.safe_load(EXPECTED_FILE.read_text())


def _invoice_key(p: Path) -> str:
    stem = p.stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[-1] == "revised":
        return f"INV-{parts[1]}-R1"
    return f"INV-{parts[1]}"


@pytest.fixture(scope="module")
def graph_and_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("intdb") / "i.db"
    init_db(db, seed_path=SEED, reset=True)
    log_dir = tmp_path_factory.mktemp("ilogs")
    llm = MockGrokClient()
    return build_graph(llm=llm, db_path=db, log_dir=log_dir), db


def _has_any_fixtures() -> bool:
    return FIXTURES_DIR.exists() and any(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize("path", sorted(
    p for p in INVOICES_DIR.iterdir()
    if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"}
))
def test_invoice_end_to_end(path: Path, graph_and_db):
    if not _has_any_fixtures():
        pytest.skip("no recorded fixtures — run scripts/record_fixtures.py first")
    graph, _ = graph_and_db
    loaded = load_invoice_file(path)
    state = InvoiceState(
        run_id=f"it-{path.stem}", source_path=str(path.resolve()),
        file_format=loaded.format,  # type: ignore[arg-type]
    )
    try:
        final = graph.invoke(state)
    except FileNotFoundError as e:
        pytest.skip(f"missing fixture for {path.name}: {e}")
    key = _invoice_key(path)
    expected = EXPECTED.get(key)
    if expected is None:
        pytest.skip(f"no expectation registered for {key}")
    decision = final.get("decision")
    error = final.get("error")
    actual_outcome = decision.outcome if decision else ("unprocessable" if error else "unknown")
    assert actual_outcome == expected["outcome"], (
        f"{key}: expected {expected['outcome']}, got {actual_outcome}; "
        f"rationale={(decision.rationale if decision else error)!r}"
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
