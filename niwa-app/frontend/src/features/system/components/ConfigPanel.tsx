import { useState, useEffect } from 'react';
import {
  Stack,
  Card,
  Text,
  Select,
  NumberInput,
  Switch,
  Button,
  Loader,
  Center,
  Group,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useSettings, useSaveSettings } from '../../../shared/api/queries';

export function ConfigPanel() {
  const { data: settings, isLoading } = useSettings();
  const saveSettings = useSaveSettings();

  const [executorEnabled, setExecutorEnabled] = useState(true);
  const [pollInterval, setPollInterval] = useState(30);
  const [executorTimeout, setExecutorTimeout] = useState(300);
  const [language, setLanguage] = useState('es');
  const [idleReview, setIdleReview] = useState(false);

  useEffect(() => {
    if (settings) {
      setExecutorEnabled(settings['executor.enabled'] !== '0');
      setPollInterval(parseInt(settings['executor.poll_interval'] || '30', 10));
      setExecutorTimeout(parseInt(settings['executor.timeout'] || '300', 10));
      setLanguage(settings['app.language'] || 'es');
      setIdleReview(settings['executor.idle_review'] === '1');
    }
  }, [settings]);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const handleSave = async () => {
    try {
      await saveSettings.mutateAsync({
        'executor.enabled': executorEnabled ? '1' : '0',
        'executor.poll_interval': String(pollInterval),
        'executor.timeout': String(executorTimeout),
        'app.language': language,
        'executor.idle_review': idleReview ? '1' : '0',
      });
      notifications.show({
        title: 'Guardado',
        message: 'Configuración guardada',
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

  return (
    <Stack gap="md">
      <Card withBorder radius="md">
        <Text fw={500} mb="md">
          Executor
        </Text>
        <Stack gap="sm">
          <Switch
            label="Executor habilitado"
            description="Ejecuta tareas automáticamente"
            checked={executorEnabled}
            onChange={(e) => setExecutorEnabled(e.currentTarget.checked)}
          />
          <NumberInput
            label="Intervalo de polling (segundos)"
            description="Cada cuántos segundos el executor busca tareas nuevas"
            value={pollInterval}
            onChange={(v) =>
              setPollInterval(typeof v === 'number' ? v : 30)
            }
            min={5}
            max={600}
          />
          <NumberInput
            label="Timeout (segundos)"
            description="Tiempo máximo de ejecución por tarea"
            value={executorTimeout}
            onChange={(v) =>
              setExecutorTimeout(typeof v === 'number' ? v : 300)
            }
            min={30}
            max={3600}
          />
          <Switch
            label="Revisión en idle"
            description="El executor revisa tareas completadas cuando no tiene trabajo"
            checked={idleReview}
            onChange={(e) => setIdleReview(e.currentTarget.checked)}
          />
        </Stack>
      </Card>

      <Card withBorder radius="md">
        <Text fw={500} mb="md">
          Aplicación
        </Text>
        <Stack gap="sm">
          <Select
            label="Idioma"
            data={[
              { value: 'es', label: 'Español' },
              { value: 'en', label: 'English' },
            ]}
            value={language}
            onChange={(v) => setLanguage(v || 'es')}
          />
        </Stack>
      </Card>

      <Group>
        <Button onClick={handleSave} loading={saveSettings.isPending}>
          Guardar configuración
        </Button>
      </Group>
    </Stack>
  );
}
