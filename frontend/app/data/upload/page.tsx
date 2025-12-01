"use client";

import Link from "next/link";
import {
  ChangeEvent,
  DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Trash2, AlertTriangle } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import { BAKERY_SELECTION_CHANGED_EVENT } from "@/lib/bakeries";

const REQUIRED_ROLES = ["date", "product_id", "product_name", "quantity"] as const;
const OPTIONAL_ROLES = ["shelf_life"] as const;
const ALL_ROLES = [...REQUIRED_ROLES, ...OPTIONAL_ROLES] as const;

type Role = (typeof ALL_ROLES)[number];

type UploadResult = {
  filename: string;
  inserted: number;
  sales_rows_inserted?: number;
  skipped_missing_product: number;
  created_products?: number;
  existing_products_used?: number;
  parse_errors: string[];
  row_errors: string[];
};

type SchemaInferenceDetail = {
  code: string;
  message: string;
  inferred_mapping: Record<string, string | null>;
  missing_roles: (typeof REQUIRED_ROLES)[number][];
  available_columns: string[];
};

type MappingState = Record<Role, string>;

const ROLE_LABEL: Record<Role, string> = {
  date: "Date",
  product_id: "Product ID",
  product_name: "Product Name",
  quantity: "Quantity",
  shelf_life: "Shelf life (optional)",
};

const ROLE_DESCRIPTION: Record<Role, string> = {
  date: "Calendar date for the sale (e.g., date, sale_date)",
  product_id: "SKU / external identifier (e.g., Product Code, SKU, product_id)",
  product_name: "Human readable product name (e.g., Product Name)",
  quantity: "Units sold for that date (e.g., Sales Qty, quantity, qty)",
  shelf_life:
    "Boolean or numeric shelf-life flag. TRUE/Yes/Y/1 or values >1 → 2 days; other non-empty values → 1 day.",
};

const createEmptyMapping = (): MappingState =>
  ALL_ROLES.reduce(
    (acc, role) => {
      acc[role] = "";
      return acc;
    },
    {} as MappingState,
  );

const STORAGE_KEY = "current_bakery_id";

export default function DataUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [schemaDetail, setSchemaDetail] = useState<SchemaInferenceDetail | null>(
    null,
  );
  const [availableColumns, setAvailableColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<MappingState>(createEmptyMapping());
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [bakeryId, setBakeryId] = useState<number | null>(null);
  const [uploadMode, setUploadMode] = useState<"append" | "replace">("append");
  const [deleteDateFrom, setDeleteDateFrom] = useState<string>("");
  const [deleteDateTo, setDeleteDateTo] = useState<string>("");
  const [deleteProductId, setDeleteProductId] = useState<string>("");
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteCount, setDeleteCount] = useState<number | null>(null);
  const [deleteAllConfirm, setDeleteAllConfirm] = useState(false);
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);

  const hasFile = Boolean(file);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const asNum = Number(stored);
      if (!Number.isNaN(asNum)) {
        setBakeryId(asNum);
      }
    }

    function handleSelectionChange() {
      if (typeof window === "undefined") return;
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        setBakeryId(null);
        return;
      }
      const asNum = Number(stored);
      setBakeryId(Number.isNaN(asNum) ? null : asNum);
    }

    window.addEventListener(
      BAKERY_SELECTION_CHANGED_EVENT,
      handleSelectionChange
    );
    return () => {
      window.removeEventListener(
        BAKERY_SELECTION_CHANGED_EVENT,
        handleSelectionChange
      );
    };
  }, []);

  const handleFileChange = (selected: File | null) => {
    setFile(selected);
    setError(null);
    setResult(null);
    setSchemaDetail(null);
    setAvailableColumns([]);
    setMapping(createEmptyMapping());
    setMappingError(null);
  };

  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    handleFileChange(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const dropped = e.dataTransfer.files?.[0] ?? null;
    if (dropped) {
      handleFileChange(dropped);
    }
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const authHeaders = useCallback((): HeadersInit | undefined => {
    if (typeof window === "undefined") return undefined;
    const token = window.localStorage.getItem("access_token");
    if (!token) return undefined;
    return {
      Authorization: `Bearer ${token}`,
    };
  }, []);

  const submitUpload = useCallback(
    async (mappingOverride?: MappingState) => {
      if (!file) {
        setError("Please choose a CSV file first.");
        return;
      }

      if (!bakeryId) {
        setError("Please select a bakery before uploading sales data. Go to the Bakeries page to create or select a bakery.");
        return;
      }

      setLoading(true);
      setError(null);
      setMappingError(null);
      if (!mappingOverride) {
        setSchemaDetail(null);
      }
      setResult(null);

      const form = new FormData();
      form.append("file", file);
      form.append("upload_mode", uploadMode);
      if (mappingOverride) {
        form.append("column_mapping", JSON.stringify(mappingOverride));
      }

      try {
        // Use bakery-specific endpoint
        const response = await fetch(
          `${API_BASE_URL}/api/bakeries/${bakeryId}/sales/upload`,
          {
            method: "POST",
            body: form,
            headers: authHeaders(),
          },
        );

        if (!response.ok) {
          const contentType = response.headers.get("content-type");
          if (contentType?.includes("application/json")) {
            const payload = await response.json();
            const detail = payload?.detail;
            if (detail?.code === "schema_inference_failed") {
              setSchemaDetail(detail);
              setAvailableColumns(detail.available_columns ?? []);
              setMapping(() => {
                const inferred = detail.inferred_mapping ?? {};
                const next = createEmptyMapping();
                for (const role of ALL_ROLES) {
                  const value = inferred[role];
                  next[role] = typeof value === "string" ? value : "";
                }
                return next;
              });
              return;
            }
            setError(
              typeof detail === "string"
                ? detail
                : detail?.message || "Upload failed.",
            );
          } else {
            const text = await response.text();
            setError(text || "Upload failed.");
          }
          return;
        }

        const data = (await response.json()) as UploadResult;
        setResult(data);
        setSchemaDetail(null);
        setAvailableColumns([]);
        setMapping(createEmptyMapping());
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to upload CSV.";
        setError(message);
      } finally {
        setLoading(false);
      }
    },
    [authHeaders, file, bakeryId, uploadMode],
  );

  const handleDeleteAll = useCallback(async () => {
    if (!bakeryId) {
      setDeleteError("Please select a bakery before deleting data.");
      return;
    }

    setDeleteAllLoading(true);
    setDeleteError(null);

    try {
      // Delete all sales data (no query parameters = delete all)
      const response = await fetch(
        `${API_BASE_URL}/api/bakeries/${bakeryId}/sales`,
        {
          method: "DELETE",
          headers: authHeaders(),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Delete failed" }));
        setDeleteError(errorData.detail || "Failed to delete all data");
        return;
      }

      const data = await response.json();
      setDeleteCount(data.deleted_count);
      setDeleteAllConfirm(false);
      // Clear filter fields too
      setDeleteDateFrom("");
      setDeleteDateTo("");
      setDeleteProductId("");
      // Clear deleteError on success
      setDeleteError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete all data.";
      setDeleteError(message);
    } finally {
      setDeleteAllLoading(false);
    }
  }, [authHeaders, bakeryId]);

  const handleDelete = useCallback(async () => {
    if (!bakeryId) {
      setDeleteError("Please select a bakery before deleting data.");
      return;
    }

    setDeleteLoading(true);
    setDeleteError(null);

    try {
      const params = new URLSearchParams();
      if (deleteDateFrom) params.append("date_from", deleteDateFrom);
      if (deleteDateTo) params.append("date_to", deleteDateTo);
      if (deleteProductId) params.append("product_id", deleteProductId);

      const response = await fetch(
        `${API_BASE_URL}/api/bakeries/${bakeryId}/sales?${params.toString()}`,
        {
          method: "DELETE",
          headers: authHeaders(),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Delete failed" }));
        setDeleteError(errorData.detail || "Failed to delete data");
        return;
      }

      const data = await response.json();
      setDeleteCount(data.deleted_count);
      setDeleteConfirm(false);
      setDeleteDateFrom("");
      setDeleteDateTo("");
      setDeleteProductId("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete data.";
      setDeleteError(message);
    } finally {
      setDeleteLoading(false);
    }
  }, [authHeaders, bakeryId, deleteDateFrom, deleteDateTo, deleteProductId]);

  const handleUpload = () => submitUpload();

  const handleMappingChange = (role: Role, value: string) => {
    setMapping((prev) => ({
      ...prev,
      [role]: value,
    }));
  };

  const mappingIsComplete = useMemo(() => {
    const values = REQUIRED_ROLES.map((role) => mapping[role]).filter(Boolean);
    return values.length === REQUIRED_ROLES.length;
  }, [mapping]);

  const validateMapping = (): boolean => {
    const missingRole = REQUIRED_ROLES.find((role) => !mapping[role]);
    if (missingRole) {
      setMappingError(`Please select a column for ${ROLE_LABEL[missingRole]}.`);
      return false;
    }
    const values = Object.values(mapping);
    const unique = new Set(values);
    if (unique.size !== values.length) {
      setMappingError("Each role must map to a unique CSV column.");
      return false;
    }
    setMappingError(null);
    return true;
  };

  const handleConfirmMapping = () => {
    if (!validateMapping()) {
      return;
    }
    submitUpload(mapping);
  };

  const summaryStats = useMemo(() => {
    if (!result) return [];
    return [
      {
        label: "Sales rows inserted",
        value: (result.sales_rows_inserted ?? result.inserted).toLocaleString(),
      },
      {
        label: "New products created",
        value: (result.created_products ?? 0).toLocaleString(),
      },
      {
        label: "Existing products referenced",
        value: (result.existing_products_used ?? 0).toLocaleString(),
      },
      {
        label: "Skipped rows (missing product)",
        value: result.skipped_missing_product.toLocaleString(),
      },
    ];
  }, [result]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">
          Data import
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-[#0f172a]">
          Upload sales CSV
        </h1>
        <p className="text-sm text-slate-600">
          Drop in historical sales and we&apos;ll auto-detect columns. If we
          can&apos;t infer them all, you&apos;ll be able to map them manually.
        </p>
        {!bakeryId && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
            <strong>No bakery selected.</strong> Please{" "}
            <Link href="/bakeries" className="font-medium underline hover:text-amber-900">
              select or create a bakery
            </Link>{" "}
            before uploading data. The bakery is taken from your current selection, so you don&apos;t need a bakery_id column in the file.
          </div>
        )}
      </header>

      <section
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`rounded-2xl border-2 border-dashed px-6 py-10 text-sm transition ${
          dragActive ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"
        }`}
      >
        <div className="flex flex-col items-center gap-4">
          <p className="text-slate-700">
            Drag & drop a CSV file or click to browse.
          </p>
          <label className="cursor-pointer rounded-full border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">
            Choose file
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={onInputChange}
            />
          </label>
          <p className="text-xs text-slate-500">
            {file ? `Selected: ${file.name}` : "No file selected yet"}
          </p>

          {/* Upload Mode Selector */}
          {hasFile && (
            <div className="w-full max-w-md space-y-2">
              <label className="block text-xs font-medium text-slate-700">
                Upload Mode
              </label>
              <div className="flex gap-4 rounded-lg border border-slate-200 bg-white p-2">
                <label className="flex flex-1 cursor-pointer items-center gap-2 rounded-md px-3 py-2 hover:bg-slate-50">
                  <input
                    type="radio"
                    name="upload_mode"
                    value="append"
                    checked={uploadMode === "append"}
                    onChange={(e) => setUploadMode(e.target.value as "append" | "replace")}
                    className="h-4 w-4 text-slate-900 focus:ring-slate-500"
                  />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-slate-900">Append</p>
                    <p className="text-xs text-slate-500">
                      Add new data to existing records
                    </p>
                  </div>
                </label>
                <label className="flex flex-1 cursor-pointer items-center gap-2 rounded-md px-3 py-2 hover:bg-slate-50">
                  <input
                    type="radio"
                    name="upload_mode"
                    value="replace"
                    checked={uploadMode === "replace"}
                    onChange={(e) => setUploadMode(e.target.value as "append" | "replace")}
                    className="h-4 w-4 text-slate-900 focus:ring-slate-500"
                  />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-slate-900">Replace</p>
                    <p className="text-xs text-slate-500">
                      Replace existing data for matching dates
                    </p>
                  </div>
                </label>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={handleUpload}
            disabled={!hasFile || loading || !bakeryId}
            className="rounded-full bg-slate-900 px-6 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Uploading…" : "Upload CSV"}
          </button>
          <p className="text-xs text-slate-500 max-w-md text-center">
            <strong>Required columns:</strong> Date, Product/SKU, and Sold quantity.
            The bakery is taken from your current selection, so you don&apos;t need a bakery_id column.
            Optional delivery/production columns are used to improve forecasts. Waste columns are ignored.
          </p>
        </div>
      </section>

      {/* Delete Data Section */}
      {bakeryId && (
        <section className="space-y-4">
          {/* Delete All Data Section */}
          <div className="rounded-2xl border-2 border-red-300 bg-red-50 p-6 shadow-sm">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-6 w-6 text-red-600 mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <h2 className="text-xl font-semibold text-slate-900">Delete All Data & Reset Model</h2>
                <p className="text-sm text-slate-700 mt-2">
                  Permanently delete all sales data for this bakery. This will also reset all forecast models and metrics.
                  You can re-upload data afterward to train fresh models.
                </p>
                <div className="mt-4 flex items-center gap-4">
                  {!deleteAllConfirm ? (
                    <>
                      <button
                        type="button"
                        onClick={() => setDeleteAllConfirm(true)}
                        disabled={deleteAllLoading || deleteLoading}
                        className="inline-flex items-center gap-2 rounded-full border-2 border-red-600 bg-red-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 hover:border-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Trash2 className="h-5 w-5" />
                        Delete All Data
                      </button>
                      <p className="text-xs font-medium text-red-700">
                        ⚠️ This action cannot be undone
                      </p>
                    </>
                  ) : (
                    <div className="flex-1 rounded-lg border-2 border-red-300 bg-red-100 p-4">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="h-5 w-5 text-red-700 mt-0.5 flex-shrink-0" />
                        <div className="flex-1">
                          <p className="text-sm font-semibold text-red-900 mb-2">
                            Confirm: Delete All Data & Reset Model
                          </p>
                          <div className="text-sm text-red-800 mb-4">
                            <p className="mb-2">This will permanently delete:</p>
                            <ul className="list-disc list-inside mt-2 space-y-1 mb-2">
                              <li>All sales records for this bakery</li>
                              <li>All forecast model metrics and accuracy data</li>
                            </ul>
                            <p>The model will be reset and can be retrained when you upload new data.</p>
                          </div>
                          <div className="flex items-center gap-3">
                            <button
                              type="button"
                              onClick={handleDeleteAll}
                              disabled={deleteAllLoading}
                              className="inline-flex items-center gap-2 rounded-full bg-red-700 px-6 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {deleteAllLoading ? "Deleting..." : "Yes, Delete Everything"}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setDeleteAllConfirm(false);
                                setDeleteError(null);
                              }}
                              disabled={deleteAllLoading}
                              className="rounded-full border-2 border-slate-300 bg-white px-6 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                
                {/* Error message for delete all - only show if deleteAll was attempted */}
                {deleteError && (deleteAllConfirm || deleteAllLoading) && (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-100 px-3 py-2 text-sm text-red-700">
                    {deleteError}
                  </div>
                )}
                
                {/* Success message for delete all - only show if deleteAll was used */}
                {deleteCount !== null && !deleteDateFrom && !deleteDateTo && !deleteProductId && deleteAllConfirm === false && (
                  <div className="mt-3 rounded-lg border border-green-200 bg-green-100 px-3 py-2 text-sm text-green-700">
                    Successfully deleted {deleteCount.toLocaleString()} record(s) and reset all forecast models.
                    You can now upload new data to train fresh models.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Filtered Delete Section */}
          <div className="rounded-2xl border border-red-100 bg-red-50/50 p-5 shadow-sm">
            <div className="flex items-start gap-3">
              <Trash2 className="h-5 w-5 text-red-600 mt-0.5" />
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-slate-900">Delete Sales Data (Filtered)</h2>
                <p className="text-sm text-slate-600 mt-1">
                  Delete specific sales records using filters. Leave all fields empty to delete all sales for this bakery.
                </p>

              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Date From (optional)
                  </label>
                  <input
                    type="date"
                    value={deleteDateFrom}
                    onChange={(e) => setDeleteDateFrom(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-red-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Date To (optional)
                  </label>
                  <input
                    type="date"
                    value={deleteDateTo}
                    onChange={(e) => setDeleteDateTo(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-red-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Product ID (optional)
                  </label>
                  <input
                    type="number"
                    value={deleteProductId}
                    onChange={(e) => setDeleteProductId(e.target.value)}
                    placeholder="All products"
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-red-500"
                  />
                </div>
              </div>

              {/* Only show messages if deleteAll was not used */}
              {deleteError && deleteAllConfirm === false && !deleteAllLoading && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-100 px-3 py-2 text-sm text-red-700">
                  {deleteError}
                </div>
              )}

              {deleteCount !== null && (deleteDateFrom || deleteDateTo || deleteProductId || deleteConfirm) && (
                <div className="mt-3 rounded-lg border border-green-200 bg-green-100 px-3 py-2 text-sm text-green-700">
                  Successfully deleted {deleteCount.toLocaleString()} record(s).
                </div>
              )}

              {!deleteConfirm ? (
                <div className="mt-4 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setDeleteConfirm(true)}
                    disabled={deleteLoading}
                    className="inline-flex items-center gap-2 rounded-full border border-red-300 bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete Data
                  </button>
                  <p className="text-xs text-slate-500">
                    {deleteDateFrom || deleteDateTo || deleteProductId
                      ? "Deletes records matching the filters above"
                      : "⚠️ Will delete ALL sales data for this bakery"}
                  </p>
                </div>
              ) : (
                <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="h-5 w-5 text-amber-600 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-amber-900">
                        Confirm Deletion
                      </p>
                      <p className="text-sm text-amber-800 mt-1">
                        This action cannot be undone. Are you sure you want to delete{" "}
                        {deleteDateFrom || deleteDateTo || deleteProductId
                          ? "the filtered sales data"
                          : "ALL sales data for this bakery"}
                        ?
                      </p>
                      <div className="mt-3 flex items-center gap-3">
                        <button
                          type="button"
                          onClick={handleDelete}
                          disabled={deleteLoading}
                          className="rounded-full bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {deleteLoading ? "Deleting…" : "Yes, Delete"}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setDeleteConfirm(false);
                            setDeleteError(null);
                          }}
                          disabled={deleteLoading}
                          className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              </div>
            </div>
          </div>
        </section>
      )}

      {error && (
        <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {schemaDetail && (
        <section className="rounded-2xl border bg-white/80 p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                Map your columns
              </h2>
              <p className="text-sm text-slate-500">
                We couldn&apos;t confidently match every column. Assign them
                below, then confirm to continue.
              </p>
            </div>
            <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
              Missing: {schemaDetail.missing_roles.join(", ")}
            </span>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {ALL_ROLES.map((role) => (
              <div key={role} className="rounded-xl border border-slate-100 p-4">
                <label className="text-sm font-medium text-slate-700">
                  {ROLE_LABEL[role]}
                  {REQUIRED_ROLES.includes(role as (typeof REQUIRED_ROLES)[number]) ? (
                    <span className="ml-1 text-[10px] font-semibold uppercase text-rose-600">
                      *
                    </span>
                  ) : (
                    <span className="ml-1 text-[10px] font-normal uppercase text-slate-400">
                      optional
                    </span>
                  )}
                </label>
                <p className="text-xs text-slate-500 mb-2">
                  {ROLE_DESCRIPTION[role]}
                </p>
                <select
                  value={mapping[role]}
                  onChange={(e) => handleMappingChange(role, e.target.value)}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-500"
                >
                  <option value="">Select column…</option>
                  {availableColumns.map((column) => (
                    <option key={`${role}-${column}`} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          {mappingError && (
            <p className="mt-3 text-sm text-red-600">{mappingError}</p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="rounded-full bg-slate-900 px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={handleConfirmMapping}
              disabled={!mappingIsComplete || loading}
            >
              {loading ? "Uploading…" : "Confirm mapping & upload"}
            </button>
            <button
              type="button"
              className="text-sm font-medium text-slate-600 hover:text-slate-900"
              onClick={() => {
                setSchemaDetail(null);
                setAvailableColumns([]);
                setMapping(createEmptyMapping());
                setMappingError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {result && (
        <section className="rounded-2xl border bg-white/80 p-5 shadow-sm">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                Upload successful
              </h2>
              <p className="text-sm text-slate-500">
                File {result.filename} was processed without blocking errors.
              </p>
            </div>
            <div className="flex gap-2">
              <Link
                href="/products"
                className="rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                View products
              </Link>
              <Link
                href="/dashboard"
                className="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
              >
                View dashboard
              </Link>
            </div>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {summaryStats.map((stat) => (
              <div
                key={stat.label}
                className="rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-3"
              >
                <p className="text-xs text-slate-500">{stat.label}</p>
                <p className="text-xl font-semibold text-slate-900">
                  {stat.value}
                </p>
              </div>
            ))}
          </div>

          {(result.parse_errors.length > 0 || result.row_errors.length > 0) && (
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              {result.parse_errors.length > 0 && (
                <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3">
                  <p className="text-sm font-semibold text-red-700">
                    Parse errors
                  </p>
                  <ul className="mt-2 list-disc pl-5 text-sm text-red-700">
                    {result.parse_errors.map((errMsg, idx) => (
                      <li key={`parse-${idx}`}>{errMsg}</li>
                    ))}
                  </ul>
                </div>
              )}

              {result.row_errors.length > 0 && (
                <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3">
                  <p className="text-sm font-semibold text-amber-800">
                    Row-level issues
                  </p>
                  <ul className="mt-2 list-disc pl-5 text-sm text-amber-800">
                    {result.row_errors.map((errMsg, idx) => (
                      <li key={`row-${idx}`}>{errMsg}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}



