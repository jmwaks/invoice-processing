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
