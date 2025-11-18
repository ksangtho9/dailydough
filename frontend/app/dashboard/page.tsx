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

// ---- helpers ---------------------------------------------------

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

  const last = trend[trend.length - 1];
  const lastDate = new Date(last.date);
  if (isNaN(lastDate.getTime())) {
    const total = trend.reduce((acc, p) => acc + safeNumber(p.units), 0);
    return { total7: total, total30: total };
  }

  const cutoff7 = new Date(lastDate);
  cutoff7.setDate(lastDate.getDate() - 6);

  const cutoff30 = new Date(lastDate);
  cutoff30.setDate(lastDate.getDate() - 29);

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

function formatAsOf(asOf?: string | null): string | null {
  if (!asOf) return null;
  const parts = asOf.split("-");
  if (parts.length < 3) return asOf;

  const [yearStr, monthStr, dayStr] = parts;
  const year = Number(yearStr);
  const month = Number(monthStr);
  const day = Number(dayStr);
  if (!year || !month || !day) return asOf;

  const date = new Date(year, month - 1, day);
  if (isNaN(date.getTime())) return asOf;

  const weekdays = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];
  const months = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  const weekday = weekdays[date.getDay()];
  const monthName = months[month - 1];

  return `${weekday}, ${monthName} ${day}, ${year}`;
}

// ---- page ------------------------------------------------------

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
  const topProduct = topProducts[0];

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

  const formattedAsOf = formatAsOf(summary?.as_of ?? null);

  return (
    <div className="w-full">
      <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
        {/* Header row */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-amber-200 text-lg">
                🥐
              </span>
              <span>Today&apos;s Forecast</span>
            </h1>

            <p className="mt-1 text-sm text-slate-600">
              Store:{" "}
              <span className="font-medium">
                {summary?.bakery_name ?? "Selected bakery"}
              </span>
              {formattedAsOf && (
                <>
                  <span className="mx-1">•</span>
                  {formattedAsOf}
                </>
              )}
            </p>
          </div>

          {/* Window toggle */}
          <div className="inline-flex items-center rounded-full bg-white/70 px-1 py-1 text-xs shadow-sm border border-amber-100">
            <button
              type="button"
              onClick={() => setWindowDays(30)}
              className={`px-3 py-1 rounded-full transition ${
                windowDays === 30
                  ? "bg-amber-500 text-white shadow-sm"
                  : "text-slate-700 hover:bg-amber-50"
              }`}
            >
              30d
            </button>
            <button
              type="button"
              onClick={() => setWindowDays(90)}
              className={`px-3 py-1 rounded-full transition ${
                windowDays === 90
                  ? "bg-amber-500 text-white shadow-sm"
                  : "text-slate-700 hover:bg-amber-50"
              }`}
            >
              90d
            </button>
          </div>
        </div>

        {/* Tabs row (visual only for now) */}
        <div className="flex gap-2 rounded-3xl bg-white/70 px-2 py-2 shadow-sm border border-amber-100">
          {["Bake plan", "Accuracy", "Insights", "Ask AI"].map((label, idx) => (
            <button
              key={label}
              type="button"
              className={`rounded-full px-4 py-1.5 text-sm transition ${
                idx === 0
                  ? "bg-amber-500 text-white shadow-sm"
                  : "text-slate-700 hover:bg-amber-50"
              }`}
            >
              {label}
            </button>
          ))}
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

        {loading && <p className="text-sm text-slate-600">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {summary && !loading && (
          <>
            {/* KPI cards */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {/* Recommended bake */}
              <div className="rounded-3xl border border-amber-100 bg-white/90 px-6 py-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                  Recommended bake
                </p>
                <p className="mt-3 text-3xl font-semibold text-slate-900">
                  {total7.toLocaleString()}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Total units (last 7 days)
                </p>
              </div>

              {/* Rolling volume */}
              <div className="rounded-3xl border border-amber-100 bg-amber-50/80 px-6 py-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                  Rolling volume
                </p>
                <p className="mt-3 text-3xl font-semibold text-slate-900">
                  {total30.toLocaleString()}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Units sold over the last 30 days
                </p>
              </div>

              {/* Trend vs previous period */}
              <div className="rounded-3xl border border-rose-100 bg-rose-50/80 px-6 py-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-700">
                  Trend vs previous period
                </p>
                <p className="mt-3 text-3xl font-semibold text-slate-900">
                  {pctChange === null
                    ? "—"
                    : `${pctChange > 0 ? "+" : ""}${pctChange.toFixed(1)}%`}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Same {windowDays}d window, if available from the model.
                </p>
              </div>

              {/* Top product (30d) */}
              <div className="rounded-3xl border border-emerald-100 bg-emerald-50/80 px-6 py-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                  Top product (30d)
                </p>
                <p className="mt-3 text-sm font-semibold text-slate-900">
                  {topProduct
                    ? topProduct.product_name
                    : "Not enough data yet to surface a hero product."}
                </p>
                {topProduct && (
                  <p className="mt-1 text-xs text-slate-500">
                    {safeNumber(topProduct.units_sold).toLocaleString()} units
                    in the last 30 days.
                  </p>
                )}
              </div>
            </div>

            {/* Trend + Forecast drivers */}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] mt-2">
              {/* Daily sales trend */}
              <section className="rounded-3xl border border-amber-100 bg-white/90 p-5 shadow-sm">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-slate-800">
                      Daily sales trend
                    </h2>
                    <p className="text-xs text-slate-500">
                      Aggregated units per day — {windowLabel}.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-full border border-amber-100 bg-white px-3 py-1 text-xs text-slate-700 shadow-sm hover:bg-amber-50"
                  >
                    ↻ Refresh forecasts
                  </button>
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

              {/* Forecast drivers (placeholder) */}
              <section className="rounded-3xl border border-sky-100 bg-sky-50/80 p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-800">
                  Forecast drivers
                </h2>
                <p className="mt-1 text-xs text-slate-600">
                  You can plug real drivers (weather, events, promos) into this
                  panel later. For now it&apos;s a simple placeholder so the
                  layout matches your future vision.
                </p>

                <div className="mt-4 space-y-3 text-xs">
                  <div className="rounded-2xl bg-white/80 p-3 border border-sky-100">
                    <p className="font-semibold text-slate-800">Weather signal</p>
                    <p className="mt-1 text-slate-600">
                      Hook in a weather API to adjust hot/cold beverages and
                      pastry demand.
                    </p>
                  </div>

                  <div className="rounded-2xl bg-white/80 p-3 border border-sky-100">
                    <p className="font-semibold text-slate-800">
                      Calendar / events
                    </p>
                    <p className="mt-1 text-slate-600">
                      Holidays, paydays and local events can all shift demand up
                      or down.
                    </p>
                  </div>

                  <div className="rounded-2xl bg-white/80 p-3 border border-sky-100">
                    <p className="font-semibold text-slate-800">
                      Model experiments
                    </p>
                    <p className="mt-1 text-slate-600">
                      Later, show which model/version is driving the current
                      bake recommendations.
                    </p>
                  </div>
                </div>
              </section>
            </div>

            {/* Top products list */}
            <section className="mt-2 rounded-3xl border border-amber-100 bg-white/90 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-800 mb-3">
                Top products (last 30 days)
              </h2>
              {topProducts.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Not enough data yet.
                </p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {topProducts.map((p, idx) => (
                    <li
                      key={p.product_id}
                      className="flex items-center justify-between rounded-2xl bg-amber-50/40 px-3 py-2"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-semibold text-amber-700">
                          #{idx + 1}
                        </span>
                        <span className="text-slate-800">
                          {p.product_name}
                        </span>
                      </div>
                      <span className="font-medium text-slate-900">
                        {safeNumber(p.units_sold).toLocaleString()} units
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}




