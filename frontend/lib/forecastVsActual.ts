import { apiFetch } from "@/lib/api";

export type ForecastVsActualPoint = {
  date: string;
  actual: number | null;
  forecast: number | null;
};

export type ForecastVsActualResponse = {
  product_id: number;
  window_days: number;
  points: ForecastVsActualPoint[];
};

export async function fetchForecastVsActual(
  productId: number,
  windowDays = 60
): Promise<ForecastVsActualResponse> {
  const params = new URLSearchParams({
    window_days: String(windowDays),
  });
  return apiFetch<ForecastVsActualResponse>(
    `/api/products/${productId}/forecast-vs-actual?${params.toString()}`
  );
}



