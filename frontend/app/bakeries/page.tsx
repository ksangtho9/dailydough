"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchBakeries,
  createBakery,
  emitBakeryUpdate,
  emitBakerySelectionChanged,
  BAKERY_UPDATED_EVENT,
  type Bakery,
  type CreateBakeryPayload,
} from "@/lib/bakeries";
import { Button } from "@/components/ui/button";
import { TextShimmer } from "@/components/ui/text-shimmer";

const DEFAULT_TIMEZONE = "America/Los_Angeles";
const STORAGE_KEY = "current_bakery_id";

export default function BakeriesPage() {
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentBakeryId, setCurrentBakeryId] = useState<number | null>(null);

  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [timezone, setTimezone] = useState(DEFAULT_TIMEZONE);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadBakeries = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchBakeries();
      setBakeries(data);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to load bakeries");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBakeries();
    
    // Load current bakery from localStorage
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const asNum = Number(stored);
        if (!Number.isNaN(asNum)) {
          setCurrentBakeryId(asNum);
        }
      }
    }

    // Listen for bakery updates (e.g., from demo seeding)
    function handleBakeryUpdate() {
      loadBakeries();
    }

    if (typeof window !== "undefined") {
      window.addEventListener(BAKERY_UPDATED_EVENT, handleBakeryUpdate);
      return () => {
        window.removeEventListener(BAKERY_UPDATED_EVENT, handleBakeryUpdate);
      };
    }
  }, [loadBakeries]);

  // Listen for bakery selection changes
  useEffect(() => {
    function handleSelectionChange(e: Event) {
      const customEvent = e as CustomEvent<{ value: string | null }>;
      const value = customEvent.detail?.value;
      if (value) {
        const asNum = Number(value);
        if (!Number.isNaN(asNum)) {
          setCurrentBakeryId(asNum);
        }
      } else {
        setCurrentBakeryId(null);
      }
    }

    if (typeof window !== "undefined") {
      window.addEventListener("current-bakery-changed", handleSelectionChange);
      return () => {
        window.removeEventListener("current-bakery-changed", handleSelectionChange);
      };
    }
  }, []);

  function setAsCurrent(bakeryId: number) {
    setCurrentBakeryId(bakeryId);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, String(bakeryId));
    }
    emitBakerySelectionChanged(String(bakeryId));
  }

  async function handleCreateBakery(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) {
      setFormError("Bakery name is required.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    setSuccessMessage(null);

    try {
      const payload: CreateBakeryPayload = {
        name: name.trim(),
      };

      if (location.trim()) {
        payload.location = location.trim();
      }

      if (timezone.trim()) {
        payload.timezone = timezone.trim();
      }

      const created = await createBakery(payload);

      setName("");
      setLocation("");
      setTimezone(DEFAULT_TIMEZONE);
      setSuccessMessage("Bakery created.");

      await loadBakeries();
      emitBakeryUpdate();
      
      // Automatically set the newly created bakery as current
      setAsCurrent(created.id);
    } catch (err: any) {
      console.error(err);
      setFormError(err?.message || "Failed to create bakery");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight text-[#0f172a]">
          Bakeries
        </h1>
        <p className="text-sm text-slate-600">
          Add locations and keep the dropdowns across the app in sync.
        </p>
      </header>

      <section className="rounded-2xl border bg-white/80 shadow-sm">
        <div className="border-b px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">Add bakery</h2>
          <p className="text-xs text-slate-500">
            Fill in basic details and the rest of the app will pick it up.
          </p>
        </div>

        <form className="space-y-5 p-4" onSubmit={handleCreateBakery}>
          {formError && (
            <p className="text-sm text-red-600">Error: {formError}</p>
          )}

          {successMessage && (
            <p className="text-sm text-green-600">{successMessage}</p>
          )}

          <div className="grid gap-4 md:grid-cols-3">
            <label className="text-sm text-slate-600 space-y-1">
              <span className="font-medium text-slate-800">Name *</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Sunrise Bakery"
                className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                required
              />
            </label>

            <label className="text-sm text-slate-600 space-y-1">
              <span className="font-medium text-slate-800">Location</span>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Seattle, WA"
                className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
              />
            </label>

            <label className="text-sm text-slate-600 space-y-1">
              <span className="font-medium text-slate-800">Timezone</span>
              <input
                type="text"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                placeholder="America/Los_Angeles"
              />
            </label>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "Creating…" : "Add bakery"}
            </button>
            <span className="text-xs text-slate-500">
              New bakeries instantly show up in filters & selectors.
            </span>
          </div>
        </form>
      </section>

      <section className="rounded-2xl border bg-white/80 shadow-sm">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-800">
              Existing bakeries
            </h2>
            <p className="text-xs text-slate-500">
              {loading ? (
                <TextShimmer className="text-sm" duration={1.5}>
                  Loading...
                </TextShimmer>
              ) : (
                `${bakeries.length} location${
                  bakeries.length === 1 ? "" : "s"
                }`
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={loadBakeries}
            className="text-xs font-medium text-slate-600 underline-offset-2 hover:underline"
          >
            Refresh
          </button>
        </div>

        {error && (
          <p className="px-4 py-3 text-sm text-red-600">Error: {error}</p>
        )}

        {!error && (
          <div className="overflow-x-auto">
            {loading ? (
              <div className="px-4 py-6">
                <TextShimmer className="text-sm text-slate-500" duration={1.5}>
                  Loading bakeries...
                </TextShimmer>
              </div>
            ) : bakeries.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-500">
                No bakeries yet — add your first one above.
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {bakeries.map((bakery) => (
                  <div
                    key={bakery.id}
                    className="flex items-center justify-between px-4 py-3"
                  >
                    <div className="flex-1 space-y-0.5">
                      <p className="text-sm font-medium text-slate-800">
                        {bakery.name}
                      </p>
                      <p className="text-xs text-slate-500">
                        {bakery.location || "No location"} • {bakery.timezone || DEFAULT_TIMEZONE}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant={currentBakeryId === bakery.id ? "default" : "outline"}
                      onClick={() => setAsCurrent(bakery.id)}
                      className="ml-4"
                    >
                      {currentBakeryId === bakery.id ? "Current" : "Set as current"}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}



