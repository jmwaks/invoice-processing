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
