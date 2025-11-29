"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import {
  BAKERY_UPDATED_EVENT,
  BAKERY_SELECTION_CHANGED_EVENT,
} from "@/lib/bakeries";
import { ForecastConfidenceBadge } from "@/components/ForecastConfidenceBadge";
import type { ForecastMetrics } from "@/lib/metrics";
import { TextShimmer } from "@/components/ui/text-shimmer";

type Product = {
  id: number;
  name: string;
  sku?: string | null;
  bakery_id?: number | null;
  forecast_metrics?: ForecastMetrics | null;
};

type Bakery = {
  id: number;
  name: string;
};
type ForecastPoint = {
  ds: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
};

type RecommendationsMap = Record<number, number | null>;

const BAKERY_STORAGE_KEY = "current_bakery_id";

export default function ProductsPage() {
  const router = useRouter();

  const [products, setProducts] = useState<Product[]>([]);
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string>("all");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [recommendations, setRecommendations] =
    useState<RecommendationsMap>({});
  const [recsLoading, setRecsLoading] = useState(false);

  // Stable date label
  const todayLabel = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const loadProductsAndRecs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [bakeryData, productData] = await Promise.all([
        apiFetch<Bakery[]>("/api/bakeries/"),
        apiFetch<Product[]>("/api/products/"),
      ]);

      setBakeries(bakeryData);
      setProducts(productData);

      if (productData.length > 0) {
        setRecsLoading(true);
        const recs = await fetchRecommendations(productData);
        setRecommendations(recs);
      } else {
        setRecommendations({});
      }
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to load products");
    } finally {
      setLoading(false);
      setRecsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    const storedBakeryId = localStorage.getItem(BAKERY_STORAGE_KEY);
    if (storedBakeryId) {
      setSelectedBakeryId(storedBakeryId);
    }

    loadProductsAndRecs();
  }, [router, loadProductsAndRecs]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handler = () => {
      loadProductsAndRecs();
    };

    window.addEventListener(BAKERY_UPDATED_EVENT, handler);
    return () => window.removeEventListener(BAKERY_UPDATED_EVENT, handler);
  }, [loadProductsAndRecs]);

  useEffect(() => {
    function handleSelectionChange() {
      if (typeof window === "undefined") return;
      const stored = window.localStorage.getItem(BAKERY_STORAGE_KEY);
      setSelectedBakeryId(stored ?? "all");
    }
    window.addEventListener(
      BAKERY_SELECTION_CHANGED_EVENT,
      handleSelectionChange
    );
    return () =>
      window.removeEventListener(
        BAKERY_SELECTION_CHANGED_EVENT,
        handleSelectionChange
      );
  }, []);

  const filteredProducts =
    selectedBakeryId === "all"
      ? products
      : products.filter(
          (p) =>
            p.bakery_id !== undefined &&
            String(p.bakery_id) === selectedBakeryId
        );

  function handleBakeryChange(value: string) {
    setSelectedBakeryId(value);

    if (typeof window !== "undefined") {
      if (value === "all") {
        window.localStorage.removeItem(BAKERY_STORAGE_KEY);
      } else {
        window.localStorage.setItem(BAKERY_STORAGE_KEY, value);
      }
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-[#0f172a]">Products</h1>
          <p className="text-sm text-slate-600">
            SKU list with bake recommendations per product.
          </p>
          <p className="text-xs text-slate-500">
            {todayLabel}
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          {/* Bakery filter */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-600">Current bakery</span>

            {bakeries.length === 0 ? (
              <span className="text-xs text-slate-500 italic">
                No bakeries yet
              </span>
            ) : (
              <div className="relative">
                <select
                  value={selectedBakeryId}
                  onChange={(e) => handleBakeryChange(e.target.value)}
                  className="appearance-none rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-medium text-slate-800 shadow-sm pr-8 outline-none focus:ring-2 focus:ring-amber-400"
                >
                  <option value="all">All bakeries</option>
                  {bakeries.map((b) => (
                    <option key={b.id} value={String(b.id)}>
                      {b.name}
                    </option>
                  ))}
                </select>
                <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-[10px] text-slate-400">
                  ▾
                </span>
              </div>
            )}
          </div>

          {/* Tiny legend for tomorrow bake */}
          <p className="text-[11px] text-slate-500">
            Tomorrow&apos;s bake uses P50 from your forecast.
          </p>
        </div>
      </header>

      {loading && (
        <TextShimmer className="text-sm text-slate-500" duration={1.5}>
          Loading products...
        </TextShimmer>
      )}
      {error && <p className="text-sm text-red-600">Error: {error}</p>}

      {!loading && !error && (
        <section className="rounded-2xl border bg-white/80 shadow-sm">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-800">
                Product list
              </h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                {filteredProducts.length} SKUs
              </span>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 text-left">ID</th>
                  <th className="px-4 py-2 text-left">Name</th>
                  <th className="px-4 py-2 text-left">SKU</th>
                  <th className="px-4 py-2 text-left">Bakery</th>
                  <th className="px-4 py-2 text-left">Confidence</th>
                  <th className="px-4 py-2 text-right">
                    Tomorrow&apos;s bake (P50)
                  </th>
                </tr>
              </thead>

              <tbody>
                {/* No bakeries at all */}
                {bakeries.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-slate-500 text-sm"
                    >
                      <div className="inline-flex flex-col items-center gap-1">
                        <span className="text-lg">🏪</span>
                        <span className="font-medium">
                          No bakeries found.
                        </span>
                        <span className="text-xs text-slate-500">
                          Create a bakery from the Bakeries page before adding
                          products.
                        </span>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Bakeries exist but no products */}
                {bakeries.length > 0 && products.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-slate-500 text-sm"
                    >
                      <div className="inline-flex flex-col items-center gap-1">
                        <span className="text-lg">🧁</span>
                        <span className="font-medium">
                          No products yet.
                        </span>
                        <span className="text-xs text-slate-500">
                          Add your first product so BAKEZY can start
                          forecasting.
                        </span>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Products exist but filter removes all */}
                {bakeries.length > 0 &&
                  products.length > 0 &&
                  filteredProducts.length === 0 && (
                    <tr>
                    <td
                      colSpan={6}
                        className="px-4 py-8 text-center text-slate-500 text-sm"
                      >
                        <div className="inline-flex flex-col items-center gap-1">
                          <span className="text-lg">🔍</span>
                          <span className="font-medium">
                            No products match this bakery.
                          </span>
                          <span className="text-xs text-slate-500">
                            Try switching the bakery filter back to{" "}
                            <span className="font-semibold">All bakeries</span>.
                          </span>
                        </div>
                      </td>
                    </tr>
                  )}

                {/* Show products */}
                {filteredProducts.map((p, idx) => {
                  const rec = recommendations[p.id];
                  const bakeryName =
                    bakeries.find((b) => b.id === p.bakery_id)?.name || "—";

                  const isStripe = idx % 2 === 1;

                  return (
                    <tr
                      key={p.id}
                      className={`border-b last:border-b-0 ${
                        isStripe ? "bg-slate-50/50" : "bg-white"
                      } hover:bg-amber-50/40 transition-colors`}
                    >
                      <td className="px-4 py-2 align-middle text-xs text-slate-500">
                        {p.id}
                      </td>

                      <td className="px-4 py-2 align-middle font-medium text-slate-900">
                        <Link
                          href={`/products/${p.id}`}
                          className="text-sm text-slate-900 hover:text-amber-700 hover:underline"
                        >
                          {p.name}
                        </Link>
                      </td>

                      <td className="px-4 py-2 align-middle text-sm text-slate-700">
                        {p.sku || (
                          <span className="text-xs italic text-slate-400">
                            none
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-2 align-middle text-sm">
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700">
                          {bakeryName}
                        </span>
                      </td>

                      <td className="px-4 py-2 align-middle text-sm">
                        <ForecastConfidenceBadge
                          metrics={p.forecast_metrics ?? null}
                        />
                      </td>

                      <td className="px-4 py-2 align-middle text-right text-sm">
                        {recsLoading && rec === undefined && (
                          <TextShimmer className="text-xs text-slate-400" duration={1.5}>
                            Generating forecast...
                          </TextShimmer>
                        )}
                        {!recsLoading && rec === undefined && (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                        {rec !== undefined && rec !== null && (
                          <span className="font-semibold text-slate-900">
                            {Math.round(rec)}
                          </span>
                        )}
                        {rec !== undefined && rec === null && (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

// Helper: for each product, call forecast endpoint and take first yhat
async function fetchRecommendations(
  products: Product[]
): Promise<RecommendationsMap> {
  const recs: RecommendationsMap = {};

  await Promise.all(
    products.map(async (p) => {
      try {
        const data = await apiFetch<ForecastPoint[]>(
          `/api/forecast/product/${p.id}`,
          {
            method: "POST",
            body: JSON.stringify({ days: 1 }), // backend can ignore/override
          }
        );

        if (Array.isArray(data) && data.length > 0) {
          recs[p.id] = data[0].yhat;
        } else {
          recs[p.id] = null;
        }
      } catch (err) {
        console.error("Failed to load forecast for product", p.id, err);
        recs[p.id] = null;
      }
    })
  );

  return recs;
}





