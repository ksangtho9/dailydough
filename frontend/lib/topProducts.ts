import { apiFetch } from "@/lib/api";

export type TopProductItem = {
  product_id: number;
  product_name: string;
  total_quantity: number;
};

export type TopProductsResponse = {
  bakery_id: number;
  window_days: number;
  items: TopProductItem[];
};

export async function fetchTopProducts(
  bakeryId: number,
  windowDays = 30,
  limit = 5,
) {
  const params = new URLSearchParams({
    window_days: String(windowDays),
    limit: String(limit),
  });
  return apiFetch<TopProductsResponse>(
    `/api/bakeries/${bakeryId}/top-products?${params.toString()}`
  );
}


