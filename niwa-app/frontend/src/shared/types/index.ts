// ── Task ──
export interface Task {
  id: string;
  title: string;
  description: string;
  area: string;
  project_id: string | null;
  project_name: string | null;
  project_slug: string | null;
  status: string;
  priority: string;
  urgent: number;
  scheduled_for: string | null;
  due_at: string | null;
  source: string;
  notes: string;
  assigned_to_yume: number;
  assigned_to_claude: number;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  tags?: string;
  agent_id?: string;
  agent_name?: string;
  agent_status?: string;
  // PR-36: populated by GET /api/tasks/:id only (not in list queries),
  // holds the stdout of the latest executor comment event after ANSI
  // stripping. Rendered as markdown in TaskDetailsTab (PR-37).
  executor_output?: string;
  parent_task_id?: string | null;
  // PR-B4a: opt-in to the planner tier. Stored as 0/1 in SQLite.
  // Set by TaskForm's "Desgranar con planner" checkbox.
  decompose?: number;
  // PR-B4b: populated by list and detail endpoints via correlated
  // subquery; lets the UI render a ``↳ N/M`` badge on parent tasks
  // without a second round-trip.
  child_count_total?: number;
  child_count_done?: number;
  // PR-39: latest run summary so the UI can show an error banner
  // without a second fetch. Populated by GET /api/tasks/:id only.
  last_run?: TaskLastRun | null;
  // PR-C1: deployment URL copied from ``projects.url`` via JOIN in
  // ``get_task``. Non-empty only when the task's project has been
  // deployed. Populated by GET /api/tasks/:id only.
  deployment_url?: string | null;
}

export interface TaskLastRun {
  id: string;
  status: string;
  outcome: string | null;
  error_code: string | null;
  finished_at: string | null;
  relation_type: string | null;
  backend_profile_slug: string | null;
  backend_profile_display_name: string | null;
}

// ── Project ──
export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  directory: string;
  url?: string | null;
  active: number;
  open_tasks: number;
  done_tasks: number;
  total_tasks: number;
  created_at: string;
  updated_at: string;
  autonomy_mode?: 'normal' | 'dangerous';
}

export interface Deployment {
  id: string;
  project_id: string;
  slug: string;
  directory: string;
  url: string | null;
  status: string;
  deployed_at: string;
  updated_at: string;
}

export interface TreeNode {
  name: string;
  path?: string;
  type: 'file' | 'folder';
  size?: number;
  children_count?: number;
}

export interface TreeResponse {
  tree: TreeNode[];
  root_file_count: number;
  truncated: boolean;
}

export interface FolderFile {
  name: string;
  size: number;
  type: 'file' | 'folder';
  children_count?: number;
}

// ── Kanban ──
export interface KanbanColumn {
  id: string;
  status: string;
  label: string;
  position: number;
  color: string;
  is_terminal: number;
  created_at: string;
  updated_at: string;
}

// ── Services ──
export interface ServiceFieldOption {
  value: string;
  label: string;
}

export interface ServiceFieldShowWhen {
  field: string;
  value: string | string[];
}

export interface ServiceField {
  key: string;
  type: 'select' | 'password' | 'text' | 'url' | 'number';
  label: string;
  required?: boolean;
  sensitive?: boolean;
  help?: string;
  default?: string;
  placeholder?: string;
  options?: ServiceFieldOption[];
  options_by_provider?: Record<string, ServiceFieldOption[]>;
  show_when?: ServiceFieldShowWhen;
}

export interface ServiceStatus {
  status: 'configured' | 'not_configured' | 'error' | 'warning' | 'unknown';
  message: string;
}

export interface Service {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  fields: ServiceField[];
  test_action?: string;
  oauth_provider?: string;
  setup_guide?: string[];
  status: ServiceStatus;
  values: Record<string, string>;
  values_set?: Record<string, boolean>;
}

// ── Models ──
export interface LLMModel {
  id: string;
  name: string;
  provider: string;
  speed: string;
  cost: string;
  description: string;
}

// ── Agents ──
export interface AgentConfig {
  model: string;
  max_turns: number;
  description: string;
}

export type AgentsConfig = Record<'chat' | 'planner' | 'executor', AgentConfig>;

// ── Notes ──
export interface Note {
  id: string;
  title: string;
  content: string;
  project_id: string | null;
  project_name?: string | null;
  tags: string | null;
  created_at: string;
  updated_at: string;
}

// ── Metrics ──
export interface ExecutorMetrics {
  today: {
    completed: number;
    failed: number;
    pending: number;
    in_progress: number;
  };
  week: {
    completed: number;
    failed: number;
  };
  avg_execution_time_seconds: number;
  success_rate: number;
  deployments: number;
}

export interface Stats {
  total: number;
  open: number;
  done: number;
  done_today: number;
  overdue: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  completions_by_day: Array<{ day: string; count: number }>;
}

// ── OAuth ──
export interface OAuthStatus {
  authenticated: boolean;
  email?: string;
  expires_at?: number;
  provider?: string;
}

// ── Settings ──
export type Settings = Record<string, string>;

// ── Version ──
export interface VersionInfo {
  version: string;
  name?: string;
  // PR-58a: enriched fields for the update UX.
  branch?: string | null;
  commit?: string | null;
  commit_short?: string | null;
  latest_remote_commit?: string | null;
  needs_update?: boolean;
  schema_version?: number | null;
  repo_dirty?: boolean;
  last_backup_path?: string | null;
  last_backup_at?: string | null;
  needs_restart?: boolean;
  // PR final 1: canonical commands for THIS install (``niwa update``
  // when a symlink is on PATH, absolute path otherwise).
  update_command?: string;
  restore_command?: string;
  [key: string]: unknown;
}

// PR-58a: the UI no longer executes update. The endpoint returns an
// ``action_required='run_cli'`` intent describing which command the
// operator should run on the host. The UI renders the command with
// a copy-to-clipboard button.
export interface SystemUpdateIntent {
  ok: boolean;
  action_required?: 'run_cli';
  command?: string;
  current_commit?: string | null;
  current_commit_short?: string | null;
  branch?: string | null;
  latest_remote_commit?: string | null;
  needs_update?: boolean;
  repo_dirty?: boolean;
  message?: string;
}

// ── Dashboard ──
export interface DashboardData {
  done_today: number;
  pending: number;
  blocked: number;
  in_progress: number;
  routines_count?: number;
  attention: Array<{
    id: string;
    title: string;
    status: string;
    priority: string;
    due_at?: string | null;
    project_name?: string | null;
  }>;
  velocity: Array<{ day: string; count: number }>;
}

// ── Activity ──
export interface ActivityItem {
  id: string;
  type: string;
  task_id?: string;
  task_title?: string;
  project_name?: string;
  agent_name?: string;
  description: string;
  created_at: string;
}

// ── History ──
export interface HistoryEntry {
  id: string;
  title: string;
  project_name?: string | null;
  agent_name?: string | null;
  source?: string;
  status: string;
  duration?: number | null;
  attempts?: number;
  completed_at?: string | null;
  created_at: string;
}

export interface HistoryResponse {
  items: HistoryEntry[];
  total: number;
  page: number;
  per_page: number;
  stats?: {
    total: number;
    success: number;
    failed: number;
    avg_duration: number;
  };
}

// ── Routine ──
export type RoutineAction = 'create_task' | 'script' | 'webhook' | 'improve';
export type ImprovementType = 'functional' | 'stability' | 'security';

export interface Routine {
  id: string;
  name: string;
  description?: string;
  schedule: string;
  action?: RoutineAction;
  action_type?: string;
  action_config?: Record<string, unknown>;
  improvement_type?: ImprovementType | null;
  enabled: boolean | number;
  last_run?: string | null;
  next_run?: string | null;
  errors?: number;
  created_at?: string;
  updated_at?: string;
}

// ── Log ──
export interface LogEntry {
  line: string;
  level?: string;
  source?: string;
  timestamp?: string;
}

// ── Search ──
export interface SearchResult {
  tasks: Array<{ id: string; title: string; status: string }>;
  projects: Array<{ id: string; name: string; slug: string }>;
  notes?: Array<{ id: string; title: string }>;
}

// ── Attachment ──
export interface TaskAttachment {
  filename: string;
  size?: number;
  created_at?: string;
}

// ── Runs / Routing (v0.2 — PR-10a) ──

export type RunStatus =
  | 'queued'
  | 'starting'
  | 'running'
  | 'waiting_approval'
  | 'waiting_input'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out'
  | 'rejected';

export type RunRelationType = 'fallback' | 'resume' | 'retry' | null;

export interface BackendRun {
  id: string;
  task_id: string;
  routing_decision_id: string | null;
  previous_run_id: string | null;
  relation_type: RunRelationType;
  backend_profile_id: string | null;
  backend_profile_slug: string | null;
  backend_profile_display_name: string | null;
  backend_kind: string | null;
  runtime_kind: string | null;
  model_resolved: string | null;
  session_handle: string | null;
  status: RunStatus;
  outcome: string | null;
  exit_code: number | null;
  error_code: string | null;
  artifact_root: string | null;
  heartbeat_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  observed_usage_signals_json: string | null;
  capability_snapshot_json: string | null;
  budget_snapshot_json: string | null;
}

export interface BackendRunEvent {
  id: string;
  backend_run_id: string;
  event_type: string;
  message: string | null;
  payload_json: string | null;
  created_at: string;
}

export interface RoutingMatchedRule {
  rule: string;
  rule_id?: string;
  rule_name?: string;
  position?: number;
  profile_id?: string;
  slug?: string;
  prior_run_id?: string;
  triggers?: unknown;
}

export interface RoutingBackend {
  id: string;
  slug: string | null;
  display_name: string | null;
}

export interface RoutingApproval {
  id: string;
  status: string;
  approval_type: string;
  risk_level: string | null;
  reason: string | null;
  requested_at: string;
  resolved_at: string | null;
}

export interface RoutingDecision {
  id: string;
  task_id: string;
  decision_index: number | null;
  requested_profile_id: string | null;
  selected_profile_id: string | null;
  selected_backend_slug: string | null;
  selected_backend_display_name: string | null;
  reason_summary: string;
  matched_rules: RoutingMatchedRule[];
  fallback_chain: RoutingBackend[];
  estimated_resource_cost: string | null;
  quota_risk: string | null;
  contract_version: string | null;
  created_at: string;
  approval_required: boolean;
  approval: RoutingApproval | null;
}

// ── Artifacts (PR-10c) ──
//
// Produced by the backend adapter's ``collect_artifacts`` after a
// run finishes (PR-04).  ``path`` is relative to ``artifact_root``
// by contract (PR-04 Dec 10) — the UI MUST NOT reconstruct the
// absolute host path.  ``size_bytes`` and ``sha256`` may be NULL on
// early-failure runs (BUGS-FOUND Bug 8).
export interface Artifact {
  id: string;
  task_id: string;
  backend_run_id: string;
  artifact_type: string;
  path: string;
  size_bytes: number | null;
  sha256: string | null;
  created_at: string;
}

// ── Approvals (PR-10b) ──
//
// The canonical status set.  ``approval_service.resolve_approval``
// only ever writes ``approved`` or ``rejected``.  ``pending`` is the
// initial state set by ``request_approval``.
export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

// Canonical risk levels per the PR-05 SPEC.  Backend validation is
// not enforced (BUGS-FOUND Bug 9) so the UI may receive values that
// fall outside this union — render them as-is with a neutral style.
export type CanonicalRiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface Approval {
  id: string;
  task_id: string;
  task_title: string | null;
  task_status: string | null;
  backend_run_id: string | null;
  approval_type: string;
  reason: string | null;
  risk_level: string | null;
  status: ApprovalStatus;
  requested_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
}

export type ApprovalDecision = 'approve' | 'reject';

// ── Backend profiles + capability profiles (PR-10d) ──

export type BackendKind = 'claude_code' | 'codex';
export type RuntimeKind = 'cli' | 'api' | 'acp' | 'local';

// Rows from the ``backend_profiles`` table.  ``enabled`` is stored
// as 0/1 in SQLite; we keep the integer shape and coerce when
// rendering to avoid surprises when the UI hits staging DBs.
export interface BackendProfile {
  id: string;
  slug: string;
  display_name: string;
  backend_kind: BackendKind;
  runtime_kind: RuntimeKind;
  default_model: string | null;
  command_template: string | null;
  capabilities_json: string | null;
  enabled: number;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface BackendProfilePatch {
  enabled?: boolean;
  priority?: number;
  default_model?: string | null;
}

// Canonical enum values (must mirror capability_service.py).
export type RepoMode = 'none' | 'read-only' | 'read-write';
export type ShellMode = 'disabled' | 'whitelist' | 'free';
export type WebMode = 'off' | 'on';
export type NetworkMode = 'off' | 'on' | 'restricted';

export interface CapabilityProfile {
  id?: string;
  project_id?: string;
  name: string;
  repo_mode: RepoMode;
  shell_mode: ShellMode;
  shell_whitelist_json: string;
  web_mode: WebMode;
  network_mode: NetworkMode;
  filesystem_scope_json: string;
  secrets_scope_json: string;
  resource_budget_json: string;
  created_at?: string;
  updated_at?: string;
}

export interface CapabilityProfileResponse {
  project_id: string;
  is_default: boolean;
  profile: CapabilityProfile;
}

export interface CapabilityProfilePatch {
  repo_mode?: RepoMode;
  shell_mode?: ShellMode;
  web_mode?: WebMode;
  network_mode?: NetworkMode;
  shell_whitelist_json?: string;
  filesystem_scope_json?: string;
  secrets_scope_json?: string;
  resource_budget_json?: string;
}

export interface ReadinessBackend {
  slug: string;
  display_name: string;
  enabled: boolean;
  has_credential: boolean;
  auth_mode: string;
  model_present: boolean;
  default_model: string | null;
  reachable: boolean;
}

export interface Readiness {
  docker_ok: boolean;
  db_ok: boolean;
  admin_ok: boolean;
  admin_detail: string;
  backends: ReadinessBackend[];
  hosting_ok: boolean;
  hosting_detail: string;
  checked_at: string;
}
