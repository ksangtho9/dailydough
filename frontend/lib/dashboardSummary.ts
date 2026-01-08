import { apiFetch } from "@/lib/api";

export type DashboardSummaryResponse = {
  bakery_id: number;
  bakery_name: string;
  as_of: string;
  recommended_bake: number | null;
  expected_waste_pct: number | null;
  forecast_accuracy_pct: number | null; // Deprecated: kept for backward compatibility
  post_training_wape: number | null;
  high_risk_items: number;
  // Date window fields for expected waste calculation (populated even when expected_waste_pct is null)
  expected_waste_forecast_date: string | null;
  expected_waste_lookback_start: string | null;
  expected_waste_lookback_end: string | null;
};

export async function fetchDashboardSummary(
  bakeryId: number,
  asOfDate?: string | null
): Promise<DashboardSummaryResponse> {
  const url = `/api/bakeries/${bakeryId}/dashboard-summary${
    asOfDate ? `?as_of_date=${asOfDate}` : ""
  }`;
  return apiFetch<DashboardSummaryResponse>(url);
}











