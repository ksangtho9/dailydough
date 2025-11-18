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
  const isUpload = pathname.startsWith("/upload");
  const isDashboard = pathname.startsWith("/dashboard");
  const isPlan = pathname.startsWith("/plan");

  return (
    <aside className="w-64 border-r bg-white shadow-sm flex flex-col">
      {/* Brand */}
      <div className="px-6 py-4 border-b">
        <h1 className="text-xl font-bold tracking-tight">BAKEZY</h1>
        <p className="text-xs text-slate-500">Bakery demand forecasting</p>
      </div>

      {/* Bakery selector */}
      <BakerySelector />

      {/* Navigation */}
      <nav className="px-4 py-4 space-y-2 flex-1">
        <Link href="/dashboard" className={navItemClass(isDashboard)}>
          Dashboard
        </Link>

        <Link href="/products" className={navItemClass(isProducts)}>
          Products
        </Link>

        <Link href="/plan" className={navItemClass(isPlan)}>
          Bake plan
        </Link>

        <Link href="/upload" className={navItemClass(isUpload)}>
          Upload sales CSV
        </Link>
      </nav>

      {/* Logout */}
      <div className="px-4 py-4 border-t">
        <LogoutButton />
      </div>
    </aside>
  );
}
