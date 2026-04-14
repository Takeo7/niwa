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

Formato: `✅ cubierto` / `🟡 parcial` / `❌ ausente`. Cada ítem cita el
archivo y — cuando aplica — la clase y el método concretos. Si hay más de
una ubicación relevante, la primera es la prueba autoritativa del
contrato; las demás son cobertura adicional.

| #  | Item SPEC PR-12                                              | Test(s) concreto(s) | Estado |
|----|--------------------------------------------------------------|---------------------|:------:|
| 1  | Migración 007 idempotente                                    | `tests/test_pr01_schema.py::TestMigration007Idempotent::test_migration_idempotent` y `::test_schema_plus_migration_no_errors`. Cobertura secundaria: `tests/test_smoke.py::TestInstalacionLimpia::test_migraciones_idempotentes_sobre_esquema` (aplica todas las migraciones dos veces sobre `schema.sql`). | ✅ |
| 2  | Creación de `routing_decision`                               | `tests/test_routing_service.py::TestDecisionPersistence::test_decision_persisted` (row escrita con shape correcto). Complementos: `tests/test_routing_service.py::TestDecidePinExplicit::test_pin_to_enabled_backend`, `::TestDecidePersistedRules::test_complex_task_matches_rule_1`, `::TestDecideIdempotency::test_idempotent_reuse`, `tests/test_routing_heuristics.py` (34 tests de heurísticas), `tests/test_routing_rules_seed.py::TestSeedRoutingRules`. | ✅ |
| 3  | Creación de `backend_run` al claim real                      | `tests/test_task_executor_routing.py::TestV02PipelineCreatesRun::test_full_pipeline` (claim end-to-end: pendiente→routing→run created). `tests/test_runs_service_lifecycle.py::TestCreateRun` (shape de la row a nivel servicio). | ✅ |
| 4  | Fallback crea run nuevo con `relation_type='fallback'`       | `tests/test_routing_fallback_claude_codex.py::TestFallbackEscalation` (cadena completa claude→codex con persistencia). `tests/test_runs_service_read_queries.py::TestGetRoutingDecisionForTask::test_resolves_fallback_chain` y `::TestListRunsForTask::test_preserves_relation_type` (lectura de la relación). | ✅ |
| 5  | Resume crea run nuevo con `relation_type='resume'`           | `tests/test_claude_adapter_lifecycle.py::TestResume` (3 tests). `tests/test_codex_adapter_lifecycle.py::TestCodexResume` (3 tests). `tests/test_claude_adapter_integration.py::TestIntegrationResume::test_resume_uses_prior_session` (E2E con fake_claude.py). `tests/test_approval_gate_integration.py::TestApprovalResumeFlow::test_approved_approval_allows_resume`. `tests/test_runs_service_lifecycle.py::TestFullLifecycle::test_happy_path` (cobertura del campo a nivel servicio). | ✅ |
| 6  | `task_request_input` usa `waiting_input`                     | `tests/test_pr02_state_machines.py::TestTaskRequestInputBugFix` (analiza el source de `_task_request_input` y garantiza que escribe `waiting_input`, nunca `revision`). Cobertura secundaria: `tests/test_smoke.py::TestTaskStateCycle::test_pendiente_to_waiting_input_cycle` (la transición es válida en la state machine). | ✅ |
| 7  | `_pipeline_status()` cuenta `waiting_input`                  | `tests/test_pr02_state_machines.py::TestPipelineStatusBugFix::test_pipeline_status_includes_waiting_input` (inspecciona el source) y `::test_pipeline_status_db` (verifica la query contra una DB semilla). | ✅ |
| 8  | Capability profile bloquea filesystem fuera de scope         | `tests/test_capability_service.py::TestFilesystemScope::test_write_outside_workspace_denied` (caso literal del checklist). Complementos: `::test_write_inside_workspace_allowed`, `::test_deny_list_takes_precedence`, `::test_explicit_allow_path`, `::test_workspace_without_path_fails_closed`, `::test_no_scope_allows_all`. | ✅ |
| 9  | Approval gate se crea antes de ejecutar                      | `tests/test_approval_gate_integration.py::TestShellViolation::test_bash_outside_whitelist_triggers_approval` y `::TestWriteViolation::test_write_outside_scope_triggers_approval` (approval creado ANTES de spawn del proceso). `tests/test_approval_gate_integration.py::TestPreExecDenialNoRunningState::test_pre_exec_denied_with_approval_skips_running` (el run nunca transita a `running`). `tests/test_task_executor_routing.py::TestV02ApprovalBlocking::test_approval_blocks_execution` (integración con el executor). `tests/test_approval_service.py::TestRequestApproval` (shape del registro). | ✅ |
| 10 | Claude backend start/resume/cancel                           | Start: `tests/test_claude_adapter_start.py::TestStartHappyPath` (6 tests: `test_start_returns_succeeded`, `test_start_persists_session_handle`, `test_start_writes_events`, `test_start_persists_usage_signals`, `test_start_creates_artifact_root`, `test_start_run_reaches_terminal_state`). Resume: `tests/test_claude_adapter_lifecycle.py::TestResume` (3 tests). Cancel: `tests/test_claude_adapter_lifecycle.py::TestCancel` (incluye `test_cancel_no_process_is_idempotent`, `test_cancel_idempotent_on_terminal_run`). E2E: `tests/test_claude_adapter_integration.py`. | ✅ |
| 11 | Codex backend start/cancel                                   | Start: `tests/test_codex_adapter_start.py::TestCodexAdapterStart::test_start_success_transitions`, `::test_start_records_events`, `::test_start_persists_session_handle`, `::test_start_persists_usage_signals`, `::test_start_failure_exit_code`. Cancel: `tests/test_codex_adapter_lifecycle.py::TestCodexCancel::test_cancel_no_process_is_idempotent`. Resume (bonus, no requerido por el SPEC): `tests/test_codex_adapter_lifecycle.py::TestCodexResume`. E2E: `tests/test_codex_adapter_integration.py`. | ✅ |
| 12 | `assistant_turn` crea tarea o responde según contexto        | Lógica del loop: `tests/test_assistant_service.py::TestAssistantTurnLoop::test_simple_text_response` (respuesta directa sin tool-call) y `::test_tool_call_creates_task` (crea tarea cuando el LLM emite `task_create`). Contract HTTP: `tests/test_assistant_turn_endpoint.py::TestAssistantTurnEndpoint::test_success_path`, `::test_contract_shape`, `::test_routing_mode_legacy_returns_409`. | ✅ (Bug 13 cerrado en PR-12; full-suite en verde) |
| 13 | Install core                                                 | `tests/test_pr11_quick_install.py::TestBuildQuickConfig::test_core_mode_sensible_defaults` (defaults sin OpenClaw ni contract v02). `tests/test_pr11_quick_install.py::TestAssistantPrereqs::test_core_mode_no_prereqs` (core no requiere OpenClaw). `tests/test_pr11_quick_install.py::TestModeIdempotence::test_detect_core` y `::test_same_mode_reinstall_allowed`. | ✅ |
| 14 | Install assistant                                            | `tests/test_pr11_quick_install.py::TestBuildQuickConfig::test_assistant_mode_sets_contract` (fija `NIWA_MCP_CONTRACT=v02-assistant`). `tests/test_pr11_quick_install.py::TestAssistantPrereqs::test_assistant_with_openclaw_ok` y `::test_assistant_without_openclaw_blocks`. `tests/test_pr11_quick_install.py::TestModeIdempotence::test_detect_assistant`, `::test_core_over_assistant_blocks`, `::test_assistant_over_core_blocks`, `::test_force_flag_bypasses_mode_mismatch`. | ✅ |
| 15 | OpenClaw registration smoke                                  | Detección de binario: `tests/test_pr11_quick_install.py::TestCredentialDetection::test_openclaw_missing`, `::test_openclaw_present`. Smoke post-registro (endpoint MCP de Niwa accesible vía gateway): `tests/test_mcp_smoke.py::TestSmokeSuccess::test_full_pass`, `::TestSmokeLLMSkip::test_llm_not_configured_is_skip`, `::TestSmokeRoutingMismatch::test_routing_mismatch_is_failure`, `::TestSmokeContractMissing::test_bad_contract_path`, `::TestSmokeAppUnreachable::test_unreachable_app`. Integración real contra app viva: `tests/test_mcp_integration.py::TestV02AssistantIntegration` (7 tests secuenciales). La llamada real a `openclaw mcp set niwa ...` vive en `setup.py::_configure_openclaw_mcp` y queda como verificación manual (restricción D: no dockerizar tests en PR-12). | ✅ |
| 16 | Contract MCP exacto para Assistant mode                      | `tests/test_mcp_contract.py::TestV02AssistantContractShape::test_exact_tool_list`, `::test_transport_is_streamable_http`, `::test_no_extra_tools`, `::test_no_missing_tools`. Filtrado a nivel server: `tests/test_mcp_server_v02.py::TestContractFiltering::test_load_contract_tools_v02`, `::test_v02_tool_names_match_contract`, `::test_v02_tool_defs_count`, `::test_assistant_turn_schema_has_channel`. | ✅ |

**Conclusión:** 16/16 items del checklist están cubiertos por tests
escritos en PRs 01–11, con referencia directa a archivo + clase +
método. PR-12 **no añade cobertura nueva**; cierra Bug 12 y Bug 13
(que dejaban cobertura existente fallando en full-suite) y recorta
legacy v0.1.

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

**Estado post-PR-12:** tras los commits que cierra este PR, la suite
completa (`pytest tests/ --durations=10`) reporta **830 passed, 0
failed, 3m 33s** (slowest individual test: 3.10s). Sin tests >30s que
anotar como candidatos a limpieza.

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

## 7. Respuestas a las preguntas abiertas en la auditoría inicial

Las tres preguntas que planteó el borrador inicial se resolvieron antes
de seguir con los commits 2-6:

- **§3.2 (reescritura del smoke de catálogo)** — confirmada la opción
  limpia: el test en `tests/test_smoke.py` filtra las tools v02 y no se
  toca `config/mcp-catalog/`. Referencias explícitas a PR-09 Decisión 3
  ("Un solo MCP server con filtrado por contract") y PR-11 Decisión 2
  (`generate_catalog_yaml(contract_file=...)` sobrescribe con
  `contract["tools"]`). Implementado en commit
  `f0195f7` (helper `_load_v02_tool_names` en el mismo test_smoke.py).
- **§6 (no añadir cobertura nueva)** — confirmado. No se añaden tests
  espejo del checklist; la trazabilidad item-SPEC ↔ archivo::clase::método
  vive en la tabla §2 de este documento.
- **Velocidad** — no se toca en PR-12. Se ejecuta `pytest --durations=10`
  como verificación al final; el test más lento tarda 3.10 s. No hay
  candidatos a limpieza por este eje.
