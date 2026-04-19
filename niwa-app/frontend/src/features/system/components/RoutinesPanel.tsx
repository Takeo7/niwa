import { useState } from 'react';
import {
  Stack,
  Paper,
  Text,
  Group,
  Badge,
  Switch,
  Button,
  ActionIcon,
  Modal,
  TextInput,
  Textarea,
  Select,
  Loader,
  Center,
} from '@mantine/core';
import {
  IconPlus,
  IconPlayerPlay,
  IconTrash,
  IconEdit,
  IconClock,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import {
  useRoutines,
  useCreateRoutine,
  useUpdateRoutine,
  useDeleteRoutine,
  useToggleRoutine,
  useRunRoutine,
  useProjects,
} from '../../../shared/api/queries';
import type {
  Routine,
  RoutineAction,
  ImprovementType,
} from '../../../shared/types';

const ACTION_OPTIONS: { value: RoutineAction; label: string }[] = [
  { value: 'script', label: 'Script' },
  { value: 'improve', label: 'Improve (plantilla)' },
];

const IMPROVEMENT_TYPE_OPTIONS: { value: ImprovementType; label: string }[] = [
  { value: 'functional', label: 'functional' },
  { value: 'stability', label: 'stability' },
  { value: 'security', label: 'security' },
];

function cronToHuman(cron: string): string {
  if (!cron) return '-';
  const parts = cron.split(' ');
  if (parts.length < 5) return cron;
  const [min, hour, dom, mon, dow] = parts;
  if (min === '*' && hour === '*') return 'Cada minuto';
  if (hour === '*') return `Cada ${min} minutos`;
  if (dom === '*' && mon === '*' && dow === '*') return `Diario a las ${hour}:${min.padStart(2, '0')}`;
  if (dow === '1-5') return `Lun-Vie ${hour}:${min.padStart(2, '0')}`;
  return cron;
}

export function RoutinesPanel() {
  const { data: routines, isLoading } = useRoutines();
  const { data: projects } = useProjects();
  const createRoutine = useCreateRoutine();
  const updateRoutine = useUpdateRoutine();
  const deleteRoutine = useDeleteRoutine();
  const toggleRoutine = useToggleRoutine();
  const runRoutine = useRunRoutine();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [name, setName] = useState('');
  const [schedule, setSchedule] = useState('');
  const [description, setDescription] = useState('');
  const [command, setCommand] = useState('');
  const [action, setAction] = useState<RoutineAction>('script');
  const [improvementType, setImprovementType] = useState<ImprovementType | ''>('');
  const [projectId, setProjectId] = useState<string>('');

  const openNew = () => {
    setEditing(null);
    setName('');
    setSchedule('');
    setDescription('');
    setCommand('');
    setAction('script');
    setImprovementType('');
    setProjectId('');
    setEditorOpen(true);
  };

  const openEdit = (r: Routine) => {
    setEditing(r);
    setName(r.name);
    setSchedule(r.schedule);
    setDescription(r.description || '');
    const routineAction: RoutineAction =
      (r.action as RoutineAction | undefined) ?? 'script';
    setAction(routineAction);
    setImprovementType((r.improvement_type ?? '') as ImprovementType | '');
    const cfg = (r.action_config ?? {}) as Record<string, unknown>;
    setProjectId(typeof cfg.project_id === 'string' ? cfg.project_id : '');
    setCommand(
      routineAction === 'script'
        ? ((cfg.script as string) || (cfg.command as string) || (typeof cfg === 'object' ? JSON.stringify(cfg) : ''))
        : '',
    );
    setEditorOpen(true);
  };

  const handleSave = async () => {
    const baseData: Record<string, unknown> = {
      name,
      schedule,
      description,
      action,
    };
    if (action === 'improve') {
      baseData.improvement_type = improvementType;
      baseData.action_config = { project_id: projectId };
    } else {
      baseData.action_config = { script: command };
      baseData.improvement_type = null;
    }
    if (editing) {
      await updateRoutine.mutateAsync({ id: editing.id, ...baseData });
      notifications.show({ title: 'Rutina actualizada', message: name, color: 'green' });
    } else {
      await createRoutine.mutateAsync(baseData);
      notifications.show({ title: 'Rutina creada', message: name, color: 'green' });
    }
    setEditorOpen(false);
  };

  const saveDisabled =
    !name.trim() ||
    !schedule.trim() ||
    (action === 'improve' && (!improvementType || !projectId));

  const handleDelete = async (r: Routine) => {
    await deleteRoutine.mutateAsync(r.id);
    notifications.show({ title: 'Rutina eliminada', message: r.name, color: 'red' });
  };

  const handleToggle = (r: Routine) => {
    toggleRoutine.mutate(r.id);
  };

  const handleRun = async (r: Routine) => {
    await runRoutine.mutateAsync(r.id);
    notifications.show({ title: 'Rutina ejecutada', message: r.name, color: 'blue' });
  };

  if (isLoading) {
    return <Center py="xl"><Loader /></Center>;
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={600} size="lg">Rutinas</Text>
        <Button leftSection={<IconPlus size={16} />} size="sm" onClick={openNew}>
          Nueva rutina
        </Button>
      </Group>

      {!routines?.length ? (
        <Center py="xl">
          <Stack align="center" gap="sm">
            <IconClock size={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">Sin rutinas configuradas</Text>
          </Stack>
        </Center>
      ) : (
        <Stack gap="xs">
          {routines.map((r) => {
            const enabled = r.enabled === true || r.enabled === 1;
            return (
              <Paper key={r.id} p="sm" radius="md" withBorder>
                <Group justify="space-between" wrap="nowrap">
                  <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                    <Group gap="xs">
                      <Text fw={500} size="sm">{r.name}</Text>
                      <Badge size="xs" color={enabled ? 'green' : 'gray'}>
                        {enabled ? 'Activa' : 'Inactiva'}
                      </Badge>
                      {r.improvement_type ? (
                        <Badge size="xs" color="violet" variant="light">
                          improve:{r.improvement_type}
                        </Badge>
                      ) : null}
                    </Group>
                    <Group gap="md">
                      <Text size="xs" c="dimmed">
                        Horario: {cronToHuman(r.schedule)}
                      </Text>
                      {r.last_run && (
                        <Text size="xs" c="dimmed">
                          Última: {new Date(r.last_run).toLocaleString('es-ES')}
                        </Text>
                      )}
                      {r.next_run && (
                        <Text size="xs" c="dimmed">
                          Siguiente: {new Date(r.next_run).toLocaleString('es-ES')}
                        </Text>
                      )}
                    </Group>
                  </Stack>
                  <Group gap="xs" wrap="nowrap">
                    <Switch
                      checked={enabled}
                      onChange={() => handleToggle(r)}
                      size="sm"
                    />
                    <ActionIcon
                      variant="light"
                      color="blue"
                      size="sm"
                      onClick={() => handleRun(r)}
                      title="Ejecutar ahora"
                    >
                      <IconPlayerPlay size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="light"
                      size="sm"
                      onClick={() => openEdit(r)}
                      title="Editar"
                    >
                      <IconEdit size={14} />
                    </ActionIcon>
                    <ActionIcon
                      variant="light"
                      color="red"
                      size="sm"
                      onClick={() => handleDelete(r)}
                      title="Eliminar"
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Paper>
            );
          })}
        </Stack>
      )}

      {/* Editor Modal */}
      <Modal
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={editing ? 'Editar rutina' : 'Nueva rutina'}
      >
        <Stack gap="sm">
          <TextInput
            label="Nombre"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
            placeholder="Nombre de la rutina"
          />
          <TextInput
            label="Horario (cron)"
            value={schedule}
            onChange={(e) => setSchedule(e.currentTarget.value)}
            required
            placeholder="0 9 * * *"
          />
          <Textarea
            label="Descripción"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            minRows={2}
            placeholder="Descripción opcional"
          />
          <Select
            label="Tipo de acción"
            data={ACTION_OPTIONS}
            value={action}
            onChange={(value) => {
              const next = (value as RoutineAction | null) ?? 'script';
              setAction(next);
              if (next !== 'improve') {
                setImprovementType('');
                setProjectId('');
              }
            }}
            allowDeselect={false}
          />
          {action === 'improve' ? (
            <>
              <Select
                label="Tipo de mejora"
                data={IMPROVEMENT_TYPE_OPTIONS}
                value={improvementType || null}
                onChange={(value) => setImprovementType((value as ImprovementType | null) ?? '')}
                placeholder="Elige una plantilla"
                required
              />
              <Select
                label="Proyecto"
                data={(projects ?? []).map((p) => ({
                  value: p.id,
                  label: p.name,
                }))}
                value={projectId || null}
                onChange={(value) => setProjectId(value ?? '')}
                placeholder="Elige el proyecto"
                searchable
                required
                nothingFoundMessage="Sin proyectos"
              />
            </>
          ) : (
            <Textarea
              label="Comando / Script"
              value={command}
              onChange={(e) => setCommand(e.currentTarget.value)}
              minRows={3}
              placeholder="echo 'hola mundo'"
              styles={{ input: { fontFamily: 'monospace' } }}
            />
          )}
          <Group justify="flex-end" mt="sm">
            <Button variant="subtle" onClick={() => setEditorOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleSave}
              loading={createRoutine.isPending || updateRoutine.isPending}
              disabled={saveDisabled}
            >
              {editing ? 'Guardar' : 'Crear'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
