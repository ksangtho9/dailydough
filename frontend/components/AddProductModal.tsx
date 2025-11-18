"use client";

import { useState, FormEvent } from "react";
import { apiFetch } from "@/lib/api";

type Product = {
  id: number;
  name: string;
  sku?: string | null;
  bakery_id?: number | null;
};

type AddProductModalProps = {
  bakeryId: number | null;
  onClose: () => void;
  onCreated: (product: Product) => void;
};

export function AddProductModal({
  bakeryId,
  onClose,
  onCreated,
}: AddProductModalProps) {
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (bakeryId == null) {
      setError("Please select a bakery first.");
      return;
    }

    try {
      setLoading(true);

      const newProduct = await apiFetch<Product>("/api/products/", {
        method: "POST",
        body: JSON.stringify({
          name,
          sku: sku || null,
          bakery_id: bakeryId,
        }),
      });

      onCreated(newProduct);
      onClose();
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to create product");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold">Add product</h3>
        <p className="mt-1 text-xs text-slate-600">
          Create a new product for the selected bakery.
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600">
              Name
            </label>
            <input
              type="text"
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600">
              SKU (optional)
            </label>
            <input
              type="text"
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
            />
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-3 py-2 text-sm hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {loading ? "Saving…" : "Create product"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
