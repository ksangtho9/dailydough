"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
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

type Product = {
  id: number;
  name: string;
  sku?: string | null;
};

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
  const router = useRouter();
  const productId = params?.id;

  const [product, setProduct] = useState<Product | null>(null);
  const [salesRaw, setSalesRaw] = useState<any>([]);
  const [forecastRaw, setForecastRaw] = useState<any>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [recommendedP50, setRecommendedP50] = useState<number | null>(null);
  const [recommendedLow, setRecommendedLow] = useState<number | null>(null);
  const [recommendedHigh, setRecommendedHigh] = useState<number | null>(null);

  useEffect(() => {
    if (!productId) return;
    if (typeof window === "undefined") return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    async function loadData() {
      try {
        setLoading(true);
        setError(null);

        // Product name for header
        const productsData = await apiFetch<Product[]>("/api/products/");
        const found = productsData.find(
          (p) => String(p.id) === String(productId)
        );
        if (found) setProduct(found);

        // Sales + forecast
        const salesData = await apiFetch<any>(
          `/api/sales/product/${productId}`
        );

        const forecastData = await apiFetch<any>(
          `/api/forecast/product/${productId}`,
          {
            method: "POST",
            body: JSON.stringify({ days: 14 }),
          }
        );

        setSalesRaw(salesData);
        setForecastRaw(forecastData);

        const normalizedForecast = normalizeForecast(forecastData);
        if (normalizedForecast.length > 0) {
          const first = normalizedForecast[0];
          setRecommendedP50(first.yhat);
          setRecommendedLow(first.yhat_lower);
          setRecommendedHigh(first.yhat_upper);
        }
      } catch (err: any) {
        console.error(err);
        setError(err.message || "Failed to load product data");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [productId, router]);

  const chartData = buildChartData(salesRaw, forecastRaw);
  const title = product ? product.name : `Product #${productId ?? ""}`;

  const salesTable = normalizeSales(salesRaw);
  const forecastTable = normalizeForecast(forecastRaw);

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
          <p className="text-sm text-slate-600">
            Sales history and demand forecast.
          </p>
        </div>

        <Link
          href="/products"
          className="text-sm text-blue-600 hover:underline"
        >
          ← Back to products
        </Link>
      </header>

      {/* How many to bake */}
      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">RECOMMENDED BAKE</p>
          <p className="mt-2 text-2xl font-semibold">
            {recommendedP50 !== null ? Math.round(recommendedP50) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P50 (best estimate) for next day
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">SAFE LOW</p>
          <p className="mt-2 text-2xl font-semibold">
            {recommendedLow !== null ? Math.round(recommendedLow) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P10 — minimize waste, more risk of stockouts
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-500">SAFE HIGH</p>
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

      {/* Tables */}
      <section className="grid gap-4 md:grid-cols-2">
        {/* Sales table */}
        <div className="rounded-xl border bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">
            Sales table
          </h3>
          {salesTable.length === 0 ? (
            <p className="text-sm text-slate-500">
              No sales data yet for this product.
            </p>
          ) : (
            <div className="max-h-64 overflow-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50 border-b text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-right">Units sold</th>
                  </tr>
                </thead>
                <tbody>
                  {salesTable.map((row, idx) => (
                    <tr
                      key={`${row.date}-${idx}`}
                      className="border-b last:border-b-0"
                    >
                      <td className="px-3 py-1.5">{row.date}</td>
                      <td className="px-3 py-1.5 text-right">
                        {row.quantity}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Forecast table */}
        <div className="rounded-xl border bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">
            Forecast table
          </h3>
          {forecastTable.length === 0 ? (
            <p className="text-sm text-slate-500">
              No forecast data yet for this product.
            </p>
          ) : (
            <div className="max-h-64 overflow-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50 border-b text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-right">P50</th>
                    <th className="px-3 py-2 text-right">P10</th>
                    <th className="px-3 py-2 text-right">P90</th>
                  </tr>
                </thead>
                <tbody>
  {forecastTable.map((row, idx) => (
    <tr
      key={`${row.ds}-${idx}`}
      className="border-b last:border-b-0"
    >
      <td className="px-3 py-1.5">{row.ds}</td>
      <td className="px-3 py-1.5 text-right">
        {Math.round(row.yhat)}
      </td>
      <td className="px-3 py-1.5 text-right">
        {Math.round(row.yhat_lower)}
      </td>
      <td className="px-3 py-1.5 text-right">
        {Math.round(row.yhat_upper)}
      </td>
    </tr>
  ))}
</tbody>

              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function normalizeSales(rawSales: any): SalesPoint[] {
  const sales: any[] = Array.isArray(rawSales)
    ? rawSales
    : rawSales?.sales || rawSales?.data || [];

  const totals = new Map<string, number>();

  for (const s of sales) {
    if (!s) continue;
    const date = s.date || s.ds;
    if (!date) continue;

    const qty =
      s.quantity ?? s.units_sold ?? s.qty ?? s.y ?? 0;

    const current = totals.get(date) ?? 0;
    totals.set(date, current + Number(qty));
  }

  return Array.from(totals.entries())
    .map(([date, quantity]) => ({ date, quantity }))
    .sort((a, b) => a.date.localeCompare(b.date));
}


// Normalize forecast into a consistent array
function normalizeForecast(rawForecast: any): ForecastPoint[] {
  const forecast: any[] = Array.isArray(rawForecast)
    ? rawForecast
    : rawForecast?.forecast || rawForecast?.data || [];

  return forecast
    .map((f) => ({
      ds: f.ds || f.date,
      yhat: f.yhat ?? f.forecast ?? 0,
      yhat_lower: f.yhat_lower ?? f.lower ?? 0,
      yhat_upper: f.yhat_upper ?? f.upper ?? 0,
    }))
    .filter((f) => !!f.ds);
}

function buildChartData(rawSales: any, rawForecast: any): ChartPoint[] {
  const sales = normalizeSales(rawSales);
  const forecast = normalizeForecast(rawForecast);

  const map = new Map<string, ChartPoint>();

  // Sales
  for (const s of sales) {
    const key = s.date;
    const existing = map.get(key) || { date: key };
    existing.actual = s.quantity;
    map.set(key, existing);
  }

  // Forecast
  for (const f of forecast) {
    const key = f.ds;
    const existing = map.get(key) || { date: key };
    existing.forecast = f.yhat;
    existing.lower = f.yhat_lower;
    existing.upper = f.yhat_upper;
    map.set(key, existing);
  }

  return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date));
}
