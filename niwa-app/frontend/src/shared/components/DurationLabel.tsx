import { Text, type TextProps } from '@mantine/core';

function formatDuration(ms: number): string {
  if (ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h ${rm}m` : `${h}h`;
}

interface Props extends Omit<TextProps, 'children'> {
  startedAt: string | null | undefined;
  finishedAt: string | null | undefined;
  /** If the run is still running, ticks the duration forward. */
  isRunning?: boolean;
}

export function DurationLabel({
  startedAt, finishedAt, isRunning = false, ...props
}: Props) {
  if (!startedAt) {
    return (
      <Text size="xs" c="dimmed" span {...props}>
        —
      </Text>
    );
  }
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) {
    return (
      <Text size="xs" c="dimmed" span {...props}>
        —
      </Text>
    );
  }
  const end = finishedAt
    ? new Date(finishedAt).getTime()
    : isRunning
    ? Date.now()
    : start;
  const ms = end - start;
  return (
    <Text
      size="xs"
      c="dimmed"
      span
      style={{ fontVariantNumeric: 'tabular-nums' }}
      {...props}
    >
      {formatDuration(ms)}
    </Text>
  );
}
