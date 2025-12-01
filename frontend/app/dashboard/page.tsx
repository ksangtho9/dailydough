"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchBakePlan, type BakePlanResponse } from "@/lib/bakePlan";
import {
  fetchDashboardSummary,
  type DashboardSummaryResponse,
} from "@/lib/dashboardSummary";
import { BAKERY_SELECTION_CHANGED_EVENT } from "@/lib/bakeries";
import { TopProductsCard } from "@/components/TopProductsCard";
import { GettingStartedChecklist } from "@/components/GettingStartedChecklist";
import { TextShimmer } from "@/components/ui/text-shimmer";
import { apiFetch } from "@/lib/api";
import type { ForecastMetrics } from "@/lib/metrics";
import { ForecastConfidenceBadge } from "@/components/ForecastConfidenceBadge";

const STORAGE_KEY = "current_bakery_id";
const DEV_MODE_KEY = "dashboard_dev_mode";

type TabKey = "bake" | "accuracy" | "insights";

type ProductWithMetrics = {
  id: number;
  name: string;
  sku?: string | null;
  bakery_id: number;
  forecast_metrics?: ForecastMetrics | null;
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

type ProductAccuracy = {
  productId: number;
  productName: string;
  mape: number | null;
  rmse: number | null;
  n_points: number;
  lastTrainedAt: string | null;
};

function formatFriendlyDate(input?: string) {
  if (!input) return "Tomorrow";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return "Tomorrow";
  return parsed.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

// Accuracy calculation utilities (from product detail page)
function normalizeSales(rawSales: any): SalesPoint[] {
  const sales: any[] = Array.isArray(rawSales)
    ? rawSales
    : rawSales?.sales || rawSales?.data || [];

  const totals = new Map<string, number>();

  for (const s of sales) {
    if (!s) continue;
    const date = s.date || s.ds;
    if (!date) continue;

    const qty = s.quantity ?? s.units_sold ?? s.qty ?? s.y ?? 0;
    const current = totals.get(date) ?? 0;
    totals.set(date, current + Number(qty));
  }

  return Array.from(totals.entries())
    .map(([date, quantity]) => ({ date, quantity }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function normalizeForecast(rawForecast: any): ForecastPoint[] {
  if (!rawForecast) return [];

  if (rawForecast.detail) {
    return [];
  }

  let forecast: any[] = [];

  if (Array.isArray(rawForecast)) {
    forecast = rawForecast;
  } else if (Array.isArray(rawForecast.forecast)) {
    forecast = rawForecast.forecast;
  } else if (Array.isArray(rawForecast.data)) {
    forecast = rawForecast.data;
  } else if (Array.isArray(rawForecast.points)) {
    forecast = rawForecast.points;
  }

  return forecast
    .map((f) => ({
      ds: f.ds || f.date,
      yhat: f.yhat ?? f.forecast ?? f.p50 ?? 0,
      yhat_lower: f.yhat_lower ?? f.lower ?? f.p10 ?? 0,
      yhat_upper: f.yhat_upper ?? f.upper ?? f.p90 ?? 0,
    }))
    .filter((f) => !!f.ds);
}

function computeForecastAccuracy(
  sales: SalesPoint[],
  forecast: ForecastPoint[],
  lastTrainedAt: string | null = null
): { mape: number | null; rmse: number | null; n_points: number } {
  if (sales.length === 0 || forecast.length === 0) {
    return { mape: null, rmse: null, n_points: 0 };
  }

  if (lastTrainedAt === null) {
    return { mape: null, rmse: null, n_points: 0 };
  }

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

    if (f.ds <= trainingDateStr) {
      continue;
    }

    const yhat = f.yhat;
    const err = yhat - actual;

    sqErrSum += err * err;
    nRmse += 1;

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

function generateMockBakePlan(bakeryId: number): BakePlanResponse {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const dateStr = tomorrow.toISOString().split("T")[0];

  const mockProducts = [
    { name: "Croissant", quantity: 45 },
    { name: "Sourdough Loaf", quantity: 28 },
    { name: "Chocolate Chip Cookie", quantity: 120 },
    { name: "Blueberry Muffin", quantity: 65 },
    { name: "Cinnamon Roll", quantity: 38 },
    { name: "Bagel", quantity: 85 },
    { name: "Danish Pastry", quantity: 52 },
    { name: "Apple Turnover", quantity: 42 },
  ];

  return {
    bakery_id: bakeryId,
    bakery_name: "Demo Bakery",
    date: dateStr,
    items: mockProducts.map((product, index) => ({
      product_id: 1000 + index, // Mock product IDs
      product_name: product.name,
      forecast_quantity: product.quantity,
    })),
  };
}

export default function DashboardPage() {
  const [bakeryId, setBakeryId] = useState<number | null>(null);
  const [bakePlan, setBakePlan] = useState<BakePlanResponse | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [dashboardSummary, setDashboardSummary] =
    useState<DashboardSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("bake");
  const [sortMode, setSortMode] = useState("sku");
  const [devMode, setDevMode] = useState(false);
  const [selectedForecastDate, setSelectedForecastDate] = useState<string | null>(null);
  
  // Accuracy tab state
  const [products, setProducts] = useState<ProductWithMetrics[]>([]);
  const [productsAccuracy, setProductsAccuracy] = useState<ProductAccuracy[]>([]);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  const [accuracyError, setAccuracyError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const asNum = Number(stored);
      if (!Number.isNaN(asNum)) {
        setBakeryId(asNum);
      }
    }
    // Load developer mode preference
    const devModeStored = window.localStorage.getItem(DEV_MODE_KEY);
    if (devModeStored === "true") {
      setDevMode(true);
    }
  }, []);

  const toggleDevMode = () => {
    const newValue = !devMode;
    setDevMode(newValue);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DEV_MODE_KEY, String(newValue));
    }
    // Reset date selection when disabling dev mode
    if (!newValue) {
      setSelectedForecastDate(null);
    }
  };

  useEffect(() => {
    function handleSelectionChange() {
      if (typeof window === "undefined") return;
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        setBakeryId(null);
        return;
      }
      const asNum = Number(stored);
      setBakeryId(Number.isNaN(asNum) ? null : asNum);
    }

    window.addEventListener(
      BAKERY_SELECTION_CHANGED_EVENT,
      handleSelectionChange
    );
    return () => {
      window.removeEventListener(
        BAKERY_SELECTION_CHANGED_EVENT,
        handleSelectionChange
      );
    };
  }, []);

  const loadPlan = useCallback(async (targetDate?: string) => {
    if (bakeryId == null) return;
    
    setPlanLoading(true);
    setPlanError(null);
    const dateToUse = targetDate || selectedForecastDate || undefined;
    console.log("[Dashboard] Loading bake plan for bakery:", bakeryId, "date:", dateToUse || "default (tomorrow)");
    
    try {
      const data = await fetchBakePlan(bakeryId, dateToUse);
      console.log("[Dashboard] Bake plan loaded successfully:", {
        itemsCount: data.items.length,
        date: data.date,
        bakeryName: data.bakery_name,
      });
      setBakePlan(data);
    } catch (err: any) {
      const errorMessage = err?.message ?? "Failed to load bake plan.";
      console.error("[Dashboard] Error loading bake plan:", {
        error: err,
        message: errorMessage,
        bakeryId,
        targetDate: dateToUse,
      });
      setPlanError(errorMessage);
      setBakePlan(null);
    } finally {
      setPlanLoading(false);
    }
  }, [bakeryId, selectedForecastDate]);

  useEffect(() => {
    if (bakeryId == null) return;
    // Only use selectedForecastDate if dev mode is enabled
    const dateToUse = devMode ? (selectedForecastDate || undefined) : undefined;
    loadPlan(dateToUse);
  }, [bakeryId, devMode, selectedForecastDate, loadPlan]);

  useEffect(() => {
    if (bakeryId == null) {
      setDashboardSummary(null);
      return;
    }
    let cancelled = false;

    async function loadSummary() {
      setSummaryLoading(true);
      setSummaryError(null);
      try {
        const data = await fetchDashboardSummary(bakeryId!);
        if (!cancelled) {
          setDashboardSummary(data);
        }
      } catch (err: any) {
        if (!cancelled) {
          setSummaryError(err?.message ?? "Failed to load summary metrics.");
          setDashboardSummary(null);
        }
      } finally {
        if (!cancelled) {
          setSummaryLoading(false);
        }
      }
    }

    loadSummary();
    return () => {
      cancelled = true;
    };
  }, [bakeryId]);

  // Load accuracy data when accuracy tab is active
  useEffect(() => {
    if (bakeryId == null || activeTab !== "accuracy") {
      setProducts([]);
      setProductsAccuracy([]);
      return;
    }

    let cancelled = false;

    async function loadAccuracyData() {
      setAccuracyLoading(true);
      setAccuracyError(null);

      try {
        // Fetch products with forecast metrics
        const productsData = await apiFetch<ProductWithMetrics[]>(
          `/api/products/?bakery_id=${bakeryId}`
        );

        if (cancelled) return;

        setProducts(productsData);

        // For each product, fetch sales and forecast data to calculate accuracy
        const accuracyPromises = productsData.map(async (product) => {
          try {
            // Fetch sales data
            const salesData = await apiFetch<any>(
              `/api/sales/product/${product.id}`
            );

            // Fetch forecast data (for a longer horizon to capture historical forecasts)
            const forecastData = await apiFetch<any>(
              `/api/forecast/product/${product.id}`,
              {
                method: "POST",
                body: JSON.stringify({ days: 30 }), // Get more historical forecast points
              }
            );

            const sales = normalizeSales(salesData);
            const forecast = normalizeForecast(forecastData);
            const lastTrainedAt = product.forecast_metrics?.last_trained_at ?? null;
            const accuracy = computeForecastAccuracy(sales, forecast, lastTrainedAt);

            return {
              productId: product.id,
              productName: product.name,
              mape: accuracy.mape,
              rmse: accuracy.rmse,
              n_points: accuracy.n_points,
              lastTrainedAt,
            } as ProductAccuracy;
          } catch (err) {
            console.error(`Failed to load accuracy for product ${product.id}:`, err);
            return {
              productId: product.id,
              productName: product.name,
              mape: null,
              rmse: null,
              n_points: 0,
              lastTrainedAt: product.forecast_metrics?.last_trained_at ?? null,
            } as ProductAccuracy;
          }
        });

        const accuracyResults = await Promise.all(accuracyPromises);

        if (!cancelled) {
          setProductsAccuracy(accuracyResults);
        }
      } catch (err: any) {
        if (!cancelled) {
          setAccuracyError(err?.message ?? "Failed to load accuracy data.");
          setProducts([]);
          setProductsAccuracy([]);
        }
      } finally {
        if (!cancelled) {
          setAccuracyLoading(false);
        }
      }
    }

    loadAccuracyData();

    return () => {
      cancelled = true;
    };
  }, [bakeryId, activeTab]);

  // In dev mode, use real API data (based on uploaded sales data)
  // No longer using mock data - dev mode now allows date selection and uses real forecasts
  const displayBakePlan = bakePlan;

  const isShowingMockData = false; // No longer using mock data

  const totalUnits = useMemo(() => {
    if (!displayBakePlan) return null;
    return displayBakePlan.items.reduce((sum, item) => sum + item.forecast_quantity, 0);
  }, [displayBakePlan]);

  const tableRows = useMemo(() => {
    if (!displayBakePlan) return [];
    const rows = displayBakePlan.items.map((item, index) => {
      const normal = item.forecast_quantity;
      const low = Math.max(0, Math.round(normal * 0.9));
      const high = Math.round(normal * 1.1);
      const waste = 7 + (index % 3) * 0.6;
      const risk = 10 + (index % 4) * 1.5;
      return {
        ...item,
        low,
        normal,
        high,
        recommended: normal,
        waste,
        risk,
      };
    });

    // Apply sorting based on sortMode
    const sorted = [...rows].sort((a, b) => {
      switch (sortMode) {
        case "sku":
          // Sort by SKU alphabetically, null/empty values go to the end
          const aSku = a.sku || "";
          const bSku = b.sku || "";
          if (!aSku && !bSku) return 0;
          if (!aSku) return 1;
          if (!bSku) return -1;
          return aSku.localeCompare(bSku);
        case "product_name":
          return a.product_name.localeCompare(b.product_name);
        case "demand":
          return b.forecast_quantity - a.forecast_quantity; // Highest first
        case "category":
          // Category sorting not implemented yet, keep original order
          return 0;
        default:
          return 0;
      }
    });

    return sorted;
  }, [displayBakePlan, sortMode]);

  // Calculate aggregate accuracy statistics
  const accuracyStats = useMemo(() => {
    const validAccuracies = productsAccuracy.filter((p) => p.mape !== null);
    const mapeValues = validAccuracies.map((p) => p.mape!);
    const rmseValues = validAccuracies.map((p) => p.rmse!).filter((r) => r !== null);
    const totalDataPoints = validAccuracies.reduce((sum, p) => sum + p.n_points, 0);
    const highRiskCount = validAccuracies.filter((p) => p.mape! > 25).length;
    const goodAccuracyCount = validAccuracies.filter((p) => p.mape! <= 10).length;

    return {
      avgMape: mapeValues.length > 0 ? mapeValues.reduce((a, b) => a + b, 0) / mapeValues.length : null,
      avgRmse: rmseValues.length > 0 ? rmseValues.reduce((a, b) => a + b, 0) / rmseValues.length : null,
      totalDataPoints,
      highRiskCount,
      goodAccuracyCount,
      totalProducts: productsAccuracy.length,
      trainedProducts: validAccuracies.length,
    };
  }, [productsAccuracy]);

  const summaryCards = [
    {
      title: "Recommended Bake",
      value:
        dashboardSummary?.recommended_bake != null
          ? dashboardSummary.recommended_bake.toLocaleString()
          : totalUnits !== null
            ? totalUnits.toLocaleString()
            : "—",
      helper: "Total units",
      accent: "bg-white shadow-sm",
    },
    {
      title: "Expected Waste",
      value:
        dashboardSummary?.expected_waste_pct != null
          ? `${(dashboardSummary.expected_waste_pct * 100).toFixed(1)}%`
          : "—",
      helper: "Based on recent sell-through",
      accent: "bg-[#FFF8EE] border border-[#F7DEC7]",
    },
    {
      title: "High Risk Items",
      value:
        dashboardSummary?.high_risk_items != null
          ? dashboardSummary.high_risk_items
          : "—",
      helper: "Products with post-training MAPE > 25%",
      accent: "bg-[#FFECEC] border border-rose-100",
    },
    {
      title: "Forecast Accuracy",
      value:
        dashboardSummary?.forecast_accuracy_pct != null
          ? `${dashboardSummary.forecast_accuracy_pct.toFixed(1)}%`
          : "—",
      helper: "Post-training avg MAPE (lower is better)",
      accent: "bg-[#E9F8EF] border border-emerald-100",
    },
  ];

  const planDateLabel = formatFriendlyDate(displayBakePlan?.date);

  const tabButtons: { key: TabKey; label: string }[] = [
    { key: "bake", label: "Bake Plan" },
    { key: "accuracy", label: "Accuracy" },
    { key: "insights", label: "Insights" },
  ];

  if (!bakeryId) {
    return (
      <div className="space-y-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm text-slate-600">
            No bakery selected yet. Go to the{" "}
            <Link href="/bakeries" className="font-medium text-amber-700 hover:underline">
              Bakeries page
            </Link>{" "}
            to create your first bakery.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {summaryCards.map((card) => (
          <div
            key={card.title}
            className={`rounded-xl p-8 shadow-sm min-h-[160px] ${card.accent}`}
          >
            <p className="text-sm font-semibold uppercase tracking-wide text-slate-600">
              {card.title}
            </p>
            <p className="mt-3 text-3xl font-bold text-slate-900">
              {card.value}
            </p>
            <p className="mt-1 text-xs text-slate-500">{card.helper}</p>
          </div>
        ))}
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-full bg-white/70 p-1 shadow-sm">
          {tabButtons.map((tab) => {
            const active = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
                  active
                    ? "bg-amber-500 text-white shadow"
                    : "text-slate-700 hover:bg-amber-50"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === "bake" && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <section className="rounded-xl border border-amber-100 bg-white p-8 shadow-sm min-h-[250px]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-xs uppercase text-slate-600">
                    {devMode && selectedForecastDate
                      ? "Forecast for Selected Date"
                      : "Tomorrow's Forecast"}
                  </p>
                  {devMode && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-700">
                      DEV MODE
                    </span>
                  )}
                </div>
                <h2 className="text-xl font-semibold text-slate-900">
                  {planDateLabel}
                </h2>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={toggleDevMode}
                  className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium transition ${
                    devMode
                      ? "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100"
                      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-100"
                  }`}
                  title="Toggle developer mode to test forecasts with real data and date selection"
                >
                  🧪 Dev Mode
                </button>
                {devMode && (
                  <input
                    type="date"
                    value={selectedForecastDate || ""}
                    onChange={(e) => {
                      const newDate = e.target.value;
                      setSelectedForecastDate(newDate || null);
                      if (newDate && bakeryId) {
                        loadPlan(newDate);
                      }
                    }}
                    className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-400/20"
                    title="Select date to forecast for (dev mode only - past or future dates allowed)"
                  />
                )}
                <select
                  value={sortMode}
                  onChange={(e) => setSortMode(e.target.value)}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 focus:outline-none"
                >
                  <option value="sku">SKU</option>
                  <option value="product_name">Product Name (A-Z)</option>
                  <option value="demand">Highest demand</option>
                  <option value="category">Category</option>
                </select>
                <button
                  type="button"
                  onClick={() => {
                    console.log("[Dashboard] Manual refresh triggered");
                    const dateToUse = devMode ? (selectedForecastDate || undefined) : undefined;
                    loadPlan(dateToUse);
                  }}
                  disabled={planLoading}
                  className="inline-flex items-center rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  ↻ Refresh forecasts
                </button>
              </div>
            </div>

            <div className="mt-4 overflow-x-auto">
              {planLoading && (
                <TextShimmer className="text-sm text-slate-500" duration={1.5}>
                  Loading tomorrow&apos;s forecast...
                </TextShimmer>
              )}
              {planError && (
                <p className="text-sm text-red-600">{planError}</p>
              )}
              {!planLoading && !planError && tableRows.length === 0 && (
                <div className="space-y-2">
                  <p className="text-sm text-slate-500">
                    No products available yet. Upload sales data to generate a bake
                    plan.
                  </p>
                  {bakePlan && bakePlan.items.length === 0 && (
                    <p className="text-xs text-slate-400 italic">
                      Note: API returned empty items array. This may indicate no products have forecasts for the selected date, or forecast generation failed for all products.
                      {devMode && selectedForecastDate && (
                        <span> Try selecting a different date or ensure you have uploaded sales data.</span>
                      )}
                    </p>
                  )}
                  {devMode && (
                    <p className="text-xs text-amber-600 italic">
                      💡 Dev Mode: Use the date picker above to test forecasts for different dates. Forecasts are based on your uploaded sales data.
                    </p>
                  )}
                </div>
              )}
              {!planLoading && !planError && tableRows.length > 0 && (
                <table className="min-w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">SKU</th>
                      <th className="px-3 py-2 text-left">Category</th>
                      <th className="px-3 py-2 text-right">Low</th>
                      <th className="px-3 py-2 text-right">Normal</th>
                      <th className="px-3 py-2 text-right">High</th>
                      <th className="px-3 py-2 text-right">Recommended</th>
                      <th className="px-3 py-2 text-right">Est. waste</th>
                      <th className="px-3 py-2 text-right">Stockout risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((row, idx) => (
                      <tr
                        key={row.product_id}
                        className={`border-b border-slate-100 ${
                          idx % 2 === 1 ? "bg-slate-50/50" : "bg-white"
                        }`}
                      >
                        <td className="px-3 py-2 font-semibold text-slate-900">
                          {row.product_name}
                        </td>
                        <td className="px-3 py-2">
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                            Pastry
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right text-slate-600">
                          {row.low}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-900">
                          {row.normal}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-600">
                          {row.high}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold text-amber-700">
                          {row.recommended}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-600">
                          {row.waste.toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 text-right text-slate-600">
                          {row.risk.toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-amber-100 bg-white p-8 shadow-sm min-h-[250px]">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                Forecast drivers
              </h3>
              <p className="mt-1 text-xs text-slate-600">
                We’ll show key factors nudging tomorrow&apos;s bake once driver
                data is available.
              </p>
            </div>
            <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 p-4">
              <p className="text-sm text-slate-600">
                No forecast drivers yet. Once we add weather, events, and promo
                signals to the model, they will appear here.
              </p>
            </div>
          </section>
        </div>
      )}

      {activeTab === "accuracy" && (
        <div className="space-y-6">
          {/* Summary Cards */}
          <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-500">
                Average MAPE
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {accuracyStats.avgMape !== null
                  ? `${accuracyStats.avgMape.toFixed(1)}%`
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Mean absolute percentage error across all products
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-500">
                Average RMSE
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {accuracyStats.avgRmse !== null
                  ? accuracyStats.avgRmse.toFixed(1)
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Root mean squared error in units
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-500">
                Products Trained
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {accuracyStats.trainedProducts} / {accuracyStats.totalProducts}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Products with accuracy data
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-500">
                High Risk Items
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {accuracyStats.highRiskCount}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Products with MAPE &gt; 25%
              </p>
            </div>
          </section>

          {/* Products Table */}
          <section className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
            <div className="mb-4">
              <h3 className="text-lg font-semibold text-slate-900">
                Product Accuracy
              </h3>
              <p className="text-sm text-slate-600">
                Accuracy metrics for each product, calculated on post-training data only.
              </p>
            </div>

            {accuracyLoading && (
              <div className="py-8">
                <TextShimmer className="text-sm text-slate-500" duration={1.5}>
                  Loading accuracy data...
                </TextShimmer>
              </div>
            )}

            {accuracyError && (
              <div className="py-8">
                <p className="text-sm text-red-600">Error: {accuracyError}</p>
              </div>
            )}

            {!accuracyLoading && !accuracyError && productsAccuracy.length === 0 && (
              <div className="py-8">
                <p className="text-sm text-slate-500">
                  No products found. Create products and train models to see accuracy metrics.
                </p>
              </div>
            )}

            {!accuracyLoading && !accuracyError && productsAccuracy.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3 text-left">Product</th>
                      <th className="px-4 py-3 text-right">MAPE</th>
                      <th className="px-4 py-3 text-right">RMSE</th>
                      <th className="px-4 py-3 text-right">Data Points</th>
                      <th className="px-4 py-3 text-center">
                        <span className="tooltip" title="Training-time model confidence based on training data fit">
                          Status
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {productsAccuracy.map((product, idx) => {
                      const productWithMetrics = products.find(
                        (p) => p.id === product.productId
                      );
                      return (
                        <tr
                          key={product.productId}
                          className={`border-b border-slate-100 ${
                            idx % 2 === 1 ? "bg-slate-50/50" : "bg-white"
                          }`}
                        >
                          <td className="px-4 py-3">
                            <Link
                              href={`/products/${product.productId}`}
                              className="font-medium text-slate-900 hover:text-amber-700 hover:underline"
                            >
                              {product.productName}
                            </Link>
                          </td>
                          <td className="px-4 py-3 text-right text-slate-900">
                            {product.mape !== null
                              ? `${product.mape.toFixed(1)}%`
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {product.rmse !== null
                              ? product.rmse.toFixed(1)
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {product.n_points}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {productWithMetrics && (
                              <ForecastConfidenceBadge
                                metrics={productWithMetrics.forecast_metrics ?? null}
                              />
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {!accuracyLoading && !accuracyError && productsAccuracy.length > 0 && (
              <div className="mt-4 text-xs text-slate-500 space-y-1">
                <p>
                  💡 Accuracy (MAPE/RMSE) is calculated only on dates after model training, excluding the initial training data.
                  Click on any product to see detailed accuracy metrics and charts.
                </p>
                <p>
                  📊 Status badge shows training-time model confidence (based on how well the model fit the training data), not real-world post-training accuracy.
                </p>
              </div>
            )}
          </section>
        </div>
      )}

      {activeTab === "insights" && (
        <section className="grid gap-6 lg:grid-cols-2">
          {bakeryId ? (
            <TopProductsCard bakeryId={bakeryId} />
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm min-h-[250px] text-sm text-slate-600">
              Select a bakery to view top products.
            </div>
          )}
          <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm min-h-[250px]">
            <h3 className="text-sm font-semibold text-slate-900">
              Getting started
            </h3>
            <p className="text-xs text-slate-600 mb-3">
              Quick checklist to unlock all analytics.
            </p>
            <GettingStartedChecklist />
          </div>
        </section>
      )}
    </div>
  );
}
