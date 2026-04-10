import { Box, Title, Badge, Paper, Stack, ScrollArea, Button } from '@mantine/core';
import { useDroppable } from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { IconPlus } from '@tabler/icons-react';
import { KanbanCard } from './KanbanCard';
import type { Task, KanbanColumn as KanbanColumnType } from '../../../shared/types';

interface Props {
  column: KanbanColumnType;
  tasks: Task[];
  onTaskClick: (taskId: string) => void;
  onAddTask?: () => void;
}

export function KanbanColumn({ column, tasks, onTaskClick, onAddTask }: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id: column.status,
  });

  return (
    <Paper
      ref={setNodeRef}
      p="xs"
      radius="md"
      w={280}
      mih={400}
      style={{
        flexShrink: 0,
        backgroundColor: isOver
          ? 'var(--mantine-color-dark-5)'
          : 'var(--mantine-color-dark-7)',
        border: isOver
          ? '2px dashed var(--mantine-color-brand-5)'
          : '1px solid var(--mantine-color-dark-4)',
        transition: 'background-color 150ms, border-color 150ms',
      }}
    >
      <Box mb="xs">
        <Title order={6} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Box
            w={10}
            h={10}
            style={{
              borderRadius: '50%',
              backgroundColor: column.color || 'var(--mantine-color-gray-5)',
              flexShrink: 0,
            }}
          />
          {column.label}
          <Badge size="xs" variant="light" circle>
            {tasks.length}
          </Badge>
        </Title>
      </Box>
      <ScrollArea.Autosize mah="calc(100vh - 280px)" offsetScrollbars>
        <SortableContext
          items={tasks.map((t) => t.id)}
          strategy={verticalListSortingStrategy}
        >
          <Stack gap={0}>
            {tasks.map((task) => (
              <KanbanCard
                key={task.id}
                task={task}
                onClick={() => onTaskClick(task.id)}
              />
            ))}
          </Stack>
        </SortableContext>
      </ScrollArea.Autosize>
      {onAddTask && (
        <Button
          variant="subtle"
          size="xs"
          fullWidth
          mt="xs"
          leftSection={<IconPlus size={14} />}
          onClick={onAddTask}
        >
          Agregar tarea
        </Button>
      )}
    </Paper>
  );
}
