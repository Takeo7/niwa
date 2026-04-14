import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Collapse,
  Divider,
  Group,
  Stack,
  Text,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconChevronDown, IconChevronRight, IconPencil } from '@tabler/icons-react';
import { JsonBlock } from '../../../shared/components/JsonBlock';
import type { BackendProfile } from '../../../shared/types';

interface Props {
  profile: BackendProfile;
  onEdit: () => void;
}

/** Fila de perfil de backend — muestra campos clave y expande para
 *  revelar los JSON read-only (capabilities, command_template).
 */
export function BackendProfileRow({ profile, onEdit }: Props) {
  const [opened, { toggle }] = useDisclosure(false);
  const isEnabled = !!profile.enabled;

  return (
    <Card withBorder padding="md" radius="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="wrap">
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={toggle}
              aria-label={opened ? 'Colapsar' : 'Expandir'}
            >
              {opened ? (
                <IconChevronDown size={14} />
              ) : (
                <IconChevronRight size={14} />
              )}
            </ActionIcon>
            <Text fw={600} size="sm">
              {profile.display_name}
            </Text>
            <Text
              size="xs"
              c="dimmed"
              style={{ fontFamily: 'var(--mantine-font-family-monospace)' }}
            >
              {profile.slug}
            </Text>
            <Badge
              size="xs"
              variant={isEnabled ? 'filled' : 'outline'}
              color={isEnabled ? 'green' : 'gray'}
            >
              {isEnabled ? 'habilitado' : 'deshabilitado'}
            </Badge>
          </Group>

          <Group gap="md" wrap="wrap">
            <MetaCell label="backend_kind" value={profile.backend_kind} />
            <MetaCell label="runtime_kind" value={profile.runtime_kind} />
            <MetaCell label="priority" value={String(profile.priority)} mono />
            <MetaCell
              label="default_model"
              value={profile.default_model ?? '—'}
              mono
            />
          </Group>
        </Stack>

        <Button
          leftSection={<IconPencil size={14} />}
          variant="light"
          size="compact-sm"
          onClick={onEdit}
        >
          Editar
        </Button>
      </Group>

      <Collapse in={opened}>
        <Divider my="sm" />
        <Stack gap="sm">
          <div>
            <Text size="xs" c="dimmed" mb={4}>
              capabilities_json (read-only en v0.2)
            </Text>
            <JsonBlock value={profile.capabilities_json} maxHeight={280} />
          </div>
          <div>
            <Text size="xs" c="dimmed" mb={4}>
              command_template (read-only en v0.2)
            </Text>
            {profile.command_template ? (
              <Text
                size="xs"
                style={{
                  fontFamily: 'var(--mantine-font-family-monospace)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  padding: 8,
                  background: 'var(--mantine-color-default-hover)',
                  borderRadius: 6,
                }}
              >
                {profile.command_template}
              </Text>
            ) : (
              <Text size="xs" c="dimmed">
                El adapter construye el comando en tiempo de ejecución.
              </Text>
            )}
          </div>
        </Stack>
      </Collapse>
    </Card>
  );
}

function MetaCell({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text
        size="xs"
        style={{
          fontFamily: mono
            ? 'var(--mantine-font-family-monospace)'
            : undefined,
          fontVariantNumeric: mono ? 'tabular-nums' : undefined,
        }}
      >
        {value}
      </Text>
    </Stack>
  );
}
