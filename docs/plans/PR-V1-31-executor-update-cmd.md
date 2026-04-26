# PR-V1-31 — `niwa-executor update` wrapper

**Tipo:** FEATURE (CLI ergonomics)
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

Nuevo subcomando `niwa-executor update` que automatiza el ciclo
de actualización: `git pull` + `pip install -e backend` (si
pyproject cambió) + `alembic upgrade head` (si hay migraciones
nuevas) + `niwa-executor restart`. Una sola invocación.

## Por qué

Cada vez que el autor mergea algo en main, su pareja tiene que
ejecutar manualmente la secuencia. Cuatro comandos, fáciles de
olvidar el orden o saltarse uno (especialmente `alembic upgrade`).
Un wrapper elimina esa fricción.

## Scope

```
backend/app/niwa_cli.py     # +cmd_update + dispatch entry
backend/tests/test_niwa_cli.py  # +1 caso
```

**Hard-cap: 100 LOC.**

## Contrato

Nuevo subcomando:

```
niwa-executor update [--no-restart]
```

Pipeline:

1. **Localiza el repo Niwa.** Asume que `niwa-executor` está
   instalado desde un editable install — busca el path del repo
   resolviendo `app.__file__` y subiendo niveles hasta encontrar
   `.git/`. Si no encuentra, falla con mensaje claro.
2. `git -C <repo> fetch origin main`
3. Compara `git rev-parse HEAD` con `git rev-parse origin/main`.
   Si iguales, imprime "Already up to date" y termina exit 0.
4. Captura el SHA antes y después del pull para detectar qué
   cambió:
   ```
   BEFORE=$(git rev-parse HEAD)
   git pull origin main --ff-only
   AFTER=$(git rev-parse HEAD)
   ```
   Si `--ff-only` falla (divergencia), imprime instrucciones para
   resolver manualmente y exit 1.
5. Detecta cambios:
   - Si `git diff --name-only $BEFORE..$AFTER | grep
     'backend/pyproject.toml'` no vacío → ejecuta `pip install
     -e backend`.
   - Si `git diff --name-only $BEFORE..$AFTER | grep
     'backend/migrations/versions/'` no vacío → ejecuta
     `alembic upgrade head` con el `db_url` correcto del config.
   - Si ningún cambio relevante → skip ambos.
6. Si `--no-restart` no se pasó: `niwa-executor restart`.
7. Imprime resumen.

## Fuera de scope

- No actualiza `npm install` ni hace `npm run build`. El
  frontend en dev (vite) hot-reloadea solo, en producción no
  hay frontend deployed.
- No hace rollback automático si algo falla — operador maneja.
- No detecta conflictos en config.toml — si el template cambió,
  el usuario lo ve manualmente.

## Tests

- `test_update_skips_when_already_up_to_date`: mock `git
  rev-parse` para devolver el mismo SHA antes/después → exit 0
  sin pip ni alembic.
- `test_update_runs_pip_when_pyproject_changed`: monkeypatch del
  diff para incluir `backend/pyproject.toml`, asserta que
  `subprocess.run` se llama con `pip install -e backend`.
- `test_update_with_no_restart_skips_restart`.

## Criterio de hecho

- [ ] `niwa-executor update` desde dentro del repo actualiza,
      reinstala, migra y reinicia.
- [ ] `niwa-executor update --no-restart` no toca el servicio.
- [ ] `pytest -q` pasa con +3 nuevos.

## Notas

Si el orquestador encuentra que el detect-of-repo-path es
ambiguo (varios clones), añade flag `--repo-path <path>`
opcional.
