import { Alert, Anchor, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useNavigate } from 'react-router-dom';
import type { Turn } from '../types';

interface Props {
  turn: Turn;
}

/**
 * Banner informativo para errores estructurados de assistant_turn.
 * Renderizado dentro de TurnView cuando turn.error está presente.
 *
 * Códigos de error del contrato PR-08 manejados explícitamente:
 *  - routing_mode_mismatch  (HTTP 409)
 *  - missing_session_id, missing_project_id, empty_message
 *  - project_not_found
 *  - llm_not_configured
 *  - session_handle_missing  (propagado desde task_resume interno —
 *    Bug 8 mitigation, PR-08 Dec)
 *  - network_error           (no del contrato — lo usa useChat para
 *    errores de fetch)
 *
 * Otros códigos desconocidos se renderizan con el message del backend
 * (si existe) o una cadena genérica con el código.
 */
export function TurnErrorBanner({ turn }: Props) {
  const navigate = useNavigate();
  if (!turn.error) return null;

  const code = turn.error;
  const msg = turn.error_message;

  if (code === 'routing_mode_mismatch') {
    return (
      <Alert
        variant="light"
        color="yellow"
        icon={<IconAlertTriangle size={16} />}
        title="Modo legacy detectado"
      >
        <Text size="sm">
          Tu instalación está en routing_mode legacy. El chat v0.2 usa
          assistant_turn, que requiere{' '}
          <Text span ff="monospace">routing_mode=&quot;v02&quot;</Text>.
          {' '}
          <Anchor
            size="sm"
            component="button"
            onClick={() => navigate('/settings')}
          >
            Ve a Ajustes
          </Anchor>
          {' '}para cambiar la configuración.
        </Text>
      </Alert>
    );
  }

  if (code === 'network_error') {
    return (
      <Alert
        variant="light"
        color="red"
        icon={<IconAlertTriangle size={16} />}
        title="Error de red"
      >
        <Text size="sm">
          No se pudo contactar con el backend. Revisa la consola
          para más detalles.
        </Text>
        {msg ? (
          <Text size="xs" c="dimmed" mt={4}>{msg}</Text>
        ) : null}
      </Alert>
    );
  }

  if (isTimeoutLike(code, msg)) {
    return (
      <Alert
        variant="light"
        color="orange"
        icon={<IconAlertTriangle size={16} />}
        title="Tiempo agotado"
      >
        <Text size="sm">
          El assistant tardó más de lo permitido (30s). Intenta de
          nuevo o reformula la petición en partes más pequeñas.
        </Text>
      </Alert>
    );
  }

  // project_not_found, llm_not_configured, session_handle_missing,
  // empty_message, missing_*, unknown codes — mensaje del backend tal
  // cual, con el código como título técnico.
  return (
    <Alert
      variant="light"
      color="red"
      icon={<IconAlertTriangle size={16} />}
      title={`Error: ${code}`}
    >
      <Text size="sm">
        {msg || 'El assistant devolvió un error estructurado.'}
      </Text>
    </Alert>
  );
}

function isTimeoutLike(code: string, msg: string | undefined): boolean {
  if (code === 'timeout') return true;
  const m = (msg || '').toLowerCase();
  return (
    m.includes('tiempo') ||
    m.includes('timeout') ||
    m.includes('tardó más')
  );
}
