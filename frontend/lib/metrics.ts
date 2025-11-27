"use client";

export type ForecastMetrics = {
  product_id: number;
  mape: number | null;
  rmse: number | null;
  n_points: number;
  model_type: string;
  status: string;
  last_trained_at: string | null;
};

export type ConfidenceLevel = "none" | "low" | "medium" | "high";

export function getConfidenceMeta(mape: number | null) {
  if (mape === null || Number.isNaN(mape)) {
    return { label: "Not trained", level: "none" as ConfidenceLevel };
  }
  if (mape < 0.1) {
    return { label: "High confidence", level: "high" as ConfidenceLevel };
  }
  if (mape < 0.25) {
    return { label: "Medium confidence", level: "medium" as ConfidenceLevel };
  }
  return { label: "Low confidence", level: "low" as ConfidenceLevel };
}

export function formatLastTrainedAt(value: string | null): string {
  if (!value) return "Never trained";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Never trained";
  }
  return date.toLocaleString();
}




