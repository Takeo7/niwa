import { Title, Tabs, Stack } from '@mantine/core';
import {
  IconPlugConnected,
  IconRobot,
  IconSettings,
} from '@tabler/icons-react';
import { ServicesPanel } from './ServicesPanel';
import { AgentsPanel } from './AgentsPanel';
import { ConfigPanel } from './ConfigPanel';

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
            Configuración
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
      </Tabs>
    </Stack>
  );
}
