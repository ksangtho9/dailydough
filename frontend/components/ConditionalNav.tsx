"use client";

import { usePathname } from "next/navigation";
import { AppTopNav } from "@/components/AppTopNav";
import { LandingNav } from "@/components/landing/LandingNav";

export function ConditionalNav() {
  const pathname = usePathname();
  const isLoginPage = pathname === "/login";
  const isSignupPage = pathname === "/signup" || pathname.startsWith("/auth/");
  const isHomePage = pathname === "/";

  if (isLoginPage || isSignupPage) {
    return null;
  }

  if (isHomePage) {
    return <LandingNav />;
  }

  return <AppTopNav />;
}









