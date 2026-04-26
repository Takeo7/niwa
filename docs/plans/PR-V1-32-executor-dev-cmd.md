# PR-V1-32 — `niwa-executor dev start/stop`

**Tipo:** FEATURE (CLI ergonomics)
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

Dos subcomandos nuevos para gestionar el ciclo de
backend+frontend (lo que hoy hace `make dev`):

- `niwa-executor dev start [--detach]` — arranca uvicorn +
  vite. Sin flag, foreground. Con `--detach`, en background con
  PID file.
- `niwa-executor dev stop` — busca el PID file y mata uvicorn +
  vite limpiamente.

## Por qué

Hoy `make dev` es foreground; cerrar la terminal mata todo. Si
el usuario lo lanza con nohup, no hay manera limpia de pararlo
sin `pkill -f vite`. La pareja del autor ya tropezó con esto.

## Scope

```
backend/app/niwa_cli.py        # +cmd_dev_start, cmd_dev_stop
backend/tests/test_niwa_cli.py # +2 casos
```

**Hard-cap: 150 LOC.**

## Contrato

### `niwa-executor dev start [--detach]`

1. Localiza el repo (mismo helper que PR-V1-31).
2. Verifica que `~/.niwa/venv/bin/uvicorn` existe; si no, falla
   con mensaje "run ./bootstrap.sh first".
3. Verifica que `<repo>/frontend/node_modules` existe; si no,
   sugiere `cd <repo>/frontend && npm install`.
4. Sin `--detach`:
   - exec `make dev` (foreground, comportamiento actual).
5. Con `--detach`:
   - Lanza uvicorn en background → guarda PID en
     `~/.niwa/run/uvicorn.pid`.
   - Lanza vite en background → guarda PID en
     `~/.niwa/run/vite.pid`.
   - Ambos redirigen stdout+stderr a `~/.niwa/logs/dev.log`.
   - Imprime URLs (8000 backend, 5173 frontend) y comando
     `niwa-executor dev stop` para parar.

### `niwa-executor dev stop`

1. Lee `~/.niwa/run/uvicorn.pid` y `~/.niwa/run/vite.pid`.
2. Para cada PID: `kill -TERM <pid>`, espera 3s, si sigue vivo
   `kill -KILL <pid>`.
3. Limpia los PID files.
4. Imprime "dev stopped" o "no dev process running" si los PID
   files no existen.

### `niwa-executor dev status`

Bonus barato: lee los PID files, hace `kill -0 <pid>` para ver
si están vivos, imprime estado.

## Fuera de scope

- No reemplaza `make dev` — coexiste. El Makefile sigue.
- No persiste los PIDs entre reboots; tras reboot los procesos
  mueren igual y los PID files quedan stale (los limpia el
  start siguiente).
- No gestiona logs rotation.

## Tests

- `test_dev_start_detach_writes_pid_files`: monkeypatch
  `subprocess.Popen` para evitar arranque real, verificar que
  los PID files se crean con el PID devuelto.
- `test_dev_stop_kills_pids_from_files`: monkeypatch `os.kill`,
  verificar que se llama con cada PID.
- `test_dev_stop_no_pid_files_is_noop`: ejecutar sin PID files →
  exit 0 con mensaje "no dev process running".

## Criterio de hecho

- [ ] `niwa-executor dev start --detach` deja uvicorn+vite
      corriendo y devuelve a la shell.
- [ ] `niwa-executor dev stop` los para limpios.
- [ ] `niwa-executor dev status` reporta correctamente.
- [ ] Sin `--detach`, comportamiento idéntico a `make dev`.
