import * as React from "react";
import type { InvoiceData } from "../types/state.ts";
import { retryRun } from "../api/client.ts";

type Props = {
  parentRunId: string;
  invoice: InvoiceData;
  onRetried: (newRunId: string) => void;
};

export function RetryButton({ parentRunId, invoice, onRetried }: Props) {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handle = async () => {
    setPending(true);
    setError(null);
    try {
      const { run_id } = await retryRun(parentRunId, invoice);
      onRetried(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "retry failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handle}
        disabled={pending}
        className="px-3 py-1 bg-slate-700 text-white text-sm rounded hover:bg-slate-800 disabled:opacity-50"
      >
        {pending ? "Retrying…" : "Save & retry"}
      </button>
      {error && <span className="text-sm text-rose-600">{error}</span>}
    </div>
  );
}
