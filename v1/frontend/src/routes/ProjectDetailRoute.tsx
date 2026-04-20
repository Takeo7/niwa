import { Alert } from "@mantine/core";
import { useParams } from "react-router-dom";

import { ProjectDetail } from "../features/projects/ProjectDetail";

export function ProjectDetailRoute() {
  const { slug } = useParams<{ slug: string }>();
  if (!slug) {
    return <Alert color="red" title="Slug faltante" />;
  }
  return <ProjectDetail slug={slug} />;
}
