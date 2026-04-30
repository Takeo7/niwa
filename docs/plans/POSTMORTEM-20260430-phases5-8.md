# Post-mortem: Fases 5-8 Niwa MVP

**Fecha:** 2026-04-30  
**Rama:** `claude/review-latest-changes-dBTTr`  
**PR:** #156  
**Alcance:** Phases 5 (Auth + Networking), 6 (Security), 7 (MCP Server), 8 (Observability)

---

## Resumen ejecutivo

Se implementaron las cuatro fases restantes del MVP de Niwa en una única sesión extendida sobre la rama `claude/review-latest-changes-dBTTr` (base: PR-V1-37). El resultado final: 253 tests pasando (58 nuevos), 47 archivos añadidos/modificados, 2462 líneas de código.

---

## Lo que salió bien

### Diseño opt-in de auth
La decisión de hacer auth completamente opt-in (activado solo cuando existe `~/.niwa/auth/password.hash`) fue correcta. Permite desarrollo local sin fricción mientras que la seguridad se activa explícitamente en producción. Ningún test existente rompió por este cambio.

### MCP sin dependencia externa
Implementar el protocolo JSON-RPC 2.0 manualmente en lugar de usar el SDK `mcp` evitó añadir una dependencia no pre-aprobada. El resultado es más simple y fácil de auditar: un único archivo `server.py` de ~200 líneas.

### Redacción de secretos modular
Centralizar la redacción en `security/redaction.py` con patrones explícitos hace que sea fácil añadir nuevos formatos. La función `redact()` es pura (sin efectos laterales), lo que facilitó el testing.

### Estructura de tests
Los 58 tests nuevos cubren todos los paths críticos: autenticación con y sin auth habilitada, scopes de tokens, todos los tools del MCP, patrones de redacción, audit log con filtros y paginación, y métricas. La separación en archivos por feature (`test_auth.py`, `test_mcp.py`, etc.) mantiene la suite organizada.

---

## Problemas encontrados y resoluciones

### 1. Confusión de base de rama
**Problema:** Las fases 0-4 se implementaron sobre el commit original del MVP (base antigua), pero main había avanzado a PR-V1-37. Había divergencia significativa entre las dos bases.

**Resolución:** Las fases 5-8 se implementaron directamente sobre `claude/review-latest-changes-dBTTr` = main actualizado. No intenté merge de la rama vieja; el trabajo de fases 0-4 quedó en `claude/pr-deploy-01-deploy-local` como referencia para futuros PRs de deploy.

**Lección:** Al arrancar una sesión larga, verificar desde el primer momento que la rama de trabajo tiene la base correcta (`git merge-base --fork-point origin/main HEAD`).

### 2. Signatura incorrecta en MCP tasks tool
**Problema:** Al integrar el MCP server con `services/tasks.py`, llamé `service.respond_to_task(db, task_id, TaskRespondPayload(response=response))` pero la función recibe `response: str`, no un payload object.

**Resolución:** Cambio trivial: pasar `response` directamente. El test `test_mcp_task_respond` lo capturó antes de push.

**Lección:** Al envolver servicios existentes en una nueva capa (MCP), revisar las signaturas exactas en lugar de asumir que coinciden con los schemas de la API REST.

### 3. Cancel/retry ausentes en tasks service (main)
**Problema:** `cancel_task` y `retry_task` existían en mi contexto de fases anteriores pero no en main (PR-V1-37 no los tenía). Los tests de métricas fallaron al importar excepciones no definidas.

**Resolución:** Implementé ambas funciones en `services/tasks.py` (con `_CANCELLABLE` y `_RETRYABLE` frozensets) y los endpoints en `api/tasks.py`. Esto quedó incluido como parte de Phase 5.

**Lección:** Antes de implementar capas superiores (MCP, métricas), verificar que los servicios base que necesito existen en la rama objetivo con `grep -r "def cancel_task"`.

### 4. HEAD_REVISION en test_models.py
**Problema:** Al añadir dos migraciones Alembic nuevas, el test `test_alembic_upgrade_records_expected_revision` falló porque `HEAD_REVISION` apuntaba al anterior head.

**Resolución:** Actualizar `HEAD_REVISION = "e2f3a4b5c6d7"` y añadir `"sessions"`, `"api_tokens"`, `"audit_events"` a `EXPECTED_TABLES`.

**Lección:** Cada migración nueva requiere actualizar `test_models.py`. Sería útil automatizar esta verificación.

---

## Decisiones de diseño discutibles

### Token env var vs DB token en MCP
`NIWA_MCP_TOKEN` env var concede scope `admin` implícito. Esto es conveniente para dev/bootstrap pero podría ser un vector si el env var se filtra. Alternativa más segura: requerir siempre un token DB con scopes explícitos. No cambié esto porque el SPEC lo describe como un caso de uso legítimo ("dev/bootstrap").

### Audit log sin integración en endpoints
El modelo y servicio de audit log están implementados pero los endpoints (auth, MCP, tasks) no llaman a `log_event()` aún. Esto significa que el audit log existe pero no se alimenta automáticamente. La integración completa quedaría para un siguiente PR (SEC-02 completo).

### Caddyfile generator sin hot-reload
`write_caddyfile()` escribe el archivo pero no envía SIGUSR1 a Caddy para recargarlo. En producción, el usuario tendría que recargar manualmente o habría que añadir un mecanismo de notificación.

---

## Métricas

| Métrica | Valor |
|---------|-------|
| Tests antes | 195 pasando |
| Tests después | 253 pasando, 1 skipped |
| Tests nuevos | 58 |
| Archivos nuevos | 34 |
| Archivos modificados | 13 |
| Líneas añadidas | ~2462 |
| Dependencias nuevas | 0 |
| Migraciones Alembic | 2 |
| Endpoints nuevos | ~14 |
| MCP tools | 9 |

---

## Deuda técnica identificada

- **SEC-02**: Integrar `audit.log_event()` en los endpoints de auth, MCP y tasks
- **NET-05..11**: Frontend login UI, VPS mode, tunnel mode, domain separation por proyecto
- **QA-01..05, QA-07..12**: Fixtures de repos, CI matrix, Playwright E2E, packaging, runbooks
- **SEC-04..11**: Políticas de proyecto, workspace isolation, process limits, kill switch, backup/restore
- **MCP-10..12**: Pull tools, deploy trigger, resources/prompts
- **Caddy hot-reload**: SIGUSR1 tras escribir Caddyfile

---

## Conclusión

El MVP de Niwa está operativo en sus fundamentos: gestión de proyectos, ejecución de tareas con Claude Code, deployments locales (fases 0-4 en rama separada), auth opt-in, servidor MCP funcional, redacción de secretos y métricas básicas. El trabajo restante es principalmente integración (audit log en endpoints), UI (login frontend), infraestructura (CI matrix, E2E) y hardening (process limits, workspace isolation).

La arquitectura opt-in para auth resultó ser la decisión más importante de esta sesión: permite que Niwa funcione en local sin configuración adicional y se endurezca progresivamente para producción.
