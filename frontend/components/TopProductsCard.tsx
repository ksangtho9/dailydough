"use client";

import { useEffect, useState } from "react";
import { fetchTopProducts, type TopProductsResponse } from "@/lib/topProducts";

type Props = {
  bakeryId: number | null;
};

export function TopProductsCard({ bakeryId }: Props) {
  const [data, setData] = useState<TopProductsResponse | null>(null);
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
        const res = await fetchTopProducts(bakeryId);
        if (!cancelled) {
          setData(res);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load top products");
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
    <section className="rounded-3xl border border-rose-100 bg-white/90 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            Top products (last 30 days)
          </h2>
          <p className="text-xs text-slate-600">
            Total units sold across the rolling 30-day window.
          </p>
        </div>
      </div>

      {bakeryId === null && (
        <p className="mt-4 text-sm text-slate-500">
          Select a bakery to see its top sellers.
        </p>
      )}

      {bakeryId !== null && (
        <div className="mt-4 space-y-3 text-sm">
          {loading && <p className="text-slate-500">Loading top products…</p>}
          {error && <p className="text-red-600">{error}</p>}
          {!loading && !error && data && data.items.length === 0 && (
            <p className="text-slate-500">
              No sales recorded for this period yet.
            </p>
          )}

          {!loading && !error && data && data.items.length > 0 && (
            <ul className="space-y-1">
              {data.items.map((item, index) => (
                <li
                  key={item.product_id}
                  className="flex items-center justify-between rounded-2xl bg-rose-50/70 px-3 py-1.5"
                >
                  <span className="text-slate-800">
                    <span className="mr-2 text-xs font-semibold text-rose-600">
                      #{index + 1}
                    </span>
                    {item.product_name}
                  </span>
                  <span className="font-semibold text-slate-900">
                    {Math.round(item.total_quantity)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}



