import type { InvoiceState } from "../../types/state.ts";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

const fmtUSD = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export function HeroCard({ state }: { state: Partial<InvoiceState> }) {
  const inv = state.invoice;
  const decision = state.decision;
  const outcome = decision?.outcome ?? (state.error ? "unprocessable" : "running");

  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-6 mb-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Invoice</div>
          <h1 className="text-xl font-semibold">
            {inv?.invoice_number ?? "—"}
            {inv?.vendor && (
              <span className="text-slate-500 font-normal"> · {inv.vendor}</span>
            )}
          </h1>
        </div>
        <OutcomeChip outcome={outcome} large />
      </div>
      <div className="mt-4 flex items-baseline gap-3">
        <span className="font-mono text-3xl font-semibold leading-none">
          {fmtUSD(inv?.total ?? null)}
        </span>
        <span className="text-xs text-slate-500">
          {inv?.date ? `dated ${inv.date}` : ""}
        </span>
      </div>
    </div>
  );
}
