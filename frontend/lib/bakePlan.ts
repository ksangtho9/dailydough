import { apiFetch } from "@/lib/api";

export type BakePlanItem = {
  product_id: number;
  product_name: string;
  forecast_quantity: number;
  sku?: string | null;
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




