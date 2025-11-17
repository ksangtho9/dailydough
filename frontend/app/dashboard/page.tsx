"use client";

import { useEffect, useState } from "react";
import {
  fetchBakerySummary,
  type BakerySummary,
} from "@/lib/bakerySummary";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const STORAGE_KEY = "current_bakery_id";

export default function DashboardPage() {
  const [bakeryId, setBakeryId] = useState<number | null>(null);
  const [summary, setSummary] = useState<BakerySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  //
  // 1️⃣ Load bakery ID from localStorage
  //
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const id = Number(stored);
      if (!isNaN(id)) setBakeryId(id);
    }
  }, []);

  //
  // 2️⃣ Whenever bakeryId changes, fetch the summary
  //
  // 2️⃣ Whenever bakeryId changes, fetch the summary
useEffect(() => {
  if (bakeryId === null) return;  // runtime guard

  const id = bakeryId;            // local copy so TS knows it's a number

  async function load() {
    try {
      setLoading(true);
      setError(null);

      const data = await fetchBakerySummary(id); // ✅ id: number
      setSummary(data);
    } catch (err) {
      console.error(err);
      setError("Failed to load dashboard data.");
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }

  load();
}, [bakeryId]);


  //
  // 3️⃣ UI rendering
  //
  return (
    <div className="space-y-6">
      {/* HEADER */}
      <h1 className="text-2xl font-semibold">
        {summary ? `${summary.bakery_name} Dashboard` : "Bakery Dashboard"}
      </h1>

      {bakeryId == null && (
        <p className="text-sm text-slate-600">
          Select a bakery in the sidebar to see its dashboard.
        </p>
      )}

      {bakeryId != null && (
        <p className="text-xs text-slate-500">
          Showing data for bakery ID{" "}
          <span className="font-semibold">{bakeryId}</span>.
        </p>
      )}

      {loading && <p className="text-sm">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {summary && !loading && (
        <>
          {/* 7/30 Days Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">Total units (last 7 days)</p>
              <p className="mt-2 text-3xl font-bold">
                {summary.total_units_last_7_days.toLocaleString()}
              </p>
            </div>

            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">Total units (last 30 days)</p>
              <p className="mt-2 text-3xl font-bold">
                {summary.total_units_last_30_days.toLocaleString()}
              </p>
            </div>
          </div>

          {/* Top Products + Chart */}
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top products list */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <h2 className="text-lg font-semibold mb-3">
                Top 5 products (last 30 days)
              </h2>

              {summary.top_products_last_30_days.length === 0 ? (
                <p className="text-sm text-gray-500">Not enough data yet.</p>
              ) : (
                <ul className="space-y-2">
                  {summary.top_products_last_30_days.map((p, idx) => (
                    <li
                      key={p.product_id}
                      className="flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">#{idx + 1}</span>
                        <span>{p.product_name}</span>
                      </div>
                      <span className="font-medium">
                        {p.units_sold.toLocaleString()} units
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Bar chart */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <h2 className="text-lg font-semibold mb-3">
                Units by top product
              </h2>

              {summary.top_products_last_30_days.length === 0 ? (
                <p className="text-sm text-gray-500">Not enough data yet.</p>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={summary.top_products_last_30_days.map((p) => ({
                        name: p.product_name,
                        units: p.units_sold,
                      }))}
                    >
                      <XAxis dataKey="name" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="units" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
