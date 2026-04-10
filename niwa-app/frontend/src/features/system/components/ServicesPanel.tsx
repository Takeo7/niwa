import {
  Stack,
  Group,
  Text,
  Badge,
  Loader,
  Center,
  Title,
  Divider,
} from '@mantine/core';
import { useServices } from '../hooks/useServices';
import { ServiceCard } from './ServiceCard';

const CATEGORY_LABELS: Record<string, string> = {
  llm: 'Proveedores LLM',
  image: 'Generación de Imágenes',
  search: 'Búsqueda',
  notifications: 'Notificaciones',
  storage: 'Almacenamiento',
  tools: 'Herramientas',
};

export function ServicesPanel() {
  const { data: services, isLoading } = useServices();

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (!services?.length) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        No hay servicios configurados
      </Text>
    );
  }

  const configured = services.filter(
    (s) => s.status?.status === 'configured',
  ).length;
  const notConfigured = services.filter(
    (s) => s.status?.status === 'not_configured',
  ).length;
  const errors = services.filter(
    (s) => s.status?.status === 'error',
  ).length;

  // Group by category
  const grouped = services.reduce<Record<string, typeof services>>(
    (acc, svc) => {
      const cat = svc.category || 'other';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(svc);
      return acc;
    },
    {},
  );

  return (
    <Stack gap="md">
      {/* Dashboard header */}
      <Group gap="md">
        <Badge size="lg" color="green" variant="light">
          {configured} configurados
        </Badge>
        <Badge size="lg" color="gray" variant="light">
          {notConfigured} sin configurar
        </Badge>
        {errors > 0 && (
          <Badge size="lg" color="red" variant="light">
            {errors} con errores
          </Badge>
        )}
      </Group>

      {/* Categories */}
      {Object.entries(grouped).map(([category, svcs]) => (
        <Stack key={category} gap="sm">
          <Divider />
          <Title order={5}>
            {CATEGORY_LABELS[category] || category}
          </Title>
          {svcs.map((svc) => (
            <ServiceCard key={svc.id} service={svc} />
          ))}
        </Stack>
      ))}
    </Stack>
  );
}
