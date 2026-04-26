import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type Project, type ProjectCreatePayload } from "../../api";

const PROJECTS_KEY = ["projects"] as const;

// ---- Pulls wire types (mirror backend app/schemas/pulls.py) -------------
//
// snake_case is intentional: the backend (PR-V1-34a) maps gh's camelCase
// payload into a Pydantic-shaped envelope and pre-collapses the
// statusCheckRollup into a single literal in `checks.state`. Keep this in
// sync with `backend/app/schemas/pulls.py`.

export type PullCheckState = "failing" | "pending" | "passing" | "none";

export interface PullCheck {
  state: PullCheckState;
}

export interface PullRead {
  number: number;
  title: string;
  state: "OPEN" | "CLOSED" | "MERGED";
  url: string;
  mergeable: "MERGEABLE" | "CONFLICTING" | "UNKNOWN";
  checks: PullCheck;
  head_ref_name: string;
  created_at: string;
  updated_at: string;
}

export interface PullsResponse {
  pulls: PullRead[];
  warning?: "no_remote" | "invalid_remote";
}

export interface ListPullsOptions {
  state?: "open" | "closed" | "all";
  include_all?: boolean;
}

export function listPulls(
  slug: string,
  opts: ListPullsOptions = {},
): Promise<PullsResponse> {
  const params = new URLSearchParams();
  if (opts.state) params.set("state", opts.state);
  if (opts.include_all !== undefined) {
    params.set("include_all", String(opts.include_all));
  }
  const qs = params.toString();
  const suffix = qs ? `?${qs}` : "";
  return apiFetch<PullsResponse>(`/projects/${slug}/pulls${suffix}`);
}

export function useProjects() {
  return useQuery<Project[]>({
    queryKey: PROJECTS_KEY,
    queryFn: () => apiFetch<Project[]>("/projects"),
  });
}

export function useProject(slug: string | undefined) {
  return useQuery<Project>({
    queryKey: ["project", slug],
    queryFn: () => apiFetch<Project>(`/projects/${slug}`),
    enabled: Boolean(slug),
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation<Project, Error, ProjectCreatePayload>({
    mutationFn: (payload) =>
      apiFetch<Project>("/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PROJECTS_KEY });
    },
  });
}
