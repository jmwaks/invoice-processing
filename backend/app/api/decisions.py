from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Outcome = Literal["approved", "rejected", "needs_review", "unprocessable"]


class EffectiveOutcome(BaseModel):
    outcome: Outcome
    override_reason: str | None = None
    overridden_at: dt.datetime | None = None
    triggered_by_run_id: str | None = None


def _decision_from_event_log(log_path: Path) -> Outcome:
    if not log_path.exists():
        return "unprocessable"
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == "approve.decision":
            outcome = event.get("output", {}).get("outcome")
            if outcome in ("approved", "rejected", "needs_review"):
                return outcome  # type: ignore[no-any-return]
    return "unprocessable"


def _latest_override(sidecar_path: Path, run_id: str) -> dict[str, object] | None:
    if not sidecar_path.exists():
        return None
    latest: dict[str, object] | None = None
    for line in sidecar_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("run_id") != run_id:
            continue
        latest = row
    return latest


def effective_outcome(
    run_id: str, *, log_dir: Path, base_outcome: Outcome | None = None,
) -> EffectiveOutcome:
    """Returns the effective outcome of a run, applying the latest decision_updates.jsonl
    override on top of the recorded Decision.

    `base_outcome` is the in-memory decision outcome if available (preferred when set);
    if None, falls back to reading approve.decision from the run's jsonl event log.
    """
    if base_outcome is not None:
        base = base_outcome
    else:
        base = _decision_from_event_log(log_dir / f"{run_id}.jsonl")
    override = _latest_override(log_dir / "decision_updates.jsonl", run_id)
    if override is None:
        return EffectiveOutcome(outcome=base)
    return EffectiveOutcome(
        outcome=override["new_outcome"],  # type: ignore[arg-type]
        override_reason=str(override["reason"]),
        overridden_at=dt.datetime.fromisoformat(str(override["updated_at"])),
        triggered_by_run_id=str(override["triggered_by_run_id"]),
    )
