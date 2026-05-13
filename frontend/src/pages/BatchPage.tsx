import { LeftRail } from "../components/layout/LeftRail.tsx";

export function BatchPage() {
  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          Batch overview (stub)
        </div>
      </main>
    </div>
  );
}
