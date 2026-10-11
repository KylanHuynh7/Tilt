// Shared fetch helper for every sport's API module.
export const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return (await res.json()) as T;
}
