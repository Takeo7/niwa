# FIX-20260420 — Update engine reliability (triple-lie bug)

**Tipo:** FIX estructural (fuera del MVP-ROADMAP, post-MVP)
**Esfuerzo:** **L** (3 días de trabajo real)
**Depende de:** ninguna
**Bloquea a:** todo testing manual que requiera actualizar una instalación
existente. Cualquier usuario que haga `./niwa update` hoy puede acabar en
estado inconsistente sin avisos.

## Observación que dispara este FIX

19-20/4/2026. Fresh install en máquina real. Tras merge del FIX-20260420
completion-truth-and-roundtrip (PR #97) que añade migración 018 + nuevo
endpoint + nueva UI, el usuario ejecuta `./niwa update`. El updater reporta:

```
✓ backup: /home/anacruz/.niwa/data/backups/niwa-...
✓ executor
✓ app:image
✓ app:restarted
⚠  systemctl restart niwa-executor.service devolvió 5. Reinicia manualmente: sudo systemctl restart niwa-executor.service
✓ /health OK tras 1 intentos
✓ schema_version: 17 → 17
✓ docker compose ps: app Up
✅ Update completado.
```

**Tres mentiras en la misma salida:**

1. **`✓ app:image`** — `docker compose build` quizá corrió, pero el container sigue
   con el image viejo. Verificable: dentro de `niwa-app` sólo existen
   migraciones 001-017 con timestamp del install original.
2. **`✓ app:restarted`** — falso. `docker logs niwa-app --since 1h` para
   `migration|init_db|error` devuelve **vacío**. El container no reinició con
   el nuevo image.
3. **`✓ schema_version: 17 → 17`** — aceptado como OK. Debería haber sido
   `17 → 18`. Entre `niwa-app/db/migrations/` en el repo (host) ya hay
   `018_*.sql`, pero el contador del updater trata "sin cambio" como
   "nada que hacer" en vez de "schema desincronizado con el código".

Además **4º bug colateral:** el exit 5 de `systemctl` es porque el updater
invoca **system scope** (`sudo systemctl restart`) pero el installer escribió
la unit en **user scope** (`~/.config/systemd/user/...`). Luego recomienda al
usuario un comando equivocado (`sudo systemctl restart ...`) que también
falla. Forma tradicional de pegarle otro parche encima.

**Resultado neto para el usuario:** DB en schema 17, código nuevo esperando
schema 18, ejecutor con código viejo, sin ninguna alarma. El sistema arranca,
`/health` devuelve `{"ok": true}`, todo parece bien. El siguiente `POST
/api/tasks/:id/respond` crashearía en runtime al intentar escribir columnas
inexistentes.

## Raíz

El update engine **no verifica lo que afirma**. Trust-but-don't-verify.

- Tras `docker compose build` no comprueba que el image que corre el
  container coincide con el recién construido (SHA / image id).
- Tras `docker compose up -d` no comprueba que el container fue realmente
  recreado (`docker inspect` StartedAt, Image id antes/después).
- Tras esperar a `/health` no comprueba que las migraciones han aplicado
  — compara `schema_version` antes y después pero no las cruza con
  `max(migrations/*.sql)` del repo.
- Hardcodea scope systemd sin leer estado del install.
- Pinta `✓` en pasos que no ha verificado, y `✅ Update completado` aunque
  hubo un warning de systemctl.

## Principio del fix

**Cada `✓` del updater debe ser una afirmación verificable**. Si no se puede
verificar, no se imprime. Si se verifica y falla, rollback — no warning.

Reemplazamos "healthcheck triple" por un **contrato post-update que Niwa
debe cumplir o el updater rueda atrás** (y lo reporta honestamente):

| Afirmación | Cómo se verifica | Qué hacemos si falla |
|---|---|---|
| Image nuevo construido | `docker inspect niwa-app:<tag>` devuelve image id ≠ pre-update | rollback |
| Container corre el image nuevo | `docker inspect niwa-app` `.Image` == post-build image id | **force-recreate**, re-verificar, si vuelve a fallar rollback |
| Container arrancó tras el update | `docker inspect niwa-app` `.State.StartedAt` > pre-update timestamp | rollback |
| Migraciones aplicadas | `schema_version` tras boot ≥ `max(ls migrations/*.sql)` del repo | rollback |
| App responde /health | HTTP 200 dentro de timeout 60s | rollback |
| Executor reiniciado | systemctl `is-active` en el scope correcto | fail explícito |

**Rollback** = `git reset --hard` al commit pre-update + restore SQLite del
backup + `docker compose up -d --force-recreate` con el image previo. Log
de auditoría explícito. Exit code ≠ 0.

## Scope — archivos a tocar

### Core del fix

- **`bin/update_engine.py`** — reescritura parcial:
  - Nueva función `_detect_systemd_scope(service_name)` que lee `~/.niwa/.install-config.json`
    (sección nueva, ver abajo). Fallback: probar `systemctl --user status` y si responde
    con exit 0 o 3 (inactive), es user scope; cualquier otra cosa es system.
  - Nueva función `_build_and_verify_image(service='app')`:
    - Captura image id previo: `docker inspect --format '{{.Image}}' niwa-app`.
    - `docker compose build app` (sin `--no-cache` por defecto; flag `NIWA_UPDATE_REBUILD=1` permite forzar).
    - Captura image id del image tag recién construido: `docker inspect --format '{{.Id}}' niwa-app:<tag>`.
    - Si pre == post → no había cambios o build cache total; OK informar y continuar.
    - Si pre != post → cambió, anota para verificar recreate.
  - Nueva función `_recreate_and_verify_container(service='app', expected_image_id)`:
    - `docker compose up -d --force-recreate app`.
    - Poll cada 2s hasta 30s: `docker inspect niwa-app` `.State.Running` == true y `.Image` == expected_image_id.
    - Fail si timeout.
  - Nueva función `_wait_for_migrations(expected_min_version, timeout=60s)`:
    - Cada 2s: conectar a la DB (mismo path que el backup), leer
      `SELECT MAX(version) FROM schema_version`.
    - Devolver OK cuando `max_version >= expected_min_version`.
    - Fail con error descriptivo si timeout; el error incluye el version
      real y el esperado.
  - Función `_compute_expected_schema_version()` que cuenta ficheros
    `NNN_*.sql` en `niwa-app/db/migrations/` del repo ya actualizado,
    extrae el NNN máximo, y lo devuelve como entero.
  - Reescribir `run_niwa_update()` para orquestar estos pasos en orden:
    ```
    pre_state = capture_state()      # image_id, container_startedAt, schema_version, commit_sha
    git_pull()
    backup_db()
    try:
        copy_host_files()            # bin/task-executor.py, etc.
        new_image = build_and_verify_image()
        recreate_and_verify_container(new_image)
        wait_for_migrations(expected_min=compute_expected_schema_version())
        wait_for_health()
        restart_executor_in_correct_scope()
        report_success(pre_state, current_state())
    except UpdateVerificationFailure as e:
        rollback(pre_state, reason=str(e))
        exit_code = 1
    ```
  - Imprimir cada paso con su **resultado verificado**, no con optimismo.
  - Si el usuario ya tenía cambios locales no pusheados (`git status --porcelain`
    no vacío antes de `git pull`), abortar antes de tocar nada.

- **`bin/task-executor.py`** — sin cambios. El executor como código no sabe
  de updates.

### State del install

- **`setup.py`** — al final de la instalación, escribir
  `~/.niwa/.install-config.json` con al menos:
  ```json
  {
    "install_version": "0.2.x",
    "install_timestamp": "...",
    "systemd_scope": "user",
    "systemd_units": {
      "executor": "niwa-executor.service",
      "hosting": "niwa-hosting.service"
    },
    "compose_file": "/home/anacruz/.niwa/docker-compose.yml",
    "db_path": "/home/anacruz/.niwa/data/niwa.sqlite3",
    "repo_path": "/home/anacruz/niwa"
  }
  ```
  Este fichero es la fuente única de verdad para el updater. Si falta,
  el updater usa heurísticas con warning.

### Backend

- **`niwa-app/backend/app.py`** — endpoint `/health` hoy devuelve
  `{"ok": true}`. Extenderlo (o añadir `/health/detail`) con
  `{ok, schema_version, code_expected_schema, pending_migrations: []}`.
  El updater consume esto para verificar, no solo un OK genérico.
  Mantener `/health` plano para compatibilidad externa.
  Fast path: no consultes migraciones en cada request — cachea al arranque.

### Tests

- **`tests/test_update_engine_image_recreate.py`** (nuevo) — mockea docker CLI
  con fixtures:
  - `build returns same image id` → updater reporta "no image change" pero no marca OK hasta verificar container corre el image correcto.
  - `build returns new image id + up fails to recreate` → updater fuerza recreate y si sigue fallando rueda atrás.
  - `build returns new image id + up recreates correctly` → verify checks pass.
- **`tests/test_update_engine_migration_verification.py`** (nuevo):
  - Migration dir has 018_*.sql, schema_version stays 17 → updater falla con mensaje claro.
  - Migration dir has 018_*.sql, schema_version bumps a 18 dentro del timeout → updater OK.
  - Schema goes al revés (18 → 17 por rollback de otro origen) → updater lo detecta y marca rollback.
- **`tests/test_update_engine_systemd_scope.py`** (nuevo):
  - install-config dice `user` → updater usa `systemctl --user`.
  - install-config dice `system` → usa `sudo systemctl`.
  - install-config ausente → fallback con warning.
  - systemctl falla con exit 5 → mensaje al usuario con el comando correcto según scope detectado, no genérico.
- **`tests/test_update_engine_rollback.py`** (nuevo):
  - Happy path con todas las verificaciones OK.
  - Migration timeout → rollback verifica: git reset_hard, DB restaurada, exit != 0.
  - Image verification failure → rollback igual.

### Docs

- **`docs/RELEASE-RUNBOOK.md`** — actualizar la sección "Flujo del update en
  1 párrafo" para reflejar el nuevo contrato verificable. Añadir sección
  "Failure modes y rollback" explicando qué ves cuando algo falla.
- **`docs/BUGS-FOUND.md`** — añadir:
  - **Bug 37**: updater hardcodea system scope de systemd.
  - **Bug 38**: updater no verifica que el container corra el image nuevo.
  - **Bug 39**: updater acepta `schema_version: X → X` como OK sin
    cruzar con migraciones esperadas.
  - Marcar los 3 como fixed en `FIX-20260420-update-engine-reliability`.
- **`CLAUDE.md`** — si el brief DOCS-20260419-handbook ya se implementó,
  actualizar la receta de "añadir una migración" para mencionar que el
  updater la verificará automáticamente; y la sección operativa con el
  nuevo contrato verificable.

## Fuera de scope (explícito)

- **No** migrar `niwa-app/db/migrations/` a un volume mount. Queda
  baked en el image — el fix es que el container corra el image
  nuevo, no que evitemos rebuildear.
- **No** añadir un "auto-update on startup" del container. El updater
  es el único camino.
- **No** arreglar `niwa update` UI button que hoy solo genera comando.
  Sigue siendo out-of-scope; este FIX mejora el CLI, no la UI.
- **No** reescribir `setup.py` más allá de escribir `.install-config.json`.
- **No** tocar Docker Compose plantilla (`docker-compose.yml.tmpl`) para
  añadir healthchecks a containers. Conversación separada — añadiría
  complejidad y no es necesario para este fix.

## Criterio de hecho (verificable punto por punto)

Reproducir el bug observado como test de regresión. Debe fallar antes del
fix y pasar después.

- [ ] **Fixture**: instalación con DB schema 17, commit pre-018. Añadir
  migración 018 al repo. Simular `docker compose build` que produce image
  id distinto pero `docker compose up -d` que no recrea (mockeado).
  Test: `update_engine.run()` termina con exit != 0 y mensaje
  "container runs stale image (expected <new_id>, got <old_id>)". Rollback
  deja DB en schema 17 sin tocar, git HEAD en commit previo.
- [ ] **Fixture igual pero `docker compose up -d` recrea correctamente**.
  Test: update termina con exit 0, DB en schema 18, mensaje honesto
  `schema_version: 17 → 18, 1 migration applied`.
- [ ] **Fixture systemd scope user**: `.install-config.json` con scope=user.
  Test: updater invoca `systemctl --user restart niwa-executor.service`,
  no sudo. Si falla, mensaje al usuario es `systemctl --user restart
  niwa-executor.service`.
- [ ] **Fixture sin .install-config.json** (upgrade desde instalaciones
  previas que no lo escribían): updater detecta scope por probe y continúa
  con warning visible `WARN: install-config.json missing, detecting scope
  by probe`.
- [ ] **Real**: el escenario exacto de 20260419 deja la DB en schema 17
  y el código esperando 18. Tras el fix, el updater muestra:
  ```
  ✗ schema verification failed: expected version 18, got 17 after 60s
    timeout. Pending migrations: [018_completion_truth.sql].
    Rolling back to <pre_commit_sha>...
    Rolled back git HEAD, restored DB from backup.
  ```
  Exit ≠ 0.
- [ ] `pytest -q` sin regresiones ≥ baseline del PR anterior.
- [ ] Codex reviewer sobre el diff, blockers resueltos.

## Riesgos conocidos

- **`docker compose up -d --force-recreate`** causa un segundo de downtime
  garantizado. Aceptable para un update. Documentar.
- **Migraciones muy lentas** (>60s) podrían dar falso positivo de
  timeout. Hacer el timeout configurable vía `NIWA_UPDATE_MIGRATION_TIMEOUT`
  con default 60s; documentar para operadores que tengan DBs grandes.
- **`.install-config.json` en instalaciones pre-fix**: no existe. El
  updater debe lidiar con ausencia sin crashear. Por eso el fallback por
  probe con warning.
- **Compose project name** puede variar entre `niwa`, `niwa-app` y otros
  dependiendo de cómo se instalara. El updater debería leerlo de
  `.install-config.json` o del `docker-compose.yml`. NO hardcodear.
- **Rollback de Docker image**: si el image nuevo se construyó y el viejo
  se borró por cleanup de Docker, rollback completo no es posible. En
  ese caso, rollback de git + DB y dejar el image nuevo con warning
  "code reverted but image could not be rolled back; next update will
  produce the clean image". Documentar como limitación aceptada.

## Orden de implementación sugerido

1. Reproducir el bug. Capturar `docker compose build` + `docker inspect`
   outputs reales de una instalación con este síntoma y convertirlo en
   fixture (`tests/fixtures/update_engine/`).
2. Escribir el test que reproduce el bug → test rojo.
3. `capture_state` + `_build_and_verify_image` + unit tests.
4. `_recreate_and_verify_container` + unit tests.
5. `_compute_expected_schema_version` + `_wait_for_migrations` + unit tests.
6. `_detect_systemd_scope` + leer `.install-config.json` + unit tests.
7. Reescribir `run_niwa_update()` orquestando todo, con rollback.
8. Actualizar `/health` endpoint con detalle.
9. Actualizar `setup.py` para escribir `.install-config.json`.
10. Tests end-to-end mockeando docker CLI.
11. Docs (RELEASE-RUNBOOK, BUGS-FOUND).
12. `pytest -q` completo.
13. Codex reviewer.
14. PR.

## Notas para Claude Code

- **Este brief es tu contrato.** Si encuentras un atajo tentador (tipo
  "pues force-recreate siempre y ya está"), párate y piensa si eso
  esconde el problema o lo arregla. Force-recreate siempre añade un
  segundo de downtime a updates triviales sin valor. Preferimos
  verificación correcta.
- **Commits pequeños**, uno por paso del orden.
- **El test que reproduce el bug de 20260419 es gold standard.** Si no
  existe como test, el fix no está hecho aunque todos los tests pasen.
- **Codex reviewer obligatorio** — PR L con lógica crítica.
- **Commit final del PR**:
  ```
  fix: update engine verifies what it claims (image, container, migrations, scope)

  Replace trust-based "healthcheck triple" with a verifiable contract:
  each ✓ in the updater output is now backed by an inspection step
  (image id, container Image, schema_version >= max(migrations/)).
  Writes .install-config.json on install to record systemd scope and
  compose paths; updater reads it to invoke the correct commands.
  Hard rollback (git reset + DB restore) on any verification failure.
  Closes Bug 37, 38, 39.  Captures the 2026-04-19 silent-downgrade
  incident as regression test.
  ```

## Qué hace el usuario cuando este FIX esté mergeado

Su instalación actual está **rota pero estable** (schema 17, código esperando
18, ejecutor viejo). Cuando este FIX entre en `v0.2`:

1. Reinstalar desde cero:
   ```bash
   docker compose -f ~/.niwa/docker-compose.yml down
   rm -rf ~/.niwa
   cd ~/niwa && git pull origin v0.2
   ./niwa install --quick --mode core --yes
   ```
2. Reconfigurar Claude setup-token en la UI.
3. Crear tarea nueva y validar que el happy path funciona (completion
   detection + round-trip).
4. Confirmar que cuando haya próximos FIX/feature, `./niwa update`
   funciona honestamente.

**No** aplicar migración 018 a mano. No es un patch que queramos normalizar.
