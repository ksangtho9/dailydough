"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function CTASection() {
  return (
    <section className="py-20 md:py-32 bg-gradient-to-br from-amber-50 to-emerald-50/30">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-3xl text-center rounded-2xl border-2 border-amber-200 bg-white p-8 md:p-12 shadow-lg">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl mb-4">
            Ready to Reduce Waste and Improve Forecasts?
          </h2>
          <p className="mb-8 text-lg text-slate-600">
            Join bakeries that are already using AI to optimize their production and increase profitability.
          </p>
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/login"
              className="group inline-flex items-center gap-2 rounded-full bg-amber-600 px-8 py-4 text-base font-semibold text-white shadow-lg hover:bg-amber-700 transition-all hover:shadow-xl"
            >
              Get Started
              <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center rounded-full border-2 border-slate-300 bg-white px-8 py-4 text-base font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Sign In
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
