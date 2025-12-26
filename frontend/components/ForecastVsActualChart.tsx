"use client";

import { useEffect, useState } from "react";
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

import {
  fetchForecastVsActual,
  type ForecastVsActualResponse,
} from "@/lib/forecastVsActual";

type Props = {
  productId: number;
};

export function ForecastVsActualChart({ productId }: Props) {
  const [data, setData] = useState<ForecastVsActualResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!productId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchForecastVsActual(productId);
        if (!cancelled) {
          setData(res);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load forecast vs actuals");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [productId]);

  const chartData =
    data?.points.map((p) => ({
      date: p.date,
      actual: p.actual,
      forecast: p.forecast,
    })) ?? [];

  return (
    <section className="rounded-xl border bg-white p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase text-slate-700">FORECAST vs ACTUALS</p>
          <p className="text-xs text-slate-500">
            Last {data?.window_days ?? 60} days
          </p>
        </div>
      </div>

      <div className="mt-4 h-72">
        {loading && (
          <p className="text-sm text-slate-500">Loading forecast vs actuals…</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && chartData.length === 0 && (
          <p className="text-sm text-slate-500">
            Not enough data to compare forecasts with actuals yet.
          </p>
        )}
        {!loading && !error && chartData.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="actual"
                name="Actual"
                stroke="#0f172a"
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="forecast"
                name="Forecast"
                stroke="#eab308"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}







