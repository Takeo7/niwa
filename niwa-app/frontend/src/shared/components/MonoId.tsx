import { Text, Tooltip, type TextProps } from '@mantine/core';

interface Props extends Omit<TextProps, 'children'> {
  id: string | null | undefined;
  /** Number of chars to show.  Default 8 — enough for collision-free
   * local context, short enough to keep dense tables readable. */
  chars?: number;
  /** Show full id on hover tooltip.  Default true. */
  withTooltip?: boolean;
}

export function MonoId({
  id, chars = 8, withTooltip = true, ...props
}: Props) {
  if (!id) {
    return (
      <Text size="xs" c="dimmed" span ff="monospace" {...props}>
        —
      </Text>
    );
  }
  const short = id.length > chars ? id.slice(0, chars) : id;
  const body = (
    <Text
      size="xs"
      c="dimmed"
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
    <Tooltip label={id} withArrow position="top" openDelay={250}>
      {body}
    </Tooltip>
  );
}
