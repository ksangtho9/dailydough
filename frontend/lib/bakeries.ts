import { apiFetch } from "./api";

export interface Bakery {
  id: number;
  name: string;
}

export async function fetchBakeries(): Promise<Bakery[]> {
  // matches backend: GET /api/bakeries/
  return apiFetch<Bakery[]>("/api/bakeries/");
}
