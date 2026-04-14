// PR-10e — Tipos del chat web v0.2 sobre assistant_turn.
//
// El contrato de entrada/salida de /api/assistant/turn está fijado en
// PR-08 (niwa-app/backend/assistant_service.py::assistant_turn).  Estos
// tipos son un mirror frontend de ese contrato — cualquier cambio debe
// coordinarse con assistant_service.

export interface AssistantTurnRequest {
  session_id: string;
  project_id: string;
  message: string;
  channel: 'web';
  metadata?: Record<string, unknown>;
}

export interface AssistantAction {
  tool: string;
  input: Record<string, unknown>;
  result: unknown;
}

export interface AssistantTurnResponse {
  session_id?: string;
  assistant_message: string;
  actions_taken: AssistantAction[];
  task_ids: string[];
  approval_ids: string[];
  run_ids: string[];
  // Presentes sólo en errores estructurados.
  error?: string;
  message?: string;
}

export interface SessionMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  task_id: string | null;
  status: 'done' | 'pending';
  created_at: string;
}

export interface SessionMessagesResponse {
  messages: SessionMessage[];
}

/**
 * Un "turn" es la unidad visual del chat: un mensaje del usuario +
 * la respuesta del assistant + los IDs creados/afectados.  No
 * corresponde 1:1 con una fila de chat_messages — se reconstruye
 * en el cliente a partir de los mensajes persistidos y del último
 * turn enviado (que todavía puede estar in-flight).
 */
export interface Turn {
  id: string;
  user_message: string;
  user_created_at: string;
  // in_flight: el turn se ha enviado pero no ha recibido respuesta.
  // assistant_message/actions_taken/ids quedan vacíos hasta que llega.
  in_flight: boolean;
  assistant_message: string;
  assistant_created_at: string | null;
  actions_taken: AssistantAction[];
  task_ids: string[];
  approval_ids: string[];
  run_ids: string[];
  // Para errores estructurados que la UI quiere renderizar con un
  // banner específico (routing_mode_mismatch, project_not_found, etc.).
  error?: string;
  error_message?: string;
}
