import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  apiFetch,
  hasInFlightTask,
  type Run,
  type Task,
  type TaskCreatePayload,
} from "../../api";

// Polling cadence (ms) while at least one task is in-flight. Turned off
// when all rows are terminal, when the list is empty, or while the query
// is still loading — see hasInFlightTask + the refetchInterval callback.
const POLL_INTERVAL_MS = 2000;

const tasksKey = (slug: string) => ["tasks", slug] as const;

interface UseTasksOptions {
  // Lets tests (and future consumers) opt out of the polling timer. The
  // default is `true`; when `false`, refetchInterval is forced off.
  enablePolling?: boolean;
}

export function useTasks(slug: string | undefined, options: UseTasksOptions = {}) {
  const { enablePolling = true } = options;
  return useQuery<Task[]>({
    queryKey: tasksKey(slug ?? ""),
    queryFn: () => apiFetch<Task[]>(`/projects/${slug}/tasks`),
    enabled: Boolean(slug),
    // Callback form: React Query passes the current Query; we read
    // `state.data` so we can turn polling off while the list is loading
    // (no data yet) and on only when there is an in-flight task. A bare
    // constant would re-fire requests forever even on cold start.
    refetchInterval: (query) => {
      if (!enablePolling) return false;
      const data = query.state.data as Task[] | undefined;
      if (!data) return false;
      return hasInFlightTask(data) ? POLL_INTERVAL_MS : false;
    },
  });
}

export function useCreateTask(slug: string) {
  const qc = useQueryClient();
  return useMutation<Task, Error, TaskCreatePayload>({
    mutationFn: (payload) =>
      apiFetch<Task>(`/projects/${slug}/tasks`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      // Refetch immediately; do not rely on the 2 s polling window so the
      // newly created row shows up on the next tick.
      qc.invalidateQueries({ queryKey: tasksKey(slug) });
    },
  });
}

// Fetches a single task by id — powers the detail route when the user
// hits /tasks/:id directly (no list in cache).
export function useTask(taskId: number | undefined) {
  return useQuery<Task>({
    queryKey: ["task", taskId] as const,
    queryFn: () => apiFetch<Task>(`/tasks/${taskId}`),
    enabled: Boolean(taskId),
  });
}

// Returns the most recent run for `taskId`, or `null` when the executor
// has not picked the task up yet. Runs list is already ordered by id ASC
// from the backend (see runs_service.list_runs_for_task); we pop the tail.
export function useLatestRun(taskId: number | undefined) {
  return useQuery<Run | null>({
    queryKey: ["task", taskId, "latest-run"] as const,
    queryFn: async () => {
      const runs = await apiFetch<Run[]>(`/tasks/${taskId}/runs`);
      return runs.length === 0 ? null : runs[runs.length - 1]!;
    },
    enabled: Boolean(taskId),
  });
}

export function useDeleteTask(slug: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (taskId) =>
      apiFetch<void>(`/tasks/${taskId}`, { method: "DELETE" }),
    onSettled: () => {
      // Invalidate on both success and error: a 409 means the server
      // refused delete (likely because the task transitioned to active
      // since render), so we want the UI to mirror the server state.
      qc.invalidateQueries({ queryKey: tasksKey(slug) });
    },
  });
}

// PR-V1-19: delivers the user clarification to the backend. On success
// we invalidate the single-task query so the detail page re-renders as
// `queued` with no pending_question.
export function useRespondTask(taskId: number) {
  const qc = useQueryClient();
  return useMutation<Task, Error, { response: string }>({
    mutationFn: (payload) =>
      apiFetch<Task>(`/tasks/${taskId}/respond`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task", taskId] });
    },
  });
}
