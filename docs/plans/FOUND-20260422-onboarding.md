# FOUND-20260422 — onboarding frictions deferred to v1.1

**Observado durante:** smoke de install fresca en
`~/Documents/niwa-fresh` del 2026-04-22, antes del PR-V1-26. El
reporte completo listó 12 fricciones; PR-V1-26 cerró los cinco
bloqueadores duros (python3.11, PATH del executor, prereqs README,
sección "First project", bootstrap footer). Las cuatro que siguen
aquí son follow-ups para v1.1 — documentadas pero no bloqueantes
para el MVP.

## Frictions diferidas

- **7 — `niwa-executor stop` no para `make dev`.** El CLI
  launcher controla solo el servicio launchd/systemd; `make dev`
  corre backend + frontend en el shell donde se invocó y queda
  huérfano al llamar `stop`. Fix = rediseño de control (PID file
  compartido, o `make dev-daemon` con nohup + pidfile). No-trivial:
  cruza executor + Makefile + UI readiness. v1.1.

- **8 — `~/.niwa` es singleton por usuario, no hay per-clone
  isolation.** Bootstrap sobreescribe `~/.niwa/config.toml`, el
  service file y la DB cuando se ejecuta desde un segundo clone.
  Es by-design en el MVP (single-user, single-machine) pero bloquea
  instalaciones paralelas para testing. Fix futuro = `NIWA_HOME`
  override via env var + soporte en templates + niwa-executor label
  derivado del path. Deferrable hasta que haya caso de uso real.

- **9 — plist/service huérfano si se mueve el repo.** El service
  file renderizado apunta a `{{REPO_DIR}}` absoluto; si el usuario
  hace `mv ~/repos/niwa ~/work/niwa` tras bootstrap, launchd/
  systemd siguen apuntando al path antiguo y fallan al arrancar
  sin mensaje claro. Fix propuesto = `niwa-executor doctor` que
  detecte drift entre `{{REPO_DIR}}` en el service file y
  `SCRIPT_DIR` actual, con sugerencia de rerun `./bootstrap.sh`.
  v1.1.

- **10 — `make dev` corre en foreground.** Cerrar el terminal
  mata backend + frontend sin warning. Fix parche (README warning)
  aplicado en PR-V1-26. Fix real = `make dev-daemon` con nohup
  + pidfile + `make dev-logs` para seguir el stderr. v1.1.

## Fricciones cerradas en PR-V1-26

Para referencia, los cinco bloqueadores que sí se cerraron:

1. `python3` vs `python3.11` en macOS con brew → `bootstrap.sh`
   prefiere `python3.11` explícitamente.
2. `niwa-executor` fuera del PATH post-bootstrap → README incluye
   `source ~/.niwa/venv/bin/activate` en los pasos de install; el
   footer del bootstrap también lo menciona.
3. README sin instrucciones de Claude CLI → sección "Install"
   con `npm install -g @anthropic-ai/claude-code && claude` + `/login`.
4. README sin mención de `gh` → añadido como prereq opcional.
5. Sin documentación de "primer proyecto" → sección "First project"
   completa con paso a paso de la UI.

## Referencia

- Brief del PR-V1-26:
  `docs/plans/PR-V1-26-onboarding-polish.md`.
- Reporte del smoke del 2026-04-22 (humano) — 12 fricciones
  originales.
