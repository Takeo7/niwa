import {
  Badge,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconFolder } from '@tabler/icons-react';
import { ByteSize } from '../../../shared/components/ByteSize';
import { HashDisplay } from '../../../shared/components/HashDisplay';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import { useRunArtifacts } from '../hooks/useRuns';

interface Props {
  runId: string | null;
}

// Editorial palette for artifact_type.  Values emitted by both
// adapters (claude_code._classify_artifact_type / codex.py mirror):
// code, document, data, log, image, file.  Unknown types fall back
// to neutral grey — mirrors PR-10b's "render unknown as-is" stance.
const TYPE_COLORS: Record<string, string> = {
  code: 'violet',
  document: 'blue',
  data: 'teal',
  log: 'gray',
  image: 'orange',
  file: 'gray',
};

/** List of artifacts registered for a run.  PR-10c scope:
 *    - metadata only (no inline previews)
 *    - path is whatever the DB holds (relative to artifact_root,
 *      per PR-04 Dec 10 — backend guarantees no absolute paths)
 *    - size + sha256 tolerate NULL (BUGS-FOUND Bug 8)
 */
export function ArtifactList({ runId }: Props) {
  const { data, isLoading } = useRunArtifacts(runId);

  if (!runId) return null;

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="baseline">
        <Title order={6}>
          <Group gap={6} align="center">
            <IconFolder size={14} />
            <span>Artifacts</span>
            {data && data.length > 0 && (
              <Text size="xs" c="dimmed">
                ({data.length})
              </Text>
            )}
          </Group>
        </Title>
        <Text size="xs" c="dimmed">
          Ficheros producidos por este run dentro de{' '}
          <code>artifact_root</code>.
        </Text>
      </Group>

      <Paper withBorder radius="sm" p={0}>
        {isLoading && !data ? (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        ) : !data || data.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="md">
            Este run todavía no ha registrado ningún artifact.
          </Text>
        ) : (
          <Table
            horizontalSpacing="sm"
            verticalSpacing={6}
            fz="sm"
            striped="even"
            highlightOnHover
            withRowBorders={false}
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: 96 }}>Tipo</Table.Th>
                <Table.Th>Path</Table.Th>
                <Table.Th style={{ width: 110, textAlign: 'right' }}>
                  Tamaño
                </Table.Th>
                <Table.Th style={{ width: 140 }}>SHA-256</Table.Th>
                <Table.Th style={{ width: 96, textAlign: 'right' }}>
                  Cuando
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.map((a) => (
                <Table.Tr key={a.id}>
                  <Table.Td>
                    <Badge
                      size="sm"
                      radius="sm"
                      variant="light"
                      color={TYPE_COLORS[a.artifact_type] ?? 'gray'}
                    >
                      {a.artifact_type}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text
                      size="sm"
                      ff="monospace"
                      style={{
                        wordBreak: 'break-all',
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {a.path}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'right' }}>
                    <ByteSize bytes={a.size_bytes} />
                  </Table.Td>
                  <Table.Td>
                    <HashDisplay hash={a.sha256} />
                  </Table.Td>
                  <Table.Td style={{ textAlign: 'right' }}>
                    <RelativeTime iso={a.created_at} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>
    </Stack>
  );
}
