"use client";

import { Upload, Sparkles, TrendingDown, CheckCircle } from "lucide-react";

const steps = [
  {
    icon: Upload,
    title: "Upload Your Data",
    description: "Simply upload your sales history via CSV. Our system handles the rest.",
  },
  {
    icon: Sparkles,
    title: "AI Models Train",
    description: "Machine learning models automatically train on your data and learn your patterns.",
  },
  {
    icon: TrendingDown,
    title: "Get Accurate Forecasts",
    description: "Receive daily demand predictions with confidence intervals for better planning.",
  },
  {
    icon: CheckCircle,
    title: "Reduce Waste & Stockouts",
    description: "Optimize production quantities and see measurable improvements in waste reduction.",
  },
];

const benefits = [
  "Reduce waste by up to 30%",
  "Improve forecast accuracy",
  "Save hours on manual planning",
  "Increase profitability",
];

export function BenefitsSection() {
  return (
    <section className="py-20 md:py-32 bg-white/50">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-2xl text-center mb-16">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            How It Works
          </h2>
          <p className="mt-4 text-lg text-slate-600">
            Get started in minutes with our simple process
          </p>
        </div>

        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-4 mb-16">
          {steps.map((step, index) => {
            const Icon = step.icon;
            return (
              <div key={step.title} className="relative">
                <div className="rounded-2xl border border-amber-100 bg-white p-6 text-center h-full">
                  <div className="mb-4 inline-flex items-center justify-center rounded-full bg-amber-600 text-white w-12 h-12">
                    <Icon className="h-6 w-6" />
                  </div>
                  <div className="mb-2 text-sm font-semibold text-amber-600">
                    Step {index + 1}
                  </div>
                  <h3 className="mb-2 text-lg font-semibold text-slate-900">
                    {step.title}
                  </h3>
                  <p className="text-sm text-slate-600">{step.description}</p>
                </div>
              </div>
            );
          })}
        </div>

        <div className="rounded-2xl border border-emerald-100 bg-emerald-50/50 p-8 md:p-12">
          <h3 className="mb-6 text-2xl font-bold text-slate-900 text-center">
            Key Benefits
          </h3>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {benefits.map((benefit) => (
              <div
                key={benefit}
                className="flex items-center gap-3 rounded-lg bg-white p-4 shadow-sm"
              >
                <CheckCircle className="h-5 w-5 text-emerald-600 flex-shrink-0" />
                <span className="font-medium text-slate-900">{benefit}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
