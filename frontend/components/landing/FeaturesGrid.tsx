"use client";

import { Brain, Target, Calendar } from "lucide-react";

const features = [
  {
    icon: Brain,
    title: "AI-Powered Forecasting",
    description:
      "Advanced machine learning models analyze your sales history to predict daily demand with high accuracy. Our models learn patterns and adapt to your business.",
  },
  {
    icon: Target,
    title: "Waste Reduction",
    description:
      "Optimize production quantities to minimize waste while ensuring you never run out of popular items. Balance customer satisfaction with cost efficiency.",
  },
  {
    icon: Calendar,
    title: "Automated Bake Planning",
    description:
      "Get automated daily recommendations for what and how much to bake, tailored to your products. Save time on manual planning and focus on what you do best.",
  },
];

export function FeaturesGrid() {
  return (
    <section id="features" className="py-20 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-2xl text-center mb-16">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Everything you need to forecast demand
          </h2>
          <p className="mt-4 text-lg text-slate-600">
            Powerful features designed to help you make better production decisions
          </p>
        </div>

        <div className="grid gap-8 md:grid-cols-3">
          {features.map((feature) => {
            const Icon = feature.icon;
            return (
              <div
                key={feature.title}
                className="group rounded-2xl border border-amber-100 bg-white p-8 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="mb-4 inline-flex items-center justify-center rounded-xl bg-amber-100 p-3 text-amber-600">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="mb-3 text-xl font-semibold text-slate-900">
                  {feature.title}
                </h3>
                <p className="text-slate-600 leading-relaxed">
                  {feature.description}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
