"use client";

import { Mail, Check } from "lucide-react";

const includedFeatures = [
  "Unlimited products",
  "Daily demand forecasts",
  "Automated model training",
  "Waste & stockout risk analysis",
  "Historical accuracy tracking",
  "CSV data import",
  "Email support",
];

export function PricingSection() {
  return (
    <section id="pricing" className="py-20 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-2xl text-center mb-16">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Pricing That Scales With Your Business
          </h2>
          <p className="mt-4 text-lg text-slate-600">
            Every bakery is unique. Contact us for custom pricing based on your size,
            number of products, and specific needs.
          </p>
        </div>

        <div className="mx-auto max-w-4xl">
          <div className="rounded-2xl border-2 border-amber-200 bg-gradient-to-br from-amber-50/50 to-white p-8 md:p-12 shadow-lg">
            <div className="text-center mb-8">
              <h3 className="text-2xl font-bold text-slate-900 mb-2">
                Custom Enterprise Pricing
              </h3>
              <p className="text-slate-600">
                Get a personalized quote tailored to your bakery's requirements
              </p>
            </div>

            <div className="mb-8 rounded-xl bg-white p-6 border border-amber-100">
              <h4 className="font-semibold text-slate-900 mb-4">
                What's Included:
              </h4>
              <ul className="grid gap-3 sm:grid-cols-2">
                {includedFeatures.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-slate-700">
                    <Check className="h-5 w-5 text-emerald-600 flex-shrink-0" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a
                href="#contact"
                className="group inline-flex items-center justify-center gap-2 rounded-full bg-amber-600 px-8 py-4 text-base font-semibold text-white shadow-lg hover:bg-amber-700 transition-all hover:shadow-xl"
              >
                <Mail className="h-5 w-5" />
                Contact Sales
              </a>
              <a
                href="mailto:sales@bloom-bakery.com"
                className="inline-flex items-center justify-center gap-2 rounded-full border-2 border-amber-600 bg-white px-8 py-4 text-base font-semibold text-amber-700 hover:bg-amber-50 transition-colors"
              >
                Email Us Directly
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
