import { Text, Tooltip, type TextProps } from '@mantine/core';

interface Props extends Omit<TextProps, 'children'> {
  hash: string | null | undefined;
  /** Number of leading chars to show.  Default 10 — keeps the cell
   *  narrow in dense tables while retaining enough bits to disambiguate
   *  by eye.  Full value is always in the tooltip. */
  chars?: number;
  /** Show the full hash on hover tooltip.  Default ``true``. */
  withTooltip?: boolean;
}

/** Truncated SHA-256 (or similar) with monospace, tabular numerals,
 *  and a tooltip revealing the full hash.  A full 64-char SHA-256 in
 *  a table cell is visual noise; ten chars is enough for humans to
 *  spot duplicates while the tooltip covers the auditable case.
 *
 *  Renders ``—`` when the hash is missing (Bug 8 tolerance — an early
 *  adapter failure can leave ``sha256`` NULL in the DB).
 */
export function HashDisplay({
  hash,
  chars = 10,
  withTooltip = true,
  ...props
}: Props) {
  if (!hash) {
    return (
      <Text size="xs" c="dimmed" span ff="monospace" {...props}>
        —
      </Text>
    );
  }
  const short = hash.length > chars ? hash.slice(0, chars) : hash;
  const body = (
    <Text
      size="xs"
      span
      ff="monospace"
      style={{ fontVariantNumeric: 'tabular-nums' }}
      {...props}
    >
      {short}
    </Text>
  );
  if (!withTooltip) return body;
  return (
    <Tooltip label={hash} withArrow position="top" openDelay={250}>
      {body}
    </Tooltip>
  );
}
