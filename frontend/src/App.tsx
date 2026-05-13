import { useEffect } from "react";
import { Route, Switch, useRoute } from "wouter";
import { AppShell } from "./components/layout/AppShell.tsx";
import { BatchPage } from "./pages/BatchPage.tsx";
import { CaseFilePage } from "./pages/CaseFilePage.tsx";
import { useRunStore } from "./store/runStore.ts";

function RunRouteSync() {
  const [match, params] = useRoute<{ id: string }>("/runs/:id");
  const setActiveRunId = useRunStore((s) => s.setActiveRunId);
  useEffect(() => {
    setActiveRunId(match && params ? params.id : null);
  }, [match, params?.id, setActiveRunId]);
  return null;
}

export default function App() {
  return (
    <AppShell>
      <RunRouteSync />
      <Switch>
        <Route path="/runs/:id" component={CaseFilePage} />
        <Route component={BatchPage} />
      </Switch>
    </AppShell>
  );
}
