import type { InvoiceState } from "../../types/state.ts";
import { Receipt } from "../common/Icons.tsx";

export function ActionCard({ state }: { state: Partial<InvoiceState> }) {
  const decision = state.decision;
  const receipt = state.payment_receipt;

  if (state.error) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
          <Receipt size={18} className="text-slate-400" />
          Action
        </h3>
        <p className="text-sm text-slate-700">Could not process — {state.error}</p>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
          <Receipt size={18} className="text-slate-400" />
          Action
        </h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }

  const rulesText = decision.rules_applied.length > 0
    ? decision.rules_applied.join(", ")
    : "—";

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
        <Receipt size={18} className="text-slate-400" />
        Action
      </h3>
      {decision.outcome === "approved" && (
        <p className="text-sm text-slate-800">
          Approved · paid{receipt ? ` · receipt ${String((receipt as any).receipt_id ?? "")}` : ""}
        </p>
      )}
      {decision.outcome === "rejected" && (
        <p className="text-sm text-slate-800">Rejected · logged · reason: {rulesText}</p>
      )}
      {decision.outcome === "needs_review" && (
        <p className="text-sm text-slate-800">Held for review · {rulesText}</p>
      )}
    </div>
  );
}
