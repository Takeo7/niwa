import { Paper, Text, Badge, Group } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Task } from '../../../shared/types';

const PRIORITY_COLORS: Record<string, string> = {
  baja: 'blue',
  media: 'yellow',
  alta: 'orange',
  critica: 'red',
};

interface Props {
  task: Task;
  onClick?: () => void;
}

export function KanbanCard({ task, onClick }: Props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({
      id: task.id,
      data: { task },
    });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    cursor: 'grab',
  };

  return (
    <Paper
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      p="xs"
      radius="md"
      withBorder
      onClick={onClick}
      shadow="xs"
      mb={6}
    >
      <Text size="sm" fw={500} lineClamp={2} mb={4}>
        {task.title}
      </Text>
      <Group gap={4}>
        <Badge
          size="xs"
          color={PRIORITY_COLORS[task.priority] || 'gray'}
          variant="light"
        >
          {task.priority}
        </Badge>
        {task.project_name && (
          <Badge size="xs" variant="outline" color="gray">
            {task.project_name}
          </Badge>
        )}
        {task.urgent === 1 && (
          <Badge size="xs" color="red">
            !
          </Badge>
        )}
      </Group>
    </Paper>
  );
}
