"use client";

import { ForecastMetrics, getConfidenceMeta } from "@/lib/metrics";
import clsx from "clsx";

type Props = {
  metrics: ForecastMetrics | null | undefined;
};

export function ForecastConfidenceBadge({ metrics }: Props) {
  const mape = metrics?.mape ?? null;
  const meta = getConfidenceMeta(mape);

  const className = clsx(
    "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
    meta.level === "high" && "bg-emerald-100 text-emerald-700",
    meta.level === "medium" && "bg-amber-100 text-amber-700",
    meta.level === "low" && "bg-red-100 text-red-700",
    meta.level === "none" && "bg-slate-100 text-slate-500",
  );

  return <span className={className}>{meta.label}</span>;
}




