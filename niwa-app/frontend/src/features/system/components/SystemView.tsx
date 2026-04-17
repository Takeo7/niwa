import { Title, Tabs, Stack } from '@mantine/core';
import {
  IconPlugConnected,
  IconRobot,
  IconSettings,
  IconClock,
  IconFileText,
  IconPalette,
  IconCloudUpload,
} from '@tabler/icons-react';
import { ServicesPanel } from './ServicesPanel';
import { AgentsPanel } from './AgentsPanel';
import { ConfigPanel } from './ConfigPanel';
import { RoutinesPanel } from './RoutinesPanel';
import { LogsPanel } from './LogsPanel';
import { StylesPanel } from './StylesPanel';
import { DeploymentsPanel } from './DeploymentsPanel';

export function SystemView() {
  return (
    <Stack gap="md">
      <Title order={3}>Sistema</Title>

      <Tabs defaultValue="services">
        <Tabs.List>
          <Tabs.Tab
            value="services"
            leftSection={<IconPlugConnected size={16} />}
          >
            Servicios
          </Tabs.Tab>
          <Tabs.Tab value="agents" leftSection={<IconRobot size={16} />}>
            Agentes
          </Tabs.Tab>
          <Tabs.Tab
            value="config"
            leftSection={<IconSettings size={16} />}
          >
            Config
          </Tabs.Tab>
          <Tabs.Tab
            value="routines"
            leftSection={<IconClock size={16} />}
          >
            Rutinas
          </Tabs.Tab>
          <Tabs.Tab
            value="logs"
            leftSection={<IconFileText size={16} />}
          >
            Logs
          </Tabs.Tab>
          <Tabs.Tab
            value="styles"
            leftSection={<IconPalette size={16} />}
          >
            Estilos
          </Tabs.Tab>
          <Tabs.Tab
            value="hosting"
            leftSection={<IconCloudUpload size={16} />}
          >
            Hosting
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="services" pt="md">
          <ServicesPanel />
        </Tabs.Panel>
        <Tabs.Panel value="agents" pt="md">
          <AgentsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="config" pt="md">
          <ConfigPanel />
        </Tabs.Panel>
        <Tabs.Panel value="routines" pt="md">
          <RoutinesPanel />
        </Tabs.Panel>
        <Tabs.Panel value="logs" pt="md">
          <LogsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="styles" pt="md">
          <StylesPanel />
        </Tabs.Panel>
        <Tabs.Panel value="hosting" pt="md">
          <DeploymentsPanel />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
