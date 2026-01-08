"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { HeroSection } from "@/components/landing/HeroSection";
import { FeaturesGrid } from "@/components/landing/FeaturesGrid";
import { BenefitsSection } from "@/components/landing/BenefitsSection";
import { PricingSection } from "@/components/landing/PricingSection";
import { ContactSection } from "@/components/landing/ContactSection";
import { CTASection } from "@/components/landing/CTASection";
import { LandingFooter } from "@/components/landing/LandingFooter";

export default function HomePage() {
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    // Check if user is authenticated
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("access_token");
      setIsAuthenticated(!!token);
      
      // Optional: Auto-redirect authenticated users to dashboard
      // Uncomment if you want to redirect logged-in users
      // if (token) {
      //   router.push("/dashboard");
      // }
    }
  }, [router]);

  // Show loading state briefly to avoid flash
  if (isAuthenticated === null) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-slate-600">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      <HeroSection />
      <FeaturesGrid />
      <BenefitsSection />
      <PricingSection />
      <ContactSection />
      <CTASection />
      <LandingFooter />
    </div>
  );
}
