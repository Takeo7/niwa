import { Route, Routes } from "react-router-dom";

import { AppShell } from "./shared/AppShell";
import { ProjectsRoute } from "./routes/ProjectsRoute";
import { ProjectDetailRoute } from "./routes/ProjectDetailRoute";
import { SystemRoute } from "./routes/SystemRoute";
import { TaskDetailRoute } from "./routes/TaskDetailRoute";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ProjectsRoute />} />
        <Route path="projects/:slug" element={<ProjectDetailRoute />} />
        <Route path="projects/:slug/tasks/:id" element={<TaskDetailRoute />} />
        <Route path="system" element={<SystemRoute />} />
      </Route>
    </Routes>
  );
}
