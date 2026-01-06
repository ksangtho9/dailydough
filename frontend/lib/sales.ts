import { apiFetch } from "./api";

export interface SalesRecord {
  id: number;
  bakery_id: number;
  product_id: number;
  date: string; // ISO date string
  quantity_sold: number;
}

export async function fetchSalesRecords(
  bakeryId?: number
): Promise<SalesRecord[]> {
  const url = bakeryId
    ? `/api/sales/?bakery_id=${bakeryId}`
    : "/api/sales/";
  return apiFetch<SalesRecord[]>(url);
}








