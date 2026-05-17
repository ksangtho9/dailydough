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
): Promise<SalesRecord[]> {
  const params = new URLSearchParams();
  if (bakeryId) params.set("bakery_id", String(bakeryId));
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const qs = params.toString();
  return apiFetch<SalesRecord[]>(qs ? `/api/sales/?${qs}` : "/api/sales/");
}









