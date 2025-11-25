"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  fetchBakeries,
  type Bakery,
  type CreateBakeryPayload,
  createBakery,
  BAKERY_UPDATED_EVENT,
  emitBakerySelectionChanged,
  emitBakeryUpdate,
} from "@/lib/bakeries";

const STORAGE_KEY = "current_bakery_id";
const DEFAULT_TIMEZONE = "America/Los_Angeles";

const navItems = [
  { label: "Products", href: "/products" },
  { label: "History", href: "/history" },
  { label: "Upload Data", href: "/data/upload" },
  { label: "AI Summary", href: "/ai-summary" },
];

const navButtonClass =
  "inline-flex items-center rounded-full border border-[#E3D3C2] px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-[#F0E4D5]";

export function AppTopNav() {
  const pathname = usePathname();
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string>("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newBakeryName, setNewBakeryName] = useState("");
  const [newBakeryLocation, setNewBakeryLocation] = useState("");
  const [newBakeryTimezone, setNewBakeryTimezone] =
    useState(DEFAULT_TIMEZONE);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

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

  function openCreateModal() {
    setNewBakeryName("");
    setNewBakeryLocation("");
    setNewBakeryTimezone(DEFAULT_TIMEZONE);
    setCreateError(null);
    setIsModalOpen(true);
  }

  function closeCreateModal() {
    if (isSaving) return;
    setIsModalOpen(false);
  }

  async function handleCreateBakery(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newBakeryName.trim()) {
      setCreateError("Bakery name is required.");
      return;
    }

    setIsSaving(true);
    setCreateError(null);
    try {
      const payload: CreateBakeryPayload = {
        name: newBakeryName.trim(),
      };
      if (newBakeryLocation.trim()) {
        payload.location = newBakeryLocation.trim();
      }
      if (newBakeryTimezone.trim()) {
        payload.timezone = newBakeryTimezone.trim();
      }

      const created = await createBakery(payload);
      emitBakeryUpdate();
      setActiveBakery(String(created.id));
      await loadBakeries();

      setIsModalOpen(false);
    } catch (err: any) {
      console.error(err);
      setCreateError(err?.message || "Failed to create bakery.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-[#E5D7C5] bg-[#F4E6D7]/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/dashboard"
            className="text-lg font-semibold tracking-tight text-slate-900 hover:text-amber-700"
          >
            Daily Dough
          </Link>
          <span className="text-xs font-medium text-slate-600">
            Bakery:{" "}
            <span className="text-slate-900">{currentBakeryName}</span>
          </span>
          {bakeries.length > 0 && (
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
          )}
        </div>

        <div className="flex flex-1 flex-wrap items-center justify-end gap-3">
          <button
            type="button"
            onClick={openCreateModal}
            className="inline-flex items-center rounded-full border border-[#E3D3C2] px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-white"
          >
            + Add bakery
          </button>

          <nav className="flex flex-wrap items-center gap-2">
            {navItems.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`${navButtonClass} ${
                    isActive ? "bg-amber-500 text-white shadow" : "bg-white/80"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <span className="whitespace-nowrap rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            Model: Prophet
          </span>
          <Link
            href="/logout"
            className="inline-flex items-center rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Sign out
          </Link>
        </div>
      </div>
      {isModalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-black/40 px-4 py-12">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">
                  Create bakery
                </h3>
                <p className="text-xs text-slate-500">
                  Add a new location and we’ll select it automatically.
                </p>
              </div>
              <button
                type="button"
                onClick={closeCreateModal}
                className="text-sm text-slate-500 hover:text-slate-700"
              >
                Close
              </button>
            </div>

            <form onSubmit={handleCreateBakery} className="mt-4 space-y-4">
              <label className="block text-xs font-medium text-slate-700">
                Name *
                <input
                  type="text"
                  value={newBakeryName}
                  onChange={(e) => setNewBakeryName(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                  placeholder="Downtown Bakery"
                  required
                />
              </label>

              <label className="block text-xs font-medium text-slate-700">
                Location
                <input
                  type="text"
                  value={newBakeryLocation}
                  onChange={(e) => setNewBakeryLocation(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                  placeholder="City / Neighborhood"
                />
              </label>

              <label className="block text-xs font-medium text-slate-700">
                Timezone
                <input
                  type="text"
                  value={newBakeryTimezone}
                  onChange={(e) => setNewBakeryTimezone(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                  placeholder="America/Los_Angeles"
                />
              </label>

              {createError && (
                <p className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-600">
                  {createError}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeCreateModal}
                  className="rounded-full px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
                  disabled={isSaving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSaving ? "Creating…" : "Create bakery"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </header>
  );
}

