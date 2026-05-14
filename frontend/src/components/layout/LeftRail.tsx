import { useQuery } from "@tanstack/react-query";
import { Link, useRoute } from "wouter";
import { getMetrics, listRuns, type Metrics } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "../common/Icons.tsx";

type RunSummary = Awaited<ReturnType<typeof listRuns>>[number];

const fmtCompactUSD = (n: number) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n)}`;
};

const fmtTotal = (n: number | null) => (n === null ? "—" : fmtCompactUSD(n));

function groupRunsByParent(runs: RunSummary[]): RunSummary[][] {
  // Returns an array of [parent, ...children] groups, in original order.
  const byId = new Map(runs.map((r) => [r.run_id, r] as const));
  const placed = new Set<string>();
  const groups: RunSummary[][] = [];
  for (const r of runs) {
    if (r.parent_run_id && byId.has(r.parent_run_id)) continue;
    const children = runs.filter((c) => c.parent_run_id === r.run_id);
    groups.push([r, ...children]);
    placed.add(r.run_id);
    for (const c of children) placed.add(c.run_id);
  }
  // Append any orphans (children whose parent isn't in the list) at the end.
  for (const r of runs) if (!placed.has(r.run_id)) groups.push([r]);
  return groups;
}

function OutcomeIcon({ outcome }: { outcome: string }) {
  const size = 14;
  if (outcome === "approved") return <CheckCircle2 size={size} className="text-emerald-600" />;
  if (outcome === "rejected") return <XCircle size={size} className="text-rose-600" />;
  if (outcome === "needs_review") return <AlertTriangle size={size} className="text-amber-500" />;
  if (outcome === "running") return <Loader2 size={size} className="text-indigo-600 animate-spin" />;
  return <Circle size={size} className="text-slate-300" />;
}

function RunRow({ run, indent, active }: { run: RunSummary; indent: boolean; active: boolean }) {
  const label = run.invoice_number ?? run.run_id.slice(0, 8);
  return (
    <Link
      href={`/runs/${run.run_id}`}
      className={`flex items-center gap-2 text-sm py-1.5 px-2 rounded relative
        ${active ? "bg-slate-100" : "hover:bg-slate-50"}
        ${indent ? "pl-6" : ""}`}
    >
      {active && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] bg-indigo-600 rounded-r" />
      )}
      <OutcomeIcon outcome={run.outcome} />
      <span className="truncate flex-1">
        {indent && <span className="text-slate-400 mr-1">↳</span>}
        {indent ? "retry" : label}
      </span>
      <span className="font-mono text-xs text-slate-500">{fmtTotal(run.total)}</span>
    </Link>
  );
}

export function LeftRail() {
  const { data: m } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });
  const batch = useRunStore((s) => s.currentBatch);
  const [, params] = useRoute<{ id: string }>("/runs/:id");
  const activeId = params?.id ?? null;

  const doneCount = (() => {
    if (!batch || !runs) return 0;
    const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
    return batch.runIds.filter((rid) => {
      const o = byId.get(rid);
      return o && o !== "running";
    }).length;
  })();

  const groups = runs ? groupRunsByParent(runs) : [];

  return (
    <aside className="w-[280px] shrink-0">
      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Session
        </h2>
        {m && (
          <p className="text-sm text-slate-700">
            {m.total_runs} runs · {m.approved_count} approved ·{" "}
            {fmtCompactUSD(m.total_dollars_approved)} approved
          </p>
        )}
        <Link href="/" className="block mt-3 text-sm text-indigo-600 hover:text-indigo-700">
          ▶ Batch overview
        </Link>
        {batch && (
          <div className="mt-3">
            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-300"
                style={{ width: `${(doneCount / batch.runIds.length) * 100}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {doneCount} / {batch.runIds.length} done
            </p>
          </div>
        )}
      </div>
      <div className="bg-white border border-slate-200 rounded-lg p-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500 px-2 py-1">
          Runs
        </h3>
        <div className="max-h-[60vh] overflow-y-auto">
          {groups.length === 0 ? (
            <p className="text-sm text-slate-400 px-2 py-3">No runs yet.</p>
          ) : (
            groups.flatMap(([parent, ...children]) => [
              <RunRow
                key={parent.run_id}
                run={parent}
                indent={false}
                active={parent.run_id === activeId}
              />,
              ...children.map((c) => (
                <RunRow key={c.run_id} run={c} indent={true} active={c.run_id === activeId} />
              )),
            ])
          )}
        </div>
      </div>
    </aside>
  );
}
