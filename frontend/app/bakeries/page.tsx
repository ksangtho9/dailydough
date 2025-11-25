"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchBakeries,
  createBakery,
  emitBakeryUpdate,
  type Bakery,
  type CreateBakeryPayload,
} from "@/lib/bakeries";

const DEFAULT_TIMEZONE = "America/Los_Angeles";

export default function BakeriesPage() {
  const [bakeries, setBakeries] = useState<Bakery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
  }, [loadBakeries]);

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

      await createBakery(payload);

      setName("");
      setLocation("");
      setTimezone(DEFAULT_TIMEZONE);
      setSuccessMessage("Bakery created.");

      await loadBakeries();
      emitBakeryUpdate();
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
              {loading
                ? "Loading..."
                : `${bakeries.length} location${
                    bakeries.length === 1 ? "" : "s"
                  }`}
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
              <p className="px-4 py-6 text-sm text-slate-500">Loading…</p>
            ) : bakeries.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-500">
                No bakeries yet — add your first one above.
              </div>
            ) : (
              <table className="min-w-full text-sm">
                <thead className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Name</th>
                    <th className="px-4 py-2 text-left">Location</th>
                    <th className="px-4 py-2 text-left">Timezone</th>
                    <th className="px-4 py-2 text-left">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {bakeries.map((bakery) => (
                    <tr key={bakery.id} className="border-b last:border-b-0">
                      <td className="px-4 py-3 font-medium text-slate-800">
                        {bakery.name}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {bakery.location || "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {bakery.timezone || DEFAULT_TIMEZONE}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {bakery.created_at
                          ? new Date(bakery.created_at).toLocaleDateString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

