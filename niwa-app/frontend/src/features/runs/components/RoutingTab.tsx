import {
  Stack,
  Paper,
  Title,
  Text,
  Group,
  Badge,
  Center,
  Loader,
  Divider,
} from '@mantine/core';
import { useParams } from 'react-router-dom';
import { MonoId } from '../../../shared/components/MonoId';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import { useTaskRoutingDecision } from '../hooks/useRuns';
import type { RoutingMatchedRule } from '../../../shared/types';

function describeRule(r: RoutingMatchedRule): string {
  if (r.rule === 'user_pin' && r.slug) {
    return `Pin explícito → ${r.slug}`;
  }
  if (r.rule === 'resume_aware' && r.slug) {
    return `Resume-aware (backend previo: ${r.slug})`;
  }
  if (r.rule === 'routing_rule' && r.rule_name) {
    const pos = r.position !== undefined ? ` · pos ${r.position}` : '';
    return `Regla '${r.rule_name}'${pos}`;
  }
  if (r.rule === 'default' && r.slug) {
    return `Default (${r.slug})`;
  }
  if (r.rule === 'capability_denied') {
    return 'Capability denegada';
  }
  return r.rule;
}

export function RoutingTab() {
  const { taskId } = useParams<{ taskId: string }>();
  const {
    data: decision,
    isLoading,
    error,
  } = useTaskRoutingDecision(taskId);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader size="sm" />
      </Center>
    );
  }

  if (error) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="red">
          No se pudo cargar la routing decision.
        </Text>
      </Paper>
    );
  }

  if (!decision) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed">
          Esta tarea aún no tiene una <code>routing_decision</code>.
          Se crea cuando la tarea pasa a <code>pendiente</code> y el
          router determinista selecciona un backend.
        </Text>
      </Paper>
    );
  }

  const selectedSlug = decision.selected_backend_slug;
  return (
    <Stack gap="md">
      <div>
        <Title order={5}>Explicación del routing</Title>
        <Text size="xs" c="dimmed">
          Por qué esta tarea se asignó al backend mostrado. La
          decisión es determinista: evalúa pin, capability, resume,
          reglas persistidas y default, en ese orden.
        </Text>
      </div>

      <Paper withBorder p="md" radius="sm">
        <Stack gap="xs">
          <Group justify="space-between" wrap="nowrap">
            <Group gap="xs" wrap="nowrap">
              <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                Backend seleccionado
              </Text>
            </Group>
            <RelativeTime iso={decision.created_at} />
          </Group>
          {selectedSlug ? (
            <Group gap="xs" wrap="nowrap">
              <Badge size="lg" radius="sm" variant="light" color="teal">
                {selectedSlug}
              </Badge>
              {decision.selected_backend_display_name && (
                <Text size="sm" c="dimmed">
                  {decision.selected_backend_display_name}
                </Text>
              )}
            </Group>
          ) : (
            <Text size="sm" c="orange">
              Ninguno — decisión pendiente de approval.
            </Text>
          )}
          {decision.reason_summary && (
            <>
              <Divider my={4} />
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {decision.reason_summary}
              </Text>
            </>
          )}
          <Group gap="md" mt={4}>
            <Text size="xs" c="dimmed">
              Decision <MonoId id={decision.id} chars={8} />
            </Text>
            {decision.contract_version && (
              <Text size="xs" c="dimmed">
                contract: {decision.contract_version}
              </Text>
            )}
            {decision.decision_index !== null &&
              decision.decision_index !== undefined && (
                <Text size="xs" c="dimmed">
                  index #{decision.decision_index}
                </Text>
              )}
          </Group>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="sm">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Fallback chain
          </Text>
          {decision.fallback_chain.length === 0 ? (
            <Text size="sm" c="dimmed">
              Sin cadena de fallback registrada.
            </Text>
          ) : (
            <Stack gap={4}>
              {decision.fallback_chain.map((b, idx) => {
                const isSelected =
                  b.id === decision.selected_profile_id;
                return (
                  <Group
                    key={`${b.id}-${idx}`}
                    gap="xs"
                    wrap="nowrap"
                    p={6}
                    style={{
                      border: '1px solid var(--mantine-color-default-border)',
                      borderRadius: 'var(--mantine-radius-sm)',
                      background: isSelected
                        ? 'var(--mantine-color-default-hover)'
                        : 'transparent',
                      borderColor: isSelected
                        ? 'var(--mantine-color-teal-filled)'
                        : 'var(--mantine-color-default-border)',
                    }}
                  >
                    <Text
                      size="xs"
                      c="dimmed"
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                      w={20}
                    >
                      {idx + 1}.
                    </Text>
                    {b.slug ? (
                      <Badge
                        variant={isSelected ? 'light' : 'outline'}
                        color={isSelected ? 'teal' : 'gray'}
                        radius="sm"
                      >
                        {b.slug}
                      </Badge>
                    ) : (
                      <Text size="xs" c="dimmed" ff="monospace">
                        unknown ({b.id.slice(0, 8)}…)
                      </Text>
                    )}
                    {b.display_name && (
                      <Text size="sm" c="dimmed">
                        {b.display_name}
                      </Text>
                    )}
                    {isSelected && (
                      <Text size="xs" c="teal" fw={500}>
                        · usado
                      </Text>
                    )}
                  </Group>
                );
              })}
            </Stack>
          )}
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="sm">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Reglas evaluadas
          </Text>
          {decision.matched_rules.length === 0 ? (
            <Text size="sm" c="dimmed">
              Sin reglas registradas.
            </Text>
          ) : (
            <Stack gap={4}>
              {decision.matched_rules.map((r, idx) => (
                <Group
                  key={idx}
                  gap="xs"
                  wrap="nowrap"
                  align="flex-start"
                >
                  <Text size="xs" c="dimmed" w={20}>
                    {idx + 1}.
                  </Text>
                  <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
                    <Text size="sm">{describeRule(r)}</Text>
                    {r.triggers !== undefined && (
                      <Text
                        size="xs"
                        c="dimmed"
                        ff="monospace"
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                        }}
                      >
                        {JSON.stringify(r.triggers)}
                      </Text>
                    )}
                  </Stack>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </Paper>

      {(decision.approval_required || decision.approval) && (
        <Paper withBorder p="md" radius="sm">
          <Stack gap="xs">
            <Group justify="space-between" wrap="nowrap">
              <Text
                size="xs"
                c="dimmed"
                tt="uppercase"
                fw={600}
              >
                Approval
              </Text>
              {decision.approval?.status && (
                <Badge
                  radius="sm"
                  variant="light"
                  color={
                    decision.approval.status === 'pending'
                      ? 'orange'
                      : decision.approval.status === 'approved'
                      ? 'teal'
                      : 'red'
                  }
                >
                  {decision.approval.status}
                </Badge>
              )}
            </Group>
            {decision.approval && (
              <>
                <Text size="sm">
                  {decision.approval.reason ?? decision.approval.approval_type}
                </Text>
                <Group gap="md">
                  <Text size="xs" c="dimmed">
                    Approval <MonoId id={decision.approval.id} chars={8} />
                  </Text>
                  {decision.approval.risk_level && (
                    <Text size="xs" c="dimmed">
                      riesgo: {decision.approval.risk_level}
                    </Text>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  El detalle del approval vivirá en la vista de
                  approvals (PR-10b).
                </Text>
              </>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
