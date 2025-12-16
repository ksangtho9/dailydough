"use client";

import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

import {
  fetchWeekdayPattern,
  type WeekdayPatternResponse,
} from "@/lib/weekdayPattern";

type Props = {
  productId: number;
};

export function ProductWeekdayPatternChart({ productId }: Props) {
  const [data, setData] = useState<WeekdayPatternResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!productId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchWeekdayPattern(productId);
        if (!cancelled) {
          setData(res);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load weekday pattern");
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

  const points = data?.points ?? [];

  return (
    <section className="rounded-xl border bg-white p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase text-slate-700">WEEKDAY PATTERN</p>
          <p className="text-xs text-slate-500">
            Average units per weekday (last {data?.window_days ?? 90} days)
          </p>
        </div>
      </div>

      <div className="mt-4 h-60">
        {loading && (
          <p className="text-sm text-slate-500">Loading weekday pattern…</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && points.length === 0 && (
          <p className="text-sm text-slate-500">
            Not enough data to show weekday trends yet.
          </p>
        )}
        {!loading && !error && points.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="avg_quantity" fill="#0f172a" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}





