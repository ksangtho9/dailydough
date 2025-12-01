"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch, updateProduct, deleteProduct } from "@/lib/api";
import { TextShimmer } from "@/components/ui/text-shimmer";
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
import { ForecastConfidenceBadge } from "@/components/ForecastConfidenceBadge";
import type { ForecastMetrics } from "@/lib/metrics";
import { formatLastTrainedAt } from "@/lib/metrics";
import { ProductWeekdayPatternChart } from "@/components/ProductWeekdayPatternChart";
import { ForecastVsActualChart } from "@/components/ForecastVsActualChart";

type Product = {
  id: number;
  name: string;
  sku?: string | null;
  price?: number | null;
  cost_per_unit?: number | null;
  shelf_life_days?: number | null;
  stockout_cost_ratio?: number | null;
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
  optimal_quantity?: number | null;
  expected_stockout_cost?: number | null;
  expected_waste_cost?: number | null;
  expected_total_cost?: number | null;
};

type ChartPoint = {
  date: string;
  actual?: number;
  forecast?: number;
  lower?: number;
  upper?: number;
};

type ForecastAccuracy = {
  mape: number | null; // in %
  rmse: number | null; // in units
  n_points: number; // overlapping days
};

type ErrorPoint = {
  date: string;
  absError: number;
};

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const productId = params?.id;

  const [product, setProduct] = useState<Product | null>(null);
  const [salesRaw, setSalesRaw] = useState<any>([]);
  const [forecastRaw, setForecastRaw] = useState<any>([]);
  const [metrics, setMetrics] = useState<ForecastMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [recommendedP50, setRecommendedP50] = useState<number | null>(null);
  const [recommendedLow, setRecommendedLow] = useState<number | null>(null);
  const [recommendedHigh, setRecommendedHigh] = useState<number | null>(null);
  const [optimalQuantity, setOptimalQuantity] = useState<number | null>(null);

  // Product editing state
  const [isEditing, setIsEditing] = useState(false);
  const [editPrice, setEditPrice] = useState<string>("");
  const [editCost, setEditCost] = useState<string>("");
  const [editShelfLife, setEditShelfLife] = useState<string>("1");
  const [editStockoutRatio, setEditStockoutRatio] = useState<string>("2.0");
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [updateSuccess, setUpdateSuccess] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

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

        // Fetch product from v1 endpoint (has auth and includes price/cost)
        try {
          const productData = await apiFetch<Product>(`/api/v1/products/${productId}`);
          setProduct(productData);
          setEditPrice(productData.price?.toString() || "");
          setEditCost(productData.cost_per_unit?.toString() || "");
          setEditShelfLife(
            productData.shelf_life_days != null
              ? String(productData.shelf_life_days)
              : "1"
          );
          setEditStockoutRatio(
            productData.stockout_cost_ratio != null
              ? String(productData.stockout_cost_ratio)
              : "2.0"
          );
        } catch (err: any) {
          // Fallback to base endpoint if v1 fails
          const productsData = await apiFetch<Product[]>("/api/products/");
          const found = productsData.find(
            (p) => String(p.id) === String(productId)
          );
          if (found) {
            setProduct(found);
            setEditPrice(found.price?.toString() || "");
            setEditCost(found.cost_per_unit?.toString() || "");
            setEditShelfLife(
              found.shelf_life_days != null ? String(found.shelf_life_days) : "1"
            );
            setEditStockoutRatio(
              found.stockout_cost_ratio != null
                ? String(found.stockout_cost_ratio)
                : "2.0"
            );
          }
        }

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
        console.log("forecastData from API", forecastData);

        try {
          const metricsData = await apiFetch<ForecastMetrics>(
            `/api/products/${productId}/metrics`
          );
          setMetrics(metricsData);
        } catch (err: any) {
          const message = String(err?.message ?? "");
          if (message.includes("404")) {
            setMetrics(null);
          } else {
            console.error("Failed to load metrics", err);
          }
        }

        const normalizedForecast = normalizeForecast(forecastData);
        if (normalizedForecast.length > 0) {
          const first = normalizedForecast[0];
          setRecommendedP50(first.yhat);
          setRecommendedLow(first.yhat_lower);
          setRecommendedHigh(first.yhat_upper);
          setOptimalQuantity(first.optimal_quantity ?? null);
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
  const accuracy = computeForecastAccuracy(
    salesTable,
    forecastTable,
    metrics?.last_trained_at ?? null
  );
  const errorSeries = buildErrorSeries(
    salesTable,
    forecastTable,
    metrics?.last_trained_at ?? null
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
          {title}
        </h2>
        <p className="text-sm text-slate-700">
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
      <section className="grid gap-4 md:grid-cols-4">
        <div className="rounded-xl border bg-white p-4 border-blue-200 bg-blue-50">
          <p className="text-xs uppercase text-blue-700 font-semibold">OPTIMAL BAKE</p>
          <p className="mt-2 text-2xl font-semibold text-blue-900">
            {optimalQuantity !== null ? Math.round(optimalQuantity) : recommendedP50 !== null ? Math.round(recommendedP50) : "—"}
          </p>
          <p className="mt-1 text-xs text-blue-600">
            Cost-optimized recommendation (minimizes stockouts + waste)
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-700">RECOMMENDED BAKE</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">
            {recommendedP50 !== null ? Math.round(recommendedP50) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P50 (best estimate) for next day
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-700">SAFE LOW</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">
            {recommendedLow !== null ? Math.round(recommendedLow) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            P10 — minimize waste, more risk of stockouts
          </p>
        </div>

        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs uppercase text-slate-700">SAFE HIGH</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">
            {recommendedHigh !== null ? Math.round(recommendedHigh) : "—"}
          </p>
          <p className="mt-1 text-xs text-slate-700">
            P90 — fewer stockouts, more risk of leftovers
          </p>
        </div>
      </section>

      <section className="rounded-xl border bg-white p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase text-slate-700">MODEL QUALITY</p>
            <div className="mt-2">
              <ForecastConfidenceBadge metrics={metrics} />
            </div>
          </div>
        </div>

        <div className="mt-3 text-xs text-slate-600 space-y-1">
          <p>
            MAPE:{" "}
            {metrics?.mape != null
              ? `${(metrics.mape * 100).toFixed(1)}%`
              : "Not available"}
          </p>
          <p>
            RMSE:{" "}
            {metrics?.rmse != null ? metrics.rmse.toFixed(2) : "Not available"}
          </p>
          <p>Training points: {metrics?.n_points ?? 0}</p>
          <p>Last trained: {formatLastTrainedAt(metrics?.last_trained_at ?? null)}</p>
        </div>
      </section>

      {/* Product Settings */}
      <section className="rounded-xl border bg-white p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-700">Product Settings</h3>
          {!isEditing && (
            <button
              onClick={() => setIsEditing(true)}
              className="text-sm text-blue-600 hover:text-blue-700 hover:underline"
            >
              Edit
            </button>
          )}
        </div>

        {isEditing ? (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Price (per unit)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={editPrice}
                  onChange={(e) => setEditPrice(e.target.value)}
                  placeholder="0.00"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Cost (per unit)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={editCost}
                  onChange={(e) => setEditCost(e.target.value)}
                  placeholder="0.00"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Shelf life (days)
                </label>
                <select
                  value={editShelfLife}
                  onChange={(e) => setEditShelfLife(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  <option value="1">1 day (same-day only)</option>
                  <option value="2">2 days (can sell next day)</option>
                </select>
                <p className="mt-1 text-[11px] text-slate-500">
                  Multi-day products aren&apos;t counted as waste until they pass their shelf life.
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Stockout cost ratio
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={editStockoutRatio}
                  onChange={(e) => setEditStockoutRatio(e.target.value)}
                  placeholder="2.0"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="mt-1 text-[11px] text-slate-500">
                  How much more expensive stockouts are vs waste (default: 2.0 = 2x)
                </p>
              </div>
            </div>

            {updateError && (
              <p className="text-sm text-red-600">{updateError}</p>
            )}
            {updateSuccess && (
              <p className="text-sm text-green-600">Product updated successfully!</p>
            )}

            <div className="flex gap-2">
              <button
                onClick={async () => {
                  if (!productId) return;
                  setIsUpdating(true);
                  setUpdateError(null);
                  setUpdateSuccess(false);
                  try {
                    const priceValue = editPrice === "" ? null : parseFloat(editPrice);
                    const costValue = editCost === "" ? null : parseFloat(editCost);
                    const shelfLifeValue = parseInt(editShelfLife, 10);
                    const stockoutRatioValue = editStockoutRatio === "" ? 2.0 : parseFloat(editStockoutRatio);
                    
                    if (priceValue !== null && priceValue < 0) {
                      setUpdateError("Price cannot be negative");
                      setIsUpdating(false);
                      return;
                    }
                    if (costValue !== null && costValue < 0) {
                      setUpdateError("Cost cannot be negative");
                      setIsUpdating(false);
                      return;
                    }
                    if (Number.isNaN(shelfLifeValue) || shelfLifeValue < 1 || shelfLifeValue > 2) {
                      setUpdateError("Shelf life must be 1 or 2 days");
                      setIsUpdating(false);
                      return;
                    }
                    if (Number.isNaN(stockoutRatioValue) || stockoutRatioValue < 0.1) {
                      setUpdateError("Stockout cost ratio must be at least 0.1");
                      setIsUpdating(false);
                      return;
                    }

                    const updated = await updateProduct(Number(productId), {
                      price: priceValue,
                      cost_per_unit: costValue,
                      shelf_life_days: shelfLifeValue,
                      stockout_cost_ratio: stockoutRatioValue,
                    });
                    setProduct(updated);
                    setUpdateSuccess(true);
                    setIsEditing(false);
                    setTimeout(() => setUpdateSuccess(false), 3000);
                  } catch (err: any) {
                    setUpdateError(err.message || "Failed to update product");
                  } finally {
                    setIsUpdating(false);
                  }
                }}
                disabled={isUpdating}
                className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isUpdating ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setEditPrice(product?.price?.toString() || "");
                  setEditCost(product?.cost_per_unit?.toString() || "");
                  setEditShelfLife(
                    product?.shelf_life_days != null
                      ? String(product.shelf_life_days)
                      : "1"
                  );
                  setEditStockoutRatio(
                    product?.stockout_cost_ratio != null
                      ? String(product.stockout_cost_ratio)
                      : "2.0"
                  );
                  setUpdateError(null);
                  setUpdateSuccess(false);
                }}
                disabled={isUpdating}
                className="px-4 py-2 bg-slate-200 text-slate-700 text-sm rounded-md hover:bg-slate-300 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500 mb-1">Price (per unit)</p>
              <p className="text-sm font-medium text-slate-900">
                {product?.price !== null && product?.price !== undefined
                  ? `$${product.price.toFixed(2)}`
                  : "Not set"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Cost (per unit)</p>
              <p className="text-sm font-medium text-slate-900">
                {product?.cost_per_unit !== null && product?.cost_per_unit !== undefined
                  ? `$${product.cost_per_unit.toFixed(2)}`
                  : "Not set"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Shelf life</p>
              <p className="text-sm font-medium text-slate-900">
                {product?.shelf_life_days === 2 ? "2 days" : "1 day"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-1">Stockout cost ratio</p>
              <p className="text-sm font-medium text-slate-900">
                {product?.stockout_cost_ratio != null
                  ? `${product.stockout_cost_ratio.toFixed(1)}x`
                  : "2.0x (default)"}
              </p>
            </div>
          </div>
        )}

        {/* Delete button */}
        <div className="mt-6 pt-4 border-t border-slate-200">
          {!showDeleteConfirm ? (
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="text-sm text-red-600 hover:text-red-700 hover:underline"
            >
              Delete Product
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-slate-700">
                Are you sure you want to delete this product? This action cannot be undone.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={async () => {
                    if (!productId) return;
                    setIsDeleting(true);
                    try {
                      await deleteProduct(Number(productId));
                      router.push("/products");
                    } catch (err: any) {
                      setUpdateError(err.message || "Failed to delete product");
                      setShowDeleteConfirm(false);
                    } finally {
                      setIsDeleting(false);
                    }
                  }}
                  disabled={isDeleting}
                  className="px-4 py-2 bg-red-600 text-white text-sm rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isDeleting ? "Deleting..." : "Yes, Delete"}
                </button>
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={isDeleting}
                  className="px-4 py-2 bg-slate-200 text-slate-700 text-sm rounded-md hover:bg-slate-300 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Chart */}
      <section className="rounded-xl border bg-white p-4">
        <h3 className="mb-4 text-sm font-semibold text-slate-700">
          Sales history & forecast
        </h3>

        {loading && (
          <TextShimmer className="text-sm text-slate-500" duration={1.5}>
            Loading product data...
          </TextShimmer>
        )}
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
                  stroke="#1e293b"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="Forecast (P50)"
                  stroke="#1e293b"
                  strokeDasharray="5 5"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="lower"
                  name="Lower bound (P10)"
                  stroke="#1e293b"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="upper"
                  name="Upper bound (P90)"
                  stroke="#1e293b"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* Forecast accuracy */}
      <section className="space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase text-slate-500">
              FORECAST ACCURACY (MAPE)
            </p>
            <p className="mt-2 text-2xl font-semibold">
              {accuracy.mape !== null ? `${accuracy.mape.toFixed(1)}%` : "—"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Average percentage error on days where actual & forecast overlap, excluding training data.
            </p>
          </div>

          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase text-slate-500">
              FORECAST ERROR (RMSE)
            </p>
            <p className="mt-2 text-2xl font-semibold">
              {accuracy.rmse !== null ? accuracy.rmse.toFixed(1) : "—"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Root mean squared error in units per day.
            </p>
          </div>

          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase text-slate-500">DATA POINTS</p>
            <p className="mt-2 text-2xl font-semibold">
              {accuracy.n_points}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Overlapping days with both actual and forecast (after training).{" "}
              {accuracy.n_points === 0 &&
                "You'll see accuracy once you have post-training forecasts overlapping with sales."}
            </p>
          </div>
        </div>

        {/* Error sparkline */}
        <div className="rounded-xl border bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs uppercase text-slate-500">
              DAILY ABSOLUTE ERROR
            </p>
            <p className="text-[11px] text-slate-500">
              |forecast − actual| per day
            </p>
          </div>

          {errorSeries.length === 0 ? (
            <p className="text-xs text-slate-500">
              No overlapping days yet — once you have both forecasts and actuals
              for the same dates, you’ll see error history here.
            </p>
          ) : (
            <div className="h-32">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={errorSeries}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    minTickGap={16}
                  />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="absError"
                    name="Absolute error"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <ProductWeekdayPatternChart productId={Number(productId)} />
        <ForecastVsActualChart productId={Number(productId)} />
      </div>

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
                <thead className="bg-slate-100 border-b text-slate-800">

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
                      <td className="px-3 py-1.5 text-slate-800">{row.ds}</td>
                      <td className="px-3 py-1.5 text-right text-slate-800">
                      {Math.round(row.yhat)}
                      </td>

                      <td className="px-3 py-1.5 text-right text-slate-800">
                        {Math.round(row.yhat_lower)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-slate-800">
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
  if (!rawForecast) return [];

  // If backend sent an error object instead of data
  if (rawForecast.detail) {
    console.warn("Forecast error from API:", rawForecast.detail);
    return [];
  }

  let forecast: any[] = [];

  if (Array.isArray(rawForecast)) {
    // Plain list of points
    forecast = rawForecast;
  } else if (Array.isArray(rawForecast.forecast)) {
    // { forecast: [...] }
    forecast = rawForecast.forecast;
  } else if (Array.isArray(rawForecast.data)) {
    // { data: [...] }
    forecast = rawForecast.data;
  } else if (Array.isArray(rawForecast.points)) {
    // { points: [...] }
    forecast = rawForecast.points;
  }

  return forecast
    .map((f) => ({
      ds: f.ds || f.date, // support "ds" or "date"
      yhat: f.yhat ?? f.forecast ?? f.p50 ?? 0,
      yhat_lower: f.yhat_lower ?? f.lower ?? f.p10 ?? 0,
      yhat_upper: f.yhat_upper ?? f.upper ?? f.p90 ?? 0,
      optimal_quantity: f.optimal_quantity ?? null,
      expected_stockout_cost: f.expected_stockout_cost ?? null,
      expected_waste_cost: f.expected_waste_cost ?? null,
      expected_total_cost: f.expected_total_cost ?? null,
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

function computeForecastAccuracy(
  sales: SalesPoint[],
  forecast: ForecastPoint[],
  lastTrainedAt: string | null = null
): ForecastAccuracy {
  if (sales.length === 0 || forecast.length === 0) {
    return { mape: null, rmse: null, n_points: 0 };
  }

  // If no training date, don't calculate accuracy (model not trained yet)
  if (lastTrainedAt === null) {
    return { mape: null, rmse: null, n_points: 0 };
  }

  // Extract date part from lastTrainedAt (ISO string, ignore time)
  const trainingDateStr = lastTrainedAt.split("T")[0];

  const actualMap = new Map<string, number>();
  for (const s of sales) {
    actualMap.set(s.date, s.quantity);
  }

  let sqErrSum = 0;
  let absPctSum = 0;
  let nRmse = 0;
  let nMape = 0;

  for (const f of forecast) {
    const actual = actualMap.get(f.ds);
    if (actual === undefined) continue;

    // Only count dates AFTER the training date
    // Compare dates as ISO strings (YYYY-MM-DD format)
    if (f.ds <= trainingDateStr) {
      continue; // Skip training data
    }

    const yhat = f.yhat;
    const err = yhat - actual;

    // RMSE uses all overlapping points
    sqErrSum += err * err;
    nRmse += 1;

    // MAPE skips days with 0 actual
    if (actual !== 0) {
      absPctSum += Math.abs(err / actual);
      nMape += 1;
    }
  }

  if (nRmse === 0) {
    return { mape: null, rmse: null, n_points: 0 };
  }

  const rmse = Math.sqrt(sqErrSum / nRmse);
  const mape = nMape > 0 ? (absPctSum / nMape) * 100 : null;

  return {
    mape,
    rmse,
    n_points: nRmse,
  };
}

function buildErrorSeries(
  sales: SalesPoint[],
  forecast: ForecastPoint[],
  lastTrainedAt: string | null = null
): ErrorPoint[] {
  if (sales.length === 0 || forecast.length === 0) return [];

  // If no training date, return empty series
  if (lastTrainedAt === null) {
    return [];
  }

  // Extract date part from lastTrainedAt (ISO string, ignore time)
  const trainingDateStr = lastTrainedAt.split("T")[0];

  const actualMap = new Map<string, number>();
  for (const s of sales) {
    actualMap.set(s.date, s.quantity);
  }

  const points: ErrorPoint[] = [];

  for (const f of forecast) {
    const actual = actualMap.get(f.ds);
    if (actual === undefined) continue;

    // Only count dates AFTER the training date
    // Compare dates as ISO strings (YYYY-MM-DD format)
    if (f.ds <= trainingDateStr) {
      continue; // Skip training data
    }

    const absError = Math.abs(f.yhat - actual);
    points.push({ date: f.ds, absError });
  }

  // Keep in chronological order
  return points.sort((a, b) => a.date.localeCompare(b.date));
}


