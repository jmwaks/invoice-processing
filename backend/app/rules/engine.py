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
        has_block
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
