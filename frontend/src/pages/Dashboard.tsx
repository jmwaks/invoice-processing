import { UploadZone } from "../components/UploadZone.tsx";
import { Timeline } from "../components/Timeline.tsx";
import { SourceAndExtraction } from "../components/SourceAndExtraction.tsx";
import { CritiquePanel } from "../components/CritiquePanel.tsx";
import { DBInspector } from "../components/DBInspector.tsx";

export default function Dashboard() {
  return (
    <div className="max-w-6xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Acme AP</h1>
      </header>
      <UploadZone />
      <Timeline />
      <SourceAndExtraction />
      <CritiquePanel />
      <DBInspector />
    </div>
  );
}
