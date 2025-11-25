"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchBakeries,
  type Bakery,
  BAKERY_UPDATED_EVENT,
} from "@/lib/bakeries";

const STORAGE_KEY = "current_bakery_id";

export function BakerySelector() {
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const loadBakeries = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchBakeries();
      setBakeries(data);

      setSelectedId((current) => {
        if (current && data.some((b) => String(b.id) === current)) {
          return current;
        }

        if (data.length === 0) {
          if (typeof window !== "undefined") {
            window.localStorage.removeItem(STORAGE_KEY);
          }
          return "";
        }

        const fallback = String(data[0].id);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, fallback);
        }
        return fallback;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setSelectedId(stored);
      }
    }

    loadBakeries();

    function handleRefresh() {
      loadBakeries();
    }

    if (typeof window !== "undefined") {
      window.addEventListener(BAKERY_UPDATED_EVENT, handleRefresh);
    }

    return () => {
      if (typeof window !== "undefined") {
        window.removeEventListener(BAKERY_UPDATED_EVENT, handleRefresh);
      }
    };
  }, [loadBakeries]);

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
        No bakeries yet — add one to get started.
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
