# PR-B2 — Fix Bug 34: forzar cwd=project_directory + validar artefactos post-run

**Hito:** B
**Esfuerzo:** M
**Depende de:** ninguna (se apoya en el sentinel de clarification introducido en PR-B1, ya mergeado)
**Bloquea a:** PR-B4 (planner tier asume que el cwd de cada hija es el project_directory del padre)

## Qué

1. Endurecer `ClaudeCodeAdapter._resolve_cwd` para que `project_directory`
   sea contrato duro: si está set, se asegura `mkdir -p` del path y ese
   es el `cwd` del `subprocess.Popen`. Se elimina el fallback silencioso
   a `os.getcwd()` cuando `project_directory` existe pero no es dir.
2. Añadir validación post-run en `_execute`: tras cerrar el stream, se
   escanean los eventos `tool_use` recogidos en `raw_lines` buscando
   operaciones de escritura (`Write`, `Edit`, `MultiEdit`,
   `NotebookEdit`) cuyo `input.file_path` / `input.path` sea un path
   absoluto fuera de `cwd`. Si se detecta al menos una y el outcome
   actual sería `success`, se degrada a `needs_clarification` con
   `error_code='artifacts_outside_cwd'` y un `result_text` generado que
   lista los paths infractores y pide al operador que reajuste la
   tarea. Los sentinels ya existentes (`runs_service.finish_run` con
   outcome `needs_clarification` → status `waiting_input`) se reusan.

## Por qué

Happy path §1.4 (`MVP-ROADMAP.md`): "escribe código/docs/nuevos
proyectos, y revisa el resultado". Bug 34 reabierto 2026-04-18 rompe
esto: Claude sigue escribiendo a `/tmp/<slug>/` en el flow
auto-project; la tarea se marca `hecha`, el proyecto aparece vacío en
la UI, y el usuario no tiene forma de recuperarlo desde la interfaz.
La regla positiva del prompt (PR-43/45) es un "hint fuerte" pero
insuficiente. PR-B2 convierte la intención en invariante:
`project_directory` es el cwd, punto; y cualquier artefacto escrito
fuera del path se reporta como `waiting_input` con mensaje claro, en
lugar de declarar la tarea como completa.

## Scope — archivos que toca

- `niwa-app/backend/backend_adapters/claude_code.py`
  - `_resolve_cwd`: si `project_directory` está set, `mkdir(parents=True,
    exist_ok=True)` y devolver siempre ese path. Propaga `OSError` como
    excepción — el caller (`_execute`) ya convierte excepciones del
    bloque en `adapter_exception` (finish_run outcome='failure').
  - Nuevo helper `_collect_artifacts_outside_cwd(raw_lines, cwd)` que
    itera los mensajes JSON recogidos, extrae `input.file_path` /
    `input.path` de tool_use `Write|Edit|MultiEdit|NotebookEdit`, y
    devuelve la lista de paths absolutos que no son descendientes de
    `cwd` (comparación vía `Path.resolve().is_relative_to(cwd)`
    usando `Path.resolve(strict=False)` para aceptar paths no
    existentes).
  - En `_execute`, tras el bloque Bug 32 (líneas 1084-1119 actuales) y
    antes de `else: outcome = "failure"` del `if exit_code == 0`,
    añadir gate: si `outcome == "success"` y
    `_collect_artifacts_outside_cwd(raw_lines, cwd)` no está vacía,
    degradar a `outcome = "needs_clarification"`, `error_code =
    "artifacts_outside_cwd"`, construir un `result_text` con la lista
    de paths, y registrar un `backend_run_event` tipo `error` con
    `payload_json={error_code, offending_paths, cwd}`.
- `tests/test_claude_adapter_cwd_enforcement.py` (nuevo). Suite con ~5
  casos. Sigue el patrón de `test_claude_adapter_clarification.py`
  (`_AdapterCase`, `_mock_popen`, `_start`).
- `docs/BUGS-FOUND.md`: marcar Bug 34 como **ARREGLADO en PR-B2**,
  manteniendo la nota "pendiente verificación e2e con Claude CLI
  real (scope PR-D1)" como en Bug 32.

## Fuera de scope (explícito)

- **No modifica el prompt de auto-project** (`_build_system_prompt`).
  Las reglas positivas del PR-43/45 siguen siendo el primer gate; esto
  es el segundo gate, no su reemplazo.
- **No detecta escrituras vía `Bash`** (ej. `mkdir /tmp/x`, `cat >
  /tmp/y`). Los patrones Bash son ambiguos (un `cd /tmp` solo no es
  una escritura) y exigirían un parser shell que excede el budget. En
  el flow observado en prod Bug 34, Claude también invoca `Write` para
  los ficheros reales (ver tabla 2026-04-18 en BUGS-FOUND.md), así que
  el gate Write cubre el caso. Bash-only queda como mejora futura.
- **No mueve ficheros** de `/tmp/` al `project_directory`. Si se
  detecta violación, el post-hook `_auto_project_finalize` actuará como
  hasta ahora (rmtree del dir vacío, orphan cleanup). El usuario ve el
  motivo en el banner de clarification y decide si re-lanzar o
  descartar.
- **No toca `bin/task-executor.py::_run_llm`** (el runner legacy sin
  adapter). Ese path se usa en chat directo y no atraviesa el flow de
  auto-project; Bug 34 no aplica.
- **No migra el runtime capability check** (`capability_service.
  evaluate_runtime_event`) para que cubra este caso. Ese motor
  dispara approval_gate, no clarification; son flujos distintos.
- **No toca la UI.** El banner `TaskDetailsTab.tsx` ya muestra
  `error_code == 'clarification_required'` (PR-B1); con que el nuevo
  error_code `artifacts_outside_cwd` mapee al mismo `waiting_input`
  estado de run, el banner lo recoge. **Verificar en el test que
  `runs_service.finish_run(..., "needs_clarification")` mapea a
  `run.status == 'waiting_input'`** (comportamiento existente; si
  cambió, parar).

## Tests

### Nuevos

`tests/test_claude_adapter_cwd_enforcement.py`:

1. `test_resolve_cwd_creates_missing_project_directory`: construye un
   `task` con `project_directory = <tmpdir>/does-not-exist`; llama
   `ClaudeCodeAdapter._resolve_cwd(task, artifact_root=None)`; espera
   que el dir exista tras la llamada y que el retorno sea el path
   exacto.
2. `test_resolve_cwd_mkdir_error_propagates`: `project_directory` no
   creable (ej. bajo un path con permisos denegados, simulado con
   `monkeypatch.setattr(Path, "mkdir", raise_oserror)`). Espera
   `OSError` o equivalente — el caller debe registrar
   `adapter_exception`. **Si el patch es demasiado invasivo**, cae
   al caso alternativo: pasar `project_directory = "/proc/self/attr"`
   (no writable). Si tampoco es portable, dejar solo el test (1) y
   confiar en el `try/except Exception` existente de `_execute`.
3. `test_write_inside_cwd_stays_success`: stream con `tool_use Write`
   sobre `<cwd>/index.html` → outcome `success`, no clarification.
4. `test_write_absolute_outside_cwd_triggers_clarification`: stream
   con `tool_use Write` sobre `/tmp/test/index.html` y `cwd =
   <tmpdir>/proj`. Espera `outcome == "needs_clarification"`,
   `error_code == "artifacts_outside_cwd"`, `result_text` contiene el
   path infractor. Run en DB queda con `status == "waiting_input"` y
   un event tipo `error` con `payload_json` parseable que incluye
   `offending_paths`.
5. `test_write_relative_path_is_safe`: stream con `tool_use Write`
   input `{"file_path": "README.md"}` (path relativo al cwd). Espera
   `success`. Guard anti-regresión: paths relativos nunca
   disparan.
6. `test_bash_command_referencing_tmp_is_ignored`: stream con
   `tool_use Bash` `{"command": "mkdir /tmp/foo"}` y ningún `Write`.
   Espera `success`. Guard: Bash no dispara (fuera de scope).
7. `test_mixed_write_in_and_out_reports_only_out`: dos `Write`, uno en
   `<cwd>/a.txt` y otro en `/tmp/b.txt`. `offending_paths` contiene
   solo `/tmp/b.txt`.

### Existentes que deben seguir verdes

- `test_claude_adapter_clarification.py` (todos los 11+ casos).
- `test_claude_adapter_start.py` (happy path).
- `test_auto_project.py` (`TestAdapterPromptInjection` + pre/post
  hooks).
- `test_e2e_auto_project_happy_path.py`.
- `test_task_executor_clarification.py` (sentinel → waiting_input).

### Baseline esperada tras el PR

`≥1033 pass` (baseline 2026-04-18). Los tests nuevos suben el `pass`
en 6-7 unidades; no se espera cambio en `errors` ni en `failed`.

## Criterio de hecho

- [ ] `Path(cwd) == Path(task["project_directory"])` en toda llamada a
  `subprocess.Popen` del adapter cuando `project_directory` está set
  (verificado en test (1) + inspección del `Popen.call_args.kwargs`).
- [ ] Stream con `tool_use Write` fuera del cwd produce `run.status
  == 'waiting_input'`, `error_code == 'artifacts_outside_cwd'`, y un
  `backend_run_event` con `payload_json` que lista los paths.
- [ ] Stream con `tool_use Write` dentro del cwd (absoluto o
  relativo) produce `run.status == 'succeeded'`.
- [ ] `pytest -q tests/test_claude_adapter_cwd_enforcement.py` verde.
- [ ] `pytest -q` completo sin regresiones respecto al baseline.
- [ ] `codex-reviewer` sobre el diff: LGTM o findings resueltos.

## Riesgos conocidos

- **Falso positivo con rutas legítimas fuera del cwd**: si un usuario
  configura una tarea para escribir a `~/.config/<app>/<file>`
  (absoluto fuera del project_directory) — por ejemplo, routine que
  toca ficheros del operador —, este gate lo marcará como
  clarification. Mitigación: el gate solo se activa cuando
  `outcome == "success"`; el operador ve el motivo en la UI y puede
  re-lanzar la tarea pulsando retry, o añadir el project_directory
  correcto. Aceptable para MVP; revisitar si aparece un false-positive
  en prod.
- **Symlinks**: `Path.resolve(strict=False)` sigue symlinks. Si el
  `project_directory` es un symlink a `/tmp/x` y el cwd del Popen
  también, un `Write` a `/tmp/x/foo` se considerará DENTRO del cwd.
  Correcto en nuestro caso (symlink farm de PR final 5 para HOME de
  Claude), pero si alguna vez `project_directory` apunta vía symlink a
  un path ajeno, la detección puede fallar. Aceptable; no hay caso en
  prod.
- **Tool names case-sensitive**: Claude CLI 2.1.97 emite `Write`,
  `Edit`, etc. con mayúscula inicial. Si una versión futura cambia a
  minúsculas, el gate no dispara. Mitigación: comparación
  case-insensitive en `_collect_artifacts_outside_cwd`.
- **Stream no-JSON**: el scan tolera líneas no parseables (las
  salta). Ya es el patrón del adapter (líneas 913-920 actuales).

## Notas para Claude Code

- **No tocar el prompt auto-project.** Si en medio del PR aparece la
  tentación de "ya que estoy aquí, endurezco también el prompt", PARA
  y saca a un FIX aparte.
- **No mover ficheros.** El detector solo reporta; reubicar artefactos
  de `/tmp/` a `project_directory` es una decisión UX que no está
  cerrada (¿los copia? ¿los mueve? ¿con qué permisos?). Queda fuera.
- **Mantener el shape del retorno de `_execute`.** El dict incluye
  `status`, `outcome`, `exit_code`, `error_code`, `session_handle`,
  `usage`, `result_text`, `tool_use_count`. No añadir claves: el
  executor consume este shape en varios sitios.
- **Un error_code nuevo no rompe la UI**: el banner amarillo de
  PR-B1 (`TaskDetailsTab.tsx`) se dispara con
  `error_code == 'clarification_required'`. Reusar ese mismo
  error_code en lugar de crear uno nuevo es una opción — mejor
  trade-off: mantener `artifacts_outside_cwd` como error_code
  específico (traceabilidad en logs) y extender el banner para
  cubrirlo. **Decidir en PR**: si extender el banner añade >15 LOC de
  frontend, parar y dejarlo para un FIX de UI aparte; el run queda en
  `waiting_input` y el usuario verá el mensaje en el output de la
  tarea igualmente.
- Commits pequeños, mensaje imperativo en inglés:
  1. `test: failing cases for cwd enforcement and post-run validation`
  2. `fix(adapter): force cwd=project_directory and flag artifacts outside`
  3. `docs(bugs): mark Bug 34 as fixed in PR-B2`
- Antes de pedir review: `python3 -m pytest -q` completo, pegar el
  diff de pass/fail/error respecto al baseline en el PR description.
