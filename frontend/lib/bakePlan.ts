import { apiFetch } from "@/lib/api";

export type BakePlanItem = {
  product_id: number;
  product_name: string;
  forecast_quantity: number;
  sku?: string | null;
  // Risk metrics (computed from forecast uncertainty)
  waste_risk_prob?: number | null;
  stockout_risk_prob?: number | null;
  risk_sigma?: number | null;
  interval_level_used?: number | string | null;
  risk_method?: string | null;
  debug_source?: string | null;
  sigma_clamped?: boolean | null;
};

export type BakePlanResponse = {
  bakery_id: number;
  bakery_name: string;
  date: string;
  items: BakePlanItem[];
};

export async function fetchBakePlan(
  bakeryId: number,
  targetDate?: string
): Promise<BakePlanResponse> {
  const params = targetDate ? `?target_date=${targetDate}` : "";
  return apiFetch<BakePlanResponse>(`/api/bakeries/${bakeryId}/bake-plan${params}`);
}




