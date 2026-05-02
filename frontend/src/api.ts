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
    credentials: "same-origin",
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
export type DeployType = "static" | "process";
export type DeployTrigger = "manual" | "on_done" | "on_merge";
export type PlanApprovalMode = "auto" | "manual";

export interface Project {
  id: number;
  slug: string;
  name: string;
  kind: ProjectKind;
  git_remote: string | null;
  local_path: string;
  deploy_port: number | null;
  autonomy_mode: AutonomyMode;
  deploy_type: DeployType;
  build_command: string | null;
  dist_dir: string | null;
  start_command: string | null;
  healthcheck_path: string | null;
  deploy_trigger: DeployTrigger;
  public_enabled: boolean;
  plan_approval_mode: PlanApprovalMode;
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
  deploy_type?: DeployType;
  build_command?: string | null;
  dist_dir?: string | null;
  start_command?: string | null;
  healthcheck_path?: string | null;
  deploy_trigger?: DeployTrigger;
  public_enabled?: boolean;
  plan_approval_mode?: PlanApprovalMode;
}

export interface ProjectPatchPayload {
  name?: string;
  kind?: ProjectKind;
  git_remote?: string | null;
  local_path?: string;
  deploy_port?: number | null;
  autonomy_mode?: AutonomyMode;
  deploy_type?: DeployType;
  build_command?: string | null;
  dist_dir?: string | null;
  start_command?: string | null;
  healthcheck_path?: string | null;
  deploy_trigger?: DeployTrigger;
  public_enabled?: boolean;
  plan_approval_mode?: PlanApprovalMode;
}

// ---- Tasks wire types (mirror backend app/schemas/task.py) --------------

export type TaskStatus =
  | "inbox"
  | "queued"
  | "triaging"
  | "planning"
  | "waiting_approval"
  | "executing"
  | "verifying"
  | "reviewing"
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

export interface TaskPlan {
  id: number;
  task_id: number;
  status: "ready" | "approved" | "rejected" | "superseded";
  summary: string;
  steps: string[];
  risks: string[];
  planner: string;
  raw_json: string;
  created_at: string;
}

export interface TaskReview {
  id: number;
  task_id: number;
  run_id: number | null;
  decision: "approved" | "request_changes";
  summary: string;
  findings: string[];
  reviewer: string;
  raw_json: string;
  created_at: string;
}

// ---- Attachments wire types (mirror backend app/schemas/attachment.py) -

export interface Attachment {
  id: number;
  task_id: number;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  created_at: string;
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
  pid: number | null;
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
const ACTIVE_STATUSES: readonly TaskStatus[] = [
  "triaging",
  "planning",
  "waiting_approval",
  "executing",
  "verifying",
  "reviewing",
  "running",
  "waiting_input",
];

export function isTaskActive(task: Task): boolean {
  return ACTIVE_STATUSES.includes(task.status);
}

// In-flight = worth polling for; covers `queued` waiting for the executor
// and anything already running. Used to gate React Query's refetchInterval.
const IN_FLIGHT_STATUSES: readonly TaskStatus[] = [
  "queued",
  "triaging",
  "planning",
  "waiting_approval",
  "executing",
  "verifying",
  "reviewing",
  "running",
  "waiting_input",
];

export function hasInFlightTask(tasks: Task[] | undefined): boolean {
  if (!tasks) return false;
  return tasks.some((t) => IN_FLIGHT_STATUSES.includes(t.status));
}

// ---- Auth wire types (mirror backend app/api/auth.py) ------------------

export interface AuthStatus {
  enabled: boolean;
}

export interface ApiToken {
  id: number;
  name: string;
  scopes: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiTokenCreated extends ApiToken {
  token: string;
}

export function getAuthStatus(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/auth/status");
}

export function login(password: string): Promise<{ ok: boolean }> {
  return apiFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return apiFetch("/auth/logout", { method: "POST" });
}

export function getMe(): Promise<{ authenticated: boolean }> {
  return apiFetch("/auth/me");
}

export function listTokens(): Promise<ApiToken[]> {
  return apiFetch<ApiToken[]>("/auth/tokens");
}

export function createTokenApi(name: string, scopes: string[]): Promise<ApiTokenCreated> {
  return apiFetch<ApiTokenCreated>("/auth/tokens", {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });
}

export function revokeTokenApi(id: number): Promise<void> {
  return apiFetch(`/auth/tokens/${id}`, { method: "DELETE" });
}

// ---- Audit ------------------------------------------------------------

export interface AuditEvent {
  id: number;
  actor_type: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload_json: string | null;
  ip_address: string | null;
  created_at: string;
}

export function listAuditEvents(params?: {
  limit?: number;
  offset?: number;
  actor_type?: string;
  action?: string;
}): Promise<AuditEvent[]> {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  if (params?.actor_type) q.set("actor_type", params.actor_type);
  if (params?.action) q.set("action", params.action);
  const qs = q.toString();
  return apiFetch<AuditEvent[]>(`/audit/events${qs ? `?${qs}` : ""}`);
}

// ---- Metrics ----------------------------------------------------------

export interface Metrics {
  total_projects: number;
  total_tasks: number;
  tasks_by_status: Record<string, number>;
  active_runs: number;
}

export function getMetrics(): Promise<Metrics> {
  return apiFetch<Metrics>("/metrics");
}

// ---- Ops --------------------------------------------------------------

export interface KillSwitchResult {
  cancelled_tasks: number;
  queued_tasks_cancelled: number;
  waiting_tasks_cancelled: number;
  running_tasks_marked: number;
}

export function killSwitch(): Promise<KillSwitchResult> {
  return apiFetch<KillSwitchResult>("/ops/kill-switch", { method: "POST" });
}

// ---- Deployments (Phase 4) -------------------------------------------

export type DeploymentStatus =
  | "queued" | "building" | "starting" | "healthy" | "unhealthy"
  | "failed" | "stopped" | "rolled_back";

export interface Deployment {
  id: number;
  project_id: number;
  task_id: number | null;
  commit_sha: string | null;
  deploy_type: DeployType;
  status: DeploymentStatus;
  artifact_path: string | null;
  port: number | null;
  url_local: string | null;
  healthcheck_path: string;
  build_log: string | null;
  error: string | null;
  pid: number | null;
  started_at: string | null;
  finished_at: string | null;
  last_health_check: string | null;
  created_at: string;
}

export function listDeployments(slug: string): Promise<Deployment[]> {
  return apiFetch<Deployment[]>(`/projects/${slug}/deployments`);
}

export function triggerDeployment(slug: string): Promise<Deployment> {
  return apiFetch<Deployment>(`/projects/${slug}/deployments`, { method: "POST" });
}

export function stopDeployment(id: number): Promise<Deployment> {
  return apiFetch<Deployment>(`/deployments/${id}/stop`, { method: "POST" });
}

export function rollbackDeployment(id: number): Promise<Deployment> {
  return apiFetch<Deployment>(`/deployments/${id}/rollback`, { method: "POST" });
}

// ---- Readiness wire types (mirror backend app/api/readiness.py) --------

export interface ReadinessResponse {
  db_ok: boolean;
  claude_cli_ok: boolean;
  git_ok: boolean;
  gh_ok: boolean;
  details: {
    db: { path: string; reachable: boolean; error?: string };
    claude_cli: { path: string | null; found: boolean; error?: string };
    git: { version?: string; error?: string };
    gh: { found: boolean; hint?: string; error?: string };
  };
}
