"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, deleteAllProducts } from "@/lib/api";
import { supabase } from "@/lib/supabase";
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
  shelf_life_days?: number | null;
  forecast_metrics?: ForecastMetrics | null;
};

type Bakery = {
  id: number;
  name: string;
};
type SortBy = "id" | "sku";
type SortDir = "asc" | "desc";

const BAKERY_STORAGE_KEY = "current_bakery_id";

export default function ProductsPage() {
  const router = useRouter();

  const [products, setProducts] = useState<Product[]>([]);
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string>("all");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Default sort: by SKU so it matches the order from your data spreadsheet.
  const [sortBy, setSortBy] = useState<SortBy>("sku");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

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

      // Build products API URL with bakery_id if a specific bakery is selected
      let productsUrl = "/api/products/";
      if (selectedBakeryId !== "all" && selectedBakeryId) {
        const bakeryIdNum = Number(selectedBakeryId);
        if (!Number.isNaN(bakeryIdNum)) {
          productsUrl = `/api/products/?bakery_id=${bakeryIdNum}`;
        }
      }

      const [bakeryData, productData] = await Promise.all([
        apiFetch<Bakery[]>("/api/bakeries/"),
        apiFetch<Product[]>(productsUrl),
      ]);

      setBakeries(bakeryData);
      setProducts(productData);

      // Log distinct shelf-life values to help verify CSV ingestion / backend wiring
      try {
        const distinctShelfLives = Array.from(
          new Set(
            productData
              .map((p) => p.shelf_life_days)
              .filter((v): v is number => v != null)
          )
        ).sort((a, b) => a - b);
        console.log("[ProductsPage] Distinct shelf_life_days:", distinctShelfLives);
        console.log(
          "[ProductsPage] Sample products with shelf_life_days:",
          productData.slice(0, 5).map((p) => ({
            id: p.id,
            name: p.name,
            shelf_life_days: p.shelf_life_days,
          }))
        );
      } catch (logErr) {
        console.error("[ProductsPage] Failed to log shelf life summary", logErr);
      }

    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to load products");
    } finally {
      setLoading(false);
    }
  }, [selectedBakeryId]);

  useEffect(() => {
    async function init() {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        router.push("/login");
        return;
      }
      const storedBakeryId = localStorage.getItem(BAKERY_STORAGE_KEY);
      if (storedBakeryId) {
        setSelectedBakeryId(storedBakeryId);
      }
    }
    init();
  }, [router]);

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

  // Load products when component mounts or selected bakery changes
  useEffect(() => {
    loadProductsAndRecs();
  }, [selectedBakeryId, loadProductsAndRecs]);

  const filteredProducts =
    selectedBakeryId === "all"
      ? products
      : products.filter(
          (p) =>
            p.bakery_id !== undefined &&
            String(p.bakery_id) === selectedBakeryId
        );

  const sortedProducts = [...filteredProducts].sort((a, b) => {
    if (sortBy === "id") {
      const diff = a.id - b.id;
      return sortDir === "asc" ? diff : -diff;
    }

    if (sortBy === "sku") {
      const aSku = a.sku || "";
      const bSku = b.sku || "";
      if (!aSku && !bSku) return 0;
      if (!aSku) return sortDir === "asc" ? 1 : -1;
      if (!bSku) return sortDir === "asc" ? -1 : 1;
      const diff = aSku.localeCompare(bSku);
      return sortDir === "asc" ? diff : -diff;
    }

    return 0;
  });

  function toggleSort(key: SortBy) {
    setSortBy((currentKey) => {
      if (currentKey === key) {
        // Toggle direction
        setSortDir((currentDir) => (currentDir === "asc" ? "desc" : "asc"));
        return currentKey;
      }
      // Switch key, reset to ascending
      setSortDir("asc");
      return key;
    });
  }

  function renderSortIndicator(key: SortBy) {
    if (sortBy !== key) return null;
    return <span className="ml-1 text-[10px]">{sortDir === "asc" ? "▲" : "▼"}</span>;
  }

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

          {/* Tiny legend + bulk actions */}
          <div className="flex flex-col items-end gap-1">
            {filteredProducts.length > 0 && selectedBakeryId !== "all" && (
              <button
                type="button"
                className="rounded-full border border-red-200 bg-red-50 px-3 py-1 text-[11px] font-medium text-red-700 shadow-sm hover:bg-red-100"
                onClick={async () => {
                  if (
                    !window.confirm(
                      "This will delete ALL products, sales, and forecast data for the current bakery. This cannot be undone. Continue?"
                    )
                  ) {
                    return;
                  }
                  try {
                    const bakeryIdNum = Number(selectedBakeryId);
                    if (Number.isNaN(bakeryIdNum)) {
                      alert("Current bakery selection is invalid.");
                      return;
                    }
                    const result = await deleteAllProducts(bakeryIdNum);
                    console.log("[ProductsPage] Deleted all products for bakery", {
                      selectedBakeryId,
                      ...result,
                    });
                    await loadProductsAndRecs();
                  } catch (err) {
                    console.error("Failed to delete all products", err);
                    alert(
                      "Failed to delete all products for this bakery. See console for details."
                    );
                  }
                }}
              >
                Delete all products for this bakery
              </button>
            )}
          </div>
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
                  <th
                    className="px-4 py-2 text-left cursor-pointer select-none"
                    onClick={() => toggleSort("id")}
                  >
                    ID
                    {renderSortIndicator("id")}
                  </th>
                  <th className="px-4 py-2 text-left">Name</th>
                  <th
                    className="px-4 py-2 text-left cursor-pointer select-none"
                    onClick={() => toggleSort("sku")}
                  >
                    SKU
                    {renderSortIndicator("sku")}
                  </th>
                  <th className="px-4 py-2 text-left">Bakery</th>
                  <th className="px-4 py-2 text-left">Shelf life</th>
                  <th className="px-4 py-2 text-left">Confidence</th>
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
                {sortedProducts.map((p, idx) => {
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

                      <td className="px-4 py-2 align-middle text-sm text-slate-700">
                        {(() => {
                          const value = p.shelf_life_days;
                          if (value == null) return "—";
                          if (value <= 1) return "Same-day";
                          if (value === 2) return "2 days";
                          return `~${value} days`;
                        })()}
                      </td>

                      <td className="px-4 py-2 align-middle text-sm">
                        <ForecastConfidenceBadge
                          metrics={p.forecast_metrics ?? null}
                        />
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






