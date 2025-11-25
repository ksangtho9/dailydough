import { apiFetch } from "@/lib/api";

export type WeekdayPoint = {
  weekday: number;
  label: string;
  avg_quantity: number;
};

export type WeekdayPatternResponse = {
  product_id: number;
  window_days: number;
  points: WeekdayPoint[];
};

export async function fetchWeekdayPattern(
  productId: number,
  windowDays = 90
) {
  const params = new URLSearchParams({
    window_days: String(windowDays),
  });
  return apiFetch<WeekdayPatternResponse>(
    `/api/products/${productId}/weekday-pattern?${params.toString()}`
  );
}


