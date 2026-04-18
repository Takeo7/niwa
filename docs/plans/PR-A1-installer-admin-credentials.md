# PR-A1 — Show admin credentials in install summary

**Hito:** A
**Esfuerzo:** S
**Depende de:** ninguna
**Bloquea a:** PR-A5 (el widget "Qué falta" asume que el operador sabe
su password admin para logear-se y ver `/api/readiness`).

## Qué

Tras un `./niwa install --quick --mode {core,assistant} --yes` el
installer termina imprimiendo el smoke result y las tres líneas
`Update/Restore/Backup`, pero **nunca muestra las credenciales admin**
— a pesar de que `setup.py:3575-3577` promete "displayed once in the
summary" y `setup.py:3629` dice "shown after install". Este PR
cumple esa promesa: imprime `username` + `password` en el resumen
final cuando la password acaba de generarse (fresh install o
`--rotate-secrets`). En reinstall-preserve se imprime solo el
username + el path del fichero `secrets/mcp.env` donde el operador
puede consultarla si la olvida.

## Por qué

Happy path §1 del MVP: *"`./niwa install --quick ...` en máquina
limpia termina mostrando credenciales admin al usuario."* Hoy el
operador tiene que abrir `secrets/mcp.env` a mano (o leer el email
interno que no existe) para logarse por primera vez.

## Contexto — cómo se calcula hoy `cfg.password`

En `build_quick_config` (`setup.py:3564-3578`) la password se
resuelve en tres ramas mutuamente excluyentes:

1. `--admin-password <val>` → `cfg.password = <val>` (operador ya lo
   sabe, no re-imprimir).
2. `existing and not rotate and existing["NIWA_APP_PASSWORD"]` →
   preservada de install previo (operador ya debería tenerla).
3. else → `generate_token()[:24]` (auto-generada en esta sesión).

Solo el caso (3) **exige** impresión en claro; los casos (1) y (2)
se gestionan con un mensaje suave ("credentials preserved; see
secrets/mcp.env"). Esto se logra con un flag nuevo
`cfg.password_auto_generated: bool` poblado en `build_quick_config`.

El punto de impresión natural es `quick_install`
(`setup.py:3779-3808`), justo tras `ok("Quick install completed ...")`
y antes del bloque de `niwa update/restore/backup`.

## Scope — archivos que toca

- `setup.py`:
  - `WizardConfig` (alrededor de líneas ~500-600, buscar dataclass):
    añadir campo `password_auto_generated: bool = False`.
  - `build_quick_config` (`setup.py:3564-3578`): poblar el flag según
    cuál rama genera/preserva la password.
  - `quick_install` (tras `setup.py:3780`, antes del `info("Update:
    ...")`): bloque nuevo de ~10 líneas que imprime credenciales o
    "preserved" según el flag.
- `tests/test_pr11_quick_install.py`:
  - Extender `TestBuildQuickConfig` con un test que verifica que
    `password_auto_generated` es `True` en caso (3) y `False` en los
    casos (1) y (2).
  - No añadir test E2E del output de `quick_install` — ese flujo
    depende de docker/smoke real y no se mockea en esta suite.

## Fuera de scope (explícito)

- No toca el flujo interactivo (`execute_install`, `setup.py:833-834`)
  donde el operador teclea la password; ahí no hay que imprimirla.
- No cambia cómo se genera ni dónde se persiste la password
  (`secrets/mcp.env`, `NIWA_APP_PASSWORD`).
- No añade logging a fichero — solo stdout. El comentario en
  `setup.py:3575-3577` explícitamente prohíbe escribirla a logs.
- No modifica `print_quick_plan` (`setup.py:3616-3639`) ni cambia el
  prompt de confirmación.

## Tests

- **Nuevos en `tests/test_pr11_quick_install.py`:**
  - `test_password_auto_generated_flag_true_on_fresh` (caso 3).
  - `test_password_auto_generated_flag_false_on_explicit` (caso 1,
    `--admin-password`).
  - `test_password_auto_generated_flag_false_on_preserved` (caso 2,
    simulando `existing` con `NIWA_APP_PASSWORD` — probablemente
    requiere monkeypatch sobre `_load_existing_mcp_env`).
- **Existentes que deben seguir verdes:** toda
  `tests/test_pr11_quick_install.py` (15 tests actuales).
- **Baseline esperada tras el PR:** `≥1036 pass / ≤60 failed / ≤104
  errors` (baseline actual 1033 pass + 3 tests nuevos).

## Criterio de hecho

- [ ] Fresh install (`./niwa install --quick --mode core --yes` en
  tmp dir limpio) imprime en stdout dos líneas al estilo:
  ```
  Admin login:   user=niwa  password=<24 chars>
  (stored in secrets/mcp.env — rotate with --rotate-secrets)
  ```
- [ ] Reinstall sin `--rotate-secrets` imprime:
  ```
  Admin login:   user=niwa  (password preserved from previous install;
                            see <niwa_home>/secrets/mcp.env)
  ```
- [ ] `--admin-password foo` imprime sin exponer la password teclada
  (operador ya la conoce; mismo mensaje que reinstall-preserve).
- [ ] `pytest tests/test_pr11_quick_install.py -q` pasa los 3 tests
  nuevos + los existentes.
- [ ] `pytest -q` sin regresiones respecto al baseline.
- [ ] LOC total del diff ≤ 80 (brief aparte).

## Riesgos conocidos

- **Leak en scroll-back del terminal**: la password queda visible en
  la terminal del operador. Mitigación: solo ocurre una vez por
  install fresh; el operador tiene que copiarla ahora o re-leerla de
  `secrets/mcp.env`. Es el trade-off consciente del comentario
  `setup.py:3575-3577`.
- **CI/logs**: si alguien ejecuta `./niwa install` bajo `tee` o
  `script(1)` el password queda fuera del repo pero en los artefactos
  de su CI. No lo evitamos en este PR — el contrato es "don't run
  interactive installers in CI without redaction".
- **`--admin-password` shell-history leak**: preexistente. No lo
  arregla este PR (scope).

## Notas para Claude Code

- Esfuerzo S: puedes saltar `codex-reviewer`; corre `pytest -q`
  completo antes de abrir el PR.
- Commits pequeños: `feat: expose admin credentials in install
  summary` + `test: cover password_auto_generated flag`.
- **Ojo** al localizar la dataclass `WizardConfig` — verifica en vivo
  con `grep -n "class WizardConfig"` antes de añadir el campo (el
  brief no fija la línea porque el fichero es de 4069 líneas y cambia
  con frecuencia).
- Si al implementar descubres que el diff excede 80 LOC o que el
  flag necesita propagarse más allá de `build_quick_config` +
  `quick_install`, PARA y renegocia el brief.
