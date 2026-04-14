import { Code, Paper, Text } from '@mantine/core';

interface Props {
  /** Raw string that is expected to parse as JSON.  If parsing fails
   *  the raw value is rendered verbatim with a warning header so the
   *  operator can still inspect malformed payloads. */
  value: string | null | undefined;
  /** Max block height in pixels — enables vertical scroll without
   *  pushing the rest of the page down when payloads are large.
   *  Default 480. */
  maxHeight?: number;
}

/** Pretty-prints a JSON string inside a monospace ``<Code block>``.
 *  No external deps (``JSON.stringify(v, null, 2)`` only) — matches
 *  the "no new npm dependencies" constraint of PR-10c.
 *
 *  Behaviours:
 *   - ``null``/``undefined``/empty string → dimmed "no payload" line.
 *   - Unparseable string → shows the raw value + a subtle marker so
 *     the caller can see the drift.  Never throws.
 *   - Parseable → indented 2-space JSON, monospace, scroll on long.
 */
export function JsonBlock({ value, maxHeight = 480 }: Props) {
  if (value == null || value === '') {
    return (
      <Text size="sm" c="dimmed" ta="center" py="sm">
        Este evento no incluye payload.
      </Text>
    );
  }

  let pretty: string;
  let unparseable = false;
  try {
    pretty = JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    unparseable = true;
    pretty = value;
  }

  return (
    <Paper
      withBorder
      radius="sm"
      p={0}
      bg="var(--mantine-color-default-hover)"
      style={{ overflow: 'hidden' }}
    >
      {unparseable && (
        <Text size="xs" c="orange" px="sm" py={4}>
          Payload no es JSON válido — mostrado tal cual.
        </Text>
      )}
      <Code
        block
        style={{
          maxHeight,
          overflow: 'auto',
          whiteSpace: 'pre',
          fontSize: 12,
          lineHeight: 1.5,
          background: 'transparent',
          border: 'none',
        }}
      >
        {pretty}
      </Code>
    </Paper>
  );
}
