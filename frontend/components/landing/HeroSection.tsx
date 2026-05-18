"use client";

import Link from "next/link";
import { TrendingUp, ArrowRight } from "lucide-react";
import { FlickeringGrid } from "@/components/ui/flickering-grid";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden pt-24 pb-20 md:pt-32 md:pb-32">
      {/* Flickering Grid Background */}
      <div className="absolute inset-0 z-0">
        <FlickeringGrid
          className="absolute inset-0"
          squareSize={4}
          gridGap={6}
          color="rgb(180, 83, 9)"
          maxOpacity={0.15}
          flickerChance={0.1}
        />
      </div>
      {/* Gradient Overlay */}
      <div className="absolute inset-0 z-0 bg-gradient-to-br from-amber-50/50 via-transparent to-emerald-50/30" />
      <div className="relative z-10 mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 py-1.5 text-sm font-medium text-amber-700">
            <TrendingUp className="h-4 w-4" />
            AI-Powered Demand Forecasting
          </div>
          
          <h1 className="mb-6 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl md:text-6xl">
            Reduce Waste, Optimize Production
            <span className="block text-amber-600">for Modern Bakeries</span>
          </h1>
          
          <p className="mb-10 text-lg text-slate-600 sm:text-xl">
            Make data-driven decisions with machine learning forecasts that predict daily demand,
            minimize waste, and ensure you never run out of popular items.
          </p>
          
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/signup"
              className="group inline-flex items-center gap-2 rounded-full bg-amber-600 px-8 py-4 text-base font-semibold text-white shadow-lg hover:bg-amber-700 transition-all hover:shadow-xl"
            >
              Get Started
              <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
            </Link>
            <a
              href="#contact"
              className="inline-flex items-center gap-2 rounded-full border-2 border-amber-600 bg-white px-8 py-4 text-base font-semibold text-amber-700 hover:bg-amber-50 transition-colors"
            >
              Contact Sales
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
