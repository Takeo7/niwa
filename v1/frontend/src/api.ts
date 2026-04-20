// Thin fetch wrapper around the backend /api surface.
// Later PRs add typed endpoints; for now we only expose the base helper and
// the /api/health call used by the system readiness page.

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(`API ${path} failed: ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}
