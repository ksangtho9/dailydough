"use client";

import Link from "next/link";

type ChecklistStep = {
  id: string;
  label: string;
  description: string;
  href?: string;
};

const DEFAULT_STEPS: ChecklistStep[] = [
  {
    id: "seed_demo",
    label: "Seed demo data",
    description:
      "Create a demo bakery with sample products and six months of history.",
    href: "/data/upload",
  },
  {
    id: "upload_csv",
    label: "Upload your own CSV",
    description: "Import your real sales data using the CSV upload tool.",
    href: "/data/upload",
  },
  {
    id: "train_all",
    label: "Models train automatically",
    description: "After uploading sales data, models retrain automatically in the background.",
    href: undefined,
  },
  {
    id: "review_bake_plan",
    label: "Review tomorrow's bake plan",
    description: "See recommended quantities for tomorrow by product.",
    href: "/plan",
  },
];

type GettingStartedChecklistProps = {
  completedSteps?: string[];
  steps?: ChecklistStep[];
};

export function GettingStartedChecklist({
  completedSteps,
  steps = DEFAULT_STEPS,
}: GettingStartedChecklistProps) {
  const isCompleted = (stepId: string) =>
    completedSteps?.includes(stepId) ?? false;

  return (
    <div className="rounded-2xl border bg-white/80 shadow-sm">
      <div className="border-b px-4 py-3">
        <h3 className="text-base font-semibold text-slate-900">
          Getting started with Bloom
        </h3>
        <p className="text-xs text-slate-500">
          Follow these steps to unlock accurate forecasts.
        </p>
      </div>

      <div className="space-y-4 px-4 py-4">
        {steps.map((step) => (
          <div key={step.id} className="flex gap-3">
            <div className="mt-0.5">
              {isCompleted(step.id) ? (
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-xs font-semibold text-white">
                  ✓
                </span>
              ) : (
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 text-xs text-slate-400">
                  ○
                </span>
              )}
            </div>

            <div className="flex-1 space-y-1">
              <div className="text-sm font-medium text-slate-900">
                {step.label}
              </div>
              <p className="text-xs text-slate-500">{step.description}</p>
              {step.href && (
                <Link
                  href={step.href}
                  className="text-xs font-medium text-slate-600 underline underline-offset-4 hover:text-slate-900"
                >
                  Go there
                </Link>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

