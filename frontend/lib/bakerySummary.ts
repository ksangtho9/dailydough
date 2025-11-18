// frontend/lib/bakerySummary.ts
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

  // Optional extras – only used if backend provides them
  total_units_window?: number;
  total_units_prev_window?: number | null;
  pct_change_vs_prev?: number | null;

  top_products_last_30_days: TopProductSummary[];
}

/**
 * Fetch per-bakery summary stats.
 * `windowDays` is used for "this period vs previous period" if backend supports it.
 */
export async function fetchBakerySummary(
  bakeryId: number,
  windowDays: number
): Promise<BakerySummary> {
  // If backend doesn't care about window_days, it'll just ignore this query param
  return apiFetch<BakerySummary>(
    `/api/v1/bakeries/${bakeryId}/summary?window_days=${windowDays}`
  );
}

