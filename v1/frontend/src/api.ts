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

// ---- Tasks wire types (mirror backend app/schemas/task.py) --------------

export type TaskStatus =
  | "inbox"
  | "queued"
  | "running"
  | "waiting_input"
  | "done"
  | "failed"
  | "cancelled";

export interface Task {
  id: number;
  project_id: number;
  parent_task_id: number | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  branch_name: string | null;
  pr_url: string | null;
  pending_question: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskCreatePayload {
  title: string;
  description?: string | null;
}

// ---- Runs wire types (mirror backend app/schemas/run.py) ---------------

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Run {
  id: number;
  task_id: number;
  status: RunStatus;
  model: string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
  outcome: string | null;
  session_handle: string | null;
  artifact_root: string;
  verification_json: string | null;
  created_at: string;
}

// Shape of one event emitted over SSE (mirrors the `data:` frame built by
// backend/app/services/run_events.py::format_sse_event). `payload` is the
// decoded JSON payload, not a string — the server parses it for us.
export interface RunEvent {
  id: number;
  event_type: string;
  payload: unknown;
  created_at: string | null;
}

// Shape of the terminal `eos` frame emitted at stream close. Mirrors
// backend format_sse_eos; `final_status` is the terminal RunStatus.
export interface EosPayload {
  run_id: number;
  final_status: RunStatus;
  exit_code: number | null;
  outcome: string | null;
}

// Active = driving toward a terminal state; delete is forbidden by backend.
const ACTIVE_STATUSES: readonly TaskStatus[] = ["running", "waiting_input"];

export function isTaskActive(task: Task): boolean {
  return ACTIVE_STATUSES.includes(task.status);
}

// In-flight = worth polling for; covers `queued` waiting for the executor
// and anything already running. Used to gate React Query's refetchInterval.
const IN_FLIGHT_STATUSES: readonly TaskStatus[] = [
  "queued",
  "running",
  "waiting_input",
];

export function hasInFlightTask(tasks: Task[] | undefined): boolean {
  if (!tasks) return false;
  return tasks.some((t) => IN_FLIGHT_STATUSES.includes(t.status));
}
