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

const STORAGE_KEY = "current_bakery_id";
const DEV_MODE_KEY = "dashboard_dev_mode";

type TabKey = "bake" | "accuracy" | "insights" | "ask";

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
    return displayBakePlan.items.map((item, index) => {
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
  }, [displayBakePlan]);

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
      helper: "MAPE > 25%",
      accent: "bg-[#FFECEC] border border-rose-100",
    },
    {
      title: "Forecast Accuracy",
      value:
        dashboardSummary?.forecast_accuracy_pct != null
          ? `${dashboardSummary.forecast_accuracy_pct.toFixed(1)}%`
          : "—",
      helper: "Avg MAPE (lower is better)",
      accent: "bg-[#E9F8EF] border border-emerald-100",
    },
  ];

  const planDateLabel = formatFriendlyDate(displayBakePlan?.date);

  const tabButtons: { key: TabKey; label: string }[] = [
    { key: "bake", label: "Bake Plan" },
    { key: "accuracy", label: "Accuracy" },
    { key: "insights", label: "Insights" },
    { key: "ask", label: "Ask AI" },
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
                  <option value="sku">SKU Name (A-Z)</option>
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
        <section className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm min-h-[250px] space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              Model accuracy
            </h3>
            <p className="text-sm text-slate-600">
              Track how forecasts compare to actuals over time. Accuracy
              breakdown by SKU is coming soon.
            </p>
          </div>
        </section>
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

      {activeTab === "ask" && (
        <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              Ask the planning assistant
            </h3>
            <p className="text-sm text-slate-600">
              Describe a scenario and the assistant will outline a bake plan.
            </p>
          </div>
          <textarea
            className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm focus:border-amber-400 focus:outline-none"
            rows={4}
            placeholder="e.g. “What should I bake if rain is forecasted and payday is this Friday?”"
          />
          <button
            type="button"
            className="inline-flex items-center rounded-full bg-amber-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-amber-600"
          >
            Ask AI
          </button>
        </section>
      )}
    </div>
  );
}
