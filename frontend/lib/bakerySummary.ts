import { apiFetch } from "./api";

export interface TopProductSummary {
  product_id: number;
  product_name: string;
  units_sold: number;
}

export interface BakerySummary {
  bakery_id: number;
  bakery_name: string;
  as_of: string;
  total_units_last_7_days: number;
  total_units_last_30_days: number;
  top_products_last_30_days: TopProductSummary[];
}

export async function fetchBakerySummary(
  bakeryId: number
): Promise<BakerySummary> {
  // ✓ This matches your exact backend path
  return apiFetch<BakerySummary>(`/api/v1/bakeries/${bakeryId}/summary`);
}
 
