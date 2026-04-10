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
} from '../../../shared/api/queries';
import type { Routine } from '../../../shared/types';

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

  const openNew = () => {
    setEditing(null);
    setName('');
    setSchedule('');
    setDescription('');
    setCommand('');
    setEditorOpen(true);
  };

  const openEdit = (r: Routine) => {
    setEditing(r);
    setName(r.name);
    setSchedule(r.schedule);
    setDescription(r.description || '');
    setCommand(
      r.action_config
        ? (r.action_config as Record<string, string>).script || (r.action_config as Record<string, string>).command || JSON.stringify(r.action_config)
        : '',
    );
    setEditorOpen(true);
  };

  const handleSave = async () => {
    const data = {
      name,
      schedule,
      description,
      action_type: 'script',
      action_config: { script: command },
    };
    if (editing) {
      await updateRoutine.mutateAsync({ id: editing.id, ...data });
      notifications.show({ title: 'Rutina actualizada', message: name, color: 'green' });
    } else {
      await createRoutine.mutateAsync(data);
      notifications.show({ title: 'Rutina creada', message: name, color: 'green' });
    }
    setEditorOpen(false);
  };

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
          <Textarea
            label="Comando / Script"
            value={command}
            onChange={(e) => setCommand(e.currentTarget.value)}
            minRows={3}
            placeholder="echo 'hola mundo'"
            styles={{ input: { fontFamily: 'monospace' } }}
          />
          <Group justify="flex-end" mt="sm">
            <Button variant="subtle" onClick={() => setEditorOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleSave}
              loading={createRoutine.isPending || updateRoutine.isPending}
              disabled={!name.trim() || !schedule.trim()}
            >
              {editing ? 'Guardar' : 'Crear'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
