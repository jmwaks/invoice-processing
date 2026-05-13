import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../api/client.ts";
import { BatchHeader } from "../components/batch/BatchHeader.tsx";
import { BatchTable } from "../components/batch/BatchTable.tsx";
import { EmptyState } from "../components/batch/EmptyState.tsx";
import { LeftRail } from "../components/layout/LeftRail.tsx";

export function BatchPage() {
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });
  const isEmpty = runs !== undefined && runs.length === 0;

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        {isEmpty ? (
          <EmptyState />
        ) : (
          <>
            <BatchHeader />
            <BatchTable />
          </>
        )}
      </main>
    </div>
  );
}
