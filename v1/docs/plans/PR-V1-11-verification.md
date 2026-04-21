# PR-V1-11 — Contrato de verificación evidence-based (SUPERSEDED)

> **Status: SUPERSEDED (2026-04-20).** Al implementar se detectó que
> el scope del brief original llegaba a 917 LOC netas (código 503 +
> tests 445), **2.3× el hard-cap 400** de Semana 3. El
> implementador paró según la política de Semana 3 y reportó
> split. Product partner aprobó **Split A (por evidencia)**:
>
> - `PR-V1-11a-verification-core.md` — E1+E2 + skeleton + integración
>   executor (~250 LOC). Cierra ya el bug corazón (pregunta sin
>   responder, tool_use sin resultado, stream vacío).
> - `PR-V1-11b-verification-artifacts.md` — E3+E4 artifact scanning
>   (~200 LOC).
> - `PR-V1-11c-verification-tests.md` — E5 project tests runner
>   (~200 LOC).
>
> Se conserva este fichero como registro del alcance combinado
> original. NO usar como brief activo — ver 11a/11b/11c.
>
> Findings colaterales detectados en la implementación completa
> (relevantes para los 3 briefs hijos):
>
> 1. `verify_run` signature debe aceptar `adapter_outcome` + `exit_code`
>    como kwargs porque `run.outcome`/`run.exit_code` no están
>    persistidos cuando se invoca (se escriben en `_finalize`).
> 2. El dirty-tree guard de PR-V1-08 choca con el fake CLI creando
>    artefactos; solución: env var `FAKE_CLAUDE_TOUCH` en el fake
>    para que escriba durante la ejecución (no antes del branch
>    prep).
> 3. Multi-task tests: el artefacto untracked de la 1ª task ensucia
>    el árbol para la 2ª. Solución aplicada: git_project por task.
>    Alternativa futura (no MVP): extender E3 para contar commits
>    `HEAD~..HEAD`.
> 4. E1 error_code: `cli_nonzero_exit → exit_nonzero`;
>    `cli_not_found`/`timeout`/`adapter_exception → adapter_failure`.
>    Confirmado por product partner.

---

*(Brief combinado original intacto abajo para referencia histórica.)*
