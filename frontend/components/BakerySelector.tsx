"use client";

import { useEffect, useState } from "react";
import { fetchBakeries, type Bakery } from "@/lib/bakeries";

const STORAGE_KEY = "current_bakery_id";

export function BakerySelector() {
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let initial = "";

    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) initial = stored;
    }

    async function load() {
      try {
        setLoading(true);
        const data = await fetchBakeries();
        setBakeries(data);

        // If we had a stored id and it still exists, use it
        if (initial && data.some((b) => String(b.id) === initial)) {
          setSelectedId(initial);
        } else if (data.length > 0) {
          // Otherwise default to first bakery and sync storage
          const firstId = String(data[0].id);
          setSelectedId(firstId);
          if (typeof window !== "undefined") {
            window.localStorage.setItem(STORAGE_KEY, firstId);
          }
        }
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  function handleChange(value: string) {
    setSelectedId(value);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, value);
    }
  }

  if (loading) {
    return (
      <p className="text-xs text-slate-500">
        Loading bakeries…
      </p>
    );
  }

  if (bakeries.length === 0) {
    return (
      <p className="text-xs text-slate-500 italic">
        No bakeries yet — add one in the backend for now.
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-slate-600">Current bakery</p>
      <select
        value={selectedId}
        onChange={(e) => handleChange(e.target.value)}
        className="w-full rounded-lg border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-slate-500"
      >
        {bakeries.map((b) => (
          <option key={b.id} value={String(b.id)}>
            {b.name}
          </option>
        ))}
      </select>
    </div>
  );
}
