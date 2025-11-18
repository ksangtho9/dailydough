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
const WINDOW_OPTIONS = [7, 30, 90];

export default function DashboardPage() {
  const [bakeryId, setBakeryId] = useState<number | null>(null);
  const [summary, setSummary] = useState<BakerySummary | null>(null);
  const [windowDays, setWindowDays] = useState<number>(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 1️⃣ Load bakery ID from localStorage
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const id = Number(stored);
      if (!isNaN(id)) setBakeryId(id);
    }
  }, []);

  // 2️⃣ Whenever bakeryId or windowDays changes, fetch summary
  useEffect(() => {
    if (bakeryId === null) return;

    const id: number = bakeryId;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const data = await fetchBakerySummary(id, windowDays);
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
  }, [bakeryId, windowDays]);

  const chartData =
    summary?.top_products.map((p) => ({
      name: p.product_name,
      units: p.units_sold,
    })) ?? [];

  // helper for % change card
  const pct = summary?.pct_change_vs_previous ?? null;
  const pctLabel =
    pct === null
      ? "Not enough data"
      : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}% vs previous ${
          summary?.window_days ?? windowDays
        } days`;
  const pctColor =
    pct === null
      ? "text-slate-500"
      : pct > 0
      ? "text-emerald-600"
      : pct < 0
      ? "text-red-600"
      : "text-slate-700";

  return (
    <div className="space-y-6">
      {/* Header + range toggle */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            {summary ? `${summary.bakery_name} Dashboard` : "Bakery Dashboard"}
          </h1>
          {bakeryId != null && (
            <p className="text-xs text-slate-500 mt-1">
              Showing last{" "}
              <span className="font-semibold">
                {summary?.window_days ?? windowDays}
              </span>{" "}
              days of sales.
            </p>
          )}
          {bakeryId == null && (
            <p className="text-sm text-slate-600">
              Select a bakery in the sidebar to see its dashboard.
            </p>
          )}
        </div>

        {/* Date range toggle */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Range:</span>
          <div className="inline-flex rounded-full border bg-white p-1">
            {WINDOW_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setWindowDays(d)}
                className={
                  "px-3 py-1 rounded-full text-xs " +
                  (windowDays === d
                    ? "bg-slate-900 text-white"
                    : "text-slate-700 hover:bg-slate-100")
                }
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && <p className="text-sm">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {summary && !loading && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">
            {/* Total units */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">
                Total units (last {summary.window_days} days)
              </p>
              <p className="mt-2 text-3xl font-bold">
                {summary.total_units.toLocaleString()}
              </p>
            </div>

            {/* As of */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">As of</p>
              <p className="mt-2 text-xl font-medium">
                {new Date(summary.as_of).toLocaleDateString()}
              </p>
            </div>

            {/* % change vs previous */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">
                Change vs previous {summary.window_days} days
              </p>
              <p className={`mt-2 text-xl font-semibold ${pctColor}`}>
                {pct === null ? "—" : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`}
              </p>
              <p className="text-xs text-slate-500 mt-1">{pctLabel}</p>
            </div>
          </div>

          {/* Top products + chart */}
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top products list */}
            <div className="rounded-2xl border p-4 shadow-sm">
              <h2 className="text-lg font-semibold mb-3">
                Top products (last {summary.window_days} days)
              </h2>

              {summary.top_products.length === 0 ? (
                <p className="text-sm text-gray-500">Not enough data yet.</p>
              ) : (
                <ul className="space-y-2">
                  {summary.top_products.map((p, idx) => (
                    <li
                      key={p.product_id}
                      className="flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">
                          #{idx + 1}
                        </span>
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

              {chartData.length === 0 ? (
                <p className="text-sm text-gray-500">Not enough data yet.</p>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
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
