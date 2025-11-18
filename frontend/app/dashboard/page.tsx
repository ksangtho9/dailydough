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

  // Assume trend is sorted ascending by date
  const last = trend[trend.length - 1];
  const lastDate = new Date(last.date);
  if (isNaN(lastDate.getTime())) {
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

  // Stable date label for header (fixed locale → no hydration error)
  const todayLabel = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

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

  // derive totals from trend, fall back to summary fields
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
      {/* Page header */}
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {summary ? summary.bakery_name : "Bakery dashboard"}
          </h1>
          <p className="text-sm text-slate-600">
            Sales & demand overview •{" "}
            <span className="font-medium text-slate-700">{todayLabel}</span>
          </p>
          {bakeryId != null && (
            <p className="text-xs text-slate-500">
              Showing data for bakery ID{" "}
              <span className="font-semibold">{bakeryId}</span> over the{" "}
              {windowLabel}.
            </p>
          )}
        </div>

        {/* Window toggle */}
        <div className="flex flex-col items-end gap-2">
          <div className="inline-flex items-center rounded-full bg-amber-50 px-1 py-0.5 text-xs border border-amber-100">
            <span className="px-3 py-1 text-[11px] uppercase tracking-wide text-amber-700">
              Window
            </span>
            <button
              type="button"
              onClick={() => setWindowDays(30)}
              className={`px-3 py-1 rounded-full text-xs ${
                windowDays === 30
                  ? "bg-white shadow-sm text-slate-900"
                  : "text-slate-600"
              }`}
            >
              30d
            </button>
            <button
              type="button"
              onClick={() => setWindowDays(90)}
              className={`px-3 py-1 rounded-full text-xs ${
                windowDays === 90
                  ? "bg-white shadow-sm text-slate-900"
                  : "text-slate-600"
              }`}
            >
              90d
            </button>
          </div>

          {/* Tab-ish row like Daily Dough (only Overview is real for now) */}
          <div className="inline-flex rounded-full bg-white border border-slate-200 text-xs shadow-sm">
            <button className="px-4 py-1.5 rounded-full bg-slate-900 text-white font-medium">
              Overview
            </button>
            <button className="px-4 py-1.5 rounded-full text-slate-500">
              Accuracy
            </button>
            <button className="px-4 py-1.5 rounded-full text-slate-500">
              Insights
            </button>
          </div>
        </div>
      </header>

      {bakeryId == null && (
        <p className="text-sm text-slate-600">
          Select a bakery in the sidebar to see its dashboard.
        </p>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {summary && !loading && (
        <>
          {/* KPI row */}
          <section className="grid gap-4 md:grid-cols-3 mt-2">
            {/* Card 1 */}
            <div className="rounded-2xl border border-amber-100 bg-white/80 p-4 shadow-sm flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
                    Total units
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Last 7 days
                  </p>
                </div>
                <div className="h-9 w-9 rounded-full bg-amber-50 flex items-center justify-center text-lg">
                  🥐
                </div>
              </div>
              <p className="text-3xl font-semibold">
                {total7.toLocaleString()}
              </p>
              <p className="text-xs text-slate-500">
                Rolling total over the last week.
              </p>
            </div>

            {/* Card 2 */}
            <div className="rounded-2xl border border-amber-100 bg-white/80 p-4 shadow-sm flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
                    Total units
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Last 30 days
                  </p>
                </div>
                <div className="h-9 w-9 rounded-full bg-emerald-50 flex items-center justify-center text-lg">
                  📈
                </div>
              </div>
              <p className="text-3xl font-semibold">
                {total30.toLocaleString()}
              </p>
              <p className="text-xs text-slate-500">
                Sum of all recorded units in this window.
              </p>
            </div>

            {/* Card 3 */}
            <div className="rounded-2xl border border-amber-100 bg-white/80 p-4 shadow-sm flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
                    Change vs previous period
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Same {windowDays}-day window
                  </p>
                </div>
                <div className="h-9 w-9 rounded-full bg-sky-50 flex items-center justify-center text-lg">
                  🔁
                </div>
              </div>
              <p className="text-3xl font-semibold">
                {pctChange === null
                  ? "—"
                  : `${pctChange > 0 ? "+" : ""}${pctChange.toFixed(1)}%`}
              </p>
              <p className="text-xs text-slate-500">
                Based on summary from the forecasting engine.
              </p>
            </div>
          </section>

          {/* Main content: chart + top products */}
          <section className="grid gap-6 mt-6 xl:grid-cols-3">
            {/* Chart */}
            <div className="rounded-2xl border bg-white/80 p-4 shadow-sm xl:col-span-2">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-800">
                    Daily sales trend
                  </h2>
                  <p className="text-xs text-slate-500">
                    {windowLabel}
                  </p>
                </div>
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
            </div>

            {/* Top products */}
            <div className="rounded-2xl border bg-white/80 p-4 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-800">
                  Top 5 products
                </h2>
                <span className="text-[11px] rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
                  Last 30 days
                </span>
              </div>

              {topProducts.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Not enough data yet.
                </p>
              ) : (
                <ul className="space-y-2">
                  {topProducts.map((p, idx) => (
                    <li
                      key={p.product_id}
                      className="flex items-center justify-between rounded-xl px-2 py-1.5 hover:bg-slate-50"
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-[11px] text-slate-600">
                          #{idx + 1}
                        </span>
                        <span className="text-sm text-slate-800">
                          {p.product_name}
                        </span>
                      </div>
                      <span className="text-sm font-medium text-slate-900">
                        {safeNumber(p.units_sold).toLocaleString()}{" "}
                        <span className="text-xs text-slate-500">units</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}



