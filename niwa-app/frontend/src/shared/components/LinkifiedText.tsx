import { Fragment, type ReactNode } from 'react';
import { Anchor, Text, type TextProps } from '@mantine/core';
import { useNavigate } from 'react-router-dom';

interface Props extends Omit<TextProps, 'children'> {
  /** Texto crudo devuelto por el backend. */
  text: string;
  /** task_ids canónicos del turn, para resolver "task:..." a /tasks/:id. */
  taskIds?: string[];
  /** approval_ids canónicos del turn. */
  approvalIds?: string[];
}

// UUID v4/v5 shape — 36 chars con guiones.  El backend devuelve
// siempre UUIDs de str(uuid.uuid4()).
const UUID_RE =
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;

/**
 * Texto del assistant con linkificación mínima de IDs mencionados en
 * prosa.  Estrategia:
 *
 * - Escaneo regex por UUIDs completos en el texto.
 * - Cada UUID se convierte en Anchor a la ruta adecuada según con qué
 *   lista coincide (taskIds -> /tasks/:id, approvalIds -> /approvals,
 *   otro caso -> span mono dimmed sin link).
 *
 * El helper NO intenta parsear markdown, ni resolver IDs truncados
 * (tarea abc12345), ni adivinar tipo desde prefijos ambiguos.  Los
 * chips canónicos debajo del mensaje (ActionChips) son la fuente
 * primaria; la linkificación del texto es un bonus para leer la
 * prosa sin saltar.
 */
export function LinkifiedText({
  text, taskIds = [], approvalIds = [], ...textProps
}: Props) {
  const navigate = useNavigate();
  const taskSet = new Set(taskIds);
  const approvalSet = new Set(approvalIds);

  const segments = splitByUuid(text);

  return (
    <Text
      size="sm"
      style={{
        whiteSpace: 'pre-wrap',
        fontVariantNumeric: 'tabular-nums',
      }}
      {...textProps}
    >
      {segments.map((seg, i) => {
        if (seg.kind === 'plain') {
          return <Fragment key={i}>{seg.value}</Fragment>;
        }
        const id = seg.value;
        const isTask = taskSet.has(id);
        const isApproval = approvalSet.has(id);
        if (isTask) {
          return (
            <Anchor
              key={i}
              component="button"
              size="sm"
              onClick={() => navigate(`/tasks/${id}`)}
              style={{
                fontFamily: 'var(--mantine-font-family-monospace)',
              }}
            >
              {id}
            </Anchor>
          );
        }
        if (isApproval) {
          return (
            <Anchor
              key={i}
              component="button"
              size="sm"
              onClick={() => navigate('/approvals')}
              style={{
                fontFamily: 'var(--mantine-font-family-monospace)',
              }}
            >
              {id}
            </Anchor>
          );
        }
        // UUID no reconocido (p.ej. run_id, session_id mencionado, o
        // id que el LLM pronuncia pero no viene en actions_taken).
        // Lo dejamos como texto mono dimmed para que sea legible pero
        // claramente no navegable.
        return (
          <Text
            key={i}
            span
            size="sm"
            c="dimmed"
            style={{
              fontFamily: 'var(--mantine-font-family-monospace)',
            }}
          >
            {id}
          </Text>
        );
      })}
    </Text>
  );
}

type Segment =
  | { kind: 'plain'; value: string }
  | { kind: 'uuid'; value: string };

function splitByUuid(text: string): Segment[] {
  const result: Segment[] = [];
  let lastIndex = 0;
  // Reset regex state — UUID_RE is global so we need to reset
  // lastIndex.  Use a local regex per call to avoid sharing state.
  const re = new RegExp(UUID_RE.source, 'gi');
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) {
      result.push({ kind: 'plain', value: text.slice(lastIndex, m.index) });
    }
    result.push({ kind: 'uuid', value: m[0] });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    result.push({ kind: 'plain', value: text.slice(lastIndex) });
  }
  return result;
}

/**
 * Exportado para tests unitarios.  No está en el API público del
 * componente.
 */
export const __internal = { splitByUuid };

/** Render helper: devuelve ReactNode sin wrapper Text externo (útil
 *  para insertar en JSX denso). */
export function linkifyInline(
  text: string,
  opts: { taskIds?: string[]; approvalIds?: string[] } = {},
): ReactNode {
  return (
    <LinkifiedText
      text={text}
      taskIds={opts.taskIds}
      approvalIds={opts.approvalIds}
    />
  );
}
