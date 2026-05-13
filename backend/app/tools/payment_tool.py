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
