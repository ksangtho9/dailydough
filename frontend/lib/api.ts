// frontend/lib/api.ts
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export { API_BASE_URL };

export type User = {
  id: number;
  email: string;
  is_admin: boolean;
  created_at: string;
};

/**
 * Get current authenticated user.
 */
export async function getCurrentUser(): Promise<User> {
  return apiFetch<User>("/api/auth/me");
}

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const token = getAuthToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    (headers as any).Authorization = `Bearer ${token}`;
  }

  const res = await fetch(url, {
    ...options,
    headers,
  });

  // 🔥 Handle expired/invalid auth
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      // clear token + mark that session expired
      localStorage.removeItem("access_token");
      localStorage.setItem("session_expired", "1");
      window.location.href = "/login";
    }
    throw new Error("Session expired. Redirecting to login.");
  }

  if (!res.ok) {
    let message = `API error ${res.status}`;

    try {
      const contentType = res.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        const data: any = await res.json();
        const detail =
          data?.detail ?? data?.error ?? data?.message ?? data?.msg;

        if (detail) {
          if (typeof detail === "string") {
            message += `: ${detail}`;
          } else {
            message += `: ${JSON.stringify(detail)}`;
          }
        } else {
          message += `: ${JSON.stringify(data)}`;
        }
      } else {
        const text = await res.text();
        if (text) {
          message += `: ${text}`;
        }
      }
    } catch {
      // If anything goes wrong while parsing the error body,
      // fall back to a generic message.
    }

    throw new Error(message);
  }

  return res.json() as Promise<T>;
}

// Product API helpers
export type Product = {
  id: number;
  name: string;
  sku?: string | null;
  category?: string | null;
  bakery_id: number;
  price?: number | null;
  cost_per_unit?: number | null;
  shelf_life_days?: number | null;
  stockout_cost_ratio?: number | null;
};

/**
 * Fetch list of products, optionally filtered by bakery_id.
 */
export async function fetchProducts(bakeryId?: number): Promise<Product[]> {
  const params = new URLSearchParams();
  if (bakeryId != null) {
    params.append("bakery_id", String(bakeryId));
  }
  const queryString = params.toString();
  const url = `/api/products${queryString ? `?${queryString}` : ""}`;
  return apiFetch<Product[]>(url);
}

export async function updateProduct(
  productId: number,
  data: { name?: string; sku?: string; category?: string; price?: number | null; cost_per_unit?: number | null; shelf_life_days?: number | null; stockout_cost_ratio?: number | null }
): Promise<any> {
  return apiFetch(`/api/v1/products/${productId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteProduct(productId: number): Promise<{ success: boolean }> {
  return apiFetch(`/api/v1/products/${productId}`, {
    method: "DELETE",
  });
}

export async function deleteAllProducts(bakeryId: number): Promise<{
  deleted_products: number;
  deleted_sales: number;
  deleted_metrics: number;
}> {
  const params = new URLSearchParams({ bakery_id: String(bakeryId) }).toString();
  return apiFetch(`/api/v1/products?${params}`, {
    method: "DELETE",
  });
}

// Admin Training API

export type RetrainRequest = {
  product_ids?: number[] | null;
  bakery_id?: number | null;
};

export type RetrainResponse = {
  status: string;
  job_id: string;
  total: number;
};

export type JobStatusResponse = {
  status: "idle" | "running" | "cancelling" | "completed" | "failed" | "completed_with_errors" | "cancelled";
  job_id?: string | null;
  progress: { completed: number; total: number };
  current_product_id?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  errors: Array<{ product_id: number; error: string }>;
};

/**
 * Start a retrain job for all products or selected products.
 */
export async function adminStartRetrain(
  productIds?: number[] | null,
  bakeryId?: number | null
): Promise<RetrainResponse> {
  const body: RetrainRequest = { product_ids: productIds ?? null };
  if (bakeryId != null) {
    body.bakery_id = bakeryId;
  }
  return apiFetch<RetrainResponse>("/api/admin/training/retrain", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Get training job status.
 */
export async function adminGetTrainingStatus(
  jobId?: string
): Promise<JobStatusResponse> {
  const url = jobId
    ? `/api/admin/training/status?job_id=${jobId}`
    : "/api/admin/training/status";
  return apiFetch<JobStatusResponse>(url);
}

/**
 * Cancel a running training job.
 */
export async function adminCancelTrainingJob(
  jobId?: string
): Promise<{ status: string; job_id?: string; message: string }> {
  const url = jobId
    ? `/api/admin/training/cancel?job_id=${jobId}`
    : "/api/admin/training/cancel";
  return apiFetch<{ status: string; job_id?: string; message: string }>(url, {
    method: "POST",
  });
}