import { useState, useMemo } from 'react';
import {
  Box,
  Title,
  Group,
  Button,
  TextInput,
  Select,
  Badge,
  Text,
  Loader,
  Center,
  Stack,
  Switch,
} from '@mantine/core';
import { DataTable, type DataTableColumn, type DataTableSortStatus } from 'mantine-datatable';
import { IconPlus, IconSearch } from '@tabler/icons-react';
import { useTasks } from '../hooks/useTasks';
import { TaskForm } from './TaskForm';
import { TaskDetail } from './TaskDetail';
import type { Task } from '../../../shared/types';

const PRIORITY_COLORS: Record<string, string> = {
  baja: 'blue',
  media: 'yellow',
  alta: 'orange',
  critica: 'red',
};

const STATUS_LABELS: Record<string, string> = {
  inbox: 'Inbox',
  pendiente: 'Pendiente',
  en_progreso: 'En Progreso',
  bloqueada: 'Bloqueada',
  revision: 'Revisión',
  hecha: 'Hecha',
  archivada: 'Archivada',
};

const STATUS_COLORS: Record<string, string> = {
  inbox: 'indigo',
  pendiente: 'yellow',
  en_progreso: 'blue',
  bloqueada: 'red',
  revision: 'grape',
  hecha: 'green',
  archivada: 'gray',
};

export function TaskList() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [priorityFilter, setPriorityFilter] = useState<string | null>(null);
  const [includeDone, setIncludeDone] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);
  const [sortStatus, setSortStatus] = useState<DataTableSortStatus<Task>>({
    columnAccessor: 'created_at',
    direction: 'desc',
  });

  const { data: tasks, isLoading } = useTasks({
    include_done: includeDone,
    status: statusFilter || undefined,
  });

  const filtered = useMemo(() => {
    let result = tasks || [];
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (t) =>
          t.title.toLowerCase().includes(q) ||
          (t.description || '').toLowerCase().includes(q) ||
          (t.project_name || '').toLowerCase().includes(q),
      );
    }
    if (priorityFilter) {
      result = result.filter((t) => t.priority === priorityFilter);
    }
    // Sort
    const { columnAccessor, direction } = sortStatus;
    result = [...result].sort((a, b) => {
      const aVal = (a as unknown as Record<string, unknown>)[columnAccessor] as string;
      const bVal = (b as unknown as Record<string, unknown>)[columnAccessor] as string;
      if (aVal < bVal) return direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return direction === 'asc' ? 1 : -1;
      return 0;
    });
    return result;
  }, [tasks, search, priorityFilter, sortStatus]);

  const columns: DataTableColumn<Task>[] = [
    {
      accessor: 'title',
      title: 'Título',
      sortable: true,
      render: (task) => (
        <Text size="sm" fw={500} lineClamp={1}>
          {task.title}
        </Text>
      ),
    },
    {
      accessor: 'status',
      title: 'Estado',
      sortable: true,
      width: 130,
      render: (task) => (
        <Badge
          color={STATUS_COLORS[task.status] || 'gray'}
          variant="light"
          size="sm"
        >
          {STATUS_LABELS[task.status] || task.status}
        </Badge>
      ),
    },
    {
      accessor: 'priority',
      title: 'Prioridad',
      sortable: true,
      width: 110,
      render: (task) => (
        <Badge
          color={PRIORITY_COLORS[task.priority] || 'gray'}
          variant="dot"
          size="sm"
        >
          {task.priority}
        </Badge>
      ),
    },
    {
      accessor: 'project_name',
      title: 'Proyecto',
      sortable: true,
      width: 150,
      render: (task) => (
        <Text size="sm" c="dimmed" lineClamp={1}>
          {task.project_name || '—'}
        </Text>
      ),
    },
    {
      accessor: 'due_at',
      title: 'Fecha límite',
      sortable: true,
      width: 120,
      render: (task) => (
        <Text size="sm" c="dimmed">
          {task.due_at
            ? new Date(task.due_at).toLocaleDateString('es-ES')
            : '—'}
        </Text>
      ),
    },
    {
      accessor: 'created_at',
      title: 'Creada',
      sortable: true,
      width: 120,
      render: (task) => (
        <Text size="sm" c="dimmed">
          {new Date(task.created_at).toLocaleDateString('es-ES')}
        </Text>
      ),
    },
  ];

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Tareas</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setEditingTask(null);
            setFormOpen(true);
          }}
        >
          Nueva tarea
        </Button>
      </Group>

      <Group gap="sm">
        <TextInput
          placeholder="Buscar tareas..."
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Select
          placeholder="Estado"
          data={[
            { value: 'pendiente', label: 'Pendiente' },
            { value: 'en_progreso', label: 'En Progreso' },
            { value: 'bloqueada', label: 'Bloqueada' },
            { value: 'revision', label: 'Revisión' },
            { value: 'hecha', label: 'Hecha' },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
          clearable
          w={160}
        />
        <Select
          placeholder="Prioridad"
          data={[
            { value: 'baja', label: 'Baja' },
            { value: 'media', label: 'Media' },
            { value: 'alta', label: 'Alta' },
            { value: 'critica', label: 'Crítica' },
          ]}
          value={priorityFilter}
          onChange={setPriorityFilter}
          clearable
          w={140}
        />
        <Switch
          label="Completadas"
          checked={includeDone}
          onChange={(e) => setIncludeDone(e.currentTarget.checked)}
        />
      </Group>

      {filtered.length === 0 ? (
        <Box py="xl">
          <Text ta="center" c="dimmed">
            No hay tareas
          </Text>
        </Box>
      ) : (
        <DataTable
          records={filtered}
          columns={columns}
          sortStatus={sortStatus}
          onSortStatusChange={setSortStatus}
          highlightOnHover
          onRowClick={({ record }) => setDetailTaskId(record.id)}
          idAccessor="id"
          minHeight={200}
          borderRadius="md"
          withTableBorder
          striped
        />
      )}

      <TaskForm
        opened={formOpen}
        onClose={() => setFormOpen(false)}
        task={editingTask}
      />
      <TaskDetail
        taskId={detailTaskId}
        opened={!!detailTaskId}
        onClose={() => setDetailTaskId(null)}
      />
    </Stack>
  );
}
