// frontend/lib/bakeryTimeseries.ts
import { apiFetch } from "./api";

interface SalesRecord {
  id: number;
  bakery_id: number;
  product_id: number;
  date: string;          // ISO date from backend
  quantity_sold: number; // or float
}

export interface BakeryDailyPoint {
  date: string; // YYYY-MM-DD
  units: number;
}

/**
 * Fetch all sales for a bakery and aggregate to daily totals.
 * We then trim down to the last `windowDays` days.
 */
export async function fetchBakeryDailySales(
  bakeryId: number,
  windowDays: number
): Promise<BakeryDailyPoint[]> {
  const records = await apiFetch<SalesRecord[]>(
    `/api/sales?bakery_id=${bakeryId}`
  );

  const totals = new Map<string, number>();

  for (const r of records) {
    const d = r.date;
    const current = totals.get(d) ?? 0;
    totals.set(d, current + Number(r.quantity_sold));
  }

  let items = Array.from(totals.entries())
    .map(([date, units]) => ({ date, units }))
    .sort((a, b) => a.date.localeCompare(b.date));

  if (windowDays > 0 && items.length > 0) {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - windowDays + 1);

    items = items.filter((p) => {
      const d = new Date(p.date);
      // if parse fails, keep it
      return isNaN(d.getTime()) ? true : d >= cutoff;
    });
  }

  return items;
}
