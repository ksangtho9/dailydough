"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

type SalesPoint = {
  date: string;
  quantity: number;
};

type ForecastPoint = {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
};

type ChartPoint = {
  date: string;
  actual?: number;
  forecast?: number;
  lower?: number;
  upper?: number;
};

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const productId = params?.id;

  const [sales, setSales] = useState<SalesPoint[]>([]);
  const [forecast, setForecast] = useState<ForecastPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [recommendedP50, setRecommendedP50] = useState<number | null>(null);
  const [recommendedLow, setRecommendedLow] = useState<number | null>(null);
  const [recommendedHigh, setRecommendedHigh] = useState<number | null>(null);

  useEffect(() => {
    if (!productId) return; // don't call API until we have an id

    async function loadData() {
      try {
        setLoading(true);
        setError(null);

        const salesData = await apiFetch<SalesPoint[]>(
          `/api/sales/product/${productId}`
        );

        const forecastData = await apiFetch<ForecastPoint[]>(
          `/api/forecast/product/${productId}`,
          {
            method: "POST",
            body: JSON.stringify({ days: 14 }),
          }
        );

        setSales(salesData);
        setForecast(forecastData);

        if (forecastData.length > 0) {
          const first = forecastData[0];
          setRecommendedP50(first.yhat);
          setRecommendedLow(first.yhat_lower);
          setRecommendedHigh(first.yhat_upper);
        }
      } catch (err: any) {
        console.error(err);
        setError(err.message || "Failed to load sales/forecast");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [productId]);

  const chartData = buildChartData(sales, forecast);

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">
          Product #{productId ?? ""}
        </h2>
        <p className="text-sm text-slate-600">
          Sales history and demand forecast.
        </p>
      </header>

      {/* How many to bake */}
      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Recommended bake</p>
          <p className="mt-2 text-2xl font-semibold">
            {recommendedP50 !== null ? Math.round(recommendedP50) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P50 (best estimate) for next day
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Safe low</p>
          <p className="mt-2 text-2xl font-semibold">
            {recommendedLow !== null ? Math.round(recommendedLow) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P10 — minimize waste, more risk of stockouts
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Safe high</p>
          <p className="mt-2 text-2xl font-semibold">
            {recommendedHigh !== null ? Math.round(recommendedHigh) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P90 — fewer stockouts, more risk of leftovers
          </p>
        </div>
      </section>

      {/* Chart */}
      <section className="rounded-xl border bg-white p-4">
        <h3 className="mb-4 text-sm font-semibold text-slate-700">
          Sales history & forecast
        </h3>

        {loading && <p className="text-sm text-slate-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">Error: {error}</p>}

        {!loading && !error && chartData.length === 0 && (
          <p className="text-sm text-slate-500">
            No data yet for this product.
          </p>
        )}

        {!loading && !error && chartData.length > 0 && (
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />

                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Actual sales"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast (P50)"
                  strokeDasharray="5 5"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="lower"
                  name="Lower bound (P10)"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="upper"
                  name="Upper bound (P90)"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}

function buildChartData(
    rawSales: any,
    rawForecast: any
  ): ChartPoint[] {
    // Normalize sales → always an array
    const sales: any[] = Array.isArray(rawSales)
      ? rawSales
      : rawSales?.sales || rawSales?.data || [];
  
    // Normalize forecast → always an array
    const forecast: any[] = Array.isArray(rawForecast)
      ? rawForecast
      : rawForecast?.forecast || rawForecast?.data || [];
  
    const map = new Map<string, ChartPoint>();
  
    // --- SALES ---
    for (const s of sales) {
      if (!s) continue;
  
      // Support backends using date or ds
      const key: string = s.date || s.ds;
      if (!key) continue;
  
      const existing = map.get(key) || { date: key };
  
      // Normalize quantity fields
      const qty =
        s.quantity ??
        s.qty ??
        s.y ??
        0;
  
      existing.actual = qty;
      map.set(key, existing);
    }
  
    // --- FORECAST ---
    for (const f of forecast) {
      if (!f) continue;
  
      // Support ds or date
      const key: string = f.ds || f.date;
      if (!key) continue;
  
      const existing = map.get(key) || { date: key };
  
      existing.forecast =
        f.yhat ??
        f.forecast ??
        0;
  
      existing.lower =
        f.yhat_lower ??
        f.lower ??
        undefined;
  
      existing.upper =
        f.yhat_upper ??
        f.upper ??
        undefined;
  
      map.set(key, existing);
    }
  
    // Sort chronologically
    return Array.from(map.values()).sort((a, b) =>
        a.date.localeCompare(b.date)
    );
}
  
