"use client";

import { useEffect, useState } from "react";
import { fetchBakePlan, type BakePlanResponse } from "@/lib/bakePlan";

type Props = {
  bakeryId: number | null;
};

export function TomorrowsBakePlanCard({ bakeryId }: Props) {
  const [data, setData] = useState<BakePlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bakeryId) {
      setData(null);
      return;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchBakePlan(bakeryId);
        if (!cancelled) {
          setData(res);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load bake plan");
          setData(null);
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
  }, [bakeryId]);

  return (
    <section className="rounded-3xl border border-emerald-100 bg-emerald-50/80 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            Tomorrow&apos;s bake plan
          </h2>
          <p className="text-xs text-slate-600">
            Based on the latest forecast for each product.
          </p>
        </div>
      </div>

      {bakeryId === null && (
        <p className="mt-4 text-sm text-slate-500">
          Select a bakery to view the bake plan.
        </p>
      )}

      {bakeryId !== null && (
        <div className="mt-4 space-y-3">
          {loading && (
            <p className="text-sm text-slate-500">Loading bake plan…</p>
          )}
          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
          {!loading && !error && data && data.items.length === 0 && (
            <p className="text-sm text-slate-500">
              No forecasted units for tomorrow yet. Upload data or retrain models to populate the plan.
            </p>
          )}
          {!loading && !error && data && data.items.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                {new Date(data.date).toLocaleDateString()} • {data.bakery_name}
              </p>
              <ul className="space-y-1 text-sm">
                {data.items.map((item) => (
                  <li
                    key={item.product_id}
                    className="flex items-center justify-between rounded-2xl bg-white/90 px-3 py-1.5"
                  >
                    <span className="text-slate-800">{item.product_name}</span>
                    <span className="font-semibold text-slate-900">
                      {item.forecast_quantity}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

