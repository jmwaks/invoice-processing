import type { ReactNode } from "react";
import { ToastContainer } from "../common/ToastContainer.tsx";
import { MetricsBand } from "./MetricsBand.tsx";
import { TopBar } from "./TopBar.tsx";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-7xl mx-auto p-6">
        <TopBar />
        <MetricsBand />
        {children}
      </div>
      <ToastContainer />
    </div>
  );
}
