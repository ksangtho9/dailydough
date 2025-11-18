"use client";

import { useState, useCallback, DragEvent, ChangeEvent } from "react";
import { API_BASE_URL } from "@/lib/api";

type UploadResult = {
  filename: string;
  inserted: number;
  skipped_missing_product: number;
  parse_errors: string[];
  row_errors: string[];
};

export default function UploadSalesPage() {
  const [file, setFile] = useState<File | null>(null);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [header, setHeader] = useState<string[]>([]);
  const [dragActive, setDragActive] = useState(false);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ----- CSV preview -----
  const handleFileSelected = useCallback((f: File | null) => {
    setFile(f);
    setResult(null);
    setError(null);
    setPreviewRows([]);
    setHeader([]);

    if (!f) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = String(e.target?.result || "");
      const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
      if (lines.length === 0) return;

      const [headerLine, ...rest] = lines;
      const headerParts = headerLine.split(",");

      const rows = rest.slice(0, 20).map((line) => line.split(","));
      setHeader(headerParts);
      setPreviewRows(rows);
    };
    reader.readAsText(f);
  }, []);

  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    handleFileSelected(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    const f = e.dataTransfer.files?.[0];
    if (f) handleFileSelected(f);
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

  // ----- Upload to backend -----
  async function handleUpload() {
    if (!file) {
      setError("Please choose a CSV file first.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      // 🔐 include auth token if present
      let headers: HeadersInit | undefined = undefined;
      if (typeof window !== "undefined") {
        const token = window.localStorage.getItem("access_token");
        if (token) {
          headers = { Authorization: `Bearer ${token}` };
        }
      }

      const res = await fetch(`${API_BASE_URL}/api/sales/upload-csv`, {
        method: "POST",
        body: formData,
        headers,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Upload failed: ${text}`);
      }

      const data = (await res.json()) as UploadResult;
      setResult(data);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Upload failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h2 className="text-2xl font-semibold">Upload sales CSV</h2>
        <p className="mt-1 text-sm text-slate-600">
          Import historical sales data to power your forecasts. Expected columns:{" "}
          <span className="font-mono text-xs">
            product_id, sale_date, units_sold, revenue
          </span>
          .
        </p>
      </header>

      {/* Dropzone */}
      <section
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-12 text-sm transition ${
          dragActive ? "border-slate-900 bg-slate-50" : "border-slate-300 bg-white"
        }`}
      >
        <p className="mb-2 text-slate-700">
          Drag and drop a CSV file here, or click to choose a file.
        </p>
        <label className="cursor-pointer rounded-lg border px-3 py-2 text-xs font-medium hover:bg-slate-100">
          Choose File
          <input
            type="file"
            accept=".csv"
            onChange={onInputChange}
            className="hidden"
          />
        </label>

        <p className="mt-2 text-xs text-slate-500">
          {file ? `Selected: ${file.name}` : "No file chosen"}
        </p>
      </section>

      {/* Preview */}
      <section className="rounded-2xl border bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-2">
          Preview (first 20 rows)
        </h3>

        {!file && (
          <p className="text-sm text-slate-500">
            Select a CSV file to see a preview.
          </p>
        )}

        {file && previewRows.length === 0 && (
          <p className="text-sm text-slate-500">Reading file…</p>
        )}

        {file && previewRows.length > 0 && (
          <div className="max-h-72 overflow-auto border rounded-lg">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50 border-b text-slate-600">
                <tr>
                  {header.map((h, idx) => (
                    <th key={idx} className="px-3 py-2 text-left font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, idx) => (
                  <tr key={idx} className="border-b last:border-b-0">
                    {row.map((cell, cidx) => (
                      <td key={cidx} className="px-3 py-1.5 text-slate-700">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Actions + result */}
      <section className="space-y-3">
        <button
          type="button"
          onClick={handleUpload}
          disabled={loading || !file}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-40"
        >
          {loading ? "Uploading…" : "Upload CSV"}
        </button>

        {error && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-3 py-2">
            {error}
          </p>
        )}

        {result && (
          <div className="rounded-xl border bg-white p-4 text-sm space-y-2">
            <p>
              <span className="font-medium">File:</span>{" "}
              <span className="text-slate-800">{result.filename}</span>
            </p>
            <p>
              <span className="font-medium">Inserted rows:</span>{" "}
              {result.inserted.toLocaleString()}
            </p>
            <p>
              <span className="font-medium">Skipped (missing product):</span>{" "}
              {result.skipped_missing_product.toLocaleString()}
            </p>

            {(result.parse_errors.length > 0 ||
              result.row_errors.length > 0) && (
              <div className="pt-2 space-y-2">
                {result.parse_errors.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-red-700">
                      Parse errors
                    </p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-red-700">
                      {result.parse_errors.map((e, idx) => (
                        <li key={idx}>{e}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {result.row_errors.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-amber-700">
                      Row-level issues
                    </p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-amber-700">
                      {result.row_errors.map((e, idx) => (
                        <li key={idx}>{e}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {result.parse_errors.length === 0 &&
              result.row_errors.length === 0 && (
                <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded px-3 py-2 mt-2">
                  Upload completed with no reported errors.
                </p>
              )}
          </div>
        )}

        {!result && !error && !loading && (
          <p className="text-xs text-slate-500">
            No upload yet — choose a CSV and click{" "}
            <span className="font-medium">Upload CSV</span>.
          </p>
        )}
      </section>
    </div>
  );
}

