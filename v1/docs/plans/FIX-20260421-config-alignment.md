# FIX-20260421 — Config alignment (templates ↔ config.py)

**Tipo:** FIX (fuera de Semana 5 — regresión de integración detectada
en revisión de Semana 4 por product partner)
**Esfuerzo:** S
**Depende de:** PR-V1-16 (cierre de Semana 4)

## Qué

Alinea el contrato entre `config.toml.tmpl` + templates de servicio
y el parser en `app/config.py`. Hoy están desalineados: el template
escribe secciones `[claude]`, `[db]`, `[executor]` y los servicios
exportan `NIWA_CONFIG_PATH`, mientras `config.py` lee `[server]` +
`[database]` y espera `NIWA_CONFIG`. Resultado práctico: un install
hecho con `bootstrap.sh` seguido de `niwa-executor start` termina
con el backend apuntando a una DB distinta de la que Alembic
migró.

## Por qué (el bug concreto)

1. **Env var name mismatch.**
   - `v1/templates/com.niwa.executor.plist.tmpl:17` → `NIWA_CONFIG_PATH`
   - `v1/templates/niwa-executor.service.tmpl:9`  → `NIWA_CONFIG_PATH`
   - `v1/backend/app/config.py:41`               → `NIWA_CONFIG`

   Funciona hoy por coincidencia porque el default
   (`~/.niwa/config.toml`) es el mismo path que el template escribe.
   Cambiar el template a otro path rompería sin explicación.

2. **Sección del TOML mismatch (el grave).**
   - `v1/templates/config.toml.tmpl` emite `[claude]`, `[db]`,
     `[executor]`.
   - `v1/backend/app/config.py:44-45` lee `[server]` y `[database]`.

   El backend ignora `[db].path` y usa `DEFAULT_DB_PATH =
   v1/data/niwa-v1.sqlite3`. El bootstrap migra la DB en
   `~/.niwa/data/niwa-v1.sqlite3`. **El backend lee una DB vacía
   mientras la migrada queda huérfana.**

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── config.py                 # aliasear env var + leer [claude]/[db]/[executor]
└── tests/
    └── test_config.py            # NUEVO: alias env, lectura de secciones
```

## Fuera de scope

- No se toca `adapter/claude_code.py` — `resolve_cli_path()` sigue
  usando `NIWA_CLAUDE_CLI` env var. Exponer `Settings.claude_cli`
  como fallback es follow-up (útil para `make dev` sin servicio),
  no bloqueante.
- No se añade compat con `[server]`/`[database]` legacy. Cero
  usuarios con esos toml hoy; no pagamos coste de mantenerlo.
- Templates NO se tocan — son la fuente de verdad. El código se
  alinea a ellos.

## Contrato tras el fix

**Env var:** `NIWA_CONFIG_PATH` preferido; `NIWA_CONFIG` sigue
aceptado como alias (deprecado en un comentario). Si ambos están
definidos, gana `NIWA_CONFIG_PATH`.

**TOML secciones leídas:**

```toml
[claude]
cli = "/path/to/claude"         # string, expuesto como Settings.claude_cli
timeout = 1800                  # int, expuesto como Settings.claude_timeout_s

[db]
path = "/absolute/path.sqlite3" # string, expuesto como Settings.db_path

[executor]
poll_interval_seconds = 5       # int, expuesto como Settings.executor_poll_interval_s
```

**`Settings` dataclass extendida:**

```python
@dataclass(frozen=True)
class Settings:
    db_path: Path
    bind_host: str                       # queda, default 127.0.0.1 (no en template hoy)
    bind_port: int                       # queda, default 8000 (no en template hoy)
    claude_cli: str | None               # NUEVO, None si no está
    claude_timeout_s: int                # NUEVO, default 1800
    executor_poll_interval_s: int        # NUEVO, default 5
    config_source: Path | None
```

`bind_host`/`bind_port` se mantienen con defaults — no están en el
template actual, pero quitarlos rompería `main.py`. Un PR futuro
puede añadir `[server]` al template si se quiere.

## Tests

- **Nuevo** `tests/test_config.py` (~50 LOC):
  - `NIWA_CONFIG_PATH` gana sobre `NIWA_CONFIG` si ambos definidos.
  - `NIWA_CONFIG` sigue funcionando (alias).
  - `[claude].cli` y `.timeout` se leen.
  - `[db].path` se lee (NO `[database].path`).
  - `[executor].poll_interval_seconds` se lee.
  - TOML ausente → defaults sensatos.

- **Existentes que no deben regresar:**
  - `tests/test_models.py:207-214` usa `NIWA_CONFIG` — sigue
    funcionando gracias al alias.
  - El resto del backend consume `Settings.db_path`, nada más.

**Baseline tras el fix:** 107 (actual) + 6 nuevos = **113 passed**.

## Criterio de hecho

- [ ] `bootstrap.sh` + `niwa-executor start` + `uvicorn` arrancan
      todos contra `~/.niwa/data/niwa-v1.sqlite3` (la DB migrada).
- [ ] `test_config.py` con 6 casos pasa.
- [ ] `pytest -q` → ≥113 passed, 0 regresiones.
- [ ] Codex-reviewer ejecutado; skip OK por S.
- [ ] Cero cambios a templates, adapter, executor core, finalize,
      niwa_cli, frontend.

## Riesgos conocidos

- **Alias de env var:** si el usuario tiene **ambas** variables
  apuntando a paths distintos (muy improbable en MVP), el alias
  elige `NIWA_CONFIG_PATH` silenciosamente. El comentario en el
  código lo deja explícito.

## Notas para el implementador

- Hard-cap 200 LOC (S).
- `tomllib` solo lee TOML — no hay TOML escribiendo en scope.
- Commits sugeridos:
  1. `fix(config): read claude/db/executor sections from toml`
  2. `fix(config): accept NIWA_CONFIG_PATH as preferred env var name`
  3. `test(config): coverage for new sections + env var alias`
