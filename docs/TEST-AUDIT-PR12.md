# Test audit — PR-12

Estado de la suite al arrancar PR-12. Primer commit del PR, previo a tocar
cualquier test. Mide el terreno:

1. Qué testea cada archivo.
2. Qué items del checklist del SPEC PR-12 están cubiertos.
3. Qué tests son legacy v0.1 y deben eliminarse o reescribirse.
4. Qué tests fallan hoy y por qué.

## 1. Mapa archivo → responsabilidad

Ejecutados en `tests/` de la rama `claude/rewrite-test-suite-hLzRG` (≡ HEAD
de v0.2 tras PR-11).

Total: **833 tests colectados**, suite completa en ≈ 3 min 33 s.

| Archivo                                         | # tests | Responsabilidad                                                                 | Añadido en |
|-------------------------------------------------|--------:|---------------------------------------------------------------------------------|-----------:|
| test_approval_gate_integration.py               |       9 | Flujo approval → bloquea ejecución, resume crea run nuevo                       | PR-05/PR-08 |
| test_approval_service.py                        |      16 | `approval_service` unit: request, resolve, idempotencia                         | PR-05      |
| test_approvals_endpoints.py                     |      25 | HTTP `/api/approvals*` (lista + acción)                                         | PR-10b     |
| test_assistant_service.py                       |      51 | `assistant_service` unit: routing gate, LLM config, loop, tool dispatch         | PR-08      |
| test_assistant_tool_endpoints.py                |      19 | HTTP `/api/assistant/tools/*` para OpenClaw                                     | PR-08      |
| test_assistant_turn_endpoint.py                 |       7 | HTTP `POST /api/assistant/turn` (contract shape, errores)                       | PR-08      |
| test_backend_profiles_endpoints.py              |      18 | HTTP `/api/backend-profiles*`                                                   | PR-10d     |
| test_capability_profile_endpoints.py            |      21 | HTTP `/api/projects/:id/capability-profile`                                     | PR-10d     |
| test_capability_service.py                      |      59 | `capability_service`: repo/shell/web/network modes, fs scope, budget            | PR-05      |
| test_chat_sessions_v02_endpoint.py              |       5 | HTTP chat sessions web v0.2                                                     | PR-10e     |
| test_claude_adapter_collect_artifacts.py        |      10 | `ClaudeCodeAdapter.collect_artifacts()`                                         | PR-04      |
| test_claude_adapter_integration.py              |       5 | Claude adapter E2E con fake_claude.py                                           | PR-04      |
| test_claude_adapter_lifecycle.py                |      14 | Claude adapter cancel/resume/heartbeat                                          | PR-04      |
| test_claude_adapter_parse_usage.py              |      20 | `parse_usage_signals()` sobre stream JSON                                       | PR-04      |
| test_claude_adapter_start.py                    |      30 | `ClaudeCodeAdapter.start()` (permissions, env, stream, approval)                | PR-04      |
| test_codex_adapter_collect_artifacts.py         |      17 | `CodexAdapter.collect_artifacts()`                                              | PR-07      |
| test_codex_adapter_integration.py               |      10 | Codex adapter E2E con fake_codex.py                                             | PR-07      |
| test_codex_adapter_lifecycle.py                 |      14 | Codex adapter cancel/resume/heartbeat                                           | PR-07      |
| test_codex_adapter_parse_usage.py               |      12 | Codex `parse_usage_signals()`                                                   | PR-07      |
| test_codex_adapter_start.py                     |      23 | `CodexAdapter.start()` + OAuth env                                              | PR-07      |
| test_e2e.py                                     |       1 | E2E v0.1 basado en `assigned_to_claude=1`, BD de producción                     | v0.1       |
| test_mcp_contract.py                            |      13 | Carga/validación del contract v02-assistant                                     | PR-09      |
| test_mcp_integration.py                         |       7 | Smoke real contra app: project_context, task_create, assistant_turn             | PR-09      |
| test_mcp_server_v02.py                          |      10 | Filtrado de tools por contract + proxy HTTP del tasks-mcp server                | PR-09      |
| test_mcp_smoke.py                               |       7 | `mcp_smoke.smoke_assistant_mode()` en casos ok/llm_missing/mismatch/unreachable | PR-09      |
| test_migration_010.py                           |       5 | Migración 010 idempotente                                                       | PR-10e     |
| test_migration_011.py                           |       3 | Migración 011 idempotente                                                       | PR-09      |
| test_pr00_docs.py                               |      27 | Documentación ADR/SPEC/INSTALL se mantiene consistente con SPEC                 | PR-00      |
| test_pr01_schema.py                             |      27 | Migración 007: tablas, columnas, índices, CHECKs, idempotencia                  | PR-01      |
| test_pr02_state_machines.py                     |      33 | state_machines, task_request_input→waiting_input, pipeline_status               | PR-02      |
| test_pr03_backend_abstraction.py                |      50 | backend_registry, BackendAdapter interface, capability_profiles                 | PR-03      |
| test_pr11_quick_install.py                      |      43 | `niwa install --quick --mode {core,assistant}`, argparse, credential detect     | PR-11      |
| test_routing_fallback_claude_codex.py           |      18 | Fallback claude↔codex; run nuevo con relation_type='fallback'                   | PR-06/PR-07|
| test_routing_heuristics.py                      |      34 | Heurísticas del router (multiarchivo, repo amplio, parche acotado, etc.)        | PR-06      |
| test_routing_rules_seed.py                      |       7 | `routing_rules` seed por defecto                                                | PR-06      |
| test_routing_service.py                         |      18 | `routing_service.decide()` persiste routing_decision                            | PR-06      |
| test_run_events_contract.py                     |      14 | Contract de `backend_run_events` (event_type, payload_json)                     | PR-04      |
| test_runs_endpoints.py                          |      24 | HTTP runs/routing/artifacts: auth, 404, joined shape                            | PR-10a/c   |
| test_runs_service_lifecycle.py                  |      26 | `runs_service.create_run/transition/heartbeat/finish`                           | PR-04      |
| test_runs_service_read_queries.py               |      20 | `runs_service` lectura: list/detail/events/routing/artifacts                    | PR-10a/c   |
| test_smoke.py                                   |      48 | Mix de smoke de instalación, auth, MCP catalog, hosting, frontend, openclaw     | v0.1+PR-09 |
| test_task_executor_routing.py                   |      13 | Bridge v0.1↔v0.2: routing_mode flag, executor pipeline v02                      | PR-06      |

## 2. Checklist SPEC PR-12 — estado por item

Formato: `✅ cubierto` / `🟡 parcial` / `❌ ausente`.

| # | Item checklist                                               | Archivo(s) cobertura                                                                   | Estado |
|---|--------------------------------------------------------------|----------------------------------------------------------------------------------------|:------:|
| 1 | Migración 007 idempotente                                    | `test_pr01_schema.py::TestMigration007Idempotent` (4 tests) + `test_smoke.py::TestInstalacionLimpia::test_migraciones_idempotentes_sobre_esquema` | ✅ |
| 2 | Creación de `routing_decision`                               | `test_routing_service.py` (18), `test_routing_heuristics.py` (34), `test_routing_rules_seed.py` (7) | ✅ |
| 3 | Creación de `backend_run` al claim real                      | `test_task_executor_routing.py::TestV02PipelineCreatesRun::test_full_pipeline`, `test_runs_service_lifecycle.py::TestCreateRun` | ✅ |
| 4 | Fallback crea run nuevo con `relation_type='fallback'`       | `test_routing_fallback_claude_codex.py` (18), `test_runs_service_read_queries.py::TestGetRoutingDecisionForTask::test_resolves_fallback_chain` | ✅ |
| 5 | Resume crea run nuevo con `relation_type='resume'`           | `test_runs_service_lifecycle.py::TestFullLifecycle`, `test_claude_adapter_lifecycle.py::TestResume` (3), `test_codex_adapter_lifecycle.py::TestResume` (3), `test_approval_gate_integration.py::TestResumeAfterApproval` | ✅ |
| 6 | `task_request_input` usa `waiting_input`                     | `test_pr02_state_machines.py::TestTaskRequestInputUsesWaitingInput` + `test_smoke.py::TestTaskStateCycle::test_pendiente_to_waiting_input_cycle` | ✅ |
| 7 | `_pipeline_status()` cuenta `waiting_input`                  | `test_pr02_state_machines.py::TestPipelineStatusIncludesWaitingInput`                   | ✅ |
| 8 | Capability profile bloquea filesystem fuera de scope         | `test_capability_service.py::TestFilesystemScope` (6)                                  | ✅ |
| 9 | Approval gate se crea antes de ejecutar                      | `test_approval_gate_integration.py::TestApprovalBlocksExecution`, `test_approval_service.py::TestRequestApproval`, `test_task_executor_routing.py::TestV02ApprovalBlocking` | ✅ |
| 10 | Claude backend start/resume/cancel                          | `test_claude_adapter_start.py` (30), `test_claude_adapter_lifecycle.py` (14 — cancel + resume), `test_claude_adapter_integration.py` (5) | ✅ |
| 11 | Codex backend start/cancel                                  | `test_codex_adapter_start.py` (23), `test_codex_adapter_lifecycle.py` (14), `test_codex_adapter_integration.py` (10) | ✅ |
| 12 | `assistant_turn` crea tarea o responde según contexto       | `test_assistant_service.py::TestAssistantTurnLoop` (8), `test_assistant_turn_endpoint.py` (7) | 🟡 (Bug 13 — endpoint falla en full-suite) |
| 13 | Install core                                                | `test_pr11_quick_install.py::TestBuildQuickConfig::test_core_mode_sensible_defaults`, `TestAssistantPrereqs::test_core_mode_no_prereqs` | ✅ |
| 14 | Install assistant                                           | `test_pr11_quick_install.py::TestBuildQuickConfig::test_assistant_mode_sets_contract`, `TestAssistantPrereqs::test_assistant_with_openclaw_ok` | ✅ |
| 15 | OpenClaw registration smoke                                 | `test_pr11_quick_install.py::TestCredentialDetection::test_openclaw_{missing,present}`, `test_mcp_smoke.py` (7 — smoke post-registro), `test_mcp_integration.py` (7 — smoke real contra app) | ✅ (llamada real a `openclaw mcp set` no testable sin binario; queda manual según restricción D) |
| 16 | Contract MCP exacto para Assistant mode                     | `test_mcp_contract.py::TestV02AssistantContractShape` (4 tests: exact_tool_list, transport, no_extra, no_missing), `test_mcp_server_v02.py::TestContractFiltering` | ✅ |

**Conclusión:** 16/16 items del checklist están cubiertos por tests
escritos en PRs 01–11. PR-12 **no necesita añadir cobertura nueva**, solo
consolidar.

## 3. Tests legacy v0.1 a eliminar o reescribir

### 3.1 Eliminar — `tests/test_e2e.py` (1 test)

- Razón: usa `assigned_to_claude=1` (campo deprecado PR-00, sin semántica
  de routing en v0.2) y abre `~/.niwa/data/niwa.sqlite3` (ruta de
  producción que no existe en CI).
- Bug 5 en BUGS-FOUND.md lo documenta y asigna el fix a PR-12.
- El SPEC dice textualmente que este test "no sirve para v0.2".
- Sustitución: no aplica. El contrato v0.2 de claim real ya está cubierto
  por `test_task_executor_routing.py::TestV02PipelineCreatesRun`.

### 3.2 Recortar — `tests/test_smoke.py` (48 tests → ~43 tras limpieza)

El archivo mezcla smoke genérico (schema, auth, sintaxis, executor queue,
task state cycle — válidos en v0.2) con tests sobre componentes
desaparecidos con PR-10e. Decisiones:

- **Eliminar** `TestFrontendBuild::test_all_react_components_exist`.
  - Lista estática de componentes que en v0.2 han cambiado radicalmente
    (chat web legacy borrado en PR-10e). Mantenerla actualizada no
    aporta; el build pass en CI es la verdadera señal.
- **Eliminar** `TestImageGeneration::test_chat_renders_images`.
  - Depende de `features/chat/components/MessageBubble.tsx`, eliminado en
    PR-10e. El servicio de imágenes sigue vivo; el test de renderizado
    frontend quedó obsoleto.
- **Reescribir** `TestSuperficieMCP::test_herramientas_catalogo_coinciden_con_servidor` y
  `TestMCPCatalogIntegrity::test_catalog_yaml_matches_server`.
  - Falla hoy porque `assistant_turn` está en server.py como tool v02
    pero no en `config/mcp-catalog/*.json` (queda en
    `config/mcp-contract/v02-assistant.json`). PR-09 diseñó esa
    separación (catálogos = tools nativas de tasks-mcp; contracts = v02
    proxies). El test debe reflejar el split: tools v02 no obligadas a
    estar en catálogo.
  - Ya existe cobertura específica del contract v02 en
    `test_mcp_contract.py`. El test de smoke puede ceñirse a las tools
    nativas y dejar las v02 fuera del matching.

### 3.3 Mantener — resto de `test_smoke.py`

Sigue siendo útil como smoke rápido:

- `TestInstalacionLimpia` (schema + migraciones idempotentes).
- `TestAutenticacion`.
- `TestSintaxisPython` (compila todo).
- `TestHosting`, `TestOpenClaw`, `TestImageGeneration` (service registry).
- `TestImageProviders`.
- `TestOpenClawConfig` (streamable-http).
- `TestAllEndpoints::test_critical_endpoints_exist`.
- `TestFrontendBuild::test_package_json_exists`, `test_all_pinned_versions`.
- `TestDatabaseBootstrap`.
- `TestMCPCatalogToolCount` (tras ajuste de 3.2).
- `TestRemoteAuth`.
- `TestExecutorQueue`, `TestTaskStateCycle`.

### 3.4 Tests de pipeline legacy 3-tier (Haiku→Opus→Sonnet)

- No existe hoy un test que dependa exclusivamente del pipeline 3-tier.
  `test_task_executor_routing.py` tiene `TestChatTasksUseLegacy` y
  `TestRoutingModeFlag::test_legacy_mode_skips_routing`, que son
  cobertura consciente del bridge v0.1↔v0.2 (routing_mode=legacy sigue
  siendo un modo válido). **Mantener**.

## 4. Tests que fallan en la suite completa hoy

Baseline medido con `pytest tests/ --tb=no -q --ignore=tests/test_e2e.py`,
sin ninguna modificación de PR-12. Resultado: **820 passed, 12 failed**.

| Test                                                                         | Causa                                                                                  | Acción PR-12 |
|------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|--------------|
| `test_pr01_schema.py::TestTableStructure::test_routing_decisions_columns`    | **Bug 12** — set `expected` sin `contract_version` (PR-09 añadió la columna via mig.11)| Fix: añadir `'contract_version'` al set. |
| `test_assistant_turn_endpoint.py` — los 7 tests                              | **Bug 13** — module-state pollution de `app.NIWA_APP_AUTH_REQUIRED` cuando otro test importó `app` primero | Fix: aplicar patrón `app.NIWA_APP_AUTH_REQUIRED = False` post-import (documentado por PR-10a en `test_runs_endpoints.py:79`). |
| `test_smoke.py::TestSuperficieMCP::test_herramientas_catalogo_coinciden_con_servidor` | `assistant_turn` tool v02 no en catálogos                                              | Ver §3.2 — reescribir para excluir tools v02. |
| `test_smoke.py::TestMCPCatalogIntegrity::test_catalog_yaml_matches_server`   | Misma causa — `ghost: {assistant_turn}`                                                | Ver §3.2. |
| `test_smoke.py::TestImageGeneration::test_chat_renders_images`               | `MessageBubble.tsx` borrado en PR-10e                                                  | Ver §3.2 — eliminar. |
| `test_smoke.py::TestFrontendBuild::test_all_react_components_exist`          | `ChatView.tsx` borrado en PR-10e                                                       | Ver §3.2 — eliminar. |

Todos los fallos son causas conocidas; no hay regresiones ocultas. Con
los fixes de Bug 12, Bug 13 y §3.2 la suite queda en verde.

## 5. Consolidaciones posibles (no bloqueantes)

Posibles merges evaluados, decisión final en implementación:

- `test_routing_service.py` + `test_routing_heuristics.py` + `test_routing_rules_seed.py`:
  tres archivos, tres responsabilidades distintas — **dejar separados**.
- `test_claude_adapter_*` y `test_codex_adapter_*`: cada archivo cubre
  una capacidad (`start`, `lifecycle`, `collect_artifacts`, `parse_usage`,
  `integration`), simetría buscada entre backends — **dejar separados**.
- `test_runs_service_lifecycle.py` + `test_runs_service_read_queries.py`:
  write vs read paths; archivos grandes, split tiene sentido — **dejar
  separados**.
- `test_migration_010.py` + `test_migration_011.py`: dos archivos de 5 y
  3 tests, patrón idéntico. Candidatos a consolidación en
  `test_migrations_post_007.py`, pero el beneficio es marginal y añade
  churn para poco — **dejar separados**.

PR-12 no realiza consolidaciones.

## 6. Tamaño propuesto del PR

Dado que el checklist está esencialmente cubierto, el alcance queda:

1. Commit 1 — este documento.
2. Commit 2 — eliminar `tests/test_e2e.py`.
3. Commit 3 — recortar `tests/test_smoke.py` (§3.2).
4. Commit 4 — arreglar Bug 12.
5. Commit 5 — arreglar Bug 13.
6. Commit 6 — nota en `docs/DECISIONS-LOG.md` + cierre de PR-12.

Ninguna cobertura nueva se añade. La decisión de no ampliar se justifica
porque los PRs 01–11 han ido escribiendo tests en el mismo PR que la
feature, que es la regla del SPEC 8.

## 7. Bloqueos y preguntas al humano

- **§3.2** — confirmar que la reescritura del smoke de catálogo para
  excluir tools v02 es el camino correcto (alternativa: añadir
  `assistant_turn` a un catálogo niwa-v02 dedicado — más invasivo,
  afecta PR-09).
- **§6 — no añadir cobertura nueva.** Si prefieres que PR-12 añada al
  menos un test explícito de "creación de `backend_run` al claim real"
  con nombre que matchee literalmente el checklist (hoy vive dentro de
  `test_task_executor_routing.py::TestV02PipelineCreatesRun`), es
  posible hacerlo sin coste. Pregunto antes.
