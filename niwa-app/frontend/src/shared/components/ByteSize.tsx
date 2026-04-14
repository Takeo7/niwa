import { Text, Tooltip, type TextProps } from '@mantine/core';

/** Format a byte count with 1024-based units (``KiB``/``MiB``/…).
 *  Binary units match what filesystems report in practice (``du``,
 *  ``ls -lh``) which matches the numbers an operator will see when
 *  poking at ``artifact_root`` from the host.
 *
 *  Falls back to ``—`` for ``null``/``undefined``/non-finite input —
 *  mirrors the pattern used by ``RelativeTime`` and ``MonoId``.
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—';
  if (bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes / 1024;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  // 1 decimal place until GiB, 2 from there for small deltas.
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[idx]}`;
}

interface Props extends Omit<TextProps, 'children'> {
  bytes: number | null | undefined;
  /** Show the raw byte count as a tooltip (default ``true``). */
  withTooltip?: boolean;
}

/** Inline byte-size label with tabular numerals and a tooltip that
 *  reveals the exact byte count.  Editorial-dense tables (artifacts
 *  lists, usage panels) should use this instead of a raw number.
 */
export function ByteSize({ bytes, withTooltip = true, ...props }: Props) {
  const label = formatBytes(bytes);
  const body = (
    <Text
      size="sm"
      span
      style={{ fontVariantNumeric: 'tabular-nums' }}
      {...props}
    >
      {label}
    </Text>
  );
  if (!withTooltip || bytes == null) return body;
  return (
    <Tooltip
      label={`${bytes.toLocaleString('es-ES')} B`}
      withArrow
      position="top"
      openDelay={250}
    >
      {body}
    </Tooltip>
  );
}
