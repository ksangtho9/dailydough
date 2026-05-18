"use client";

import { usePathname } from "next/navigation";

export function ConditionalMain({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLoginPage = pathname === "/login";
  const isSignupPage = pathname === "/signup" || pathname.startsWith("/auth/");
  const isHomePage = pathname === "/";

  if (isLoginPage || isSignupPage || isHomePage) {
    return <>{children}</>;
  }

  return (
    <main className="mx-auto max-w-6xl px-6 pt-28 pb-10">
      {children}
    </main>
  );
}

