import json
from pathlib import Path

from app.tools.replay import replay_trace


def test_replay_summarises_final_state(tmp_path: Path, capsys):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    run_id = "test-run"
    events = [
        {"kind": "node.start", "node": "ingest", "ts": "t1"},
        {
            "kind": "llm.call", "node": "ingest",
            "tokens_in": 100, "tokens_out": 50, "latency_ms": 200, "model": "grok-4",
        },
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


def test_replay_tolerates_duplicate_detected_retroactive_event(tmp_path: Path) -> None:
    run_id = "test-run"
    log = tmp_path / f"{run_id}.jsonl"
    log.write_text(
        json.dumps({"kind": "node.start", "node": "ingest"}) + "\n"
        + json.dumps({
            "kind": "duplicate_detected_retroactive",
            "ts": "2026-05-13T12:00:00Z",
            "later_run_id": "later",
            "later_amount": 1250.0,
            "later_invoice_number": "INV-1001",
        }) + "\n"
        + json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "x", "rules_applied": []},
        }) + "\n"
    )
    summary = replay_trace(run_id, log_dir=tmp_path)
    assert summary["events"] == 3
    assert summary["decision"] is not None
    assert summary["decision"]["outcome"] == "approved"
