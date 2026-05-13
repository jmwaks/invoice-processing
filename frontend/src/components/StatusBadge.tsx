type Status = "pending" | "running" | "complete" | "error";

const COLORS: Record<Status, string> = {
  pending: "text-slate-400 border-slate-300",
  running: "text-amber-700 border-amber-400 animate-pulse",
  complete: "text-emerald-700 border-emerald-400",
  error: "text-rose-700 border-rose-400",
};

const ICONS: Record<Status, string> = {
  pending: "○", running: "◐", complete: "●", error: "✗",
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`inline-block w-5 text-center font-mono ${COLORS[status]}`}>{ICONS[status]}</span>;
}
