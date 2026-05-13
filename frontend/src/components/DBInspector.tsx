import { useQuery } from "@tanstack/react-query";
import { getInventory } from "../api/client.ts";
import { useRunStore } from "../store/runStore.ts";

export function DBInspector() {
  const { data } = useQuery({ queryKey: ["inventory"], queryFn: getInventory });
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const lookups = run?.state.validation?.inventory_lookups ?? [];
  const looked = new Set(lookups.map((l) => l.item));

  if (!data) return <div className="text-slate-400 text-sm">Loading DB…</div>;
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Inventory</h3>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500"><th>Item</th><th>Stock</th><th>Price</th><th></th></tr>
          </thead>
          <tbody>
            {data.inventory.map((row) => (
              <tr key={row.item} className={looked.has(row.item) ? "bg-amber-50" : ""}>
                <td className="font-mono">{row.item}</td>
                <td>{row.stock}</td>
                <td>${row.unit_price.toFixed(2)}</td>
                <td>{looked.has(row.item) && <span className="text-[10px] text-amber-700">looked up</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Vendors</h3>
        <ul className="text-xs space-y-1 max-h-60 overflow-auto">
          {data.vendors.map((v) => (
            <li key={v.name} className="flex justify-between">
              <span>{v.display_name}</span>
              <span className="text-slate-500">{v.status}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
