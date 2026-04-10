import { useState, useMemo } from 'react';
import {
  Box,
  Title,
  Loader,
  Center,
  Text,
  ScrollArea,
  Group,
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
import { TaskDetail } from '../../tasks/components/TaskDetail';
import type { Task } from '../../../shared/types';

export function KanbanBoard() {
  const { data: columns, isLoading: colsLoading } = useKanbanColumns();
  const { data: tasks, isLoading: tasksLoading } = useTasks({ include_done: true });
  const updateTask = useUpdateTask();
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  );

  const tasksByStatus = useMemo(() => {
    const map: Record<string, Task[]> = {};
    if (columns) {
      for (const col of columns) {
        map[col.status] = [];
      }
    }
    if (tasks) {
      for (const task of tasks) {
        if (map[task.status]) {
          map[task.status].push(task);
        }
      }
    }
    return map;
  }, [columns, tasks]);

  const handleDragStart = (event: DragStartEvent) => {
    const task = tasks?.find((t) => t.id === event.active.id);
    if (task) setActiveTask(task);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null);
    const { active, over } = event;
    if (!over) return;

    const taskId = String(active.id);
    const newStatus = String(over.id);
    const task = tasks?.find((t) => t.id === taskId);

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
                onTaskClick={setDetailTaskId}
              />
            ))}
          </Box>
          <DragOverlay>
            {activeTask ? <KanbanCard task={activeTask} /> : null}
          </DragOverlay>
        </DndContext>
      </ScrollArea>

      <TaskDetail
        taskId={detailTaskId}
        opened={!!detailTaskId}
        onClose={() => setDetailTaskId(null)}
      />
    </Box>
  );
}
