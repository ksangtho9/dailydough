"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { BAKERY_UPDATED_EVENT } from "@/lib/bakeries";

type Bakery = {
  id: number;
  name: string;
};
type Product = {
  id: number;
  name: string;
  bakery_id?: number | null;
};

type ForecastPoint = {
  ds: string;
  yhat: number;
};

type PlanRow = {
  productId: number;
  productName: string;
  bakeryName: string;
  horizonDays: number;
  totalUnits: number;
  avgPerDay: number;
};

type RecommendationsMap = Record<number, PlanRow>;

const BAKERY_STORAGE_KEY = "current_bakery_id";

type Horizon = 1 | 3 | 7;

export default function BakePlanPage() {
  const router = useRouter();

  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string>("all");
  const [horizon, setHorizon] = useState<Horizon>(1);

  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState<RecommendationsMap>({});
  const [error, setError] = useState<string | null>(null);
  const [forecastsLoading, setForecastsLoading] = useState(false);

  const loadBasics = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [bakeryData, productData] = await Promise.all([
        apiFetch<Bakery[]>("/api/bakeries/"),
        apiFetch<Product[]>("/api/products/"),
      ]);

      setBakeries(bakeryData);
      setProducts(productData);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to load bake plan data");
    } finally {
      setLoading(false);
    }
  }, []);

  // On mount: auth check, load bakeries/products, restore bakery filter
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

    loadBasics();
  }, [router, loadBasics]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const handler = () => {
      loadBasics();
    };

    window.addEventListener(BAKERY_UPDATED_EVENT, handler);
    return () => window.removeEventListener(BAKERY_UPDATED_EVENT, handler);
  }, [loadBasics]);

  // When products, bakery filter or horizon change → recompute plan
  useEffect(() => {
    if (products.length === 0) {
      setPlan({});
      return;
    }

    async function buildPlan() {
      try {
        setForecastsLoading(true);
        setError(null);

        const filteredProducts =
          selectedBakeryId === "all"
            ? products
            : products.filter(
                (p) =>
                  p.bakery_id !== undefined &&
                  String(p.bakery_id) === selectedBakeryId
              );

        const newPlan: RecommendationsMap = {};

        await Promise.all(
          filteredProducts.map(async (p) => {
            try {
              const data = await apiFetch<ForecastPoint[]>(
                `/api/forecast/product/${p.id}`,
                {
                  method: "POST",
                  body: JSON.stringify({ days: horizon }),
                }
              );

              const points = Array.isArray(data) ? data : [];
              if (points.length === 0) return;

              const total = points.reduce(
                (sum, d) => sum + (d.yhat ?? 0),
                0
              );
              const avg = total / horizon;

              const bakeryName =
                bakeries.find((b) => b.id === p.bakery_id)?.name || "—";

              newPlan[p.id] = {
                productId: p.id,
                productName: p.name,
                bakeryName,
                horizonDays: horizon,
                totalUnits: total,
                avgPerDay: avg,
              };
            } catch (err) {
              console.error("Failed forecast for product", p.id, err);
            }
          })
        );

        setPlan(newPlan);
      } catch (err: any) {
        console.error(err);
        setError(err.message || "Failed to build bake plan");
      } finally {
        setForecastsLoading(false);
      }
    }

    buildPlan();
  }, [products, bakeries, selectedBakeryId, horizon]);

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

  const planRows = Object.values(plan);
  const totalPlanned = planRows.reduce(
    (sum, row) => sum + row.totalUnits,
    0
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Bake plan</h2>
          <p className="text-sm text-slate-600">
            Combined forecast to decide how much to bake for each product.
          </p>
        </div>

        {/* Horizon toggle */}
        <div className="inline-flex items-center rounded-full bg-slate-100 p-1 text-xs">
          <button
            type="button"
            onClick={() => setHorizon(1)}
            className={`px-3 py-1 rounded-full ${
              horizon === 1
                ? "bg-white shadow text-slate-900"
                : "text-slate-600"
            }`}
          >
            1 day
          </button>
          <button
            type="button"
            onClick={() => setHorizon(3)}
            className={`px-3 py-1 rounded-full ${
              horizon === 3
                ? "bg-white shadow text-slate-900"
                : "text-slate-600"
            }`}
          >
            3 days
          </button>
          <button
            type="button"
            onClick={() => setHorizon(7)}
            className={`px-3 py-1 rounded-full ${
              horizon === 7
                ? "bg-white shadow text-slate-900"
                : "text-slate-600"
            }`}
          >
            7 days
          </button>
        </div>
      </header>

      {/* Filters */}
      <section className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-slate-600">Bakery:</span>
          {bakeries.length === 0 ? (
            <span className="text-xs text-slate-500 italic">
              No bakeries yet
            </span>
          ) : (
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
          )}
        </div>

        <div className="text-xs text-slate-500">
          {planRows.length > 0 && (
            <>
              Planning for{" "}
              <span className="font-semibold">{planRows.length}</span>{" "}
              products, total{" "}
              <span className="font-semibold">
                {Math.round(totalPlanned)}
              </span>{" "}
              units over {horizon} day{horizon > 1 ? "s" : ""}.
            </>
          )}
        </div>
      </section>

      {loading && <p>Loading…</p>}
      {error && <p className="text-sm text-red-600">Error: {error}</p>}

      {/* Table */}
      {!loading && !error && (
        <div className="overflow-x-auto border bg-white rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 border-b text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">Product</th>
                <th className="px-4 py-2 text-left">Bakery</th>
                <th className="px-4 py-2 text-right">
                  Total units (next {horizon}d)
                </th>
                <th className="px-4 py-2 text-right">Avg / day</th>
              </tr>
            </thead>
            <tbody>
              {planRows.length === 0 && (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-6 text-center text-slate-500"
                  >
                    {forecastsLoading
                      ? "Building bake plan…"
                      : "No forecast data yet for this selection."}
                  </td>
                </tr>
              )}

              {planRows.map((row) => (
                <tr key={row.productId} className="border-b last:border-b-0">
                  <td className="px-4 py-2">{row.productName}</td>
                  <td className="px-4 py-2">{row.bakeryName}</td>
                  <td className="px-4 py-2 text-right">
                    {Math.round(row.totalUnits)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {row.avgPerDay.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
