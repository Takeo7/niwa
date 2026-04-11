import { type ReactNode, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  AppShell as MantineAppShell,
  NavLink,
  Group,
  Title,
  Text,
  ActionIcon,
  Burger,
  ScrollArea,
  Divider,
  Menu,
  Stack,
  Box,
  Kbd,
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { useMantineColorScheme } from '@mantine/core';
import { spotlight } from '@mantine/spotlight';
import {
  IconDashboard,
  IconMessageCircle,
  IconChecklist,
  IconLayoutKanban,
  IconFolders,
  IconSettings,
  IconNotebook,
  IconLogout,
  IconUser,
  IconHistory,
  IconChartBar,
  IconSun,
  IconMoon,
  IconSearch,
  IconPlus,
  IconRefresh,
} from '@tabler/icons-react';
import { useVersion, useSystemUpdate } from '../api/queries';
import { usePolling } from '../hooks/usePolling';
import { SearchOverlay } from './SearchOverlay';
import { TaskForm } from '../../features/tasks/components/TaskForm';
import { notifications } from '@mantine/notifications';

interface Props {
  children: ReactNode;
}

const NAV_ITEMS = [
  { label: 'Panel', icon: IconDashboard, path: '/dashboard', shortcut: 'D' },
  { label: 'Chat', icon: IconMessageCircle, path: '/chat', shortcut: 'C' },
  { label: 'Tareas', icon: IconChecklist, path: '/tasks', shortcut: 'T' },
  { label: 'Kanban', icon: IconLayoutKanban, path: '/kanban', shortcut: 'K' },
  { label: 'Proyectos', icon: IconFolders, path: '/projects', shortcut: 'P' },
  { label: 'Notas', icon: IconNotebook, path: '/notes', shortcut: 'N' },
  { label: 'Historial', icon: IconHistory, path: '/history', shortcut: 'Y' },
  { label: 'Métricas', icon: IconChartBar, path: '/metrics', shortcut: 'M' },
  { label: 'Sistema', icon: IconSettings, path: '/system', shortcut: 'S' },
];

export function AppShell({ children }: Props) {
  const [opened, { toggle, close }] = useDisclosure(true);
  const isMobile = useMediaQuery('(max-width: 768px)');
  const navigate = useNavigate();
  const location = useLocation();
  const { data: versionData } = useVersion();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const { disconnected } = usePolling();
  const systemUpdate = useSystemUpdate();
  const [taskFormOpen, setTaskFormOpen] = useState(false);

  const handleNav = (path: string) => {
    navigate(path);
    if (isMobile) close();
  };

  const handleLogout = () => {
    window.location.href = '/logout';
  };

  const handleUpdate = async () => {
    try {
      const result = await systemUpdate.mutateAsync();
      if (result.ok) {
        const msg = result.needs_restart
          ? `${result.message}\nRecarga la página para ver los cambios.`
          : result.message;
        notifications.show({
          title: 'Actualización exitosa',
          message: msg,
          color: 'green',
          autoClose: 8000,
        });
      } else if (result.manual_steps) {
        notifications.show({
          title: 'Actualización manual requerida',
          message: `${result.message}\n${result.manual_steps.join('\n')}`,
          color: 'yellow',
          autoClose: false,
        });
      } else {
        notifications.show({
          title: 'Error al actualizar',
          message: result.message || 'Error desconocido',
          color: 'red',
        });
      }
    } catch {
      notifications.show({ title: 'Error', message: 'No se pudo conectar con el servidor', color: 'red' });
    }
  };

  const isActive = (path: string) => {
    if (path === '/dashboard') return location.pathname === '/dashboard' || location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  const isDark = colorScheme === 'dark';

  return (
    <>
      <SearchOverlay />
      <MantineAppShell
        header={{ height: disconnected ? 80 : 50 }}
        navbar={{
          width: 220,
          breakpoint: 'sm',
          collapsed: { mobile: !opened, desktop: !opened },
        }}
        padding="md"
      >
        <MantineAppShell.Header>
          {disconnected && (
            <Box
              py={4}
              px="md"
              style={{
                backgroundColor: 'var(--mantine-color-red-9)',
                color: '#fff',
                textAlign: 'center',
                fontSize: 13,
              }}
            >
              Sin conexión con el servidor. Reintentando...
            </Box>
          )}
          <Group h={50} px="md" justify="space-between">
            <Group gap="sm">
              <Burger opened={opened} onClick={toggle} size="sm" />
              <Title order={4} fw={800} style={{ letterSpacing: '-0.04em' }}>
                Niwa
              </Title>
            </Group>
            <Group gap="xs">
              <ActionIcon
                variant="subtle"
                size="lg"
                onClick={() => spotlight.open()}
                title="Buscar (/) "
              >
                <IconSearch size={20} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                size="lg"
                onClick={() => toggleColorScheme()}
                title={isDark ? 'Modo claro' : 'Modo oscuro'}
              >
                {isDark ? <IconSun size={20} /> : <IconMoon size={20} />}
              </ActionIcon>
              <Menu shadow="md" width={200}>
                <Menu.Target>
                  <ActionIcon variant="subtle" size="lg">
                    <IconUser size={20} />
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item
                    leftSection={<IconLogout size={16} />}
                    onClick={handleLogout}
                    color="red"
                  >
                    Cerrar sesión
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>
        </MantineAppShell.Header>

        <MantineAppShell.Navbar p="xs">
          <MantineAppShell.Section grow component={ScrollArea}>
            <Stack gap={2}>
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.path}
                  label={item.label}
                  leftSection={<item.icon size={20} />}
                  rightSection={
                    <Kbd size="xs" style={{ opacity: 0.5 }}>
                      {item.shortcut}
                    </Kbd>
                  }
                  active={isActive(item.path)}
                  onClick={() => handleNav(item.path)}
                  variant="light"
                  styles={{
                    root: { borderRadius: 'var(--mantine-radius-md)' },
                  }}
                />
              ))}
            </Stack>
          </MantineAppShell.Section>
          <MantineAppShell.Section>
            <Divider my="xs" />
            <Stack gap={4}>
              <NavLink
                label="Nueva tarea"
                leftSection={<IconPlus size={18} />}
                onClick={() => setTaskFormOpen(true)}
                variant="filled"
                color="brand"
                styles={{
                  root: { borderRadius: 'var(--mantine-radius-md)' },
                }}
              />
              <NavLink
                label="Actualizar Niwa"
                leftSection={<IconRefresh size={18} />}
                onClick={handleUpdate}
                variant="subtle"
                styles={{
                  root: { borderRadius: 'var(--mantine-radius-md)' },
                }}
              />
              <Text size="xs" c="dimmed" ta="center" mt={4}>
                Niwa {versionData?.version || ''}
              </Text>
            </Stack>
          </MantineAppShell.Section>
        </MantineAppShell.Navbar>

        <MantineAppShell.Main>{children}</MantineAppShell.Main>
      </MantineAppShell>

      <TaskForm
        opened={taskFormOpen}
        onClose={() => setTaskFormOpen(false)}
      />
    </>
  );
}
