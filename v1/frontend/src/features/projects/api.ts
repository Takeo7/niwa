import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type Project, type ProjectCreatePayload } from "../../api";

const PROJECTS_KEY = ["projects"] as const;

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
