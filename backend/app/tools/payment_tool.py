from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def mock_payment(*, vendor: str, amount: float, invoice_number: str, run_id: str) -> dict[str, Any]:
    return {
        "status": "success",
        "transaction_id": f"TXN-{invoice_number}-{run_id[:8]}",
        "vendor": vendor,
        "amount": amount,
        "invoice_number": invoice_number,
        "paid_at": datetime.now(UTC).isoformat(),
    }
