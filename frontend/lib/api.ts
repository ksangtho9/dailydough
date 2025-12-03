// frontend/lib/api.ts
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export { API_BASE_URL };

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
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }

  return res.json() as Promise<T>;
}

// Product API helpers
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