# PR-V1-33 — Context attachments en tareas

**Tipo:** FEATURE
**Esfuerzo:** M
**Depende de:** ninguna

## Qué

Permitir adjuntar archivos al crear (o editar) una tarea. Los
archivos se guardan en `<project.local_path>/.niwa/attachments/
task-<id>/` y se mencionan al adapter como rutas relativas en el
prompt. Claude puede leerlos como contexto (imágenes, PDFs, CSVs,
specs en markdown, etc).

## Por qué

Pareja del autor pidió "pasarle archivos a la tarea o al
proyecto". Caso de uso: adjuntar un screenshot de un mockup, un
PDF de spec, un CSV de datos, y la task lleva la referencia
"usa el archivo `mockup.png` para la maqueta". Hoy es imposible
sin commitear los archivos manualmente al repo, lo que rompe el
flujo `working tree clean`.

## Scope

```
backend/app/api/tasks.py            # +endpoint POST .../attachments
backend/app/services/attachments.py # NUEVO: storage helpers
backend/app/models/attachment.py    # NUEVO: Attachment ORM
backend/migrations/versions/...py   # NUEVA migration: tabla attachments
backend/app/executor/core.py        # _build_prompt menciona attachments
backend/tests/test_attachments.py   # NUEVO

frontend/src/features/tasks/TaskCreateModal.tsx  # Dropzone
frontend/src/features/tasks/TaskDetail.tsx        # mostrar adjuntos
frontend/src/features/tasks/api.ts                # uploadAttachment
frontend/tests/TaskCreateModal.test.tsx           # +1 caso
```

**Hard-cap: 350 LOC** código + tests + migration + frontend.
Excede 250 por scope justificado (backend + DB + frontend en un
solo PR cohesivo).

## Fuera de scope

- No procesar/transformar archivos (no thumbnail, no OCR, no
  vector embedding). Niwa los guarda y le dice al adapter dónde
  están.
- No límite de tamaño server-side estricto — confiar en sentido
  común; si abusan, lo afinamos en v1.2.
- No drag-and-drop al detalle de proyecto (sólo a tasks). El
  alcance "archivos al proyecto en sí" del usuario se interpreta
  como adjuntar al primer task del proyecto si quiere
  context-wide. Caso de uso clarificable después.
- No editar attachments tras crear la task. Si la task aún no se
  ejecutó, puede hacer DELETE + recrear.
- No commitear los attachments al repo. Viven en
  `.niwa/attachments/` que el `.gitignore` del proyecto debería
  excluir (lo gestiona el usuario; documentar).

## Modelo de datos

Nueva tabla `attachments`:

```sql
id INTEGER PRIMARY KEY,
task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
filename TEXT NOT NULL,           -- nombre original (sanitized)
content_type TEXT,                -- mime sniffed o trusted from upload
size_bytes INTEGER NOT NULL,
storage_path TEXT NOT NULL,       -- ruta absoluta en disco
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

Migration nueva. Indexada por `task_id`.

## Endpoints

### `POST /api/tasks/{task_id}/attachments` (multipart/form-data)

- Acepta `file` field.
- Sanitiza `filename` (sin `..`, sin `/`, sin path traversal).
- Calcula path destino: `<project.local_path>/.niwa/attachments/
  task-<id>/<sanitized_filename>` con dedup tipo
  `<name>__<n>.<ext>` si hay colisión.
- Crea directorio si no existe.
- Streamea el upload a disco.
- Inserta `Attachment` en DB.
- Devuelve 201 con AttachmentRead.
- Validaciones:
  - 404 si task no existe.
  - 409 si task no está en `inbox` o `queued` (solo se adjuntan
    a tareas no-empezadas).

### `GET /api/tasks/{task_id}/attachments`

Lista los adjuntos de la task.

### `DELETE /api/tasks/{task_id}/attachments/{attachment_id}`

Borra el fichero del disco + fila DB. 409 si task ya empezó.

## Integración con executor

`_build_prompt` en `executor/core.py` extiende el prompt cuando
hay attachments:

```python
def _build_prompt(task: Task, attachments: list[Attachment]) -> str:
    parts = []
    if task.title:
        parts.append(f"# Task: {task.title}")
    if task.description:
        parts.append(task.description)
    if attachments:
        parts.append("\n## Attached files (read these as context):\n")
        for a in attachments:
            rel = os.path.relpath(a.storage_path, task.project.local_path)
            parts.append(f"- `{rel}`")
    return "\n\n".join(parts) if parts else "Complete the assigned task."
```

Claude Code puede leer ficheros del cwd; los attachments están
dentro del cwd del proyecto, accesibles vía `Read` tool.

## Frontend

### `TaskCreateModal.tsx`

Añadir un `Dropzone` (Mantine `@mantine/dropzone`, ya en deps)
debajo del campo `description`. Acepta cualquier MIME, sin
límite. Lista de archivos seleccionados con icono + nombre +
tamaño + botón borrar.

Al submit del modal:
1. Crea la task vía POST normal.
2. Si la creación devuelve OK Y hay archivos, hace N requests
   secuenciales `POST .../attachments` por cada archivo.
3. Si algún upload falla, muestra toast con error pero la task
   queda creada (consistencia eventual).

### `TaskDetail.tsx`

Añadir sección "Attachments" sobre el stream con lista, link
para descarga (otro endpoint `GET .../download` opcional, fuera
de scope), y botón delete si la task no ha empezado.

## Tests

Backend:
- `test_post_attachment_writes_file_and_row`.
- `test_post_attachment_rejects_path_traversal`.
- `test_post_attachment_409_when_task_running`.
- `test_executor_prompt_includes_attachments`.

Frontend:
- `test_create_modal_uploads_files_after_task_create`.

## Criterio de hecho

- [ ] Modal de task con dropzone visible y funcional.
- [ ] Al crear task con archivo adjunto, fichero acaba en
      `<local_path>/.niwa/attachments/task-N/`.
- [ ] El executor mete la lista de attachments en el prompt y
      Claude puede leerlos.
- [ ] Tras task `done`, los attachments siguen en disco
      (lifecycle independiente de la task).
- [ ] DELETE cascade: borrar task elimina los attachments.
- [ ] `pytest -q` y `npm test` pasan.
- [ ] Codex ejecutado.

## Riesgos

- **`.niwa/attachments/` no en `.gitignore` del usuario:** los
  archivos quedan untracked → working tree dirty → próxima task
  falla guard de PR-V1-08. **Mitigación:** documentar en README
  ("First project") que añada `.niwa/` a su `.gitignore`. **Fix
  más robusto v1.2:** que `prepare_task_branch` ignore
  específicamente `.niwa/attachments/` en su check de cleanliness.
- **Filenames con caracteres unicode raros:** sanitización mínima
  (sin `/`, `\`, `..`, NUL). Si cae carácter rarito, queda como
  está; OS lo guarda. Acceptable.
