# PR-A3 — Retire `{instance}` naming; Niwa is single-instance

**Hito:** A
**Esfuerzo:** S-M
**Depende de:** ninguna
**Bloquea a:** ninguno

## Qué

Elimina la maquinaria de *multi-instance* del installer y del update
engine. `cfg.instance_name`, el flag CLI `--instance`, el prompt
`step_naming` y todo el sufijo `{instance}` en unit names, launchd
labels, rutas y contenedores desaparecen. El proyecto asume **una
única instancia por host**, siempre llamada `niwa`.

## Por qué

- El happy path del MVP (§1.1) exige `./niwa install --quick --mode
  core --yes` sin fricción. Un nombre de instancia configurable
  nunca se ha usado fuera de tests y genera artefactos feos del
  tipo `niwa-niwa-executor.service` (ver comentario en
  `bin/update_engine.py:283-286`, arrastrado desde PR-58b1).
- La sección §3 del roadmap marca "no refactors aprovechando": esto
  **no** es refactor oportunista, es una deuda declarada en §4
  Hito A.

## Scope — archivos que toca

### Installer (`setup.py`)

- `setup.py:164-167` — eliminar `valid_instance_name` (ya no se
  usa).
- `setup.py:657` — quitar `self.instance_name` de `WizardConfig`.
- `setup.py:784-796` — `step_naming`: borrar prompt "Instance name";
  el único prompt superviviente es `cfg.niwa_home` con default
  `~/.niwa`.
- `setup.py:1368,1509,1615,1625,1661,1706-1709,1750,1753,1764,1773,1905`
  — sustituir `cfg.instance_name` por literal `"niwa"` en:
    - `INSTANCE_NAME` env var (se sigue escribiendo con valor
      fijo `"niwa"` para no romper readers externos ya pusheados).
    - `NIWA_APP_URL` (hostname `niwa-app`).
    - Listados de imágenes docker (`niwa-tasks-mcp`, etc.).
    - Mensajes de `warn`/`print` con `docker logs niwa-*`.
- `setup.py:1933,1993` — launchd label `com.niwa.executor` (antes
  `com.niwa.{instance}.executor`).
- `setup.py:2139,2179` — rutas `/home/niwa/.niwa`, `/opt/niwa`
  hardcoded.
- `setup.py:2361,2379,2409` — systemd unit `niwa-executor.service`
  + descripción sin sufijo.
- `setup.py:2447-2477` — `_uninstall_service` / `_uninstall_task_executor`:
  firma pierde el parámetro `instance`; construye `niwa-<service_type>.service`
  directo.
- `setup.py:2499,2549,2562,2574,2599,2627` — hosting: launchd label
  y unit name sin `{instance}`.
- `setup.py:2885-2919,2942-3014,3044-3070` — `cmd_status`,
  `cmd_uninstall`, `cmd_logs`: dejar de leer `INSTANCE_NAME` de
  `mcp.env`; usar literal `"niwa"`. `cmd_uninstall` llama a
  `_uninstall_task_executor(install_dir)` con la nueva firma.
- `setup.py:3579-3583` — `build_quick_config`: borrar asignación de
  `cfg.instance_name`; `cfg.niwa_home` default pasa a `Path.home()
  / ".niwa"`.
- `setup.py:3707` — quitar la línea "Instance name" del resumen de
  summary.
- `setup.py:4089-4092` — borrar `p_install.add_argument("--instance",
  ...)`. `--dir` pierde la mención a `~/.<instance>` → `~/.niwa`.

### Update engine (`bin/update_engine.py`)

- `bin/update_engine.py:282-303` — `_restart_executor`: service
  name fijo `niwa-executor.service`; borrar la derivación
  `ctx.install_dir.name.replace(".", "")` y su comentario.

### Tests tocados (actualizar, no crear otros)

- `tests/test_pr11_quick_install.py:40-100` — casos que ejercitan
  `--instance stg`: reemplazar por comprobación de que
  `--instance` **no** es aceptado (argparse error) y que el install
  dir cae en `~/.niwa` por defecto.
- `tests/test_pr11_quick_install.py:330-360` — sacar `self.instance`
  del stub args y borrar `assert cfg.instance_name == "niwa"`.
- `tests/test_pr11_quick_install.py:560-575` — el snapshot de env
  sigue conteniendo `INSTANCE_NAME="niwa"` (lo mantenemos por
  estabilidad externa).
- `tests/test_pr58b1_update_engine.py:260-281` — cambiar la
  aserción de `"niwa-niwa-executor.service"` a
  `"niwa-executor.service"`; renombrar el test a
  `test_systemctl_restart_uses_fixed_service_name` y actualizar el
  docstring.
- `tests/test_installer_hosting_path.py:85-137` — la regex que
  valida la construcción de `niwa_home` en la rama `run_as_root`
  pasa a literal `Path("/home/niwa") / ".niwa"`; los comentarios
  que hablen de `<instance>` se reescriben a `.niwa`.

## Fuera de scope (explícito)

- **No** tocar nada dentro de `niwa-app/backend/`, `niwa-app/frontend/`,
  `bin/task-executor.py`, adapters o scheduler. El paradigma "una
  sola instancia" ya está asumido ahí.
- **No** eliminar la variable de entorno `INSTANCE_NAME=niwa` de
  `mcp.env`: la dejamos escrita con el literal fijo. Borrarla
  obliga a mirar cada lector (compose vars, healthchecks externos);
  ese barrido es scope creep.
- **No** migrar installs existentes con unit `niwa-niwa-executor.service`.
  `niwa update` contra esos hosts detectará que el nuevo unit
  `niwa-executor.service` no existe y escribirá `needs_restart=True`
  + warning — el operador reinstala. Nota en el PR body.
- **No** añadir detección de "legacy unit" en `_uninstall_task_executor`.
  Un uninstall desde binario nuevo sobre install viejo dejará el
  unit antiguo colgando; se documenta en el PR body como known-cost.
- **No** tocar `docs/archive/PORTABILITY-PLAN-2026-04-07.md` ni
  `INSTALL.md` para no meter cambios de docs no esenciales. Si hay
  mención a `--instance` en `INSTALL.md` la arreglo en su sitio
  (una línea) — cualquier cosa mayor sale aparte.

## Tests

- **Nuevos (en `tests/test_pr11_quick_install.py`):**
  - `test_install_parser_rejects_instance_flag`: `--instance` ya no
    existe en argparse → `SystemExit(2)`.
  - `test_quick_config_defaults_home_to_dot_niwa`:
    `build_quick_config(args_sin_dir)` → `cfg.niwa_home ==
    Path.home() / ".niwa"`.
  - `test_executor_unit_name_is_fixed`: snapshot-light del unit
    escrito (match sobre la ruta final) → `niwa-executor.service`.
- **Reescritos (baseline no cambia de nombre):**
  - `tests/test_pr58b1_update_engine.py::test_systemctl_restart_uses_fixed_service_name`
  - `tests/test_installer_hosting_path.py::test_root_install_puts_hosting_under_niwa_user`
    (la regex ahora comprueba literal `".niwa"`).
- **Existentes que deben seguir verdes:** todo el resto del
  baseline. Nada de `niwa-app/`, `bin/task-executor.py`,
  `scheduler.py`, `adapters/` toca; esos tests no deberían moverse.
- **Baseline esperada tras el PR:** igual o superior al último
  punto medido (post-PR-B3). Números `pass` solo suben o
  quedan igual. Si al correr `pytest -q` completo queda algo por
  debajo, se declara antes de abrir el PR.

## Criterio de hecho

- [ ] `python3 setup.py install --quick --help` no muestra
  `--instance`.
- [ ] `grep -rn "cfg.instance_name" setup.py` devuelve **cero**
  hits.
- [ ] `grep -rn "instance_name" bin/update_engine.py` devuelve
  **cero** hits.
- [ ] En una instalación limpia simulada con `build_quick_config`
  + `install_task_executor` (sin ejecutar systemctl — los tests
  ya mockean), el unit escrito es `niwa-executor.service` y
  `cfg.niwa_home == ~/.niwa`.
- [ ] `pytest -q` sin regresiones respecto al baseline.
- [ ] Codex review resuelto (o "LGTM" para blocker/major).

## Riesgos conocidos

- **Unit huérfano en hosts existentes.** Hosts con
  `niwa-niwa-executor.service` seguirán arrancándose por systemd
  hasta que el operador reinstale. Mitigación: nota en el PR body
  + mención en `docs/RELEASE-RUNBOOK.md` si procede (verifico que
  exista esa sección; si no, no lo añado en este PR).
- **Readers externos de `INSTANCE_NAME`.** Mitigación: se mantiene
  escrito con valor fijo `"niwa"` — compatibilidad conservada.
- **Test `test_pr11_quick_install.py` es grande y contiene muchos
  usos colaterales.** Mitigación: no reformateo nada fuera de los
  bloques declarados; edits puntuales.

## Notas para Claude Code

- Si al tocar tests descubro un caso que depende del nombre
  antiguo por un motivo no documentado en el brief, **paro** y
  pregunto antes de cambiarlo.
- Commits pequeños, mensaje imperativo en inglés:
  1. `test: rewrite pr11/pr58b1/hosting-path for single instance`
  2. `refactor(setup): drop instance_name field and --instance flag`
  3. `refactor(update_engine): use fixed niwa-executor.service`
  4. (si hace falta) `docs: trim {instance} mentions in INSTALL.md`
- Antes de abrir el PR: `pytest -q`, copiar el diff
  pass/fail/error vs baseline en el PR body.
- Esfuerzo S-M → Codex reviewer opcional. Por el riesgo de romper
  el installer, **sí** lo invoco.
