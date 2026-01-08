import { apiFetch } from "./api";

export interface Bakery {
  id: number;
  name: string;
  location?: string | null;
  timezone?: string | null;
  created_at?: string;
}

export type CreateBakeryPayload = {
  name: string;
  location?: string;
  timezone?: string;
};

export const BAKERY_UPDATED_EVENT = "bakery-list-updated";
export const BAKERY_SELECTION_CHANGED_EVENT = "current-bakery-changed";

export async function fetchBakeries(): Promise<Bakery[]> {
  // matches backend: GET /api/bakeries/
  return apiFetch<Bakery[]>("/api/bakeries/");
}

export async function createBakery(
  payload: CreateBakeryPayload
): Promise<Bakery> {
  return apiFetch<Bakery>("/api/bakeries/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteBakery(bakeryId: number): Promise<void> {
  return apiFetch<void>(`/api/bakeries/${bakeryId}`, {
    method: "DELETE",
  });
}

export function emitBakeryUpdate(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(BAKERY_UPDATED_EVENT));
}

export function emitBakerySelectionChanged(value: string | null): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(BAKERY_SELECTION_CHANGED_EVENT, { detail: { value } })
  );
}
