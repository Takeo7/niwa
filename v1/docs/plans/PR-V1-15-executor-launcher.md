# PR-V1-15 — Executor launcher + `niwa-executor` CLI

**Semana:** 4
**Esfuerzo:** M
**Depende de:** PR-V1-14 mergeado (service file + venv existen).

## Qué

Carga y arranca el servicio que PR-V1-14 escribió. Añade un CLI
wrapper `niwa-executor` con subcomandos `start | stop | restart |
status | logs` que envuelve `launchctl` (macOS) o `systemctl --user`
(Linux).

- `start`: carga + arranca. Idempotente. Al boot/login, el servicio
  ya está cargado porque los templates incluyen `RunAtLoad=true`
  (macOS) y `WantedBy=default.target` (Linux).
- `stop`: descarga + para.
- `restart`: stop + start (o `launchctl kickstart -k` si hay que
  recargar el plist).
- `status`: imprime `launchctl list <label>` o `systemctl --user
  status niwa-executor` con exit code mapeado.
- `logs [--follow] [--lines N]`: lee `~/.niwa/logs/executor.log`
  con `tail -f` o `tail -n N`.

El CLI se registra como entry point del paquete backend:

```toml
# v1/backend/pyproject.toml
[project.scripts]
niwa-executor = "app.niwa_cli:main"
```

Tras `bootstrap.sh` (PR-14), `~/.niwa/venv/bin/niwa-executor` es
invocable directamente.

## Por qué

Sin este PR, el service file de PR-14 queda inerte: el usuario
tiene que recordar los flags de `launchctl load -w` o `systemctl
--user enable --now` y los paths exactos. Con `niwa-executor
start`, una sola línea arranca el executor como daemon de usuario
que sobrevive reboot/login.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── niwa_cli.py                         # nuevo, ~180 LOC
├── pyproject.toml                          # +entry point
└── tests/
    └── test_niwa_cli.py                    # nuevo, ~150 LOC
```

**HARD-CAP 400 LOC netas código+tests** (sin HANDBOOK). Proyección
~350. Si excedes, PARAS.

## Fuera de scope (explícito)

- **No toca `bootstrap.sh` ni los templates** de PR-14.
- **No instala dependencias**. Todo stdlib (`argparse`,
  `subprocess`, `pathlib`, `platform`, `shutil`).
- **No gestiona logs rotation**. `~/.niwa/logs/executor.log` crece
  indefinidamente; rotate es follow-up.
- **No hay modo `uninstall`**. Follow-up (junto con
  `bootstrap.sh --remove`).
- **No hay healthcheck activo** más allá de `status`. No se
  conecta al backend HTTP para verificar E2E.
- **No hay diff entre el plist escrito y el runtime**. Solo
  dispara comandos.
- **No hay modo Windows.** Linux + macOS.
- **No toca el executor daemon en sí** — `app/executor` intacto.

## Dependencias nuevas

- **Ninguna**.

## Contrato funcional

### Platform dispatch

`platform.system()`:
- `"Darwin"` → `launchctl` backend.
- `"Linux"` → `systemctl --user` backend.
- otro → exit 1 con mensaje "Unsupported OS".

### Paths canónicos

```python
NIWA_HOME = Path(os.environ.get("NIWA_HOME", str(Path.home() / ".niwa")))
LOG_PATH = NIWA_HOME / "logs" / "executor.log"

# macOS:
PLIST_PATH = Path.home() / "Library/LaunchAgents/com.niwa.executor.plist"
LAUNCHD_LABEL = "com.niwa.executor"

# Linux:
SYSTEMD_UNIT = "niwa-executor.service"
```

`NIWA_HOME` env var overridable para testing.

### Subcomandos

```python
def cmd_start(args) -> int:
    if platform.system() == "Darwin":
        _ensure_plist_exists()
        return _run(["launchctl", "load", "-w", str(PLIST_PATH)])
    elif platform.system() == "Linux":
        return _run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT])
    return 1

def cmd_stop(args) -> int:
    if platform.system() == "Darwin":
        return _run(["launchctl", "unload", "-w", str(PLIST_PATH)])
    elif platform.system() == "Linux":
        return _run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT])
    return 1

def cmd_restart(args) -> int:
    if platform.system() == "Darwin":
        return _run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"])
    elif platform.system() == "Linux":
        return _run(["systemctl", "--user", "restart", SYSTEMD_UNIT])
    return 1

def cmd_status(args) -> int:
    if platform.system() == "Darwin":
        return _run(["launchctl", "list", LAUNCHD_LABEL])
    elif platform.system() == "Linux":
        return _run(["systemctl", "--user", "status", SYSTEMD_UNIT])
    return 1

def cmd_logs(args) -> int:
    if not LOG_PATH.exists():
        print(f"log not found at {LOG_PATH}; run 'niwa-executor start' first")
        return 1
    cmd = ["tail", "-n", str(args.lines)]
    if args.follow:
        cmd.append("-f")
    cmd.append(str(LOG_PATH))
    # tail es stdin-friendly; subprocess.run con stdout heredado
    return _run(cmd, inherit_stdio=True)
```

### `_run(cmd, inherit_stdio=False)`

Wrapper sobre `subprocess.run`:
- Si `inherit_stdio`: hereda stdout/stderr del proceso padre (para
  `status`, `logs`). `stdin` también se hereda en `logs -f` para
  que `Ctrl-C` mate el tail.
- Si no: `capture_output=True`; stdout/stderr se imprimen del
  buffer.
- Devuelve `exit_code` del proceso.
- Captura `FileNotFoundError` (p. ej. `launchctl` ausente) y
  devuelve 127 con mensaje útil.

### `_ensure_plist_exists()`

Si `PLIST_PATH` no existe → print error "service file missing, run
bootstrap.sh first" y `sys.exit(1)`.

### `main()`

Argparse con subparsers:
```
niwa-executor start
niwa-executor stop
niwa-executor restart
niwa-executor status
niwa-executor logs [--follow] [--lines 50]
```

Default `--lines` = 50. `--follow` → `tail -f`.

Exit code del CLI = exit code del subcomando.

### Entry point en `pyproject.toml`

```toml
[project.scripts]
niwa-executor = "app.niwa_cli:main"
```

Tras `pip install -e v1/backend` dentro del venv de `~/.niwa`,
`~/.niwa/venv/bin/niwa-executor` existe y funciona.

## Tests

### Nuevos — `tests/test_niwa_cli.py` (5-6 casos)

Mockean `subprocess.run` con `monkeypatch.setattr(subprocess,
"run", _fake_run)` y `platform.system` para controlar OS dispatch.
Helper `_capture(caller, subcommand_argv)` que invoca
`app.niwa_cli.main([...])` sin spawnear subprocess real.

1. `test_start_macos_calls_launchctl_load` — `platform.system` →
   "Darwin"; ensure_plist crea fake plist en tmp_path (via
   `NIWA_HOME` override). `niwa-executor start` dispara
   `launchctl load -w <plist>`.
2. `test_start_linux_calls_systemctl_enable_now` — "Linux";
   `niwa-executor start` → `systemctl --user enable --now
   niwa-executor.service`.
3. `test_start_macos_fails_when_plist_missing` — Darwin, plist
   no existe. Exit 1, stderr menciona "service file missing".
4. `test_stop_dispatches_correct_cmd_per_platform` — parametrizado
   Darwin/Linux, verifica `launchctl unload -w` / `systemctl
   --user disable --now`.
5. `test_status_returns_subcmd_exit_code` — fake run devuelve
   exit 3; `niwa-executor status` devuelve 3.
6. `test_logs_missing_file_returns_1` — LOG_PATH no existe, exit
   1 con mensaje útil.
7. (opcional si cabe) `test_logs_invokes_tail_with_lines_and_follow`
   — fake run; verifica que el cmd es `["tail", "-n", "100", "-f",
   "<path>"]` cuando se pasa `--lines 100 --follow`.
8. (opcional) `test_unsupported_os_returns_1` — `platform.system`
   → "Windows"; exit 1.

### Baseline tras PR-V1-15

- Backend: **≥99 passed** (94 actuales + 5-6 CLI).
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `niwa-executor` registrado como entry point; tras `pip
  install -e`, `which niwa-executor` devuelve path al script del
  venv.
- [ ] `niwa-executor start` en macOS carga el plist con `launchctl
  load -w`; en Linux `systemctl --user enable --now
  niwa-executor`.
- [ ] `stop/restart/status` dispatchean al comando correcto por
  OS.
- [ ] `logs [--follow]` lee `~/.niwa/logs/executor.log` con `tail`.
- [ ] Plist ausente → mensaje util "run bootstrap.sh first" +
  exit 1.
- [ ] `pytest -q tests/test_niwa_cli.py` → 5-6 passed.
- [ ] `pytest -q` completo → ≥99 passed, 0 regresiones.
- [ ] HANDBOOK sección "Executor launcher (PR-V1-15)" con CLI
  reference, dispatch por OS, path del log, cómo se arranca al
  boot/login.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~350.

## Riesgos conocidos

- **`launchctl load -w` deprecated en macOS 10.11+** (favor de
  `bootstrap` + `bootout`). MVP usa `load` porque funciona en
  todas las versiones target del autor; si deprecation real,
  follow-up.
- **`systemctl --user` requiere `XDG_RUNTIME_DIR`** correcto. En
  setups headless (ssh sin `loginctl enable-linger`) puede no
  funcionar. Usuario documentado.
- **`kickstart -k` requiere macOS 10.10+**. Precondición asumida.
- **Logs crecen indefinidamente**. Rotate follow-up.
- **`tail -f` no termina limpio en `tests` si no mockeas**. Tests
  NO pasan `--follow`; solo happy path `--lines N`.
- **Entry point `niwa-executor`** colisiona con un hipotético
  comando del sistema. Unlikely pero posible; `pip install` solo
  lo registra dentro del venv, así que no hay colisión global.
- **`os.getuid()` en macOS `kickstart`** asume sesión GUI. En ssh
  puede ser `-` (sin sesión); fallback: `launchctl stop + start`.
  MVP: usa `kickstart` y documenta.

## Notas para Claude Code

- Commits sugeridos (4-5):
  1. `feat(cli): niwa-executor argparse skeleton`
  2. `feat(cli): start/stop/restart dispatch per platform`
  3. `feat(cli): status and logs subcommands`
  4. `chore(backend): register niwa-executor entry point`
  5. `test(cli): subcommand dispatch and error paths`
  6. `docs(v1): handbook executor launcher section`
- `app/niwa_cli.py` plano; sin clases de infra. Subcomandos como
  funciones, dispatch map `{"start": cmd_start, ...}`.
- `_run` centraliza subprocess para facilitar mock.
- Para tests: `monkeypatch.setattr("platform.system", lambda: ...)`
  y `monkeypatch.setattr("subprocess.run", fake_run)`.
- NO dependencias de test nuevas.
- **Si algo del brief es ambiguo, PARA y reporta.**
