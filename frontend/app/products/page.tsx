"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Product = {
  id: number;
  name: string;
  sku?: string | null;
  bakery_id?: number;
};

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadProducts() {
      try {
        const data = await apiFetch<Product[]>("/api/products/");
        setProducts(data);
      } catch (err: any) {
        setError(err.message || "Failed to load products");
      } finally {
        setLoading(false);
      }
    }

    loadProducts();
  }, []);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Products</h2>

      {loading && <p>Loading…</p>}
      {error && <p className="text-red-600">Error: {error}</p>}

      {!loading && !error && (
        <div className="overflow-x-auto border bg-white rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 border-b text-slate-500">
              <tr>
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">SKU</th>
              </tr>
            </thead>

            <tbody>
              {products.map((p) => (
                <tr key={p.id} className="border-b">
                  <td className="px-4 py-2">{p.id}</td>

                  {/* Clickable product name */}
                  <td className="px-4 py-2 font-medium">
                    <Link
                      href={`/products/${p.id}`}
                      className="text-blue-600 hover:underline"
                    >
                      {p.name}
                    </Link>
                  </td>

                  <td className="px-4 py-2">{p.sku || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
