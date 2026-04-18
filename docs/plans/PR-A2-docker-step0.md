# PR-A2 — installer Step 0: offer to install Docker when missing

**Hito:** A
**Esfuerzo:** S
**Depende de:** ninguna
**Bloquea a:** ninguno

## Qué

Cuando el Step 0 del installer (interactivo y `--quick`) detecta que
Docker no está presente, en lugar de imprimir el hint y salir, **ofrece
instalarlo** con confirmación explícita del usuario:

- Linux: `curl -fsSL https://get.docker.com | sh` (universal).
- macOS: `brew install --cask docker` (Docker Desktop) si `brew` está
  disponible; si no, imprime el hint actual y sale.
- Otras plataformas (`other`): comportamiento actual (imprimir hint +
  salir).

Tras aceptar e instalar, re-detecta. Si sigue fallando, sale con el
mensaje actual.

## Por qué

Conecta con el happy path §1.1: *"Instalación sin fricción. `./niwa
install --quick --mode core --yes` en máquina limpia — incluyendo
Docker si falta — termina mostrando credenciales admin al usuario."*

## Scope — archivos que toca

- `setup.py:676-684` (`step_detection`): sustituir el exit por un
  prompt que llama a un nuevo helper `_offer_docker_install()` antes
  de salir.
- `setup.py:3495-3500` (`build_quick_config` pre-flight): idéntica
  sustitución, pero respetando `args.yes` (ver "Decisiones").
- `setup.py` nuevo helper `_offer_docker_install(plat: str,
  non_interactive: bool) -> bool` que encapsula el prompt + ejecución
  + re-detección. Devuelve `True` si Docker quedó disponible.
- `tests/test_pr_a2_docker_step0.py` (nuevo): tests unitarios con
  `monkeypatch` de `detect_docker`, `which`, `subprocess.run`.

## Fuera de scope (explícito)

- No se toca el `niwa` bash wrapper (detectar Python3 missing queda
  fuera; abre un FIX aparte si aparece).
- No se añade soporte para Windows / WSL — `other` mantiene el
  comportamiento actual.
- No se intenta `sudo` automáticamente: si el proceso no es root y
  `get.docker.com` requiere privilegios, la llamada fallará con el
  stderr del instalador; el mensaje sugiere re-ejecutar con `sudo`.
- No se instala `colima` ni `orbstack` aunque sean preferibles en
  macOS: un único camino por plataforma para no inflar el scope.
- No se toca el sistema de Step 0 para otras dependencias (`python3`,
  `claude`, etc.) — su flujo ya existe.
- No se reemplaza el mensaje final de "re-run ./niwa install" cuando
  el usuario rechaza o la instalación falla.

## Decisiones a validar (humano confirma en el review)

1. **`--yes` auto-acepta instalar Docker?** Propuesta: **no**. `--yes`
   salta la confirmación final del wizard, pero instalar Docker es
   una acción con privilegios + red + ~300 MB. Si el proceso no tiene
   TTY (modo CI, pipe), tampoco puede promptear: en ese caso saldrá
   con error como hoy. Alternativa si rechazas: flag nuevo
   `--install-docker` explícito para permitirlo bajo `--yes`.
2. **macOS sin `brew`**: propuesta = fallback al hint + salir. Sin
   auto-instalar brew (`/bin/bash -c "$(curl -fsSL .../install.sh)"`)
   porque instala Xcode CLT y es intrusivo.
3. Comandos ejecutados: `sh -c "curl -fsSL https://get.docker.com |
   sh"` en Linux, `brew install --cask docker` en macOS. No se
   arrancan servicios (`systemctl enable docker`) ni se añade el
   usuario al grupo `docker` automáticamente — el hint textual sigue
   apareciendo con esos pasos post-instalación si el usuario los
   necesita.

## Tests

- **Nuevos:** `tests/test_pr_a2_docker_step0.py`:
  - `docker_present` → `_offer_docker_install` no se invoca.
  - `docker_missing + user accepts + subprocess ok + re-detect ok` →
    devuelve True, no sale.
  - `docker_missing + user declines` → `SystemExit(1)` con hint
    impreso.
  - `docker_missing + non_interactive=True (--yes sin
    --install-docker)` → `SystemExit(1)` (no promptea).
  - `docker_missing + subprocess fails (rc != 0)` → `SystemExit(1)`
    con stderr del comando en el log.
  - macOS sin `brew` → `SystemExit(1)` + hint, sin prompt.
- **Existentes que deben seguir verdes:**
  `tests/test_pr11_quick_install.py` (usa `detect_docker` stubbed a
  available=True, no toca este camino; verificar que la nueva firma
  no rompe la fixture `_stub_docker`).
- **Baseline esperada tras el PR:** `≥1039 pass / ≤60 failed / ≤104
  errors` (baseline 2026-04-18: 1033 pass / 60 failed / 104 errors;
  sumo ~6 tests nuevos).

## Criterio de hecho

- [ ] En Linux sin Docker + TTY + `y` al prompt → se ejecuta
  `get.docker.com`, si Docker queda disponible el wizard continúa.
- [ ] En Linux sin Docker + `n` al prompt → el installer sale con
  mensaje claro y exit code 1.
- [ ] En `--quick --yes` sin Docker → sale con error (no promptea).
- [ ] En macOS sin `brew` → imprime hint y sale (no intenta nada
  raro).
- [ ] `pytest -q tests/test_pr_a2_docker_step0.py` verde.
- [ ] `pytest -q` sin regresiones vs baseline.
- [ ] Review Codex resuelto (o "LGTM").

## Riesgos conocidos

- **`get.docker.com` requiere root.** Si el installer corre como
  usuario normal, `sh` fallará a mitad. Mitigación: captura de
  stderr + mensaje claro ("re-ejecuta con `sudo`"). No intento
  auto-sudo: es peor romper silenciosamente que fallar explícito.
- **Red caída durante curl.** El comando fallará por timeout; lo
  tratamos como "instalación fallida" y salimos con hint.
- **`brew install --cask docker` abre el .app en Applications pero
  no arranca Docker Desktop.** La re-detección puede fallar porque
  el daemon no está arriba. Mitigación: mensaje post-install
  explícito ("abre Docker Desktop y re-ejecuta ./niwa install").

## Notas para Claude Code

- Helper nuevo aislado y testeable con `monkeypatch`; no inlinearlo.
- Reusar `print_install_hint("docker")` para el mensaje de fallback;
  no duplicar texto.
- Commits pequeños, mensaje imperativo en inglés.
- Antes de pedir review: `pytest -q` completo y pegar diff vs
  baseline en el body del PR.
