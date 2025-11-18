"use client";

import { useEffect, useState } from "react";
import {
  fetchBakerySummary,
  type BakerySummary,
} from "@/lib/bakerySummary";
import {
  fetchBakeryDailySales,
  type BakeryDailyPoint,
} from "@/lib/bakeryTimeseries";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

// Make sure we never crash if backend sends strings / undefined
function safeNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const n = Number(value);
    return Number.isNaN(n) ? 0 : n;
  }
  return 0;
}

const STORAGE_KEY = "current_bakery_id";

type WindowDays = 30 | 90;

function computeRollingTotals(trend: BakeryDailyPoint[]) {
  if (trend.length === 0) {
    return { total7: 0, total30: 0 };
  }

  // Assume trend is sorted ascending by date (we already do this in fetchBakeryDailySales)
  const last = trend[trend.length - 1];
  const lastDate = new Date(last.date);
  if (isNaN(lastDate.getTime())) {
    // If parsing fails, just sum everything as 30d and 7d fallback
    const total = trend.reduce((acc, p) => acc + safeNumber(p.units), 0);
    return { total7: total, total30: total };
  }

  const cutoff7 = new Date(lastDate);
  cutoff7.setDate(lastDate.getDate() - 6); // last 7 days inclusive

  const cutoff30 = new Date(lastDate);
  cutoff30.setDate(lastDate.getDate() - 29); // last 30 days inclusive

  let total7 = 0;
  let total30 = 0;

  for (const p of trend) {
    const d = new Date(p.date);
    if (isNaN(d.getTime())) continue;

    if (d >= cutoff30) {
      total30 += safeNumber(p.units);
      if (d >= cutoff7) {
        total7 += safeNumber(p.units);
      }
    }
  }

  return { total7, total30 };
}

export default function DashboardPage() {
  const [bakeryId, setBakeryId] = useState<number | null>(null);
  const [summary, setSummary] = useState<BakerySummary | null>(null);
  const [trend, setTrend] = useState<BakeryDailyPoint[]>([]);
  const [windowDays, setWindowDays] = useState<WindowDays>(30);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read selected bakery from localStorage
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const asNum = Number(stored);
      if (!Number.isNaN(asNum)) {
        setBakeryId(asNum);
      }
    }
  }, []);

  // Whenever bakeryId or windowDays change, load summary + trend
  useEffect(() => {
    if (bakeryId == null) return;

    const id = bakeryId;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const [summaryData, trendData] = await Promise.all([
          fetchBakerySummary(id, windowDays),
          fetchBakeryDailySales(id, windowDays),
        ]);

        setSummary(summaryData);
        setTrend(trendData);
      } catch (err) {
        console.error(err);
        setError("Failed to load dashboard data.");
        setSummary(null);
        setTrend([]);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [bakeryId, windowDays]);

  // % change vs previous period (if backend sends it)
  const pctChangeRaw =
    summary?.pct_change_vs_prev !== undefined &&
    summary?.pct_change_vs_prev !== null
      ? summary.pct_change_vs_prev
      : null;

  const pctChange =
    pctChangeRaw === null ? null : safeNumber(pctChangeRaw);

  const windowLabel =
    windowDays === 30 ? "last 30 days" : "last 90 days";

  const topProducts = summary?.top_products_last_30_days ?? [];

  // 👉 derive totals from trend, fall back to summary fields
  const { total7: derived7, total30: derived30 } = computeRollingTotals(trend);
  const total7 =
    derived7 > 0
      ? derived7
      : safeNumber(summary?.total_units_last_7_days ?? 0);
  const total30 =
    derived30 > 0
      ? derived30
      : safeNumber(summary?.total_units_last_30_days ?? 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">
            {summary ? `${summary.bakery_name} dashboard` : "Bakery Dashboard"}
          </h1>
          <p className="text-sm text-slate-600">
            High-level view of sales and demand.
          </p>
        </div>

        {/* Window toggle */}
        <div className="inline-flex items-center rounded-full bg-slate-100 p-1 text-xs">
          <button
            type="button"
            onClick={() => setWindowDays(30)}
            className={`px-3 py-1 rounded-full ${
              windowDays === 30
                ? "bg-white shadow text-slate-900"
                : "text-slate-600"
            }`}
          >
            30d
          </button>
          <button
            type="button"
            onClick={() => setWindowDays(90)}
            className={`px-3 py-1 rounded-full ${
              windowDays === 90
                ? "bg-white shadow text-slate-900"
                : "text-slate-600"
            }`}
          >
            90d
          </button>
        </div>
      </div>

      {bakeryId == null && (
        <p className="text-sm text-slate-600">
          Select a bakery in the sidebar to see its dashboard.
        </p>
      )}

      {bakeryId != null && (
        <p className="text-xs text-slate-500">
          Showing data for bakery ID{" "}
          <span className="font-semibold">{bakeryId}</span> over the{" "}
          {windowLabel}.
        </p>
      )}

      {loading && <p>Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {summary && !loading && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">
                Total units (last 7 days)
              </p>
              <p className="mt-2 text-3xl font-bold">
                {total7.toLocaleString()}
              </p>
            </div>

            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">
                Total units (last 30 days)
              </p>
              <p className="mt-2 text-3xl font-bold">
                {total30.toLocaleString()}
              </p>
            </div>

            <div className="rounded-2xl border p-4 shadow-sm">
              <p className="text-sm text-gray-500">
                vs previous {windowDays === 30 ? "30d" : "90d"} period
              </p>
              <p className="mt-2 text-3xl font-bold">
                {pctChange === null
                  ? "—"
                  : `${pctChange > 0 ? "+" : ""}${pctChange.toFixed(1)}%`}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Uses the same {windowDays}d window if provided by backend.
              </p>
            </div>
          </div>

          {/* Daily sales trend chart */}
          <section className="mt-6 rounded-2xl border p-4 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold">
                Daily sales trend
              </h2>
              <span className="text-xs text-slate-500">
                {windowLabel}
              </span>
            </div>

            {trend.length === 0 ? (
              <p className="text-sm text-slate-500">
                Not enough data yet to show a trend.
              </p>
            ) : (
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis />
                    <Tooltip />
                    <Line
                      type="monotone"
                      dataKey="units"
                      name="Units sold"
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          {/* Top products list */}
          <div className="mt-6 rounded-2xl border p-4 shadow-sm">
            <h2 className="text-lg font-semibold mb-3">
              Top 5 products (last 30 days)
            </h2>
            {topProducts.length === 0 ? (
              <p className="text-sm text-gray-500">
                Not enough data yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {topProducts.map((p, idx) => (
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
                      {safeNumber(p.units_sold).toLocaleString()} units
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}

