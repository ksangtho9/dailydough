"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Product = {
  id: number;
  name: string;
  sku?: string | null;
  bakery_id?: number | null;
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

  const [recommendations, setRecommendations] = useState<RecommendationsMap>({});
  const [recsLoading, setRecsLoading] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    // 👇 initialize selected bakery from shared storage
    const storedBakeryId = localStorage.getItem(BAKERY_STORAGE_KEY);
    if (storedBakeryId) {
      setSelectedBakeryId(storedBakeryId);
    }

    async function loadProductsAndRecs() {
      try {
        setLoading(true);
        setError(null);

        // 1) Load bakeries
        const bakeryData = await apiFetch<Bakery[]>("/api/bakeries/");
        setBakeries(bakeryData);

        // 2) Load products
        const productData = await apiFetch<Product[]>("/api/products/");
        setProducts(productData);

        // 3) Load recommendations for all products
        if (productData.length > 0) {
          setRecsLoading(true);
          const recs = await fetchRecommendations(productData);
          setRecommendations(recs);
        }
      } catch (err: any) {
        console.error(err);
        setError(err.message || "Failed to load products");
      } finally {
        setLoading(false);
        setRecsLoading(false);
      }
    }

    loadProductsAndRecs();
  }, [router]);

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
        // If "All bakeries", clear the shared selection
        window.localStorage.removeItem(BAKERY_STORAGE_KEY);
      } else {
        // Otherwise, keep in sync with dashboard/sidebar
        window.localStorage.setItem(BAKERY_STORAGE_KEY, value);
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-2xl font-semibold">Products</h2>

        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-600">Bakery:</span>
          <select
            value={selectedBakeryId}
            onChange={(e) => handleBakeryChange(e.target.value)}
            className="rounded-lg border px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-slate-500"
          >
            <option value="all">All bakeries</option>
            {bakeries.map((b) => (
              <option key={b.id} value={String(b.id)}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p className="text-red-600">Error: {error}</p>}

      {!loading && !error && (
        <div className="overflow-x-auto border bg-white rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 border-b text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">ID</th>
                <th className="px-4 py-2 text-left">Name</th>
                <th className="px-4 py-2 text-left">SKU</th>
                <th className="px-4 py-2 text-left">Bakery</th>
                <th className="px-4 py-2 text-right">
                  Tomorrow&apos;s bake (P50)
                </th>
              </tr>
            </thead>

            <tbody>
              {filteredProducts.map((p) => {
                const rec = recommendations[p.id];
                const bakeryName =
                  bakeries.find((b) => b.id === p.bakery_id)?.name || "—";

                return (
                  <tr key={p.id} className="border-b last:border-b-0">
                    <td className="px-4 py-2">{p.id}</td>

                    <td className="px-4 py-2 font-medium">
                      <Link
                        href={`/products/${p.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {p.name}
                      </Link>
                    </td>

                    <td className="px-4 py-2">{p.sku || "—"}</td>
                    <td className="px-4 py-2">{bakeryName}</td>

                    <td className="px-4 py-2 text-right">
                      {recsLoading && rec === undefined && "…"}
                      {!recsLoading && rec === undefined && "—"}
                      {rec !== undefined && rec !== null && Math.round(rec)}
                      {rec !== undefined && rec === null && "—"}
                    </td>
                  </tr>
                );
              })}

              {filteredProducts.length === 0 && (
                <tr>
                  <td
                    className="px-4 py-4 text-center text-slate-500"
                    colSpan={5}
                  >
                    No products for this bakery yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
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


