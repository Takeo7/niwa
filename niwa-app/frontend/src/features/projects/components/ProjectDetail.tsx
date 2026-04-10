import { useState } from 'react';
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
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import {
  IconArrowLeft,
  IconUpload,
  IconFile,
  IconX,
} from '@tabler/icons-react';
import {
  useProject,
  useProjectUploads,
  useUploadFile,
} from '../hooks/useProjects';
import { useTasks } from '../../../shared/api/queries';
import { FileTree } from './FileTree';
import type { Task } from '../../../shared/types';

function TaskRow({ task }: { task: Task }) {
  const statusColor: Record<string, string> = {
    pendiente: 'yellow',
    en_progreso: 'blue',
    bloqueada: 'red',
    revision: 'grape',
    hecha: 'green',
  };
  return (
    <Group justify="space-between" py={4}>
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
    </Stack>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
