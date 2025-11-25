"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

type TrainAllResponse = {
  trained_products: number;
  failed_products: number[];
  avg_mape: number | null;
};

export function TrainAllModelsButton() {
  const [isTraining, setIsTraining] = useState(false);
  const [lastSummary, setLastSummary] = useState<TrainAllResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setIsTraining(true);
    setError(null);
    try {
      const data = await apiFetch<TrainAllResponse>("/api/forecast/train-all", {
        method: "POST",
      });
      setLastSummary(data);
    } catch (err: any) {
      setError(err?.message ?? "Failed to train models");
    } finally {
      setIsTraining(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={isTraining}
        className="inline-flex w-full items-center justify-center rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isTraining ? "Training models…" : "Train all products"}
      </button>

      {lastSummary && (
        <p className="text-xs text-slate-600">
          Trained {lastSummary.trained_products} products.
          {typeof lastSummary.avg_mape === "number" && (
            <>
              {" "}
              Avg MAPE {(lastSummary.avg_mape * 100).toFixed(1)}%.
            </>
          )}
          {lastSummary.failed_products.length > 0 && (
            <>
              {" "}
              Failed IDs: {lastSummary.failed_products.join(", ")}.
            </>
          )}
        </p>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}


