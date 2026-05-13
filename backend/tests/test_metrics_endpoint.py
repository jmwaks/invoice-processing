from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_endpoint_empty_state(api_client: TestClient):
    resp = api_client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 0
    assert body["approved_count"] == 0
    assert body["rejected_count"] == 0
    assert body["needs_review_count"] == 0
    assert body["unprocessable_count"] == 0
    assert body["total_dollars_approved"] == 0.0
    assert body["simulated_dollars_saved"] == 0.0
    assert body["avg_run_seconds"] is None
    assert body["manual_cost_per_invoice_usd"] == 12.0


def test_metrics_endpoint_aggregates_runs(api_client: TestClient):
    import datetime as dt
    from app.graph.state import Decision, Proposal, Critique, InvoiceData, LineItem

    registry = api_client.app.state.registry

    proposal = Proposal(outcome="approved", rationale="r", rules_applied=[], unresolved_concerns=[])
    critique = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    approved_decision = Decision(
        outcome="approved", rationale="ok", rules_applied=["auto_approve"],
        initial_proposal=proposal, critique=critique, final_proposal=proposal,
    )
    rejected_proposal = Proposal(outcome="rejected", rationale="bad", rules_applied=[], unresolved_concerns=[])
    rejected_decision = Decision(
        outcome="rejected", rationale="bad", rules_applied=["unknown_vendor"],
        initial_proposal=rejected_proposal, critique=critique, final_proposal=rejected_proposal,
    )

    r1 = registry.create(source_path="/tmp/a.txt", file_format="txt")
    r1.state.invoice = InvoiceData(
        invoice_number="A", vendor="V", date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=1000.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    r1.state.decision = approved_decision
    r1.created_at = dt.datetime(2026, 5, 13, 12, 0, 0, tzinfo=dt.UTC)
    r1.completed_at = dt.datetime(2026, 5, 13, 12, 0, 4, tzinfo=dt.UTC)

    r2 = registry.create(source_path="/tmp/b.txt", file_format="txt")
    r2.state.decision = rejected_decision
    r2.created_at = dt.datetime(2026, 5, 13, 12, 1, 0, tzinfo=dt.UTC)
    r2.completed_at = dt.datetime(2026, 5, 13, 12, 1, 6, tzinfo=dt.UTC)

    resp = api_client.get("/api/metrics")
    body = resp.json()
    assert body["total_runs"] == 2
    assert body["approved_count"] == 1
    assert body["rejected_count"] == 1
    assert body["total_dollars_approved"] == 1000.0
    # 2 invoices × $12 manual cost
    assert body["simulated_dollars_saved"] == 24.0
    # Avg of (4s, 6s) = 5s
    assert body["avg_run_seconds"] == 5.0
