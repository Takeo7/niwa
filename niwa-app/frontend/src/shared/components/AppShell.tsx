import { type ReactNode } from 'react';
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
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import {
  IconMessageCircle,
  IconChecklist,
  IconLayoutKanban,
  IconFolders,
  IconSettings,
  IconChartBar,
  IconNotebook,
  IconLogout,
  IconUser,
} from '@tabler/icons-react';
import { useVersion } from '../api/queries';

interface Props {
  children: ReactNode;
}

const NAV_ITEMS = [
  { label: 'Chat', icon: IconMessageCircle, path: '/' },
  { label: 'Tareas', icon: IconChecklist, path: '/tasks' },
  { label: 'Kanban', icon: IconLayoutKanban, path: '/kanban' },
  { label: 'Proyectos', icon: IconFolders, path: '/projects' },
  { label: 'Sistema', icon: IconSettings, path: '/system' },
  { label: 'Métricas', icon: IconChartBar, path: '/metrics' },
  { label: 'Notas', icon: IconNotebook, path: '/notes' },
];

export function AppShell({ children }: Props) {
  const [opened, { toggle, close }] = useDisclosure(true);
  const isMobile = useMediaQuery('(max-width: 768px)');
  const navigate = useNavigate();
  const location = useLocation();
  const { data: versionData } = useVersion();

  const handleNav = (path: string) => {
    navigate(path);
    if (isMobile) close();
  };

  const handleLogout = () => {
    window.location.href = '/logout';
  };

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <MantineAppShell
      header={{ height: 50 }}
      navbar={{
        width: 220,
        breakpoint: 'sm',
        collapsed: { mobile: !opened, desktop: !opened },
      }}
      padding="md"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger
              opened={opened}
              onClick={toggle}
              size="sm"
            />
            <Title order={4} fw={800} style={{ letterSpacing: '-0.04em' }}>
              Niwa
            </Title>
          </Group>
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
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="xs">
        <MantineAppShell.Section grow component={ScrollArea}>
          <Stack gap={2}>
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.path}
                label={item.label}
                leftSection={<item.icon size={20} />}
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
          <Text size="xs" c="dimmed" ta="center">
            Niwa {versionData?.version || ''}
          </Text>
        </MantineAppShell.Section>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>{children}</MantineAppShell.Main>
    </MantineAppShell>
  );
}
