import { Routes, Route, Navigate } from 'react-router-dom';
import { ChatView } from '../features/chat/components/ChatView';
import { TaskList } from '../features/tasks/components/TaskList';
import { KanbanBoard } from '../features/kanban/components/KanbanBoard';
import { ProjectList } from '../features/projects/components/ProjectList';
import { ProjectDetail } from '../features/projects/components/ProjectDetail';
import { SystemView } from '../features/system/components/SystemView';
import { MetricsDashboard } from '../features/metrics/components/MetricsDashboard';
import { NotesList } from '../features/notes/components/NotesList';
import { DashboardView } from '../features/dashboard/components/DashboardView';
import { HistoryView } from '../features/history/components/HistoryView';

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<DashboardView />} />
      <Route path="/chat" element={<ChatView />} />
      <Route path="/tasks" element={<TaskList />} />
      <Route path="/kanban" element={<KanbanBoard />} />
      <Route path="/projects" element={<ProjectList />} />
      <Route path="/projects/:slug" element={<ProjectDetail />} />
      <Route path="/system" element={<SystemView />} />
      <Route path="/metrics" element={<MetricsDashboard />} />
      <Route path="/notes" element={<NotesList />} />
      <Route path="/history" element={<HistoryView />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
