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
import { apiFetch, adminStartRetrain, adminGetTrainingStatus, adminCancelTrainingJob, type JobStatusResponse, fetchProducts, type Product } from "@/lib/api";
import type { ForecastMetrics } from "@/lib/metrics";
import { ForecastConfidenceBadge } from "@/components/ForecastConfidenceBadge";
import { AdminOnly } from "@/components/AdminOnly";
import { isAdminMode, isDevMode } from "@/lib/admin";

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
  wape: number | null;
  n_points: number;
  valid_points_count: number | null;
  lastTrainedAt: string | null;
  start_date: string | null;
  end_date: string | null;
};

type ForecastVsActualRow = {
  date: string;
  actual: number | null;
  forecast: number | null;
  error: number | null;
  abs_error: number | null;
  pct_error: number | null;
};

type ForecastVsActualData = {
  product_id: number;
  rows: ForecastVsActualRow[];
  wape: number | null;
  valid_points_count: number;
  start_date: string;
  end_date: string;
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
  
  // Date selection state - default to range mode with last 30 days to ensure WAPE is calculated
  const [dateMode, setDateMode] = useState<"single" | "range">("range");
  const [singleDate, setSingleDate] = useState<string>(() => {
    const date = new Date();
    date.setDate(date.getDate() - 1); // Yesterday
    return date.toISOString().split('T')[0];
  });
  const [startDate, setStartDate] = useState<string>(() => {
    const date = new Date();
    date.setDate(date.getDate() - 30);
    return date.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState<string>(() => {
    const date = new Date();
    date.setDate(date.getDate() - 1); // Yesterday
    return date.toISOString().split('T')[0];
  });
  
  // Forecast vs actual data state
  const [forecastVsActualData, setForecastVsActualData] = useState<ForecastVsActualData | null>(null);
  const [forecastVsActualLoading, setForecastVsActualLoading] = useState(false);
  const [forecastVsActualError, setForecastVsActualError] = useState<string | null>(null);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  
  // Admin retrain state
  const [showRetrainModal, setShowRetrainModal] = useState(false);
  const [retrainJobStatus, setRetrainJobStatus] = useState<JobStatusResponse | null>(null);
  const [retrainLoading, setRetrainLoading] = useState(false);
  const [selectedProductIds, setSelectedProductIds] = useState<number[]>([]);
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);
  const [productsLoading, setProductsLoading] = useState(false);
  const [productsError, setProductsError] = useState<string | null>(null);

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
  
  // Check for existing training job on page load (e.g., after refresh)
  // This runs after component mount to ensure all functions are defined
  useEffect(() => {
    // Only check if admin mode is enabled
    if (!isAdminMode()) return;
    
    adminGetTrainingStatus()
      .then((status) => {
        // If there's a running or cancelling job, restore the UI and resume polling
        // Do NOT restore cancelled jobs - once dismissed, they should stay dismissed
        if (status.status === "running" || status.status === "cancelling") {
          setRetrainJobStatus(status);
          if (status.job_id) {
            startPolling(status.job_id);
          }
        }
        // Cancelled jobs are intentionally not restored on page load
      })
      .catch((error) => {
        // Silently fail - no job running or API error
        // Don't show error to user as this is just a background check
        console.log("No existing training job found:", error);
      });
  }, []); // Empty deps - only run once on mount

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

  // Admin retrain handlers
  const startRetrain = async (productIds?: number[] | null) => {
    try {
      setRetrainLoading(true);
      const response = await adminStartRetrain(productIds, bakeryId);
      setRetrainJobStatus({
        status: "running",
        job_id: response.job_id,
        progress: { completed: 0, total: response.total },
        errors: [],
      });
      setShowRetrainModal(false);
      // Start polling
      startPolling(response.job_id);
    } catch (error: any) {
      alert(`Failed to start retrain: ${error.message}`);
      setRetrainLoading(false);
    }
  };

  const startPolling = (jobId: string) => {
    // Clear existing interval
    if (pollingInterval) {
      clearInterval(pollingInterval);
    }
    
    const interval = setInterval(async () => {
      try {
        const status = await adminGetTrainingStatus(jobId);
        setRetrainJobStatus(status);
        
          // Stop polling if job is done
          if (status.status === "completed" || status.status === "failed" || status.status === "completed_with_errors" || status.status === "cancelled") {
            clearInterval(interval);
            setPollingInterval(null);
            setRetrainLoading(false);
            
            // Refresh dashboard data
            if (bakeryId) {
              loadPlan();
              // Reload summary and accuracy data
              window.location.reload(); // Simple refresh for now
            }
            
            // Show completion message
            if (status.status === "completed") {
              alert("Training completed successfully!");
            } else if (status.status === "completed_with_errors") {
              alert(`Training completed with ${status.errors.length} errors. Check details below.`);
            } else if (status.status === "cancelled") {
              alert("Training was cancelled.");
            } else {
              alert("Training failed. Check details below.");
            }
          }
          
          // If status is "cancelling", show that cancellation is in progress
          // Don't stop polling yet - wait for it to become "cancelled"
          if (status.status === "cancelling") {
            // Status panel will show "Training Cancelled" message
            // Keep polling until status becomes "cancelled"
          }
      } catch (error) {
        console.error("Error polling training status:", error);
      }
    }, 2000); // Poll every 2 seconds
    
    setPollingInterval(interval);
  };

  const cancelTraining = async () => {
    if (!retrainJobStatus?.job_id) return;
    
    if (!confirm("Are you sure you want to cancel the training job? It will stop after the current product completes.")) {
      return;
    }
    
    try {
      await adminCancelTrainingJob(retrainJobStatus.job_id);
      // Immediately fetch status to show "cancelling" right away
      const updatedStatus = await adminGetTrainingStatus(retrainJobStatus.job_id);
      setRetrainJobStatus(updatedStatus);
      // Polling will continue and detect when status becomes "cancelled"
    } catch (error: any) {
      alert(`Failed to cancel training: ${error.message}`);
    }
  };

  useEffect(() => {
    // Cleanup polling on unmount
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  // Load products when retrain modal opens
  useEffect(() => {
    if (!showRetrainModal || bakeryId == null) {
      return;
    }

    let cancelled = false;

    async function loadProductsForRetrain() {
      setProductsLoading(true);
      setProductsError(null);
      try {
        const fetchedProducts = await fetchProducts(bakeryId);
        if (!cancelled) {
          setProducts(fetchedProducts);
        }
      } catch (err: any) {
        if (!cancelled) {
          setProductsError(err?.message ?? "Failed to load products.");
          setProducts([]);
        }
      } finally {
        if (!cancelled) {
          setProductsLoading(false);
        }
      }
    }

    loadProductsForRetrain();

    return () => {
      cancelled = true;
    };
  }, [showRetrainModal, bakeryId]);

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
    
    try {
      const data = await fetchBakePlan(bakeryId, dateToUse);
      
      // Dev-mode console logging
      if (isDevMode()) {
        console.log(
          `BAKE_PLAN_API_RESPONSE: endpoint=GET /api/bakeries/${bakeryId}/bake-plan${dateToUse ? `?target_date=${dateToUse}` : ""}, ` +
          `items_count=${data.items.length}, ` +
          `response_shape=${JSON.stringify(Object.keys(data))}`
        );
        // Log risk values for first 3 items
        const first3 = data.items.slice(0, 3).map((item) => ({
          product_id: item.product_id,
          product_name: item.product_name,
          forecast_quantity: item.forecast_quantity,
          waste_risk_prob: item.waste_risk_prob,
          stockout_risk_prob: item.stockout_risk_prob,
          risk_method: item.risk_method,
          interval_level_used: item.interval_level_used,
        }));
        console.log("BAKE_PLAN_RISK_VALUES_FIRST_3:", JSON.stringify(first3, null, 2));
      }
      
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

  // Load accuracy data when accuracy tab is active or date range changes
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
        // Build query params for date filtering
        // Always provide dates to ensure WAPE is calculated (default to last 30 days if not set)
        const params = new URLSearchParams();
        if (dateMode === "single" && singleDate) {
          params.append('start_date', singleDate);
          // end_date not provided = single date mode
        } else if (dateMode === "range") {
          if (startDate) params.append('start_date', startDate);
          if (endDate) params.append('end_date', endDate);
        } else {
          // Default to last 30 days if no dates selected
          params.append('start_date', startDate);
          params.append('end_date', endDate);
        }
        const queryString = params.toString();
        const url = `/api/forecast-accuracy/bakery/${bakeryId}${queryString ? `?${queryString}` : ''}`;
        
        // Fetch per-product accuracy metrics with date filtering
        const accuracyResults = await apiFetch<ProductAccuracy[]>(url);

        if (!cancelled) {
          // Map API response to frontend format
          setProductsAccuracy(accuracyResults.map((r: any) => ({
            productId: r.product_id,
            productName: r.product_name,
            mape: r.mape,
            rmse: r.rmse,
            wape: r.wape,
            n_points: r.n_points,
            valid_points_count: r.valid_points_count ?? null,
            lastTrainedAt: r.last_trained_at,
            start_date: r.start_date,
            end_date: r.end_date,
          })));
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
  }, [bakeryId, activeTab, dateMode, singleDate, startDate, endDate]);

  // Load forecast vs actual data when product is selected
  useEffect(() => {
    if (selectedProductId == null || activeTab !== "accuracy") {
      setForecastVsActualData(null);
      return;
    }

    let cancelled = false;

    async function loadForecastVsActual() {
      setForecastVsActualLoading(true);
      setForecastVsActualError(null);

      try {
        const params = new URLSearchParams();
        if (dateMode === "single" && singleDate) {
          params.append('start_date', singleDate);
          params.append('end_date', singleDate);
        } else if (dateMode === "range") {
          if (startDate) params.append('start_date', startDate);
          if (endDate) params.append('end_date', endDate);
        }
        const queryString = params.toString();
        const url = `/api/products/${selectedProductId}/forecast-vs-actual${queryString ? `?${queryString}` : ''}`;
        
        const data = await apiFetch<ForecastVsActualData>(url);

        if (!cancelled) {
          setForecastVsActualData(data);
        }
      } catch (err: any) {
        if (!cancelled) {
          setForecastVsActualError(err?.message ?? "Failed to load forecast vs actual data.");
          setForecastVsActualData(null);
        }
      } finally {
        if (!cancelled) {
          setForecastVsActualLoading(false);
        }
      }
    }

    loadForecastVsActual();

    return () => {
      cancelled = true;
    };
  }, [selectedProductId, dateMode, singleDate, startDate, endDate, activeTab]);

  // In dev mode, use real API data (based on uploaded sales data)
  // No longer using mock data - dev mode now allows date selection and uses real forecasts
  const displayBakePlan = bakePlan;

  const isShowingMockData = false; // No longer using mock data

  const totalUnits = useMemo(() => {
    if (!displayBakePlan) return null;
    return displayBakePlan.items.reduce(
      (sum, item) => sum + Math.round(item.forecast_quantity),
      0
    );
  }, [displayBakePlan]);

  const tableRows = useMemo(() => {
    if (!displayBakePlan) return [];
    const rows = displayBakePlan.items.map((item) => {
      const normal = Math.round(item.forecast_quantity);
      const low = Math.max(0, Math.round(normal * 0.9));
      const high = Math.round(normal * 1.1);
      
      // Use API-provided risk metrics (convert from 0-1 probability to percentage)
      const waste = item.waste_risk_prob != null 
        ? item.waste_risk_prob * 100 
        : null;
      const risk = item.stockout_risk_prob != null 
        ? item.stockout_risk_prob * 100 
        : null;
      
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

  // Calculate aggregate accuracy statistics (using WAPE as primary metric)
  const accuracyStats = useMemo(() => {
    const validAccuracies = productsAccuracy.filter((p) => p.wape !== null);
    const wapeValues = validAccuracies.map((p) => p.wape!);
    const mapeValues = productsAccuracy.map((p) => p.mape).filter((m) => m !== null) as number[];
    const rmseValues = productsAccuracy.map((p) => p.rmse).filter((r) => r !== null) as number[];
    const totalDataPoints = validAccuracies.reduce((sum, p) => sum + (p.valid_points_count ?? p.n_points), 0);
    const highRiskCount = validAccuracies.filter((p) => p.wape! > 25).length;
    const goodAccuracyCount = validAccuracies.filter((p) => p.wape! <= 10).length;

    return {
      avgWape: wapeValues.length > 0 ? wapeValues.reduce((a, b) => a + b, 0) / wapeValues.length : null,
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
        totalUnits !== null
          ? totalUnits.toLocaleString()
          : dashboardSummary?.recommended_bake != null
            ? dashboardSummary.recommended_bake.toLocaleString()
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
      title: "Forecast Error (WAPE)",
      value:
        dashboardSummary?.post_training_wape != null
          ? `${dashboardSummary.post_training_wape.toFixed(1)}%`
          : "—",
      helper: "Post-training, volume-weighted error (lower is better)",
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
                <AdminOnly>
                  <button
                    type="button"
                    onClick={() => setShowRetrainModal(true)}
                    disabled={retrainLoading || (retrainJobStatus?.status === "running")}
                    className="inline-flex items-center rounded-full border border-purple-300 bg-purple-50 px-3 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Retrain models (admin only)"
                  >
                    🔄 Retrain Models
                  </button>
                </AdminOnly>
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
                          {row.waste != null ? row.waste.toFixed(0) + "%" : "—"}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-600">
                          {row.risk != null ? row.risk.toFixed(0) + "%" : "—"}
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
              <p className="text-xs uppercase text-slate-700 font-semibold">
                Average WAPE
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">
                {accuracyStats.avgWape !== null
                  ? `${accuracyStats.avgWape.toFixed(1)}%`
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Weighted absolute percentage error (primary metric)
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-700 font-semibold">
                Average RMSE
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">
                {accuracyStats.avgRmse !== null
                  ? accuracyStats.avgRmse.toFixed(1)
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Root mean squared error in units
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-700 font-semibold">
                Products Trained
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">
                {accuracyStats.trainedProducts} / {accuracyStats.totalProducts}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Products with accuracy data
              </p>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <p className="text-xs uppercase text-slate-700 font-semibold">
                High Risk Items
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">
                {accuracyStats.highRiskCount}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Products with WAPE &gt; 25%
              </p>
            </div>
          </section>

          {/* Date Selection Picker */}
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-4 flex-wrap">
              <label className="text-sm font-medium text-slate-900">Date Selection:</label>
              <select
                value={dateMode}
                onChange={(e) => setDateMode(e.target.value as "single" | "range")}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
              >
                <option value="single">Single Date</option>
                <option value="range">Date Range</option>
              </select>
              
              {dateMode === "single" ? (
                <input
                  type="date"
                  value={singleDate}
                  onChange={(e) => setSingleDate(e.target.value)}
                  className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                />
              ) : (
                <>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                  />
                  <span className="text-sm text-slate-700 font-medium">to</span>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                  />
                </>
              )}
              
              {forecastVsActualData && (
                <span className="ml-auto text-xs text-slate-700">
                  {forecastVsActualData.valid_points_count} valid data points
                </span>
              )}
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
                      <th className="px-4 py-3 text-right">WAPE</th>
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
                            <button
                              onClick={() => setSelectedProductId(product.productId)}
                              className={`font-medium hover:text-amber-700 hover:underline ${
                                selectedProductId === product.productId
                                  ? "text-amber-700 underline"
                                  : "text-slate-900"
                              }`}
                            >
                              {product.productName}
                            </button>
                          </td>
                          <td className="px-4 py-3 text-right text-slate-900">
                            {product.wape !== null
                              ? `${product.wape.toFixed(1)}%`
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {product.rmse !== null
                              ? product.rmse.toFixed(1)
                              : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {product.valid_points_count ?? product.n_points}
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
                  💡 Accuracy (WAPE/RMSE) is calculated for the selected date range. Click on any product to see forecast vs actual comparison.
                </p>
                <p>
                  📊 Status badge shows training-time model confidence (based on how well the model fit the training data), not real-world post-training accuracy.
                </p>
              </div>
            )}
          </section>

          {/* Forecast vs Actual Table */}
          {selectedProductId && (
            <section className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
              <div className="mb-4">
                <h3 className="text-lg font-semibold text-slate-900">
                  Forecast vs Actual
                </h3>
                <p className="text-sm text-slate-600">
                  {forecastVsActualData && (
                    <>
                      <span className="font-medium">WAPE: {forecastVsActualData.wape !== null ? `${forecastVsActualData.wape.toFixed(1)}%` : "—"}</span>
                      <span className="text-slate-500" title="WAPE (Weighted Absolute Percentage Error) is calculated as an aggregate metric over all dates in the range. Even if one date matches perfectly, other dates with errors will contribute to a non-zero WAPE.">
                        {" "}(aggregate over {forecastVsActualData.valid_points_count} dates)
                      </span>
                      {" • "}
                      Date Range: {forecastVsActualData.start_date} to {forecastVsActualData.end_date}
                    </>
                  )}
                </p>
                {forecastVsActualData && forecastVsActualData.valid_points_count > 0 && (
                  <p className="mt-2 text-xs text-slate-500">
                    💡 <strong>Note:</strong> WAPE is calculated over all {forecastVsActualData.valid_points_count} dates in the range. 
                    Individual date errors are shown in the "% Error" column. 
                    A single date matching perfectly doesn't guarantee WAPE = 0% if other dates have errors.
                  </p>
                )}
              </div>

              {forecastVsActualLoading && (
                <div className="py-8">
                  <TextShimmer className="text-sm text-slate-500" duration={1.5}>
                    Loading forecast vs actual data...
                  </TextShimmer>
                </div>
              )}

              {forecastVsActualError && (
                <div className="py-8">
                  <p className="text-sm text-red-600">Error: {forecastVsActualError}</p>
                </div>
              )}

              {!forecastVsActualLoading && !forecastVsActualError && forecastVsActualData && (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="px-4 py-3 text-left">Date</th>
                        <th className="px-4 py-3 text-right">Forecast</th>
                        <th className="px-4 py-3 text-right">Actual</th>
                        <th className="px-4 py-3 text-right">Error</th>
                        <th className="px-4 py-3 text-right">Abs Error</th>
                        <th className="px-4 py-3 text-right">% Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {forecastVsActualData.rows.map((row, idx) => (
                        <tr
                          key={row.date}
                          className={`border-b border-slate-100 ${
                            idx % 2 === 1 ? "bg-slate-50/50" : "bg-white"
                          }`}
                        >
                          <td className="px-4 py-3 text-slate-900">{row.date}</td>
                          <td className="px-4 py-3 text-right text-slate-900">
                            {row.forecast !== null ? row.forecast.toFixed(1) : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-900">
                            {row.actual !== null ? row.actual.toFixed(1) : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {row.error !== null ? row.error.toFixed(1) : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {row.abs_error !== null ? row.abs_error.toFixed(1) : "—"}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {row.pct_error !== null ? `${row.pct_error.toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!forecastVsActualLoading && !forecastVsActualError && !forecastVsActualData && (
                <div className="py-8">
                  <p className="text-sm text-slate-500">
                    Select a product from the table above to view forecast vs actual comparison.
                  </p>
                </div>
              )}
            </section>
          )}
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

      {/* Retrain Modal */}
      {showRetrainModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[90vh] flex flex-col">
            <h3 className="text-lg font-semibold text-slate-900 mb-4">Retrain Models</h3>
            
            <div className="space-y-4 flex-1 overflow-y-auto">
              <button
                type="button"
                onClick={() => startRetrain(null)}
                disabled={retrainLoading}
                className="w-full rounded-lg border border-purple-300 bg-purple-50 px-4 py-2 text-sm font-medium text-purple-700 hover:bg-purple-100 disabled:opacity-50"
              >
                Retrain All Products
              </button>
              
              <div className="border-t pt-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-sm font-medium text-slate-700">
                    Or select specific products:
                  </label>
                  {products.length > 0 && (
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          if (selectedProductIds.length === products.length) {
                            setSelectedProductIds([]);
                          } else {
                            setSelectedProductIds(products.map(p => p.id));
                          }
                        }}
                        className="text-xs px-2 py-1 rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      >
                        {selectedProductIds.length === products.length ? "Deselect All" : "Select All"}
                      </button>
                    </div>
                  )}
                </div>
                
                {productsLoading && (
                  <div className="text-sm text-slate-500 py-4 text-center">Loading products...</div>
                )}
                
                {productsError && (
                  <div className="text-sm text-red-600 py-4 text-center">{productsError}</div>
                )}
                
                {!productsLoading && !productsError && products.length === 0 && (
                  <div className="text-sm text-slate-500 py-4 text-center">No products found for this bakery.</div>
                )}
                
                {!productsLoading && !productsError && products.length > 0 && (
                  <div className="border border-slate-300 rounded-lg max-h-64 overflow-y-auto p-2">
                    {products.map((p) => (
                      <label
                        key={p.id}
                        className="flex items-center gap-2 p-2 hover:bg-slate-50 rounded cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedProductIds.includes(p.id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedProductIds([...selectedProductIds, p.id]);
                            } else {
                              setSelectedProductIds(selectedProductIds.filter(id => id !== p.id));
                            }
                          }}
                          className="rounded border-slate-300 text-purple-600 focus:ring-purple-500"
                        />
                        <span className="text-sm text-slate-900 flex-1">
                          {p.name}
                          {p.sku && <span className="text-slate-500 ml-1">({p.sku})</span>}
                          <span className="text-slate-400 ml-1">ID: {p.id}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                
                <button
                  type="button"
                  onClick={() => startRetrain(selectedProductIds.length > 0 ? selectedProductIds : null)}
                  disabled={retrainLoading || selectedProductIds.length === 0}
                  className="mt-3 w-full rounded-lg border border-purple-300 bg-purple-50 px-4 py-2 text-sm font-medium text-purple-700 hover:bg-purple-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Retrain Selected ({selectedProductIds.length})
                </button>
              </div>
            </div>
            
            <div className="mt-4 flex justify-end gap-2 border-t pt-4">
              <button
                type="button"
                onClick={() => {
                  setShowRetrainModal(false);
                  setSelectedProductIds([]);
                }}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Training Status Panel */}
      {retrainJobStatus && (retrainJobStatus.status === "running" || retrainJobStatus.status === "cancelling" || retrainJobStatus.status === "cancelled") && (
        <div className="fixed bottom-4 right-4 z-40 bg-white rounded-lg shadow-lg border border-purple-200 p-4 max-w-sm">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-slate-900">
              {retrainJobStatus.status === "cancelled" || retrainJobStatus.status === "cancelling" 
                ? "Training Cancelled" 
                : "Training in Progress"}
            </h4>
            <div className="flex items-center gap-2">
              {retrainJobStatus.status === "running" && (
                <button
                  type="button"
                  onClick={cancelTraining}
                  className="text-xs px-2 py-1 rounded border border-red-300 bg-red-50 text-red-700 hover:bg-red-100"
                  title="Cancel training job"
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                onClick={() => setRetrainJobStatus(null)}
                className="text-slate-400 hover:text-slate-600"
                title={retrainJobStatus.status === "running" ? "Hide panel (training continues)" : "Close panel"}
              >
                ×
              </button>
            </div>
          </div>
          <div className="space-y-2">
            {(retrainJobStatus.status === "cancelling" || retrainJobStatus.status === "cancelled") && (
              <div className="text-xs text-amber-600 font-medium">
                {retrainJobStatus.status === "cancelling" 
                  ? "⏸️ Cancellation requested. Training will stop after current product completes..."
                  : "⏹️ Training has been cancelled."}
              </div>
            )}
            <div className="text-xs text-slate-600">
              Progress: {retrainJobStatus.progress.completed} / {retrainJobStatus.progress.total}
            </div>
            <div className="w-full bg-slate-200 rounded-full h-2">
              <div
                className="bg-purple-600 h-2 rounded-full transition-all"
                style={{
                  width: `${(retrainJobStatus.progress.completed / retrainJobStatus.progress.total) * 100}%`,
                }}
              />
            </div>
            {retrainJobStatus.current_product_id && (
              <div className="text-xs text-slate-500">
                Current: Product {retrainJobStatus.progress.completed + 1} of {retrainJobStatus.progress.total}
              </div>
            )}
            {retrainJobStatus.errors.length > 0 && (
              <div className="text-xs text-red-600">
                Errors: {retrainJobStatus.errors.length}
                <details className="mt-1">
                  <summary className="cursor-pointer">View errors</summary>
                  <ul className="list-disc list-inside mt-1 space-y-1">
                    {retrainJobStatus.errors.map((err, idx) => (
                      <li key={idx}>
                        Product {err.product_id}: {err.error}
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
