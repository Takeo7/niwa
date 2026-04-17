import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Title,
  SimpleGrid,
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Loader,
  Center,
  Progress,
  Button,
  Modal,
  TextInput,
  Textarea,
  ActionIcon,
  Menu,
} from '@mantine/core';
import {
  IconFolders,
  IconPlus,
  IconDotsVertical,
  IconEdit,
  IconTrash,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import {
  useProjects,
  useCreateProject,
  useUpdateProject,
  useDeleteProject,
} from '../hooks/useProjects';
import type { Project } from '../../../shared/types';

export function ProjectList() {
  const { data: projects, isLoading } = useProjects();
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();
  const navigate = useNavigate();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [directory, setDirectory] = useState('');

  const openNew = () => {
    setEditing(null);
    setName('');
    setDescription('');
    setDirectory('');
    setFormOpen(true);
  };

  const openEdit = (p: Project, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(p);
    setName(p.name);
    setDescription(p.description || '');
    setDirectory(p.directory || '');
    setFormOpen(true);
  };

  const handleSave = async () => {
    // Always send ``directory``; empty string means "autogenerate"
    // (backend /api/projects since PR-51 for POST, PR-55 for PATCH).
    const dir = directory.trim();
    if (editing) {
      await updateProject.mutateAsync({
        slug: editing.slug,
        name,
        description,
        directory: dir,
      });
      notifications.show({ title: 'Proyecto actualizado', message: name, color: 'green' });
    } else {
      await createProject.mutateAsync({
        name,
        description,
        directory: dir,
      });
      notifications.show({ title: 'Proyecto creado', message: name, color: 'green' });
    }
    setFormOpen(false);
  };

  const handleDelete = async (p: Project, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`¿Eliminar el proyecto "${p.name}"?`)) return;
    await deleteProject.mutateAsync(p.slug);
    notifications.show({ title: 'Proyecto eliminado', message: p.name, color: 'red' });
  };

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
        <Title order={3}>Proyectos</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={openNew}>
          Nuevo proyecto
        </Button>
      </Group>

      {!projects?.length ? (
        <Center py="xl">
          <Stack align="center" gap="sm">
            <IconFolders size={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">No hay proyectos</Text>
          </Stack>
        </Center>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          {projects.map((p) => {
            const pct = p.total_tasks > 0
              ? Math.round((p.done_tasks / p.total_tasks) * 100)
              : 0;
            return (
              <Card
                key={p.id}
                shadow="sm"
                padding="lg"
                radius="md"
                withBorder
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/projects/${p.slug}`)}
              >
                <Group justify="space-between" mb="xs" wrap="nowrap">
                  <Text fw={600} lineClamp={1} style={{ flex: 1 }}>
                    {p.name}
                  </Text>
                  <Group gap={4} wrap="nowrap">
                    <Badge
                      color={p.open_tasks > 0 ? 'blue' : 'green'}
                      variant="light"
                      size="sm"
                    >
                      {p.open_tasks} abiertas
                    </Badge>
                    <Menu shadow="md" width={160}>
                      <Menu.Target>
                        <ActionIcon
                          variant="subtle"
                          size="sm"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <IconDotsVertical size={14} />
                        </ActionIcon>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item
                          leftSection={<IconEdit size={14} />}
                          onClick={(e) => openEdit(p, e as unknown as React.MouseEvent)}
                        >
                          Editar
                        </Menu.Item>
                        <Menu.Item
                          leftSection={<IconTrash size={14} />}
                          color="red"
                          onClick={(e) => handleDelete(p, e as unknown as React.MouseEvent)}
                        >
                          Eliminar
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                </Group>
                <Text size="sm" c="dimmed" lineClamp={2} mb="sm">
                  {p.description || 'Sin descripción'}
                </Text>
                <Progress value={pct} size="sm" mb="xs" color="brand" />
                <Group gap="xs" justify="space-between">
                  <Group gap="xs">
                    <Badge size="xs" variant="outline">
                      {p.total_tasks} tareas
                    </Badge>
                    <Badge size="xs" color="green" variant="outline">
                      {p.done_tasks} hechas
                    </Badge>
                    {!p.directory && (
                      <Badge size="xs" color="orange" variant="light">
                        sin directorio
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">{pct}%</Text>
                </Group>
              </Card>
            );
          })}
        </SimpleGrid>
      )}

      {/* Create/Edit Modal */}
      <Modal
        opened={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? 'Editar proyecto' : 'Nuevo proyecto'}
      >
        <Stack gap="sm">
          <TextInput
            label="Nombre"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
            placeholder="Nombre del proyecto"
          />
          <Textarea
            label="Descripción"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            minRows={3}
            placeholder="Descripción del proyecto"
          />
          <TextInput
            label="Directorio"
            value={directory}
            onChange={(e) => setDirectory(e.currentTarget.value)}
            placeholder="Déjalo vacío para autogenerar en /home/niwa/projects/<slug>"
            description="Ruta absoluta donde Claude y el executor trabajarán. Si lo dejas vacío, Niwa genera una bajo NIWA_PROJECTS_ROOT."
          />
          <Group justify="flex-end" mt="sm">
            <Button variant="subtle" onClick={() => setFormOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleSave}
              loading={createProject.isPending || updateProject.isPending}
              disabled={!name.trim()}
            >
              {editing ? 'Guardar' : 'Crear'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
