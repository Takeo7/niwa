import { Stack, Tabs, Text, Title } from '@mantine/core';
import { IconServer } from '@tabler/icons-react';
import { BackendsPanel } from './BackendsPanel';

/** /settings — panel de ajustes del sistema.
 *
 *  PR-10d sólo expone la pestaña "Backends" (perfiles de ejecución).
 *  Queda como marco para que PR-11 (installer) meta más paneles
 *  (assistant, policies globales, etc.) sin reestructurar la
 *  navegación. Por ahora se muestra una sola Tab por coherencia
 *  visual con el resto de vistas con sub-navegación.
 */
export function SettingsPage() {
  return (
    <Stack gap="md">
      <div>
        <Title order={3}>Ajustes</Title>
        <Text size="xs" c="dimmed">
          Configuración del sistema de ejecución v0.2. Los cambios
          aquí afectan a nuevos runs — los runs en curso conservan
          el snapshot del perfil con el que arrancaron.
        </Text>
      </div>

      <Tabs defaultValue="backends">
        <Tabs.List>
          <Tabs.Tab value="backends" leftSection={<IconServer size={16} />}>
            Backends
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="backends" pt="md">
          <BackendsPanel />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
