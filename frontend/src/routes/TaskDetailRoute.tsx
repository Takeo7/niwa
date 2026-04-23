import { Alert } from "@mantine/core";
import { useParams } from "react-router-dom";

import { TaskDetail } from "../features/tasks/TaskDetail";

export function TaskDetailRoute() {
  const { id } = useParams<{ slug: string; id: string }>();
  const taskId = id ? Number(id) : NaN;
  if (!id || !Number.isFinite(taskId)) {
    return <Alert color="red" title="Id de tarea inválido" />;
  }
  return <TaskDetail taskId={taskId} />;
}
