import { useToastStore } from "../../store/toastStore.ts";
import { AlertTriangle, CheckCircle2, XCircle } from "./Icons.tsx";

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismissToast = useToastStore((s) => s.dismissToast);

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-start gap-2 px-3 py-2 rounded-lg border shadow-sm bg-white text-sm
            ${t.kind === "error" ? "border-rose-200 text-rose-800" : "border-emerald-200 text-emerald-800"}`}
        >
          {t.kind === "error" ? (
            <AlertTriangle size={16} className="text-rose-600 mt-0.5" />
          ) : (
            <CheckCircle2 size={16} className="text-emerald-600 mt-0.5" />
          )}
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => dismissToast(t.id)}
            className="text-slate-400 hover:text-slate-600"
            aria-label="dismiss"
          >
            <XCircle size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
