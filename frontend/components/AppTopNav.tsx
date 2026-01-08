"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Package,
  Clock,
  Upload,
  Sparkles,
  Plus,
  LogOut,
} from "lucide-react";
import {
  fetchBakeries,
  type Bakery,
  BAKERY_UPDATED_EVENT,
  emitBakerySelectionChanged,
} from "@/lib/bakeries";
const STORAGE_KEY = "current_bakery_id";

const navItems = [
  { label: "Products", href: "/products", icon: Package },
  { label: "History", href: "/history", icon: Clock },
  { label: "Upload Data", href: "/data/upload", icon: Upload },
  { label: "Ask AI", href: "/ai-summary", icon: Sparkles },
];

const navButtonClass =
  "inline-flex items-center rounded-full border border-[#E3D3C2] px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:bg-[#F0E4D5]";

export function AppTopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string>("");
  const [bakeriesLoading, setBakeriesLoading] = useState(true);

  const setActiveBakery = useCallback((value: string | null) => {
    const nextValue = value ?? "";
    setSelectedBakeryId(nextValue);
    if (typeof window !== "undefined") {
      if (nextValue) {
        window.localStorage.setItem(STORAGE_KEY, nextValue);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    }
    emitBakerySelectionChanged(nextValue || null);
  }, []);

  const loadBakeries = useCallback(async () => {
    try {
      setBakeriesLoading(true);
      const data = await fetchBakeries();
      setBakeries(data);

      if (data.length === 0) {
        setActiveBakery(null);
        return;
      }

      const stored =
        typeof window !== "undefined"
          ? window.localStorage.getItem(STORAGE_KEY)
          : null;
      const validStored =
        stored && data.some((b) => String(b.id) === stored) ? stored : null;
      const fallback = String(data[0].id);
      setActiveBakery(validStored ?? fallback);
    } catch (err) {
      console.error("Failed to load bakeries", err);
      setBakeries([]);
      setActiveBakery(null);
    } finally {
      setBakeriesLoading(false);
    }
  }, [setActiveBakery]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        setSelectedBakeryId(stored);
      }
    }
    loadBakeries();

    function handleUpdate() {
      loadBakeries();
    }

    window.addEventListener(BAKERY_UPDATED_EVENT, handleUpdate);
    return () => {
      window.removeEventListener(BAKERY_UPDATED_EVENT, handleUpdate);
    };
  }, [loadBakeries]);

  const currentBakeryName = useMemo(() => {
    if (bakeries.length === 0) return "No bakeries yet";
    if (!selectedBakeryId) return "Select a bakery";
    const found = bakeries.find((b) => String(b.id) === selectedBakeryId);
    return found ? found.name : "Select a bakery";
  }, [bakeries, selectedBakeryId]);

  const handleLogout = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem(STORAGE_KEY);
    }
    router.push("/login");
  }, [router]);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-[#E5D7C5] bg-[#F4E6D7]/95 backdrop-blur">
      <div className="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-4 px-6 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/dashboard"
            className="text-3xl font-bold tracking-tight text-slate-900 hover:text-amber-700"
          >
            Bloom
          </Link>
          <span className="text-xs font-medium text-slate-600">
            Bakery:{" "}
            <span className="text-slate-900">{currentBakeryName}</span>
          </span>
          {bakeriesLoading ? (
            <span className="text-xs text-slate-500">Loading...</span>
          ) : bakeries.length > 0 ? (
            <select
              value={selectedBakeryId}
              onChange={(e) => setActiveBakery(e.target.value)}
              className="rounded-full border border-[#E3D3C2] bg-white px-3 py-1 text-xs font-medium text-slate-800 focus:outline-none"
            >
              {bakeries.map((bakery) => (
                <option key={bakery.id} value={String(bakery.id)}>
                  {bakery.name}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
          <Link
            href="/bakeries"
            className="inline-flex items-center gap-1 rounded-full border border-[#E3D3C2] px-2.5 py-1 text-xs font-semibold text-slate-700 transition hover:bg-white"
          >
            <Plus className="h-3 w-3" />
            Add bakery
          </Link>

          <nav className="flex flex-wrap items-center gap-1.5">
            {navItems.map((item) => {
              const isActive = pathname === item.href;
              const IconComponent = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`${navButtonClass} gap-1 ${
                    isActive ? "bg-amber-500 text-white shadow" : "bg-white/80"
                  }`}
                >
                  <IconComponent className="h-3 w-3" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <span className="whitespace-nowrap rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            Model: Prophet
          </span>
          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            <LogOut className="h-3 w-3" />
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
