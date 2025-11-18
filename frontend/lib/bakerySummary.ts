import { apiFetch } from "./api";

export interface TopProductSummary {
  product_id: number;
  product_name: string;
  units_sold: number;
}

export interface BakerySummary {
  bakery_id: number;
  bakery_name: string;
  as_of: string; // ISO date string
  window_days: number;
  total_units: number;

  previous_total_units: number;
  pct_change_vs_previous: number | null;

  top_products: TopProductSummary[];
}

export async function fetchBakerySummary(
  bakeryId: number,
  windowDays: number
): Promise<BakerySummary> {
  const params = new URLSearchParams({ days: String(windowDays) });
  return apiFetch<BakerySummary>(
    `/api/v1/bakeries/${bakeryId}/summary?${params.toString()}`
  );
}
