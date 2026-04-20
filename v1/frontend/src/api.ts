// Thin fetch wrapper + shared wire types used across features.
// Proxy `/api` → backend is configured in vite.config.ts; tests mock the
// network at the feature hook level (see tests/ProjectList.test.tsx).

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
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
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // non-JSON error bodies are tolerated; keep body=null
    }
    throw new ApiError(`API ${path} failed: ${response.status}`, response.status, body);
  }
  if (response.status === 204) {
    return undefined as T;
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

// ---- Projects wire types (mirror backend app/schemas/project.py) --------

export type ProjectKind = "web-deployable" | "library" | "script";
export type AutonomyMode = "safe" | "dangerous";

export interface Project {
  id: number;
  slug: string;
  name: string;
  kind: ProjectKind;
  git_remote: string | null;
  local_path: string;
  deploy_port: number | null;
  autonomy_mode: AutonomyMode;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreatePayload {
  slug: string;
  name: string;
  kind: ProjectKind;
  local_path: string;
  git_remote?: string | null;
  deploy_port?: number | null;
  autonomy_mode?: AutonomyMode;
}
