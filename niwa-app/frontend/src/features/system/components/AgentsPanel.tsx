import { useState, useEffect } from 'react';
import {
  Stack,
  Card,
  Text,
  Select,
  NumberInput,
  Button,
  Group,
  Loader,
  Center,
  Badge,
  Divider,
} from '@mantine/core';
import { IconReload } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import {
  useAgentsConfig,
  useSaveAgentsConfig,
  useModels,
  useRestartExecutor,
} from '../hooks/useAgents';
import type { AgentConfig } from '../../../shared/types';

const AGENT_LABELS: Record<string, { title: string; description: string; color: string }> = {
  chat: {
    title: 'Agente Chat',
    description: 'Responde en el chat. Rápido y conversacional.',
    color: 'blue',
  },
  planner: {
    title: 'Agente Planner',
    description: 'Analiza tareas complejas y las divide en subtareas.',
    color: 'grape',
  },
  executor: {
    title: 'Agente Executor',
    description: 'Implementa código y ejecuta las tareas reales.',
    color: 'orange',
  },
};

function AgentCard({
  role,
  config,
  models,
  onChange,
}: {
  role: string;
  config: AgentConfig;
  models: Array<{ value: string; label: string }>;
  onChange: (config: AgentConfig) => void;
}) {
  const info = AGENT_LABELS[role] || {
    title: role,
    description: '',
    color: 'gray',
  };

  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="sm">
        <Group gap="xs">
          <Badge color={info.color} variant="light">
            {info.title}
          </Badge>
        </Group>
      </Group>
      <Text size="sm" c="dimmed" mb="md">
        {info.description}
      </Text>
      <Stack gap="sm">
        <Select
          label="Modelo"
          data={models}
          value={config.model}
          onChange={(v) => onChange({ ...config, model: v || config.model })}
          searchable
        />
        <NumberInput
          label="Máximo de turnos"
          value={config.max_turns}
          onChange={(v) =>
            onChange({ ...config, max_turns: typeof v === 'number' ? v : 10 })
          }
          min={1}
          max={200}
        />
      </Stack>
    </Card>
  );
}

export function AgentsPanel() {
  const { data: agentsConfig, isLoading: agentsLoading } = useAgentsConfig();
  const { data: models, isLoading: modelsLoading } = useModels();
  const saveAgents = useSaveAgentsConfig();
  const restartExecutor = useRestartExecutor();
  const [localConfig, setLocalConfig] = useState<Record<string, AgentConfig>>({});

  useEffect(() => {
    if (agentsConfig) {
      setLocalConfig({ ...agentsConfig });
    }
  }, [agentsConfig]);

  if (agentsLoading || modelsLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const modelOptions = (models || []).map((m) => ({
    value: m.id,
    label: `${m.name} (${m.provider})`,
  }));

  const handleSave = async () => {
    try {
      await saveAgents.mutateAsync(localConfig);
      notifications.show({
        title: 'Guardado',
        message: 'Configuración de agentes guardada',
        color: 'green',
      });
    } catch (e) {
      notifications.show({
        title: 'Error',
        message: e instanceof Error ? e.message : 'Error guardando',
        color: 'red',
      });
    }
  };

  const handleRestart = async () => {
    try {
      const result = await restartExecutor.mutateAsync();
      notifications.show({
        title: 'Executor',
        message: result.message || 'Recarga solicitada',
        color: 'green',
      });
    } catch (e) {
      notifications.show({
        title: 'Error',
        message: e instanceof Error ? e.message : 'Error',
        color: 'red',
      });
    }
  };

  return (
    <Stack gap="md">
      {(['chat', 'planner', 'executor'] as const).map((role) => (
        <AgentCard
          key={role}
          role={role}
          config={
            localConfig[role] || { model: '', max_turns: 10, description: '' }
          }
          models={modelOptions}
          onChange={(c) =>
            setLocalConfig((prev) => ({ ...prev, [role]: c }))
          }
        />
      ))}

      <Divider />

      <Group gap="xs">
        <Button onClick={handleSave} loading={saveAgents.isPending}>
          Guardar configuración
        </Button>
        <Button
          variant="light"
          leftSection={<IconReload size={16} />}
          onClick={handleRestart}
          loading={restartExecutor.isPending}
        >
          Recargar executor
        </Button>
      </Group>
    </Stack>
  );
}
