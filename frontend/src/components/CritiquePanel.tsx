import { useRunStore } from "../store/runStore.ts";

const OUTCOME_COLORS: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-900",
  rejected: "bg-rose-100 text-rose-900",
  needs_review: "bg-amber-100 text-amber-900",
};

export function CritiquePanel() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const decision = run?.state.decision;
  if (!run) return null;
  if (!decision) {
    return <div className="bg-white border rounded p-3 text-slate-400 text-sm">Approval not started yet.</div>;
  }
  const initial = decision.initial_proposal;
  const critique = decision.critique;
  const final = decision.final_proposal;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <Cell title="Initial proposal" outcome={initial.outcome} body={initial.rationale} extras={initial.rules_applied} />
        <div className="bg-white border rounded p-3">
          <h3 className="font-semibold text-sm">Critique</h3>
          <p className="text-xs mt-1">{critique.agrees ? "Agrees" : "Disagrees"}</p>
          {critique.objections.length > 0 && <List label="Objections" items={critique.objections} />}
          {critique.missed_signals.length > 0 && <List label="Missed signals" items={critique.missed_signals} />}
          {critique.rule_misapplications.length > 0 && <List label="Rule issues" items={critique.rule_misapplications} />}
        </div>
        <Cell title="Final" outcome={final.outcome} body={final.rationale} extras={final.rules_applied}
              changed={initial.outcome !== final.outcome} />
      </div>
      {decision.tool_calls.length > 0 && (
        <div className="bg-white border rounded p-3">
          <h3 className="font-semibold text-sm mb-2">Investigation tool calls</h3>
          <ul className="space-y-1">
            {decision.tool_calls.map((tc, i) => (
              <li key={i} className="text-xs font-mono bg-slate-50 p-2 rounded">
                <span className="text-purple-700">{tc.tool}</span>(
                {JSON.stringify(tc.arguments)}) →{" "}
                <span className="text-slate-700">{JSON.stringify(tc.result)}</span>
                <span className="text-slate-400 ml-2">({tc.latency_ms}ms)</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Cell({ title, outcome, body, extras, changed }: {
  title: string; outcome: string; body: string; extras: string[]; changed?: boolean;
}) {
  return (
    <div className={`bg-white border rounded p-3 ${changed ? "ring-2 ring-amber-300" : ""}`}>
      <h3 className="font-semibold text-sm flex justify-between">
        <span>{title}</span>
        <span className={`text-xs px-2 py-0.5 rounded ${OUTCOME_COLORS[outcome] ?? ""}`}>{outcome}</span>
      </h3>
      <p className="text-xs mt-2 whitespace-pre-wrap">{body}</p>
      {extras.length > 0 && (
        <div className="mt-2 space-x-1">
          {extras.map((r, i) => <span key={i} className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-slate-100">{r}</span>)}
        </div>
      )}
    </div>
  );
}

function List({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="mt-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <ul className="list-disc list-inside text-xs">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}
