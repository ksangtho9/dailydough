"use client";

import Link from "next/link";

export function LandingFooter() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="border-t border-[#E5D7C5] bg-white/50 py-12">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid gap-8 md:grid-cols-4">
          <div className="md:col-span-2">
            <h3 className="text-xl font-bold tracking-tight text-slate-900 mb-2">
              Bloom
            </h3>
            <p className="text-sm text-slate-600 mb-4">
              AI-powered demand forecasting for modern bakeries. Reduce waste, optimize production, and make data-driven decisions.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 mb-4">Product</h4>
            <ul className="space-y-2 text-sm">
              <li>
                <a
                  href="#features"
                  className="text-slate-600 hover:text-amber-700 transition-colors"
                >
                  Features
                </a>
              </li>
              <li>
                <a
                  href="#pricing"
                  className="text-slate-600 hover:text-amber-700 transition-colors"
                >
                  Pricing
                </a>
              </li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 mb-4">Company</h4>
            <ul className="space-y-2 text-sm">
              <li>
                <Link
                  href="/login"
                  className="text-slate-600 hover:text-amber-700 transition-colors"
                >
                  Sign In
                </Link>
              </li>
              <li>
                <a
                  href="#contact"
                  className="text-slate-600 hover:text-amber-700 transition-colors"
                >
                  Contact
                </a>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-8 border-t border-[#E5D7C5] pt-8 text-center text-sm text-slate-600">
          <p>© {currentYear} Bloom. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
