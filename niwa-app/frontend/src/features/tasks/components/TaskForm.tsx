import { useState, useEffect } from 'react';
import {
  Modal,
  TextInput,
  Textarea,
  Select,
  Button,
  Stack,
  Group,
  Checkbox,
} from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useCreateTask, useUpdateTask } from '../hooks/useTasks';
import { useProjects } from '../../../shared/api/queries';
import type { Task } from '../../../shared/types';

interface Props {
  opened: boolean;
  onClose: () => void;
  /** Full task → edit mode. ``null``/``undefined`` → create mode. */
  task?: Task | null;
  /** Pre-select this status when creating (e.g. kanban column "+"). */
  initialStatus?: string;
  /** Pre-select this project when creating (e.g. "Nueva tarea" desde
   * la vista de un proyecto). Only applies in create mode. */
  initialProjectId?: string | null;
  /** Link this new task to a parent task (PR-55: "Responder" para
   * tareas en ``waiting_input``). Only applies in create mode. */
  initialParentTaskId?: string | null;
  /** Pre-fill the description field. Used by "Responder" to seed the
   * reply context. */
  initialDescription?: string;
  /** Pre-fill the title field. */
  initialTitle?: string;
}

const STATUS_OPTIONS = [
  { value: 'pendiente', label: 'Pendiente' },
  { value: 'en_progreso', label: 'En Progreso' },
  { value: 'bloqueada', label: 'Bloqueada' },
  { value: 'revision', label: 'Revisión' },
  { value: 'hecha', label: 'Hecha' },
  { value: 'archivada', label: 'Archivada' },
];

const PRIORITY_OPTIONS = [
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

const AREA_OPTIONS = [
  { value: 'personal', label: 'Personal' },
  { value: 'empresa', label: 'Empresa' },
  { value: 'proyecto', label: 'Proyecto' },
  { value: 'sistema', label: 'Sistema' },
];

export function TaskForm({
  opened,
  onClose,
  task,
  initialStatus,
  initialProjectId,
  initialParentTaskId,
  initialDescription,
  initialTitle,
}: Props) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [status, setStatus] = useState('pendiente');
  const [priority, setPriority] = useState('media');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [dueDate, setDueDate] = useState<Date | null>(null);
  const [startDate, setStartDate] = useState<Date | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [urgent, setUrgent] = useState(false);

  const createTask = useCreateTask();
  const updateTask = useUpdateTask();
  const { data: projects } = useProjects();

  // Only treat as editing when we have a real persisted task (has an id).
  // Callers that want to pre-seed fields on create (e.g. the kanban "+"
  // button pre-selecting a column's status) should use ``initialStatus``
  // instead of synthesising a partial ``Task``.
  const isEditing = !!task && !!task.id;

  useEffect(() => {
    if (isEditing && task) {
      setTitle(task.title || '');
      setDescription(task.description || '');
      setStatus(task.status || 'pendiente');
      setPriority(task.priority || 'media');
      setProjectId(task.project_id);
      setDueDate(task.due_at ? new Date(task.due_at) : null);
      setStartDate(task.scheduled_for ? new Date(task.scheduled_for) : null);
      setArea(task.area || null);
      setUrgent(task.urgent === 1);
    } else {
      setTitle(initialTitle || '');
      setDescription(initialDescription || '');
      setStatus(initialStatus || 'pendiente');
      setPriority('media');
      setProjectId(initialProjectId || null);
      setDueDate(null);
      setStartDate(null);
      setArea(null);
      setUrgent(false);
    }
  }, [
    task,
    opened,
    initialStatus,
    initialProjectId,
    initialParentTaskId,
    initialDescription,
    initialTitle,
    isEditing,
  ]);

  const projectOptions = (projects || []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  const handleSubmit = async () => {
    const data: Record<string, unknown> = {
      title,
      description,
      status,
      priority,
      project_id: projectId,
      due_at: dueDate ? dueDate.toISOString().split('T')[0] : null,
      scheduled_for: startDate ? startDate.toISOString().split('T')[0] : null,
      area: area || '',
      urgent: urgent ? 1 : 0,
    };
    // PR-55: record the parent relation when this is a reply / follow-up.
    // Only applies on create — updating parent_task_id via the form is
    // not exposed in the UI.
    if (!isEditing && initialParentTaskId) {
      data.parent_task_id = initialParentTaskId;
    }

    if (isEditing) {
      await updateTask.mutateAsync({ id: task.id, ...data } as Parameters<typeof updateTask.mutateAsync>[0]);
    } else {
      await createTask.mutateAsync(data as Parameters<typeof createTask.mutateAsync>[0]);
    }
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEditing ? 'Editar tarea' : 'Nueva tarea'}
      size="lg"
    >
      <Stack gap="sm">
        <TextInput
          label="Título"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
          required
          placeholder="Título de la tarea"
        />
        <Textarea
          label="Descripción"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          minRows={3}
          placeholder="Describe la tarea..."
        />
        <Group grow>
          <Select
            label="Estado"
            data={STATUS_OPTIONS}
            value={status}
            onChange={(v) => setStatus(v || 'pendiente')}
          />
          <Select
            label="Prioridad"
            data={PRIORITY_OPTIONS}
            value={priority}
            onChange={(v) => setPriority(v || 'media')}
          />
        </Group>
        <Group grow>
          <Select
            label="Proyecto"
            data={projectOptions}
            value={projectId}
            onChange={setProjectId}
            clearable
            placeholder="Sin proyecto"
          />
          <Select
            label="Área"
            data={AREA_OPTIONS}
            value={area}
            onChange={setArea}
            clearable
            placeholder="Sin área"
          />
        </Group>
        <Group grow>
          <DateInput
            label="Fecha inicio"
            value={startDate}
            onChange={setStartDate}
            clearable
            placeholder="Sin fecha"
            valueFormat="DD/MM/YYYY"
          />
          <DateInput
            label="Fecha límite"
            value={dueDate}
            onChange={setDueDate}
            clearable
            placeholder="Sin fecha"
            valueFormat="DD/MM/YYYY"
          />
        </Group>
        <Checkbox
          label="Urgente"
          checked={urgent}
          onChange={(e) => setUrgent(e.currentTarget.checked)}
        />
        <Group justify="flex-end" mt="md">
          <Button variant="subtle" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            onClick={handleSubmit}
            loading={createTask.isPending || updateTask.isPending}
            disabled={!(title || '').trim()}
          >
            {isEditing ? 'Guardar' : 'Crear tarea'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
