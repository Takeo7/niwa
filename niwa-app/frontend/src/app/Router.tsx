import { Routes, Route, Navigate } from 'react-router-dom';
import { ChatView } from '../features/chat/components/ChatView';
import { TaskList } from '../features/tasks/components/TaskList';
import { KanbanBoard } from '../features/kanban/components/KanbanBoard';
import { ProjectList } from '../features/projects/components/ProjectList';
import { ProjectDetail } from '../features/projects/components/ProjectDetail';
import { SystemView } from '../features/system/components/SystemView';
import { MetricsDashboard } from '../features/metrics/components/MetricsDashboard';
import { NotesList } from '../features/notes/components/NotesList';

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<ChatView />} />
      <Route path="/tasks" element={<TaskList />} />
      <Route path="/kanban" element={<KanbanBoard />} />
      <Route path="/projects" element={<ProjectList />} />
      <Route path="/projects/:slug" element={<ProjectDetail />} />
      <Route path="/system" element={<SystemView />} />
      <Route path="/metrics" element={<MetricsDashboard />} />
      <Route path="/notes" element={<NotesList />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
