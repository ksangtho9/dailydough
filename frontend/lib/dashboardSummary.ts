import { apiFetch } from "@/lib/api";

export type DashboardSummaryResponse = {
  bakery_id: number;
  bakery_name: string;
  as_of: string;
  recommended_bake: number | null;
  expected_waste_pct: number | null;
  forecast_accuracy_pct: number | null;
  high_risk_items: number;
};

export async function fetchDashboardSummary(
  bakeryId: number
): Promise<DashboardSummaryResponse> {
  return apiFetch<DashboardSummaryResponse>(
    `/api/bakeries/${bakeryId}/dashboard-summary`
  );
}







