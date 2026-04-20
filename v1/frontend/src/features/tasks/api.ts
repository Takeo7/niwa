import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  apiFetch,
  hasInFlightTask,
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
