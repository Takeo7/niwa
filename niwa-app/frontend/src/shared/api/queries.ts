import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { api, apiPost, apiPatch, apiDelete } from './client';
import type {
  Task,
  Project,
  TreeResponse,
  FolderFile,
  KanbanColumn,
  ChatSession,
  ChatMessage,
  Service,
  LLMModel,
  AgentsConfig,
  Note,
  ExecutorMetrics,
  Stats,
  OAuthStatus,
  Settings,
  VersionInfo,
} from '../types';

// ── Tasks ──
export function useTasks(params?: {
  include_done?: boolean;
  status?: string;
  area?: string;
  project_id?: string;
}) {
  const qs = new URLSearchParams();
  if (params?.include_done) qs.set('include_done', '1');
  if (params?.status) qs.set('status', params.status);
  if (params?.area) qs.set('area', params.area);
  if (params?.project_id) qs.set('project_id', params.project_id);
  const query = qs.toString();
  return useQuery({
    queryKey: ['tasks', params],
    queryFn: () => api<Task[]>(`tasks${query ? `?${query}` : ''}`),
  });
}

export function useTask(id: string | null) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => api<Task>(`tasks/${id}`),
    enabled: !!id,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Task>) => apiPost<{ ok: boolean; id: string }>('tasks', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['kanban'] });
    },
  });
}

export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: Partial<Task> & { id: string }) =>
      apiPatch<{ ok: boolean }>(`tasks/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['task'] });
      qc.invalidateQueries({ queryKey: ['kanban'] });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`tasks/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['kanban'] });
    },
  });
}

// ── Projects ──
export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => api<Project[]>('projects'),
  });
}

export function useProject(slug: string | undefined) {
  return useQuery({
    queryKey: ['project', slug],
    queryFn: () => api<Project>(`projects/${slug}`),
    enabled: !!slug,
  });
}

export function useProjectTree(slug: string | undefined, mode: string = 'folders') {
  return useQuery({
    queryKey: ['project-tree', slug, mode],
    queryFn: () => api<TreeResponse>(`projects/${slug}/tree?mode=${mode}`),
    enabled: !!slug,
  });
}

export function useProjectFolderFiles(slug: string | undefined, folderPath: string | null) {
  return useQuery({
    queryKey: ['project-folder', slug, folderPath],
    queryFn: () => api<{ files: FolderFile[] }>(`projects/${slug}/folder-files/${folderPath}`),
    enabled: !!slug && !!folderPath,
  });
}

export function useProjectUploads(slug: string | undefined) {
  return useQuery({
    queryKey: ['project-uploads', slug],
    queryFn: () => api<{ files: Array<{ name: string; size: number }> }>(`projects/${slug}/uploads`),
    enabled: !!slug,
  });
}

export function useUploadFile(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('files', file);
      const res = await fetch(`/api/projects/${slug}/upload`, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('Error al subir archivo');
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project-uploads', slug] });
    },
  });
}

// ── Kanban ──
export function useKanbanColumns() {
  return useQuery({
    queryKey: ['kanban', 'columns'],
    queryFn: () => api<KanbanColumn[]>('kanban-columns'),
  });
}

// ── Chat ──
export function useChatSessions() {
  return useQuery({
    queryKey: ['chat', 'sessions'],
    queryFn: () => api<ChatSession[]>('chat/sessions'),
  });
}

export function useChatMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['chat', 'messages', sessionId],
    queryFn: () => api<ChatMessage[]>(`chat/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
    refetchInterval: 3000,
  });
}

export function useCreateChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: { title?: string }) =>
      apiPost<ChatSession>('chat/sessions', data ?? {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat', 'sessions'] });
    },
  });
}

export function useSendChatMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { session_id: string; content: string }) =>
      apiPost<{
        user_message: ChatMessage;
        assistant_message: ChatMessage;
      }>('chat/send', data),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({
        queryKey: ['chat', 'messages', vars.session_id],
      });
      qc.invalidateQueries({ queryKey: ['chat', 'sessions'] });
    },
  });
}

export function useDeleteChatSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiPost<{ ok: boolean }>(`chat/sessions/${sessionId}/delete`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat', 'sessions'] });
    },
  });
}

// ── Services ──
export function useServices() {
  return useQuery({
    queryKey: ['services'],
    queryFn: () => api<Service[]>('services'),
  });
}

export function useSaveService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, values }: { id: string; values: Record<string, string> }) =>
      apiPost<{ ok: boolean; saved: string[] }>(`services/${id}`, values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['services'] });
    },
  });
}

export function useTestService() {
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<{ ok: boolean; message?: string; error?: string }>(`services/${id}/test`, {}),
  });
}

// ── OAuth ──
export function useOAuthStatus(provider: string) {
  return useQuery({
    queryKey: ['oauth', 'status', provider],
    queryFn: () => api<OAuthStatus>(`auth/oauth/status?provider=${provider}`),
    enabled: !!provider,
  });
}

export function useStartOAuth() {
  return useMutation({
    mutationFn: (provider: string) => {
      window.open(`/api/auth/oauth/start?provider=${provider}`, '_blank', 'width=600,height=700');
      return Promise.resolve({ ok: true });
    },
  });
}

export function useRevokeOAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) =>
      apiPost<{ ok: boolean }>('auth/oauth/revoke', { provider }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['oauth'] });
    },
  });
}

export function useImportOAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { provider: string; auth_json: string }) =>
      apiPost<{ ok: boolean; status?: OAuthStatus }>('auth/oauth/import', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['oauth'] });
    },
  });
}

// ── Models ──
export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => api<LLMModel[]>('models'),
  });
}

// ── Agents ──
export function useAgentsConfig() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: () => api<AgentsConfig>('agents'),
  });
}

export function useSaveAgentsConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<AgentsConfig>) =>
      apiPost<AgentsConfig>('agents', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
      qc.invalidateQueries({ queryKey: ['models'] });
    },
  });
}

export function useRestartExecutor() {
  return useMutation({
    mutationFn: () => apiPost<{ ok: boolean; message: string }>('executor/restart', {}),
  });
}

// ── Notes ──
export function useNotes(search?: string) {
  return useQuery({
    queryKey: ['notes', search],
    queryFn: () => {
      const qs = search ? `?search=${encodeURIComponent(search)}` : '';
      return api<Note[]>(`notes${qs}`);
    },
  });
}

export function useNote(id: string | null) {
  return useQuery({
    queryKey: ['note', id],
    queryFn: () => api<Note>(`notes/${id}`),
    enabled: !!id,
  });
}

export function useCreateNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Note>) =>
      apiPost<{ ok: boolean; id: string }>('notes', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
    },
  });
}

export function useUpdateNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: Partial<Note> & { id: string }) =>
      apiPatch<{ ok: boolean }>(`notes/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
      qc.invalidateQueries({ queryKey: ['note'] });
    },
  });
}

export function useDeleteNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`notes/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
    },
  });
}

// ── Metrics ──
export function useExecutorMetrics() {
  return useQuery({
    queryKey: ['metrics', 'executor'],
    queryFn: () => api<ExecutorMetrics>('metrics/executor'),
  });
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('stats'),
  });
}

// ── Settings ──
export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Settings>('settings'),
  });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, string>) =>
      apiPost<{ ok: boolean }>('settings', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] });
    },
  });
}

// ── Version ──
export function useVersion() {
  return useQuery({
    queryKey: ['version'],
    queryFn: () => api<VersionInfo>('version'),
    staleTime: 300000,
  });
}
