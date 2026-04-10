// ── Task ──
export interface Task {
  id: string;
  title: string;
  description: string;
  area: string;
  project_id: string | null;
  project_name: string | null;
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
}

// ── Project ──
export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  directory: string;
  active: number;
  open_tasks: number;
  done_tasks: number;
  total_tasks: number;
  created_at: string;
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

// ── Chat ──
export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  task_id?: string;
  status: 'done' | 'pending';
  created_at: string;
}

// ── Services ──
export interface ServiceFieldOption {
  value: string;
  label: string;
}

export interface ServiceFieldShowWhen {
  field: string;
  value: string;
}

export interface ServiceField {
  key: string;
  type: 'select' | 'password' | 'text' | 'url';
  label: string;
  required?: boolean;
  sensitive?: boolean;
  help?: string;
  default?: string;
  options?: ServiceFieldOption[];
  options_by_provider?: Record<string, ServiceFieldOption[]>;
  show_when?: ServiceFieldShowWhen;
}

export interface ServiceStatus {
  status: 'configured' | 'not_configured' | 'error' | 'warning';
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
  [key: string]: unknown;
}
