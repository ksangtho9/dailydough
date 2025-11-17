"use client";

import { useEffect, useState } from "react";
import { fetchBakeries, type Bakery } from "@/lib/bakeries";

const STORAGE_KEY = "current_bakery_id";

export function BakerySelector() {
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let initialId: string | null = null;
    if (typeof window !== "undefined") {
      initialId = window.localStorage.getItem(STORAGE_KEY);
    }

    async function load() {
      try {
        setLoading(true);
        const data = await fetchBakeries();
        setBakeries(data);

        if (data.length > 0) {
          const idToUse =
            initialId && data.some((b) => b.id === Number(initialId))
              ? initialId
              : String(data[0].id);

          setSelectedId(idToUse);
          if (typeof window !== "undefined") {
            window.localStorage.setItem(STORAGE_KEY, idToUse);
          }
        }
      } catch (err) {
        console.error(err);
        setError("Failed to load bakeries");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setSelectedId(val);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, val);
    }
  }

  if (loading) {
    return (
      <div className="px-4 py-2 text-xs text-slate-500">
        Loading bakeries…
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-4 py-2 text-xs text-red-600">
        {error}
      </div>
    );
  }

  if (!bakeries.length) {
    return (
      <div className="px-4 py-2 text-xs text-slate-500">
        No bakeries found.
      </div>
    );
  }

  return (
    <div className="px-4 py-3 border-b">
      <label className="block text-xs font-medium text-slate-600 mb-1">
        Current bakery
      </label>
      <select
        value={selectedId}
        onChange={handleChange}
        className="w-full rounded-lg border px-2 py-1 text-xs"
      >
        {bakeries.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name} (#{b.id})
          </option>
        ))}
      </select>
    </div>
  );
}
