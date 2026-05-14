import type { Decision, Proposal, ToolCall } from "../../types/state.ts";
import { Wrench } from "../common/Icons.tsx";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

export function AgentReasoning({ decision }: { decision: Decision | null }) {
  if (!decision) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-3">Agent reasoning</h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }
  const changed = decision.initial_proposal.outcome !== decision.final_proposal.outcome;
  // Tool calls live on the decision object. For now we attribute all tool calls
  // to the PROPOSE stage since that's where most tool use happens; if events
  // are needed for finer attribution, extend this to read from run.events.
  return (
    <div className="space-y-4">
      <Card stageLabel="Propose" proposal={decision.initial_proposal} toolCalls={decision.tool_calls} />
      <CritiqueCard critique={decision.critique} />
      <Card stageLabel="Finalize" proposal={decision.final_proposal} highlight={changed} />
    </div>
  );
}

function Card({
  stageLabel,
  proposal,
  toolCalls,
  highlight,
}: {
  stageLabel: string;
  proposal: Proposal;
  toolCalls?: ToolCall[];
  highlight?: boolean;
}) {
  return (
    <div
      className={`bg-white border border-slate-200 rounded-lg p-6 ${highlight ? "ring-2 ring-amber-300" : ""}`}
    >
      <div className="flex items-start justify-between mb-3">
        <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {stageLabel}
        </h4>
        <OutcomeChip outcome={proposal.outcome} />
      </div>
      <p className="text-sm text-slate-800 whitespace-pre-wrap mb-3">{proposal.rationale}</p>
      {proposal.rules_applied.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {proposal.rules_applied.map((r, i) => (
            <span
              key={i}
              className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-700"
            >
              {r}
            </span>
          ))}
        </div>
      )}
      {toolCalls && toolCalls.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-3">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1.5 flex items-center gap-1.5">
            <Wrench size={12} /> Tools consulted
          </div>
          <ul className="space-y-1">
            {toolCalls.map((tc, i) => (
              <li key={i} className="font-mono text-xs text-slate-600">
                {tc.tool}({JSON.stringify(tc.arguments)}) → {JSON.stringify(tc.result)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CritiqueCard({ critique }: { critique: Decision["critique"] }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-start justify-between mb-3">
        <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">Critique</h4>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${critique.agrees ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200"}`}
        >
          {critique.agrees ? "Agrees" : "Disagrees"}
        </span>
      </div>
      {critique.objections.length > 0 && (
        <List label="Objections" items={critique.objections} />
      )}
      {critique.missed_signals.length > 0 && (
        <List label="Missed signals" items={critique.missed_signals} />
      )}
      {critique.rule_misapplications.length > 0 && (
        <List label="Rule issues" items={critique.rule_misapplications} />
      )}
    </div>
  );
}

function List({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="mb-2 last:mb-0">
      <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">{label}</div>
      <ul className="list-disc list-inside text-sm text-slate-800 space-y-0.5">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}
