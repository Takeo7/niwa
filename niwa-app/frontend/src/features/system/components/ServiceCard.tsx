import { useState, useEffect } from 'react';
import {
  Card,
  Stack,
  Group,
  Text,
  Badge,
  Button,
  TextInput,
  PasswordInput,
  Select,
  Collapse,
  Stepper,
  Alert,
  UnstyledButton,
  Box,
} from '@mantine/core';
import {
  IconChevronDown,
  IconChevronUp,
  IconCheck,
  IconAlertCircle,
  IconLoader,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useSaveService, useTestService } from '../hooks/useServices';
import { OAuthSection } from './OAuthSection';
import type { Service, ServiceField } from '../../../shared/types';

interface Props {
  service: Service;
}

const STATUS_BADGE: Record<
  string,
  { color: string; label: string }
> = {
  configured: { color: 'green', label: 'Configurado' },
  not_configured: { color: 'gray', label: 'Sin configurar' },
  error: { color: 'red', label: 'Error' },
  warning: { color: 'yellow', label: 'Aviso' },
};

export function ServiceCard({ service }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message?: string;
  } | null>(null);

  const saveService = useSaveService();
  const testService = useTestService();

  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const field of service.fields) {
      initial[field.key] = service.values[field.key] || field.default || '';
    }
    setValues(initial);
  }, [service]);

  const isFieldVisible = (field: ServiceField): boolean => {
    if (!field.show_when) return true;
    const currentVal = values[field.show_when.field];
    if (Array.isArray(field.show_when.value)) {
      return field.show_when.value.includes(currentVal);
    }
    return currentVal === field.show_when.value;
  };

  const getFieldOptions = (field: ServiceField) => {
    if (field.options) return field.options;
    if (field.options_by_provider) {
      const providerField = service.fields.find(
        (f) => f.key.endsWith('.provider') || f.key.includes('.provider'),
      );
      if (providerField) {
        const provider = values[providerField.key];
        return field.options_by_provider[provider] || [];
      }
    }
    return [];
  };

  const handleSave = async () => {
    // Only send visible fields' values
    const toSave: Record<string, string> = {};
    for (const field of service.fields) {
      if (isFieldVisible(field)) {
        const val = values[field.key];
        // Don't send masked values for sensitive fields
        if (field.sensitive && val && val.includes('•')) {
          continue;
        }
        toSave[field.key] = val;
      }
    }
    try {
      await saveService.mutateAsync({ id: service.id, values: toSave });
      notifications.show({
        title: 'Guardado',
        message: `Configuración de ${service.name} guardada`,
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

  const handleTest = async () => {
    setTestResult(null);
    try {
      const result = await testService.mutateAsync(service.id);
      setTestResult({ ok: result.ok, message: result.message || result.error });
    } catch (e) {
      setTestResult({
        ok: false,
        message: e instanceof Error ? e.message : 'Error',
      });
    }
  };

  const badgeInfo = STATUS_BADGE[service.status?.status] || STATUS_BADGE.not_configured;

  return (
    <Card withBorder radius="md">
      <UnstyledButton
        onClick={() => setExpanded(!expanded)}
        w="100%"
      >
        <Group justify="space-between">
          <Group gap="sm">
            <Text size="xl">{service.icon}</Text>
            <Box>
              <Text fw={600} size="sm">
                {service.name}
              </Text>
              <Text size="xs" c="dimmed" lineClamp={1}>
                {service.description}
              </Text>
            </Box>
          </Group>
          <Group gap="xs">
            <Badge
              color={badgeInfo.color}
              variant="light"
              size="sm"
            >
              {badgeInfo.label}
            </Badge>
            {expanded ? (
              <IconChevronUp size={16} />
            ) : (
              <IconChevronDown size={16} />
            )}
          </Group>
        </Group>
      </UnstyledButton>

      <Collapse in={expanded}>
        <Stack gap="sm" mt="md">
          {/* Dynamic fields */}
          {service.fields.map((field) =>
            isFieldVisible(field) ? (
              <FieldRenderer
                key={field.key}
                field={field}
                value={values[field.key] || ''}
                onChange={(v) =>
                  setValues((prev) => ({ ...prev, [field.key]: v }))
                }
                options={getFieldOptions(field)}
              />
            ) : null,
          )}

          {/* OAuth section */}
          {service.oauth_provider && (
            <OAuthSection provider={service.oauth_provider} />
          )}

          {/* Setup guide */}
          {service.setup_guide && service.setup_guide.length > 0 && (
            <Stepper active={-1} size="xs" orientation="vertical">
              {service.setup_guide.map((step, i) => (
                <Stepper.Step
                  key={i}
                  label={step}
                />
              ))}
            </Stepper>
          )}

          {/* Test result */}
          {testResult && (
            <Alert
              color={testResult.ok ? 'green' : 'red'}
              icon={
                testResult.ok ? (
                  <IconCheck size={16} />
                ) : (
                  <IconAlertCircle size={16} />
                )
              }
              variant="light"
            >
              {testResult.message || (testResult.ok ? 'Conexión exitosa' : 'Error de conexión')}
            </Alert>
          )}

          <Group gap="xs">
            <Button
              size="xs"
              onClick={handleSave}
              loading={saveService.isPending}
            >
              Guardar
            </Button>
            {service.test_action && (
              <Button
                size="xs"
                variant="light"
                onClick={handleTest}
                loading={testService.isPending}
                leftSection={
                  testService.isPending ? (
                    <IconLoader size={14} />
                  ) : undefined
                }
              >
                Probar
              </Button>
            )}
          </Group>
        </Stack>
      </Collapse>
    </Card>
  );
}

function FieldRenderer({
  field,
  value,
  onChange,
  options,
}: {
  field: ServiceField;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  switch (field.type) {
    case 'select':
      return (
        <Select
          label={field.label}
          description={field.help}
          data={options.length > 0 ? options : field.options || []}
          value={value}
          onChange={(v) => onChange(v || '')}
        />
      );
    case 'password':
      return (
        <PasswordInput
          label={field.label}
          description={field.help}
          value={value}
          onChange={(e) => onChange(e.currentTarget.value)}
          placeholder={field.sensitive ? '••••••••' : undefined}
        />
      );
    case 'url':
      return (
        <TextInput
          label={field.label}
          description={field.help}
          value={value}
          onChange={(e) => onChange(e.currentTarget.value)}
          placeholder="https://..."
          type="url"
        />
      );
    case 'number':
      return (
        <TextInput
          label={field.label}
          description={field.help}
          value={value}
          onChange={(e) => onChange(e.currentTarget.value)}
          placeholder={field.placeholder}
          type="number"
        />
      );
    default:
      return (
        <TextInput
          label={field.label}
          description={field.help}
          value={value}
          onChange={(e) => onChange(e.currentTarget.value)}
          placeholder={field.placeholder}
        />
      );
  }
}
