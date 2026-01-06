"use client";

import { usePathname } from "next/navigation";
import { AppTopNav } from "@/components/AppTopNav";

export function ConditionalNav() {
  const pathname = usePathname();
  const isLoginPage = pathname === "/login";

  if (isLoginPage) {
    return null;
  }

  return <AppTopNav />;
}








