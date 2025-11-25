"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BakerySelector } from "@/components/BakerySelector";
import { LogoutButton } from "@/components/LogoutButton";

function navItemClass(active: boolean) {
  return (
    "block rounded-lg px-3 py-2 text-sm " +
    (active
      ? "bg-slate-900 text-white"
      : "text-slate-800 hover:bg-slate-100")
  );
}

export function Sidebar() {
  const pathname = usePathname();

  const isProducts = pathname.startsWith("/products");
  const isDataUpload = pathname.startsWith("/data");
  const isDashboard = pathname.startsWith("/dashboard");
  const isPlan = pathname.startsWith("/plan");
  const isBakeries = pathname.startsWith("/bakeries");

  return (
    <aside className="w-64 border-r bg-white shadow-sm flex flex-col">
      {/* Brand */}
      <div className="px-6 py-4 border-b">
        <h1 className="text-xl font-bold tracking-tight text-[#0f172a]">Daily Dough</h1>
        <p className="text-xs text-slate-500">AI Bakery demand forecasting</p>
      </div>

      {/* Bakery selector */}
      <BakerySelector />

      {/* Navigation */}
      <nav className="px-4 py-4 space-y-2 flex-1">
        <Link href="/dashboard" className={navItemClass(isDashboard)}>
          Dashboard
        </Link>

        <Link href="/bakeries" className={navItemClass(isBakeries)}>
          Bakeries
        </Link>

        <Link href="/products" className={navItemClass(isProducts)}>
          Products
        </Link>

        <Link href="/plan" className={navItemClass(isPlan)}>
          Bake plan
        </Link>

        <Link href="/data/upload" className={navItemClass(isDataUpload)}>
          Data upload
        </Link>
      </nav>

      {/* Logout */}
      <div className="px-4 py-4 border-t">
        <LogoutButton />
      </div>
    </aside>
  );
}
