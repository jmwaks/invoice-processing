from __future__ import annotations

import json
import logging

from app.graph.state import (
    Critique,
    Decision,
    InvoiceState,
    Proposal,
)
from app.llm.grok_client import CallMeta, GrokClient
from app.logging_.event_emitter import EventEmitter
from app.rules.engine import RuleEvaluation, evaluate_rules

_logger = logging.getLogger(__name__)

PROPOSE_SYSTEM = """You are an accounts payable approver at Acme Corp.

Given the invoice data, validation report, suspicion signals, extraction confidence,
and rule-engine evaluation, decide: approved | rejected | needs_review.

Rules to apply (verbatim):
- If the rule engine reports any hard_blocks, the outcome MUST be 'rejected'
  — explain which blocks and why.
- If auto_approve is true (all gates green), approve and cite "auto_approve".
- If scrutiny is required, weigh the validation warnings and suspicion signals;
  rejected only for clear cause, needs_review for genuine ambiguity,
  approved only with explicit reasoning.

Cite every rule you apply by name. Be concise — 2-4 sentences of rationale max.

Return JSON: {
  "outcome": "...", "rationale": "...",
  "rules_applied": [...], "unresolved_concerns": [...]
}
"""

CRITIQUE_SYSTEM = """You are an adversarial reviewer of an AP approver's decision.

Look for:
- Missed red flags in suspicion_signals or raw invoice text
- Rules cited but applied incorrectly
- Low extraction confidence the approver glossed over
- Unwarranted approval of borderline cases
- Unwarranted rejection where the data supports approval

If you agree, say so plainly — do not manufacture objections.

Return JSON: {
  "agrees": bool, "objections": [...],
  "missed_signals": [...], "rule_misapplications": [...]
}
"""

FINALIZE_SYSTEM = """You are the AP approver finalizing your decision after a peer critique.

If the critique raises valid points, revise. If not, explain why you stand by the original.

Return JSON: {
  "outcome": "...", "rationale": "...",
  "rules_applied": [...], "unresolved_concerns": [...]
}
"""


def _emit_llm(emitter: EventEmitter, sub: str, meta: CallMeta) -> None:
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


def _run_propose(llm: GrokClient, emitter: EventEmitter, context: str) -> tuple[Proposal, object]:
    emitter.emit("approve.propose.start", node="approve")
    proposal, meta = llm.structured_complete(
        system=PROPOSE_SYSTEM, user=context, schema=Proposal,
    )
    _emit_llm(emitter, "propose", meta)
    emitter.emit("approve.propose.complete", node="approve", output=proposal.model_dump())
    return proposal, meta


def _run_critique(
    llm: GrokClient, emitter: EventEmitter, context: str,
    proposal: Proposal, raw_text: str | None,
) -> tuple[Critique, bool]:
    """Returns (critique, forced_review)."""
    critique_user = context + "\n\nApprover proposal:\n" + proposal.model_dump_json(indent=2)
    if raw_text:
        critique_user += "\n\nRaw invoice text:\n" + raw_text
    emitter.emit("approve.critique.start", node="approve")
    try:
        critique, meta = llm.structured_complete(
            system=CRITIQUE_SYSTEM, user=critique_user, schema=Critique,
        )
        _emit_llm(emitter, "critique", meta)
        emitter.emit("approve.critique.complete", node="approve", output=critique.model_dump())
        return critique, False
    except Exception as e:
        _logger.exception("approve: critique pass failed")
        emitter.emit("approve.critique.complete", node="approve", output={"error": str(e)})
        return Critique(
            agrees=False, objections=[f"critique pass failed: {e}"],
            missed_signals=[], rule_misapplications=[],
        ), True


def _run_finalize(
    llm: GrokClient, emitter: EventEmitter, context: str,
    proposal: Proposal, critique: Critique,
) -> Proposal:
    finalize_user = (
        context
        + "\n\nInitial proposal:\n" + proposal.model_dump_json(indent=2)
        + "\n\nCritique:\n" + critique.model_dump_json(indent=2)
    )
    emitter.emit("approve.finalize.start", node="approve")
    final_proposal, meta = llm.structured_complete(
        system=FINALIZE_SYSTEM, user=finalize_user, schema=Proposal,
    )
    _emit_llm(emitter, "finalize", meta)
    emitter.emit("approve.finalize.complete", node="approve", output=final_proposal.model_dump())
    return final_proposal


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
    raw_text = state.invoice.raw_text if state.invoice else None

    proposal, _ = _run_propose(llm, emitter, context)
    critique, forced_review = _run_critique(llm, emitter, context, proposal, raw_text)
    final_proposal = _run_finalize(llm, emitter, context, proposal, critique)

    outcome = final_proposal.outcome
    rules_applied = list(final_proposal.rules_applied)
    rationale = final_proposal.rationale

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
        outcome=outcome, rationale=rationale, rules_applied=rules_applied,
        initial_proposal=proposal, critique=critique, final_proposal=final_proposal,
    )
    emitter.emit("approve.decision", node="approve", output=state.decision.model_dump())
    emitter.emit("node.complete", node="approve", output={"outcome": outcome})
    return state


def route_after_approve(state: InvoiceState) -> str:
    if state.decision is None:
        return "log"
    return "pay" if state.decision.outcome == "approved" else "log"
