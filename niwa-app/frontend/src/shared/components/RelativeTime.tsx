import { Text, Tooltip, type TextProps } from '@mantine/core';

function format(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  if (diff < 0) return 'en el futuro';
  const s = Math.floor(diff / 1000);
  if (s < 45) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo`;
  const y = Math.floor(d / 365);
  return `${y}a`;
}

interface Props extends Omit<TextProps, 'children'> {
  iso: string | null | undefined;
  /** When true, render the absolute ISO timestamp as tooltip. */
  withTooltip?: boolean;
}

export function RelativeTime({ iso, withTooltip = true, ...props }: Props) {
  const rel = format(iso);
  const abs = iso ? new Date(iso).toLocaleString('es-ES') : '';
  const body = (
    <Text
      size="xs"
      c="dimmed"
      span
      style={{ fontVariantNumeric: 'tabular-nums' }}
      {...props}
    >
      {rel}
    </Text>
  );
  if (!withTooltip || !iso) return body;
  return (
    <Tooltip label={abs} withArrow position="top" openDelay={250}>
      {body}
    </Tooltip>
  );
}
