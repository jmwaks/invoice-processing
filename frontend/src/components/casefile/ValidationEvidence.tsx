import type { ValidationReport } from "../../types/state.ts";
import { AlertTriangle, CheckCircle2, ScrollText, XCircle } from "../common/Icons.tsx";

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "block") return <XCircle size={14} className="text-rose-600" />;
  if (severity === "warn") return <AlertTriangle size={14} className="text-amber-500" />;
  return <CheckCircle2 size={14} className="text-emerald-600" />;
}

export function ValidationEvidence({ report }: { report: ValidationReport | null }) {
  if (!report) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
          <ScrollText size={18} className="text-slate-400" />
          Validation evidence
        </h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
        <ScrollText size={18} className="text-slate-400" />
        Validation evidence
      </h3>
      <table className="w-full text-sm">
        <tbody>
          {report.vendor_lookup && (
            <tr className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">vendor.lookup</td>
              <td className="py-2 pr-3 font-mono">{report.vendor_lookup.name}</td>
              <td className="py-2 pr-3 text-slate-600">
                {report.vendor_lookup.found
                  ? `status: ${report.vendor_lookup.status}`
                  : "not found"}
              </td>
              <td className="py-2 text-right">
                {report.vendor_lookup.found && report.vendor_lookup.status === "approved" ? (
                  <CheckCircle2 size={14} className="text-emerald-600 inline" />
                ) : (
                  <XCircle size={14} className="text-rose-600 inline" />
                )}
              </td>
            </tr>
          )}
          {report.inventory_lookups.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">inventory.find</td>
              <td className="py-2 pr-3 font-mono">{row.item}</td>
              <td className="py-2 pr-3 text-slate-600">
                {row.found
                  ? `stock: ${row.stock}${row.unit_price !== null ? ` · $${row.unit_price.toFixed(2)}` : ""}`
                  : "not found"}
              </td>
              <td className="py-2 text-right">
                {row.found ? (
                  <CheckCircle2 size={14} className="text-emerald-600 inline" />
                ) : (
                  <XCircle size={14} className="text-rose-600 inline" />
                )}
              </td>
            </tr>
          ))}
          {report.issues.map((iss, i) => (
            <tr key={`iss-${i}`} className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">issue.{iss.kind}</td>
              <td className="py-2 pr-3 font-mono">{iss.item ?? "—"}</td>
              <td className="py-2 pr-3 text-slate-600">{iss.detail}</td>
              <td className="py-2 text-right">
                <SeverityIcon severity={iss.severity} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
