"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { fetchSalesRecords, type SalesRecord } from "@/lib/sales";
import { BAKERY_SELECTION_CHANGED_EVENT } from "@/lib/bakeries";
import { TextShimmer } from "@/components/ui/text-shimmer";

type Product = {
  id: number;
  name: string;
  bakery_id?: number | null;
};

const BAKERY_STORAGE_KEY = "current_bakery_id";

type SalesRecordWithProduct = SalesRecord & {
  product_name: string;
};

type DateRange = "7d" | "30d" | "90d" | "6m" | "all";

const dateRangeOptions: { value: DateRange; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "6m", label: "Last 6 months" },
  { value: "all", label: "All time" },
];

function getCutoffDate(range: DateRange): Date | null {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  switch (range) {
    case "7d":
      return new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
    case "30d":
      return new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
    case "90d":
      return new Date(today.getTime() - 90 * 24 * 60 * 60 * 1000);
    case "6m":
      const sixMonthsAgo = new Date(today);
      sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
      return sixMonthsAgo;
    case "all":
      return null;
  }
}

export default function HistoryPage() {
  const router = useRouter();
  const [salesRecords, setSalesRecords] = useState<SalesRecordWithProduct[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedBakeryId, setSelectedBakeryId] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<DateRange>("30d");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      if (typeof window === "undefined") return;

      const token = localStorage.getItem("access_token");
      if (!token) {
        router.push("/login");
        return;
      }

      const bakeryId = localStorage.getItem(BAKERY_STORAGE_KEY);
      if (!bakeryId) {
        setSelectedBakeryId(null);
        setSalesRecords([]);
        setLoading(false);
        return;
      }

      setSelectedBakeryId(bakeryId);
      const bakeryIdNum = parseInt(bakeryId, 10);

      // Fetch products and sales records in parallel
      const [productsData, salesData] = await Promise.all([
        apiFetch<Product[]>("/api/products/"),
        fetchSalesRecords(bakeryIdNum),
      ]);

      setProducts(productsData);

      // Map product names to sales records
      const productMap = new Map(
        productsData.map((p) => [p.id, p.name])
      );

      const recordsWithProducts: SalesRecordWithProduct[] = salesData.map(
        (record) => ({
          ...record,
          product_name: productMap.get(record.product_id) || "Unknown Product",
        })
      );

      // Sort by date descending (most recent first)
      recordsWithProducts.sort(
        (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
      );

      setSalesRecords(recordsWithProducts);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    function handleSelectionChange() {
      loadData();
    }

    window.addEventListener(
      BAKERY_SELECTION_CHANGED_EVENT,
      handleSelectionChange
    );
    return () =>
      window.removeEventListener(
        BAKERY_SELECTION_CHANGED_EVENT,
        handleSelectionChange
      );
  }, [loadData]);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  // Filter sales records based on selected date range
  const cutoffDate = getCutoffDate(dateRange);
  const filteredRecords = cutoffDate
    ? salesRecords.filter((record) => {
        const recordDate = new Date(record.date);
        recordDate.setHours(0, 0, 0, 0);
        return recordDate >= cutoffDate;
      })
    : salesRecords;

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">History</h1>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <TextShimmer className="text-sm text-slate-600" duration={1.5}>
            Loading sales history...
          </TextShimmer>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">History</h1>
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 shadow-sm">
          <p className="text-sm text-red-700">
            Error: {error}
          </p>
        </div>
      </div>
    );
  }

  if (!selectedBakeryId) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">History</h1>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm text-slate-600">
            No bakery selected. Please select a bakery from the top navigation
            to view sales history.
          </p>
        </div>
      </div>
    );
  }

  if (salesRecords.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-slate-900">History</h1>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm text-slate-600">
            No sales records found. Upload sales data to see history here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">History</h1>
          <p className="mt-1 text-sm text-slate-600">
            Showing {filteredRecords.length} of {salesRecords.length} records
          </p>
        </div>

        {/* Date Range Selector */}
        <div className="inline-flex items-center rounded-full bg-white/70 px-1 py-1 text-xs shadow-sm border border-amber-100">
          {dateRangeOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setDateRange(option.value)}
              className={`px-3 py-1 rounded-full transition ${
                dateRange === option.value
                  ? "bg-amber-500 text-white shadow-sm"
                  : "text-slate-700 hover:bg-amber-50"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {filteredRecords.length === 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm text-slate-600">
            No sales records found for the selected date range. Try selecting a
            different time period.
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
                    Product
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-slate-700 uppercase tracking-wider">
                    Quantity Sold
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-slate-200">
                {filteredRecords.map((record) => (
                  <tr key={record.id} className="hover:bg-slate-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900">
                      {formatDate(record.date)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900">
                      {record.product_name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 text-right">
                      {Number(record.quantity_sold).toLocaleString(undefined, {
                        maximumFractionDigits: 0,
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
