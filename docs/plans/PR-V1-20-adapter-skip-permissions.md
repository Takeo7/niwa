# PR-V1-20 — Adapter: `--dangerously-skip-permissions` siempre

**Tipo:** FIX (bug crítico de integración detectado en smoke real del MVP)
**Semana:** 6 (primer PR)
**Esfuerzo:** S
**Depende de:** PR-V1-19 (Semana 5 cerrada)

## Qué

Añadir `--dangerously-skip-permissions` a los args por defecto del
`ClaudeCodeAdapter` y del flujo de triage. Sin este flag, el Claude
CLI en modo `-p --output-format stream-json` pide aprobación
interactiva en cada `Write`/`Edit`/`Bash`/`MultiEdit`; como el
stream-json no tiene canal de aprobación, las tool_use se rechazan
automáticamente y el run termina sin artefactos.

## Por qué

Bug descubierto en el smoke real (2026-04-22). 6 tareas ejecutadas
contra Claude CLI autenticado, las 6 terminaron `verification_failed`
con `error_code=no_artifacts`. Evidencia en `run_events` de task 1:

```json
{"type": "tool_result", "is_error": true,
 "content": "Claude requested permissions to write to
   /Users/.../README.md, but you haven't granted it yet."}
```

Task 5 además reportó 4 denegaciones "This command requires
approval". El proyecto estaba marcado `autonomy_mode=dangerous`,
pero ese flag solo se consume en `finalize.py` (auto-merge),
nunca llega al adapter. Niwa no puede escribir ficheros hoy.

## Decisión de producto

**El flag se pasa siempre**, independiente de `autonomy_mode`.
Racional:

- Niwa ejecuta SIEMPRE en una rama dedicada `niwa/task-N-<slug>`
  aislada del `main` del proyecto (PR-V1-08).
- Todas las escrituras del adapter quedan en esa rama.
- La diferencia real entre modos `safe` y `dangerous` vive
  post-hoc en `finalize.py`: `safe` abre PR para que el humano
  mergee, `dangerous` auto-mergea con `gh pr merge --squash`.
- La "safety" del modo `safe` está en el gate de merge, no en
  la ejecución del adapter. Ejecutar sin permisos dentro del
  workspace aislado es coherente con el diseño.
- La alternativa (implementar canal de aprobación interactivo
  en stream-json) es scope v1.x+, no MVP.

Registrar la decisión en `v1/docs/HANDBOOK.md` con un párrafo
que explique por qué `--dangerously-skip-permissions` es seguro
dado el modelo de rama por tarea + gate en merge.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── adapters/
│   │   └── claude_code.py        # DEFAULT_ARGS += flag
│   └── triage.py                 # el adapter spawn usa mismo flag
├── tests/
│   ├── test_adapter.py           # regression: args contain flag
│   └── test_triage.py            # regression: adapter spawn args
└── docs/
    └── HANDBOOK.md               # sección "Permissions model"
```

**Hard-cap: 150 LOC netas** (código+tests).

## Fuera de scope

- **No cambiar `autonomy_mode` semantics** — sigue controlando
  solo auto-merge post-finalize.
- No añadir canal de aprobación interactivo.
- No tocar el executor ni finalize — siguen igual.
- No introducir un flag opcional `skip_permissions: bool` en el
  constructor — siempre activo. YAGNI.

## Contrato tras el fix

`ClaudeCodeAdapter.DEFAULT_ARGS` debe ser:

```python
DEFAULT_ARGS: tuple[str, ...] = (
    "-p",
    "--output-format", "stream-json",
    "--verbose",
    "--dangerously-skip-permissions",
)
```

Mismo contrato para el adapter que `triage_task` spawna.

## Tests

- **`tests/test_adapter.py`** nuevo caso:
  `test_default_args_include_dangerously_skip_permissions` —
  verifica que al spawnear, `cmd` contiene el flag.
- **`tests/test_triage.py`** nuevo caso:
  `test_triage_adapter_spawns_with_permissions_flag`.
- **Regression:** si algún test previo mockeaba `DEFAULT_ARGS` o
  asumía el set anterior, actualizar.

**Baseline tras el fix:** 128 + 2 nuevos = **130 passed**.

## Criterio de hecho

- [ ] `grep -n "dangerously-skip-permissions"
       v1/backend/app/adapters/claude_code.py` devuelve ≥1 match
      dentro de `DEFAULT_ARGS`.
- [ ] Lo mismo en `v1/backend/app/triage.py` (mismo flag en el
      adapter que spawn).
- [ ] `pytest -q` → 130 passed, 0 regresiones.
- [ ] `HANDBOOK.md` tiene sección "Permissions model" con 1-2
      párrafos explicando la decisión.
- [ ] Codex-reviewer (opcional en S, pero úsalo — es fix del core
      del motor).

## Riesgos conocidos

- **Irreversibilidad local:** con el flag activo, Claude puede
  tocar cualquier fichero accesible desde el cwd. Está mitigado
  por la rama dedicada, pero si el usuario configura
  `project.local_path` apuntando a un path con cambios sin
  commitear, teóricamente Claude podría modificar esos. El guard
  de `prepare_task_branch` (PR-V1-08) que exige tree limpio
  antes de arrancar cubre este escenario — ningún archivo del
  usuario queda en riesgo.

## Notas para el implementador

- Cambio MINIMAL. No aproveches para refactorizar `DEFAULT_ARGS`
  a un builder, constructor con kwargs, etc. Añadir un string
  a la tupla y mover hacia la derecha del tuple.
- Commit message: `fix(adapter): always pass
  --dangerously-skip-permissions to claude CLI`.
