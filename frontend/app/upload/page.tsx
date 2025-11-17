"use client";

import { useEffect, useState, ChangeEvent } from "react";
import { useRouter } from "next/navigation";
import Papa from "papaparse";
import { API_BASE_URL } from "@/lib/api";

type CsvPreviewRow = Record<string, any>;

export default function UploadPage() {
  const router = useRouter();

  const [file, setFile] = useState<File | null>(null);
  const [previewRows, setPreviewRows] = useState<CsvPreviewRow[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [parsing, setParsing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Protect route – require login
  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
    }
  }, [router]);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setPreviewRows([]);
    setColumns([]);
    setMessage(null);
    setError(null);

    if (f) {
      parseCsv(f);
    }
  }

  function parseCsv(f: File) {
    setParsing(true);
    Papa.parse<CsvPreviewRow>(f, {
      header: true,
      dynamicTyping: true,
      preview: 20, // only first 20 rows for preview
      skipEmptyLines: true,
      complete: (results) => {
        const rows = results.data || [];
        setPreviewRows(rows);

        if (rows.length > 0) {
          setColumns(Object.keys(rows[0]));
        }

        setParsing(false);

        // Quick validation hint
        const required = ["sale_date", "product_id", "units_sold", "revenue"];
        const missing = required.filter(
          (col) => !Object.keys(rows[0] || {}).includes(col)
        );
        if (missing.length > 0) {
          setError(
            `Warning: missing expected columns: ${missing.join(
              ", "
            )}. Check your CSV headers.`
          );
        }
      },
      error: (err) => {
        console.error(err);
        setError("Failed to parse CSV file");
        setParsing(false);
      },
    });
  }

  async function handleUpload() {
    if (!file) {
      setError("Please select a CSV file first.");
      return;
    }

    setUploading(true);
    setMessage(null);
    setError(null);

    try {
      const formData = new FormData();
      // Adjust field name if your backend expects something else
      formData.append("file", file);

      let headers: HeadersInit = {};
      if (typeof window !== "undefined") {
        const token = localStorage.getItem("access_token");
        if (token) {
          headers = {
            Authorization: `Bearer ${token}`,
          };
        }
      }

      const res = await fetch(`${API_BASE_URL}/api/sales/upload-csv`, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Upload failed: ${text}`);
      }

      const text = await res.text(); // backend might return JSON or plain text
      setMessage(
        text || "Upload successful. Sales data has been ingested."
      );
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to upload CSV.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">
          Upload sales CSV
        </h2>
        <p className="text-sm text-slate-600">
          Import historical sales data to power your forecasts. Expected
          columns: <code>date</code>, <code>product_id</code>,{" "}
          <code>units_sold</code>, <code>revenue</code>.
        </p>
      </header>

      {/* File picker */}
      <section className="rounded-2xl border border-dashed bg-white p-6">
        <div className="flex flex-col items-center justify-center gap-3 text-center">
          <p className="text-sm text-slate-700">
            Drag and drop a CSV file here, or click to choose a file.
          </p>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={handleFileChange}
            className="block text-sm"
          />
          {file && (
            <p className="text-xs text-slate-500">
              Selected file: <span className="font-medium">{file.name}</span>
            </p>
          )}
          {parsing && (
            <p className="text-xs text-slate-500">Parsing preview…</p>
          )}
        </div>
      </section>

      {/* Preview */}
      <section className="rounded-xl border bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-700">
          Preview (first 20 rows)
        </h3>

        {!file && (
          <p className="text-sm text-slate-500">
            Select a CSV file to see a preview.
          </p>
        )}

        {file && previewRows.length === 0 && !parsing && (
          <p className="text-sm text-slate-500">
            No rows found in this CSV (or headers only).
          </p>
        )}

        {file && previewRows.length > 0 && (
          <div className="max-h-64 overflow-auto border rounded-lg">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50 border-b text-slate-500">
                <tr>
                  {columns.map((col) => (
                    <th
                      key={col}
                      className="px-3 py-2 text-left whitespace-nowrap"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, idx) => (
                  <tr key={idx} className="border-b last:border-b-0">
                    {columns.map((col) => (
                      <td
                        key={col}
                        className="px-3 py-1.5 whitespace-nowrap"
                      >
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Messages + Upload button */}
      <section className="space-y-3">
        {error && (
          <p className="text-sm text-red-600">
            {error}
          </p>
        )}
        {message && (
          <p className="text-sm text-emerald-600">
            {message}
          </p>
        )}

        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload CSV"}
        </button>
      </section>
    </div>
  );
}
