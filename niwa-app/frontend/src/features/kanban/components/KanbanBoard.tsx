import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Title,
  Loader,
  Center,
  Text,
  ScrollArea,
  Group,
  Select,
  Checkbox,
} from '@mantine/core';
import {
  DndContext,
  DragOverlay,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { KanbanColumn } from './KanbanColumn';
import { KanbanCard } from './KanbanCard';
import { useKanbanColumns, useTasks, useUpdateTask } from '../hooks/useKanban';
import { useProjects } from '../../../shared/api/queries';
import { TaskForm } from '../../tasks/components/TaskForm';
import type { Task } from '../../../shared/types';

export function KanbanBoard() {
  const navigate = useNavigate();
  const { data: columns, isLoading: colsLoading } = useKanbanColumns();
  const [showDone, setShowDone] = useState(false);
  const [projectFilter, setProjectFilter] = useState<string | null>(null);
  const { data: tasks, isLoading: tasksLoading } = useTasks({ include_done: showDone });
  const { data: projects } = useProjects();
  const updateTask = useUpdateTask();
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [addTaskStatus, setAddTaskStatus] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  );

  const filteredTasks = useMemo(() => {
    if (!tasks) return [];
    if (!projectFilter) return tasks;
    return tasks.filter((t) => String(t.project_id) === projectFilter);
  }, [tasks, projectFilter]);

  const tasksByStatus = useMemo(() => {
    const map: Record<string, Task[]> = {};
    if (columns) {
      for (const col of columns) {
        map[col.status] = [];
      }
    }
    for (const task of filteredTasks) {
      if (map[task.status]) {
        map[task.status].push(task);
      }
    }
    return map;
  }, [columns, filteredTasks]);

  const projectOptions = (projects || []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  const handleDragStart = (event: DragStartEvent) => {
    const task = filteredTasks.find((t) => t.id === event.active.id);
    if (task) setActiveTask(task);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null);
    const { active, over } = event;
    if (!over) return;

    const taskId = String(active.id);
    const newStatus = String(over.id);
    const task = filteredTasks.find((t) => t.id === taskId);

    if (task && task.status !== newStatus) {
      updateTask.mutate({ id: taskId, status: newStatus });
    }
  };

  if (colsLoading || tasksLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (!columns?.length) {
    return (
      <Center py="xl">
        <Text c="dimmed">No hay columnas configuradas</Text>
      </Center>
    );
  }

  return (
    <Box>
      <Group justify="space-between" mb="md">
        <Title order={3}>Kanban</Title>
        <Group gap="sm">
          <Select
            placeholder="Filtrar proyecto"
            data={projectOptions}
            value={projectFilter}
            onChange={setProjectFilter}
            clearable
            size="xs"
            w={180}
          />
          <Checkbox
            label="Mostrar hechas"
            checked={showDone}
            onChange={(e) => setShowDone(e.currentTarget.checked)}
            size="xs"
          />
        </Group>
      </Group>
      <ScrollArea>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <Box style={{ display: 'flex', gap: 12, paddingBottom: 16 }}>
            {columns.map((col) => (
              <KanbanColumn
                key={col.id}
                column={col}
                tasks={tasksByStatus[col.status] || []}
                onTaskClick={(id) => navigate(`/tasks/${id}`)}
                onAddTask={() => setAddTaskStatus(col.status)}
              />
            ))}
          </Box>
          <DragOverlay>
            {activeTask ? <KanbanCard task={activeTask} /> : null}
          </DragOverlay>
        </DndContext>
      </ScrollArea>

      <TaskForm
        opened={!!addTaskStatus}
        onClose={() => setAddTaskStatus(null)}
        initialStatus={addTaskStatus || undefined}
      />
    </Box>
  );
}
