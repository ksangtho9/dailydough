import { apiFetch } from "./api";

export interface SalesRecord {
  id: number;
  bakery_id: number;
  product_id: number;
  date: string; // ISO date string
  quantity_sold: number;
}

export async function fetchSalesRecords(
  bakeryId?: number,
  startDate?: string,
  endDate?: string,
  limit = 5000,
): Promise<SalesRecord[]> {
  const params = new URLSearchParams();
  if (bakeryId) params.set("bakery_id", String(bakeryId));
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  params.set("limit", String(limit));
  return apiFetch<SalesRecord[]>(`/api/sales/?${params.toString()}`);
}









