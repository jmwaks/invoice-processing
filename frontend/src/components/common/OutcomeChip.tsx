import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "./Icons.tsx";

const STYLES: Record<string, { cls: string; label: string }> = {
  approved: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Approved" },
  rejected: { cls: "bg-rose-50 text-rose-700 border-rose-200", label: "Rejected" },
  needs_review: { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Needs review" },
  unprocessable: { cls: "bg-slate-100 text-slate-600 border-slate-200", label: "Unprocessable" },
  running: { cls: "bg-indigo-50 text-indigo-700 border-indigo-200", label: "Running" },
};

function Icon({ outcome, size }: { outcome: string; size: number }) {
  if (outcome === "approved") return <CheckCircle2 size={size} />;
  if (outcome === "rejected") return <XCircle size={size} />;
  if (outcome === "needs_review") return <AlertTriangle size={size} />;
  if (outcome === "running") return <Loader2 size={size} className="animate-spin" />;
  return <Circle size={size} />;
}

export function OutcomeChip({ outcome, large = false }: { outcome: string; large?: boolean }) {
  const s = STYLES[outcome] ?? { cls: "bg-slate-100 text-slate-600 border-slate-200", label: outcome };
  const padding = large ? "px-3 py-1.5 text-sm" : "px-2 py-0.5 text-xs";
  const iconSize = large ? 16 : 12;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border ${s.cls} ${padding}`}>
      <Icon outcome={outcome} size={iconSize} />
      {s.label}
    </span>
  );
}
