import {
  Badge,
  Divider,
  Drawer,
  Group,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { JsonBlock } from '../../../shared/components/JsonBlock';
import { MonoId } from '../../../shared/components/MonoId';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import type { BackendRunEvent } from '../../../shared/types';

interface Props {
  event: BackendRunEvent | null;
  onClose: () => void;
}

// Matches the Timeline dot palette so the drawer keeps visual
// continuity with the row the operator clicked on.
const KIND_BADGE_COLOR: Record<string, string> = {
  system_init: 'gray',
  assistant_message: 'blue',
  tool_use: 'violet',
  tool_result: 'violet',
  result: 'teal',
  error: 'red',
  fallback_escalation: 'orange',
  raw_output: 'gray',
};

/** Side-panel detail view for a single ``backend_run_event``.
 *
 *  Opens when the operator clicks a row in ``Timeline`` and shows the
 *  full ``payload_json`` pretty-printed in a monospace code block.
 *  Mantine's ``Drawer`` was chosen over ``Modal`` per the prompt:
 *  the intent is "deepen without leaving the timeline".  The drawer
 *  overlays a column on the right without obscuring the timeline
 *  rail, which matters when cross-referencing adjacent events. */
export function EventDetailDrawer({ event, onClose }: Props) {
  return (
    <Drawer
      opened={event !== null}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        event ? (
          <Group gap="xs" wrap="nowrap">
            <Badge
              variant="light"
              color={KIND_BADGE_COLOR[event.event_type] ?? 'gray'}
              radius="sm"
            >
              {event.event_type}
            </Badge>
            <Title order={5} style={{ margin: 0 }}>
              Detalle de evento
            </Title>
          </Group>
        ) : null
      }
      padding="md"
      keepMounted={false}
      overlayProps={{ backgroundOpacity: 0.2, blur: 1 }}
    >
      {event && (
        <Stack gap="sm">
          <Group gap="md" wrap="wrap">
            <Field label="ID">
              <MonoId id={event.id} chars={12} />
            </Field>
            <Field label="Run">
              <MonoId id={event.backend_run_id} chars={12} />
            </Field>
            <Field label="Cuando">
              <RelativeTime iso={event.created_at} />
            </Field>
          </Group>

          {event.message && (
            <>
              <Divider my={4} label="Mensaje" labelPosition="left" />
              <Text
                size="sm"
                style={{ whiteSpace: 'pre-wrap' }}
              >
                {event.message}
              </Text>
            </>
          )}

          <Divider my={4} label="Payload" labelPosition="left" />
          <JsonBlock value={event.payload_json} />
        </Stack>
      )}
    </Drawer>
  );
}

function Field({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <Stack gap={2}>
      <Text
        size="xs"
        c="dimmed"
        tt="uppercase"
        style={{ letterSpacing: '0.04em' }}
      >
        {label}
      </Text>
      {children}
    </Stack>
  );
}
