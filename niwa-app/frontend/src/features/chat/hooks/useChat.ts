import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../shared/api/client';
import type {
  AssistantTurnRequest,
  AssistantTurnResponse,
  SessionMessagesResponse,
  Turn,
} from '../types';

const LAST_PROJECT_KEY = 'niwa.chat.lastProjectId';

function newSessionId(): string {
  // crypto.randomUUID exists in all browsers Mantine 7 supports.
  return crypto.randomUUID();
}

function newTurnId(): string {
  return crypto.randomUUID();
}

/**
 * Llamada directa al endpoint assistant_turn con fetch crudo.
 *
 * Usa fetch en lugar de apiPost para preservar el body estructurado
 * en respuestas 4xx/5xx — la ApiError compartida pierde el campo
 * `message` (humano) y sólo retiene `error` (code) y status.  Ver
 * DECISIONS-LOG PR-10e Dec 6.
 */
async function callAssistantTurn(
  body: AssistantTurnRequest,
): Promise<{ status: number; data: AssistantTurnResponse }> {
  const res = await fetch('/api/assistant/turn', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 401 || res.status === 302) {
    // Avoid reload loop if already on /login — mirror the guard in
    // shared/api/client.ts::api. See that file for the full rationale.
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
    throw new Error('No autenticado');
  }
  let data: AssistantTurnResponse;
  try {
    data = (await res.json()) as AssistantTurnResponse;
  } catch {
    // Respuesta no-JSON (500 HTML, proxy error, etc.).
    throw new Error(`HTTP ${res.status}: respuesta no estructurada`);
  }
  return { status: res.status, data };
}

export interface UseChatResult {
  sessionId: string;
  projectId: string | null;
  setProjectId: (id: string | null) => void;
  turns: Turn[];
  loading: boolean;
  /** Último error no estructurado (fetch falló, 500 sin body, etc.). */
  networkError: string | null;
  send: (message: string) => Promise<void>;
  newConversation: () => void;
  /** Flag de carga del historial al mount (raro — normalmente vacío). */
  historyLoading: boolean;
}

/**
 * Hook central del chat web v0.2.
 *
 * Gestiona un session_id client-side, la lista de turns, el estado de
 * loading del turn en vuelo, y la carga de historial cuando se monta
 * con un session_id existente (caso raro — el flow normal es session
 * fresca por montaje).
 */
export function useChat(initialProjectId?: string | null): UseChatResult {
  const [sessionId, setSessionId] = useState<string>(() => newSessionId());
  const [projectId, setProjectIdState] = useState<string | null>(() => {
    if (initialProjectId) return initialProjectId;
    try {
      return localStorage.getItem(LAST_PROJECT_KEY);
    } catch {
      return null;
    }
  });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  const setProjectId = useCallback((id: string | null) => {
    setProjectIdState(id);
    try {
      if (id) localStorage.setItem(LAST_PROJECT_KEY, id);
      else localStorage.removeItem(LAST_PROJECT_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  // Cargar historial si la sesión ya tiene mensajes (p.ej. el usuario
  // pega un session_id existente).  Para el flow normal (session nueva
  // por montaje) esta llamada vuelve con messages: [] y es barata.
  useEffect(() => {
    let cancelled = false;
    setHistoryLoading(true);
    api<SessionMessagesResponse>(`chat-sessions/${sessionId}/messages`)
      .then((data) => {
        if (cancelled) return;
        const rebuilt = rebuildTurnsFromMessages(data.messages);
        setTurns(rebuilt);
      })
      .catch(() => {
        // 404 de sesión inexistente = sesión fresca sin mensajes.  No
        // es un error.  Dejamos turns = [].
        if (!cancelled) setTurns([]);
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const send = useCallback(
    async (message: string) => {
      const trimmed = message.trim();
      if (!trimmed) return;
      if (!projectId) {
        setNetworkError('Selecciona un proyecto antes de enviar.');
        return;
      }
      if (loading) return;

      const turnId = newTurnId();
      const userTurn: Turn = {
        id: turnId,
        user_message: trimmed,
        user_created_at: new Date().toISOString(),
        in_flight: true,
        assistant_message: '',
        assistant_created_at: null,
        actions_taken: [],
        task_ids: [],
        approval_ids: [],
        run_ids: [],
      };
      setTurns((prev) => [...prev, userTurn]);
      setLoading(true);
      setNetworkError(null);

      try {
        const { status, data } = await callAssistantTurn({
          session_id: sessionRef.current,
          project_id: projectId,
          message: trimmed,
          channel: 'web',
        });

        // El backend puede devolver un session_id canonicalizado
        // distinto (p.ej. si channel="openclaw" — no aplica aquí,
        // pero cubrimos el caso por robustez).
        if (data.session_id && data.session_id !== sessionRef.current) {
          setSessionId(data.session_id);
        }

        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? {
                  ...t,
                  in_flight: false,
                  assistant_message: data.assistant_message || '',
                  assistant_created_at: new Date().toISOString(),
                  actions_taken: data.actions_taken || [],
                  task_ids: data.task_ids || [],
                  approval_ids: data.approval_ids || [],
                  run_ids: data.run_ids || [],
                  error: status !== 200 ? data.error : undefined,
                  error_message:
                    status !== 200 ? data.message || data.error : undefined,
                }
              : t,
          ),
        );
      } catch (e) {
        // Error no estructurado (red, 500 HTML, etc.).  No se registra
        // como turn completo — el mensaje del usuario queda pero sin
        // respuesta, y mostramos un banner de error.
        const msg = e instanceof Error ? e.message : String(e);
        // eslint-disable-next-line no-console
        console.error('assistant_turn fetch failed:', e);
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? {
                  ...t,
                  in_flight: false,
                  assistant_message: '',
                  assistant_created_at: new Date().toISOString(),
                  error: 'network_error',
                  error_message: msg,
                }
              : t,
          ),
        );
        setNetworkError(msg);
      } finally {
        setLoading(false);
      }
    },
    [projectId, loading],
  );

  const newConversation = useCallback(() => {
    setSessionId(newSessionId());
    setTurns([]);
    setNetworkError(null);
  }, []);

  return {
    sessionId,
    projectId,
    setProjectId,
    turns,
    loading,
    networkError,
    send,
    newConversation,
    historyLoading,
  };
}

/**
 * Reconstruye turns a partir de una lista plana de mensajes
 * persistidos en chat_messages.  Pareja cada user con el siguiente
 * assistant (el patrón que escribe assistant_service es
 * user-then-assistant por turn).
 *
 * Exportado para tests de unidad si los añadimos más adelante.
 */
export function rebuildTurnsFromMessages(
  messages: { id: string; role: 'user' | 'assistant'; content: string;
    task_id: string | null; created_at: string }[],
): Turn[] {
  const turns: Turn[] = [];
  let pendingUser: typeof messages[number] | null = null;
  for (const m of messages) {
    if (m.role === 'user') {
      if (pendingUser) {
        // user sin respuesta previa — lo cerramos como turn con assistant
        // vacío (el usuario envió dos veces sin que el backend respondiera
        // entre medias).  Edge case.
        turns.push({
          id: pendingUser.id,
          user_message: pendingUser.content,
          user_created_at: pendingUser.created_at,
          in_flight: false,
          assistant_message: '',
          assistant_created_at: null,
          actions_taken: [],
          task_ids: [],
          approval_ids: [],
          run_ids: [],
        });
      }
      pendingUser = m;
    } else if (pendingUser) {
      const task_ids = m.task_id ? [m.task_id] : [];
      turns.push({
        id: pendingUser.id,
        user_message: pendingUser.content,
        user_created_at: pendingUser.created_at,
        in_flight: false,
        assistant_message: m.content,
        assistant_created_at: m.created_at,
        // actions_taken no se persiste en chat_messages (sólo en el
        // response del turn).  Al recargar no recuperamos el detalle
        // de los tool calls — los chips que mostramos son los task_ids
        // asociados al mensaje.
        actions_taken: [],
        task_ids,
        approval_ids: [],
        run_ids: [],
      });
      pendingUser = null;
    }
  }
  if (pendingUser) {
    turns.push({
      id: pendingUser.id,
      user_message: pendingUser.content,
      user_created_at: pendingUser.created_at,
      in_flight: false,
      assistant_message: '',
      assistant_created_at: null,
      actions_taken: [],
      task_ids: [],
      approval_ids: [],
      run_ids: [],
    });
  }
  return turns;
}
