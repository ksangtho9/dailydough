"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, ChevronDown, ChevronRight } from "lucide-react";
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
const RECORDS_PER_PAGE = 25;

type SalesRecordWithProduct = SalesRecord & {
  product_name: string;
};

type DateRange = "7d" | "30d" | "90d" | "6m" | "all";
type ViewMode = "individual" | "byDate" | "byProduct";

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
  const [productSearch, setProductSearch] = useState<string>("");
  const [viewMode, setViewMode] = useState<ViewMode>("individual");
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
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

  // Calculate the most recent date from sales records
  const mostRecentDate = salesRecords.length > 0 ? salesRecords[0].date : null;
  
  // Calculate the oldest date from all sales records
  const oldestDate = useMemo(() => {
    if (salesRecords.length === 0) return null;
    const dates = salesRecords.map((r) => new Date(r.date).getTime());
    const oldest = new Date(Math.min(...dates));
    return oldest.toISOString().split("T")[0];
  }, [salesRecords]);

  // Calculate date range span in days
  const dateRangeSpan = useMemo(() => {
    if (!mostRecentDate || !oldestDate) return null;
    const newest = new Date(mostRecentDate);
    const oldest = new Date(oldestDate);
    newest.setHours(0, 0, 0, 0);
    oldest.setHours(0, 0, 0, 0);
    const diffTime = newest.getTime() - oldest.getTime();
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  }, [mostRecentDate, oldestDate]);
  
  // Calculate days ago for the most recent date
  const getDaysAgo = (dateString: string): number => {
    const date = new Date(dateString);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    date.setHours(0, 0, 0, 0);
    const diffTime = today.getTime() - date.getTime();
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  // Filter sales records based on selected date range
  const cutoffDate = getCutoffDate(dateRange);
  const dateFilteredRecords = cutoffDate
    ? salesRecords.filter((record) => {
        const recordDate = new Date(record.date);
        recordDate.setHours(0, 0, 0, 0);
        return recordDate >= cutoffDate;
      })
    : salesRecords;

  // Filter by product search
  const filteredRecords = useMemo(() => {
    if (!productSearch.trim()) return dateFilteredRecords;
    const searchLower = productSearch.toLowerCase().trim();
    return dateFilteredRecords.filter((record) =>
      record.product_name.toLowerCase().includes(searchLower)
    );
  }, [dateFilteredRecords, productSearch]);

  // Calculate summary metrics
  const summaryMetrics = useMemo(() => {
    if (filteredRecords.length === 0) {
      return {
        totalSales: 0,
        averagePerDay: 0,
        uniqueProducts: 0,
        topProducts: [] as Array<{ name: string; total: number }>,
      };
    }

    const totalSales = filteredRecords.reduce(
      (sum, record) => sum + Number(record.quantity_sold),
      0
    );

    // Get unique dates
    const uniqueDates = new Set(
      filteredRecords.map((r) => r.date.split("T")[0])
    );
    const daysCount = uniqueDates.size;
    const averagePerDay = daysCount > 0 ? totalSales / daysCount : 0;

    // Get unique products
    const uniqueProducts = new Set(
      filteredRecords.map((r) => r.product_name)
    ).size;

    // Calculate top products
    const productTotals = new Map<string, number>();
    filteredRecords.forEach((record) => {
      const current = productTotals.get(record.product_name) || 0;
      productTotals.set(
        record.product_name,
        current + Number(record.quantity_sold)
      );
    });

    const topProducts = Array.from(productTotals.entries())
      .map(([name, total]) => ({ name, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 3);

    return {
      totalSales,
      averagePerDay,
      uniqueProducts,
      topProducts,
    };
  }, [filteredRecords]);

  // Group records based on view mode
  const groupedRecords = useMemo(() => {
    if (viewMode === "individual") {
      return { type: "individual" as const, records: filteredRecords };
    }

    if (viewMode === "byDate") {
      const groups = new Map<string, SalesRecordWithProduct[]>();
      filteredRecords.forEach((record) => {
        const dateKey = record.date.split("T")[0];
        const existing = groups.get(dateKey) || [];
        groups.set(dateKey, [...existing, record]);
      });

      const sortedGroups = Array.from(groups.entries()).sort(
        (a, b) => b[0].localeCompare(a[0])
      );

      return {
        type: "byDate" as const,
        groups: sortedGroups.map(([date, records]) => ({
          key: date,
          label: formatDate(date),
          total: records.reduce(
            (sum, r) => sum + Number(r.quantity_sold),
            0
          ),
          records,
        })),
      };
    }

    // byProduct
    const groups = new Map<string, SalesRecordWithProduct[]>();
    filteredRecords.forEach((record) => {
      const existing = groups.get(record.product_name) || [];
      groups.set(record.product_name, [...existing, record]);
    });

    const sortedGroups = Array.from(groups.entries()).sort((a, b) =>
      a[0].localeCompare(b[0])
    );

    return {
      type: "byProduct" as const,
      groups: sortedGroups.map(([product, records]) => ({
        key: product,
        label: product,
        total: records.reduce(
          (sum, r) => sum + Number(r.quantity_sold),
          0
        ),
        records: records.sort(
          (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
        ),
      })),
    };
  }, [filteredRecords, viewMode]);

  // Pagination
  const paginatedRecords = useMemo(() => {
    if (groupedRecords.type === "individual") {
      const start = (currentPage - 1) * RECORDS_PER_PAGE;
      const end = start + RECORDS_PER_PAGE;
      return groupedRecords.records.slice(start, end);
    }
    // For grouped views, paginate groups
    const start = (currentPage - 1) * RECORDS_PER_PAGE;
    const end = start + RECORDS_PER_PAGE;
    return groupedRecords.groups.slice(start, end);
  }, [groupedRecords, currentPage]);

  const totalPages = useMemo(() => {
    if (groupedRecords.type === "individual") {
      return Math.ceil(groupedRecords.records.length / RECORDS_PER_PAGE);
    }
    return Math.ceil(groupedRecords.groups.length / RECORDS_PER_PAGE);
  }, [groupedRecords]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [dateRange, productSearch, viewMode]);

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

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
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">History</h1>
          <p className="mt-1 text-sm text-slate-600">
            {productSearch
              ? `Showing ${filteredRecords.length} of ${dateFilteredRecords.length} filtered records`
              : `Showing ${filteredRecords.length} of ${salesRecords.length} records`}
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

      {/* Summary Cards */}
      {filteredRecords.length > 0 && (
        <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Total Sales
            </p>
            <p className="mt-2 text-2xl font-bold text-slate-900">
              {summaryMetrics.totalSales.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
            </p>
            <p className="mt-1 text-xs text-slate-500">Units sold</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Average per Day
            </p>
            <p className="mt-2 text-2xl font-bold text-slate-900">
              {summaryMetrics.averagePerDay.toLocaleString(undefined, {
                maximumFractionDigits: 1,
              })}
            </p>
            <p className="mt-1 text-xs text-slate-500">Units per day</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Unique Products
            </p>
            <p className="mt-2 text-2xl font-bold text-slate-900">
              {summaryMetrics.uniqueProducts}
            </p>
            <p className="mt-1 text-xs text-slate-500">Different products</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Top Product
            </p>
            <p className="mt-2 text-lg font-semibold text-slate-900 line-clamp-1">
              {summaryMetrics.topProducts[0]?.name || "—"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {summaryMetrics.topProducts[0]
                ? `${summaryMetrics.topProducts[0].total.toLocaleString()} units`
                : "No data"}
            </p>
          </div>
        </section>
      )}

      {/* Filters and View Mode */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Product Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search by product name..."
            value={productSearch}
            onChange={(e) => setProductSearch(e.target.value)}
            className="w-full rounded-full border border-slate-200 bg-white pl-10 pr-4 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-400/20"
          />
        </div>

        {/* View Mode Selector */}
        <div className="inline-flex items-center rounded-full bg-white/70 px-1 py-1 text-xs shadow-sm border border-amber-100">
          <button
            type="button"
            onClick={() => setViewMode("individual")}
            className={`px-3 py-1 rounded-full transition ${
              viewMode === "individual"
                ? "bg-amber-500 text-white shadow-sm"
                : "text-slate-700 hover:bg-amber-50"
            }`}
          >
            Individual
          </button>
          <button
            type="button"
            onClick={() => setViewMode("byDate")}
            className={`px-3 py-1 rounded-full transition ${
              viewMode === "byDate"
                ? "bg-amber-500 text-white shadow-sm"
                : "text-slate-700 hover:bg-amber-50"
            }`}
          >
            By Date
          </button>
          <button
            type="button"
            onClick={() => setViewMode("byProduct")}
            className={`px-3 py-1 rounded-full transition ${
              viewMode === "byProduct"
                ? "bg-amber-500 text-white shadow-sm"
                : "text-slate-700 hover:bg-amber-50"
            }`}
          >
            By Product
          </button>
        </div>
      </div>

      {/* Data Date Range Section */}
      {mostRecentDate && oldestDate && (
        <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-4 shadow-sm">
          <div className="grid gap-4 md:grid-cols-3">
            {/* Most Recent Date */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                Most Recent Data
              </p>
              <p className="mt-1 text-lg font-semibold text-slate-900">
                {formatDate(mostRecentDate)}
              </p>
              <div className="mt-2">
                {(() => {
                  const daysAgo = getDaysAgo(mostRecentDate);
                  if (daysAgo === 0) {
                    return (
                      <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        Today
                      </span>
                    );
                  } else if (daysAgo === 1) {
                    return (
                      <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                        Yesterday
                      </span>
                    );
                  } else {
                    return (
                      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                        {daysAgo} days ago
                      </span>
                    );
                  }
                })()}
              </div>
            </div>

            {/* Oldest Date */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                Oldest Data
              </p>
              <p className="mt-1 text-lg font-semibold text-slate-900">
                {formatDate(oldestDate)}
              </p>
              <div className="mt-2">
                {(() => {
                  const daysAgo = getDaysAgo(oldestDate);
                  return (
                    <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                      {daysAgo} days ago
                    </span>
                  );
                })()}
              </div>
            </div>

            {/* Date Range Span */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                Data Range
              </p>
              <p className="mt-1 text-lg font-semibold text-slate-900">
                {dateRangeSpan !== null
                  ? dateRangeSpan === 0
                    ? "Single day"
                    : `${dateRangeSpan.toLocaleString()} days`
                  : "—"}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {dateRangeSpan !== null && dateRangeSpan > 0
                  ? `From ${formatDate(oldestDate)} to ${formatDate(mostRecentDate)}`
                  : "No range data"}
              </p>
            </div>
          </div>
        </div>
      )}

      {filteredRecords.length === 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm text-slate-600">
            No sales records found for the selected filters. Try adjusting your
            search or date range.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    {viewMode !== "individual" && (
                      <th className="px-6 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider w-12"></th>
                    )}
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
                      {viewMode === "byProduct" ? "Product" : "Date"}
                    </th>
                    {viewMode === "individual" && (
                      <th className="px-6 py-3 text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
                        Product
                      </th>
                    )}
                    <th className="px-6 py-3 text-right text-xs font-medium text-slate-700 uppercase tracking-wider">
                      Quantity Sold
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-200">
                  {viewMode === "individual" ? (
                    // Individual records view
                    paginatedRecords.map((record) => (
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
                    ))
                  ) : (
                    // Grouped views (byDate or byProduct)
                    paginatedRecords.map((group) => {
                      const isExpanded = expandedGroups.has(group.key);
                      return (
                        <React.Fragment key={group.key}>
                          <tr
                            className="hover:bg-slate-50 cursor-pointer"
                            onClick={() => toggleGroup(group.key)}
                          >
                            <td className="px-6 py-4">
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4 text-slate-500" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-slate-500" />
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-slate-900">
                              {group.label}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-slate-900 text-right">
                              {group.total.toLocaleString(undefined, {
                                maximumFractionDigits: 0,
                              })}
                            </td>
                          </tr>
                          {isExpanded &&
                            group.records.map((record) => (
                              <tr
                                key={record.id}
                                className="bg-slate-50/50 hover:bg-slate-100"
                              >
                                <td className="px-6 py-2"></td>
                                <td className="px-6 py-2 whitespace-nowrap text-sm text-slate-600 pl-8">
                                  {viewMode === "byDate"
                                    ? record.product_name
                                    : formatDate(record.date)}
                                </td>
                                <td className="px-6 py-2 whitespace-nowrap text-sm text-slate-600 text-right">
                                  {Number(record.quantity_sold).toLocaleString(
                                    undefined,
                                    {
                                      maximumFractionDigits: 0,
                                    }
                                  )}
                                </td>
                              </tr>
                            ))}
                        </React.Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
              <div className="text-sm text-slate-600">
                Showing page {currentPage} of {totalPages}
                {viewMode === "individual" && groupedRecords.type === "individual" && (
                  <span className="ml-2">
                    (
                    {(currentPage - 1) * RECORDS_PER_PAGE + 1}-
                    {Math.min(
                      currentPage * RECORDS_PER_PAGE,
                      groupedRecords.records.length
                    )}{" "}
                    of {groupedRecords.records.length})
                  </span>
                )}
                {viewMode !== "individual" && groupedRecords.type !== "individual" && (
                  <span className="ml-2">
                    (
                    {(currentPage - 1) * RECORDS_PER_PAGE + 1}-
                    {Math.min(
                      currentPage * RECORDS_PER_PAGE,
                      groupedRecords.groups.length
                    )}{" "}
                    of {groupedRecords.groups.length})
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <div className="flex items-center gap-1">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pageNum;
                    if (totalPages <= 5) {
                      pageNum = i + 1;
                    } else if (currentPage <= 3) {
                      pageNum = i + 1;
                    } else if (currentPage >= totalPages - 2) {
                      pageNum = totalPages - 4 + i;
                    } else {
                      pageNum = currentPage - 2 + i;
                    }
                    return (
                      <button
                        key={pageNum}
                        type="button"
                        onClick={() => setCurrentPage(pageNum)}
                        className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                          currentPage === pageNum
                            ? "bg-amber-500 text-white shadow-sm"
                            : "text-slate-700 hover:bg-amber-50"
                        }`}
                      >
                        {pageNum}
                      </button>
                    );
                  })}
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setCurrentPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={currentPage === totalPages}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
