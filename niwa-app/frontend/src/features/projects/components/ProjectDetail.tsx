import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Title,
  Text,
  Stack,
  Tabs,
  Group,
  Badge,
  Button,
  Loader,
  Center,
  Card,
  SimpleGrid,
  Progress,
  Modal,
  TextInput,
  Textarea,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { notifications } from '@mantine/notifications';
import {
  IconArrowLeft,
  IconUpload,
  IconFile,
  IconX,
  IconCloudUpload,
  IconExternalLink,
  IconPlus,
  IconEdit,
} from '@tabler/icons-react';
import {
  useProject,
  useProjectUploads,
  useUploadFile,
  useUpdateProject,
} from '../hooks/useProjects';
import {
  useTasks,
  useDeployments,
  useDeployProject,
  useUndeployProject,
} from '../../../shared/api/queries';
import { FileTree } from './FileTree';
import { CapabilitiesTab } from './CapabilitiesTab';
import { TaskForm } from '../../tasks/components/TaskForm';
import type { Task, Project, Deployment } from '../../../shared/types';

function TaskRow({ task }: { task: Task }) {
  const navigate = useNavigate();
  const statusColor: Record<string, string> = {
    pendiente: 'yellow',
    en_progreso: 'blue',
    bloqueada: 'red',
    revision: 'grape',
    hecha: 'green',
  };
  return (
    <Group
      justify="space-between"
      py={4}
      px="xs"
      style={{ cursor: 'pointer', borderRadius: 4 }}
      onClick={() => navigate(`/tasks/${task.id}`)}
      role="link"
      aria-label={`Abrir tarea ${task.title}`}
    >
      <Text size="sm" lineClamp={1} style={{ flex: 1 }}>
        {task.title}
      </Text>
      <Badge size="xs" color={statusColor[task.status] || 'gray'} variant="light">
        {task.status}
      </Badge>
    </Group>
  );
}

export function ProjectDetail() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading } = useProject(slug);
  const { data: tasks } = useTasks({ project_id: project?.id, include_done: true });
  const { data: uploads } = useProjectUploads(slug);
  const uploadFile = useUploadFile(slug || '');
  const [activeTab, setActiveTab] = useState<string | null>('overview');
  const [taskFormOpen, setTaskFormOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [focusDirectory, setFocusDirectory] = useState(false);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (!project) {
    return (
      <Center py="xl">
        <Text c="dimmed">Proyecto no encontrado</Text>
      </Center>
    );
  }

  const progressPct =
    project.total_tasks > 0
      ? Math.round((project.done_tasks / project.total_tasks) * 100)
      : 0;

  return (
    <Stack gap="md">
      <Group>
        <Button
          variant="subtle"
          leftSection={<IconArrowLeft size={16} />}
          onClick={() => navigate('/projects')}
          size="compact-sm"
        >
          Proyectos
        </Button>
      </Group>

      <Group justify="space-between">
        <Title order={3}>{project.name}</Title>
        <Group gap="xs">
          <Button
            size="compact-sm"
            variant="light"
            leftSection={<IconEdit size={14} />}
            onClick={() => {
              setFocusDirectory(false);
              setEditOpen(true);
            }}
          >
            Editar
          </Button>
          <Button
            size="compact-sm"
            leftSection={<IconPlus size={14} />}
            onClick={() => setTaskFormOpen(true)}
          >
            Nueva tarea
          </Button>
          <Badge color="blue" variant="light">
            {project.open_tasks} abiertas
          </Badge>
          <Badge color="green" variant="light">
            {project.done_tasks} hechas
          </Badge>
        </Group>
      </Group>

      <Tabs value={activeTab} onChange={setActiveTab}>
        <Tabs.List>
          <Tabs.Tab value="overview">Resumen</Tabs.Tab>
          <Tabs.Tab value="tasks">Tareas</Tabs.Tab>
          <Tabs.Tab value="files">Archivos</Tabs.Tab>
          <Tabs.Tab value="uploads">Uploads</Tabs.Tab>
          <Tabs.Tab value="capabilities">Capabilities</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Card withBorder>
              <Text fw={500} mb="xs">
                Descripción
              </Text>
              <Text size="sm" c="dimmed">
                {project.description || 'Sin descripción'}
              </Text>
            </Card>
            <Card withBorder>
              <Text fw={500} mb="xs">
                Progreso
              </Text>
              <Progress
                value={progressPct}
                color="brand"
                size="lg"
                radius="md"
                mb="xs"
              />
              <Text size="sm" c="dimmed">
                {project.done_tasks} de {project.total_tasks} tareas completadas ({progressPct}%)
              </Text>
            </Card>
            <DeployCard
              project={project}
              onConfigure={() => {
                setFocusDirectory(true);
                setEditOpen(true);
              }}
            />
          </SimpleGrid>
        </Tabs.Panel>

        <Tabs.Panel value="tasks" pt="md">
          {!tasks?.length ? (
            <Text c="dimmed" size="sm" ta="center" py="md">
              Sin tareas para este proyecto
            </Text>
          ) : (
            <Stack gap={0}>
              {tasks.map((t) => (
                <TaskRow key={t.id} task={t} />
              ))}
            </Stack>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="files" pt="md">
          {slug && <FileTree slug={slug} />}
        </Tabs.Panel>

        <Tabs.Panel value="capabilities" pt="md">
          {slug && <CapabilitiesTab projectKey={slug} />}
        </Tabs.Panel>

        <Tabs.Panel value="uploads" pt="md">
          <Stack gap="md">
            <Dropzone
              onDrop={(files) => {
                for (const file of files) {
                  uploadFile.mutate(file);
                }
              }}
              loading={uploadFile.isPending}
              maxSize={50 * 1024 * 1024}
            >
              <Group
                justify="center"
                gap="xl"
                mih={100}
                style={{ pointerEvents: 'none' }}
              >
                <Dropzone.Accept>
                  <IconUpload size={32} color="var(--mantine-color-brand-5)" />
                </Dropzone.Accept>
                <Dropzone.Reject>
                  <IconX size={32} color="var(--mantine-color-red-5)" />
                </Dropzone.Reject>
                <Dropzone.Idle>
                  <IconUpload size={32} color="var(--mantine-color-dimmed)" />
                </Dropzone.Idle>
                <Text size="sm" c="dimmed">
                  Arrastra archivos aquí o haz clic para subir
                </Text>
              </Group>
            </Dropzone>

            {uploads?.files?.length ? (
              <Stack gap={4}>
                {uploads.files.map((f) => (
                  <Group key={f.name} gap="xs" py={4}>
                    <IconFile size={16} />
                    <Text size="sm">{f.name}</Text>
                    <Text size="xs" c="dimmed">
                      ({formatSize(f.size)})
                    </Text>
                  </Group>
                ))}
              </Stack>
            ) : (
              <Text c="dimmed" size="sm" ta="center">
                Sin archivos subidos
              </Text>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>

      <TaskForm
        opened={taskFormOpen}
        onClose={() => setTaskFormOpen(false)}
        initialProjectId={project.id}
      />
      <EditProjectModal
        opened={editOpen}
        onClose={() => setEditOpen(false)}
        project={project}
        focusDirectory={focusDirectory}
      />
    </Stack>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function EditProjectModal({
  opened,
  onClose,
  project,
  focusDirectory,
}: {
  opened: boolean;
  onClose: () => void;
  project: Project;
  focusDirectory: boolean;
}) {
  const updateProject = useUpdateProject();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || '');
  const [directory, setDirectory] = useState(project.directory || '');

  useEffect(() => {
    if (opened) {
      setName(project.name);
      setDescription(project.description || '');
      setDirectory(project.directory || '');
    }
  }, [opened, project]);

  async function handleSave() {
    try {
      await updateProject.mutateAsync({
        slug: project.slug,
        name,
        description,
        directory: directory.trim() || undefined,
      });
      notifications.show({
        title: 'Proyecto actualizado',
        message: name,
        color: 'green',
      });
      onClose();
    } catch (err) {
      notifications.show({
        title: 'Error al guardar',
        message: err instanceof Error ? err.message : 'Fallo desconocido',
        color: 'red',
      });
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title="Editar proyecto">
      <Stack gap="sm">
        <TextInput
          label="Nombre"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />
        <Textarea
          label="Descripción"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          minRows={3}
        />
        <TextInput
          label="Directorio"
          value={directory}
          onChange={(e) => setDirectory(e.currentTarget.value)}
          placeholder="/home/niwa/projects/<slug>"
          description="Ruta absoluta donde Claude y el executor trabajarán sobre el proyecto. Déjalo vacío para autogenerar."
          autoFocus={focusDirectory}
        />
        <Group justify="flex-end" mt="sm">
          <Button variant="subtle" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            onClick={handleSave}
            loading={updateProject.isPending}
            disabled={!name.trim()}
          >
            Guardar
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DeployCard({
  project,
  onConfigure,
}: {
  project: Project;
  onConfigure: () => void;
}) {
  const deployments = useDeployments();
  const deploy = useDeployProject();
  const undeploy = useUndeployProject();
  const deployment: Deployment | undefined = deployments.data?.deployments.find(
    (d) => d.project_id === project.id,
  );

  const hasDirectory = Boolean(project.directory);
  const isActive = deployment?.status === 'active';

  async function handleDeploy() {
    try {
      const result = await deploy.mutateAsync(project.slug);
      notifications.show({
        title: 'Proyecto desplegado',
        message: result.url,
        color: 'green',
      });
    } catch (err) {
      notifications.show({
        title: 'Error al desplegar',
        message: err instanceof Error ? err.message : 'Falló el deploy',
        color: 'red',
      });
    }
  }

  async function handleUndeploy() {
    try {
      await undeploy.mutateAsync(project.slug);
      notifications.show({
        title: 'Proyecto despublicado',
        message: project.name,
        color: 'yellow',
      });
    } catch (err) {
      notifications.show({
        title: 'Error al despublicar',
        message: err instanceof Error ? err.message : 'Falló el undeploy',
        color: 'red',
      });
    }
  }

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={500}>Hosting</Text>
        {isActive && (
          <Badge color="green" variant="light">
            activo
          </Badge>
        )}
      </Group>
      {!hasDirectory ? (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            Este proyecto no tiene directorio asignado. Asigna uno para
            poder desplegar.
          </Text>
          <Button
            variant="light"
            size="compact-sm"
            leftSection={<IconEdit size={14} />}
            onClick={onConfigure}
          >
            Configurar directorio
          </Button>
        </Stack>
      ) : isActive && deployment?.url ? (
        <Stack gap="xs">
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              URL pública:
            </Text>
            <Text
              component="a"
              href={deployment.url}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              c="brand"
              style={{ wordBreak: 'break-all' }}
            >
              {deployment.url} <IconExternalLink size={12} />
            </Text>
          </Group>
          <Button
            variant="light"
            color="red"
            size="compact-sm"
            loading={undeploy.isPending}
            onClick={handleUndeploy}
          >
            Despublicar
          </Button>
        </Stack>
      ) : (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            Publica los archivos de este proyecto como sitio estático.
          </Text>
          <Button
            leftSection={<IconCloudUpload size={16} />}
            size="compact-sm"
            loading={deploy.isPending}
            onClick={handleDeploy}
          >
            Deploy
          </Button>
        </Stack>
      )}
    </Card>
  );
}
