# Fase 5 — Dominio, subdominios y acceso online

Fecha de preparación: 2026-04-30

**Resumen.** Publicar la UI de Niwa y los proyectos con reverse proxy, TLS y controles de exposición, manteniendo operación local/VPS/casa.

## Contexto

- El MVP excluye auth, acceso por red y subdominios wildcard; por tanto esta fase debe empezar por auth y proxy.
- El objetivo es UI en niwa.dominio y proyectos en slug.dominio o slug.apps.dominio.
- La fase depende de deploy local serio y de seguridad básica inicial.

## No-objetivos

- No multi-tenant.
- No exponer proyectos por defecto.
- No reemplazar Caddy/Traefik por una plataforma cloud completa.

## Reglas para pasar estas tareas a un LLM implementador

Usa estas reglas como preámbulo de cualquier brief:

1. Trabaja sobre `main` actualizado y lee primero `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md` y el documento de la fase correspondiente.
2. Implementa solo la tarea o PR block indicado. No adelantes fases posteriores aunque parezcan relacionadas.
3. Mantén los cambios pequeños. Si una tarea supera el scope, detente y deja explícito qué sub-tareas nuevas propones.
4. Añade o actualiza tests en el mismo PR. Si no puedes probar algo, explica exactamente por qué y deja un check manual reproducible.
5. Conserva compatibilidad con proyectos/tareas existentes salvo que el brief diga lo contrario.
6. No ocultes fallos. Los errores deben ser visibles por API/UI/logs con causa accionable.
7. No uses servicios externos en tests obligatorios. Claude real, GitHub real, DNS real y TLS real solo van en pruebas live opcionales.
8. Antes de cerrar, ejecuta como mínimo `make test`; cuando exista, ejecuta también `make smoke`.

## Brief base copiable para LLM

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 5 — Dominio, subdominios y acceso online.

Contexto: Publicar la UI de Niwa y los proyectos con reverse proxy, TLS y controles de exposición, manteniendo operación local/VPS/casa.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-NET-01.** Auth local-first + tokens.
- **PR-NET-02.** Domain config + Caddy generator.
- **PR-NET-03.** Wildcard/subdomain routing para projects.
- **PR-NET-04.** TLS y modos VPS/casa/tunnel.
- **PR-NET-05.** UI de exposición y smoke de red local.

## Tareas

### NET-01 — Auth para UI/API

**Objetivo.** Evitar exponer un executor sin protección.

**Archivos probables.**

- `backend/app/auth`
- `frontend/src/features/auth`

**Instrucciones de implementación.**

- Implementar login local con password inicial o token generado en bootstrap.
- Usar cookie HttpOnly SameSite para UI.
- Proteger rutas mutantes y vistas sensibles; dejar /api/health o readiness pública solo si no filtra detalles.
- Añadir comando reset-password/token.

**Tests/verificación.**

- Backend auth tests.
- Frontend login tests.

**Criterios de aceptación.**

- Sin login no se puede crear task/proyecto ni ver detalles sensibles.
- Bootstrap muestra cómo obtener credencial inicial.
- Tests cubren 401/200.

**Brief corto para LLM.**

```text
Implementa NET-01 (Auth para UI/API) en Niwa. Objetivo: Evitar exponer un executor sin protección. Toca principalmente `backend/app/auth`, `frontend/src/features/auth`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend auth tests.; Frontend login tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-02 — API tokens con scopes

**Objetivo.** Permitir clientes externos/MCP sin cookie.

**Archivos probables.**

- `backend/app/auth/tokens.py`
- `backend/app/models`

**Instrucciones de implementación.**

- Crear tabla api_tokens hashed, name, scopes, created_at, last_used_at, revoked_at.
- Scopes iniciales: read, task:create, task:write, merge, deploy, admin.
- Autenticación Bearer para API.

**Tests/verificación.**

- Auth scope tests.

**Criterios de aceptación.**

- Token con read no puede mergear ni desplegar.
- Revocación efectiva.
- last_used_at se actualiza sin romper rendimiento.

**Brief corto para LLM.**

```text
Implementa NET-02 (API tokens con scopes) en Niwa. Objetivo: Permitir clientes externos/MCP sin cookie. Toca principalmente `backend/app/auth/tokens.py`, `backend/app/models`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Auth scope tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-03 — Config de dominio base

**Objetivo.** Declarar dominios de UI y apps.

**Archivos probables.**

- `backend/app/config.py`
- `backend/app/schemas`

**Instrucciones de implementación.**

- Añadir config fields base_domain, ui_domain, apps_domain, public_scheme.
- Permitir overrides por project public_host si se necesita.
- Validar dominios y documentar DNS esperado.

**Tests/verificación.**

- Config tests.

**Criterios de aceptación.**

- Settings muestran URLs calculadas.
- Sin dominio configurado, Niwa sigue local.

**Brief corto para LLM.**

```text
Implementa NET-03 (Config de dominio base) en Niwa. Objetivo: Declarar dominios de UI y apps. Toca principalmente `backend/app/config.py`, `backend/app/schemas`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Config tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-04 — Generador de Caddyfile

**Objetivo.** Crear reverse proxy reproducible.

**Archivos probables.**

- `backend/app/network/caddy.py`
- `backend/app/niwa_cli.py`

**Instrucciones de implementación.**

- Generar Caddyfile desde config: UI/API, static deploys y process deploys.
- No editar archivos del sistema sin confirmación; escribir a ~/.niwa/caddy/Caddyfile o path config.
- Comando niwa-executor proxy render y proxy validate.

**Tests/verificación.**

- Unit tests snapshot Caddyfile.

**Criterios de aceptación.**

- Caddyfile generado contiene rutas correctas.
- El comando informa de DNS/TLS prerequisites.
- No requiere root para render.

**Brief corto para LLM.**

```text
Implementa NET-04 (Generador de Caddyfile) en Niwa. Objetivo: Crear reverse proxy reproducible. Toca principalmente `backend/app/network/caddy.py`, `backend/app/niwa_cli.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Unit tests snapshot Caddyfile.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-05 — Wildcard subdomains para proyectos

**Objetivo.** Publicar deploys por slug.

**Archivos probables.**

- `backend/app/network/caddy.py`
- `backend/app/deployments`

**Instrucciones de implementación.**

- Mapear slug.apps_domain a deployment activo del proyecto.
- Para static: proxy a FastAPI deploy handler o servir directamente artifact path si Caddy lo permite.
- Para process: reverse_proxy localhost:port.
- Respetar public_enabled por proyecto.

**Tests/verificación.**

- Caddyfile snapshot tests.
- Smoke local con Host header.

**Criterios de aceptación.**

- Proyecto public_enabled=false no se publica.
- Proyecto enabled tiene URL slug.apps_domain.
- Static y process resuelven al deployment activo.

**Brief corto para LLM.**

```text
Implementa NET-05 (Wildcard subdomains para proyectos) en Niwa. Objetivo: Publicar deploys por slug. Toca principalmente `backend/app/network/caddy.py`, `backend/app/deployments`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Caddyfile snapshot tests.; Smoke local con Host header.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-06 — TLS automático y DNS modes

**Objetivo.** Soportar certificados reales.

**Archivos probables.**

- `docs/NETWORK.md`
- `backend/app/network/caddy.py`

**Instrucciones de implementación.**

- Documentar modo A: subdominios explícitos con HTTP-01.
- Documentar modo B: wildcard con DNS-01 si se usa *.apps.domain.
- No guardar tokens DNS en logs; si se soporta Cloudflare API token, tratarlo como secreto.

**Tests/verificación.**

- Manual verification docs.
- Secret redaction tests si aplica.

**Criterios de aceptación.**

- Docs explican cómo configurar TLS en VPS.
- Caddyfile no expone secretos.
- Modo local sin TLS sigue funcionando.

**Brief corto para LLM.**

```text
Implementa NET-06 (TLS automático y DNS modes) en Niwa. Objetivo: Soportar certificados reales. Toca principalmente `docs/NETWORK.md`, `backend/app/network/caddy.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Manual verification docs.; Secret redaction tests si aplica.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-07 — Modo VPS

**Objetivo.** Instalación reproducible en servidor.

**Archivos probables.**

- `docs/NETWORK.md`
- `backend/app/ops/doctor.py`

**Instrucciones de implementación.**

- Documentar systemd user/system, Caddy, firewall, puertos 80/443, backups.
- Añadir niwa-executor install-vps-checks o doctor --profile vps.
- No asumir proveedor específico.

**Tests/verificación.**

- Doctor tests.
- Docs review.

**Criterios de aceptación.**

- Un usuario puede montar Niwa en VPS siguiendo docs.
- doctor --profile vps detecta faltantes críticos.

**Brief corto para LLM.**

```text
Implementa NET-07 (Modo VPS) en Niwa. Objetivo: Instalación reproducible en servidor. Toca principalmente `docs/NETWORK.md`, `backend/app/ops/doctor.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Doctor tests.; Docs review.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-08 — Modo casa/túnel

**Objetivo.** Publicar desde Linux/Mac doméstico sin abrir router si se desea.

**Archivos probables.**

- `docs/NETWORK.md`
- `frontend/src/routes/SystemRoute.tsx`

**Instrucciones de implementación.**

- Documentar Cloudflare Tunnel/Tailscale Funnel como opciones.
- Añadir config tunnel_mode informativa, no automatizar credenciales en primera iteración.
- UI/System muestra si el túnel está configurado de forma manual si se puede detectar.

**Tests/verificación.**

- Docs review.

**Criterios de aceptación.**

- Docs cubren casa detrás de NAT.
- Niwa no exige VPS.

**Brief corto para LLM.**

```text
Implementa NET-08 (Modo casa/túnel) en Niwa. Objetivo: Publicar desde Linux/Mac doméstico sin abrir router si se desea. Toca principalmente `docs/NETWORK.md`, `frontend/src/routes/SystemRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Docs review.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-09 — Separar dominio UI de dominios app

**Objetivo.** Evitar mezclar admin y proyectos.

**Archivos probables.**

- `backend/app/auth`
- `backend/app/config.py`

**Instrucciones de implementación.**

- Default recomendado: niwa.example.com para admin y *.apps.example.com para proyectos.
- Asegurar cookies de UI no se mandan innecesariamente a apps.
- Añadir warnings si se configura mismo dominio sin subdominio separado.

**Tests/verificación.**

- Auth cookie tests si aplica.
- Config validation tests.

**Criterios de aceptación.**

- Cookie scope seguro.
- URLs generadas no mezclan admin/app.

**Brief corto para LLM.**

```text
Implementa NET-09 (Separar dominio UI de dominios app) en Niwa. Objetivo: Evitar mezclar admin y proyectos. Toca principalmente `backend/app/auth`, `backend/app/config.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Auth cookie tests si aplica.; Config validation tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-10 — Control de exposición por proyecto

**Objetivo.** No publicar proyectos accidentalmente.

**Archivos probables.**

- `backend/app/schemas/project.py`
- `frontend/src/features/projects/ProjectSettings.tsx`

**Instrucciones de implementación.**

- public_enabled default false.
- UI pide confirmación para activar publicación.
- Mostrar status público: local only, configured, published, unhealthy.

**Tests/verificación.**

- Backend project patch tests.
- Frontend settings test.

**Criterios de aceptación.**

- Un proyecto nuevo no aparece online.
- Activar publicación requiere acción explícita.
- Desactivar corta ruta/proxy en config renderizada.

**Brief corto para LLM.**

```text
Implementa NET-10 (Control de exposición por proyecto) en Niwa. Objetivo: No publicar proyectos accidentalmente. Toca principalmente `backend/app/schemas/project.py`, `frontend/src/features/projects/ProjectSettings.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend project patch tests.; Frontend settings test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### NET-11 — Smoke de red local con Host header

**Objetivo.** Validar routing sin DNS real.

**Archivos probables.**

- `scripts/smoke_v1_1.py`
- `backend/tests/test_caddy.py`

**Instrucciones de implementación.**

- Extender smoke para renderizar Caddyfile y/o probar FastAPI/proxy local con Host header si se arranca Caddy fake/real.
- No depender de certificados reales en CI.

**Tests/verificación.**

- make smoke.

**Criterios de aceptación.**

- make smoke valida generación de rutas para ui/app domains.
- No requiere red externa.

**Brief corto para LLM.**

```text
Implementa NET-11 (Smoke de red local con Host header) en Niwa. Objetivo: Validar routing sin DNS real. Toca principalmente `scripts/smoke_v1_1.py`, `backend/tests/test_caddy.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

## Criterio de cierre de fase

La fase se considera cerrada cuando todos los PR blocks están mergeados, `make test` pasa, el smoke aplicable pasa, la documentación afectada queda actualizada y `docs/STATE.md` refleja el nuevo estado operativo.

## Fuentes usadas para el estado actual del repo

Consultadas el 2026-04-30. Estos documentos no sustituyen a una lectura fresca de `main` antes de implementar.

- `README.md` — Instalación, flujo inicial, backend/frontend, requisitos, modo safe/dangerous.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/README.md
- `docs/STATE.md` — Estado operativo: ciclo v1.1 cerrado y siguiente paso smoke-v1.1.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/STATE.md
- `docs/SPEC.md` — Contrato MVP: triage, execute, verify, finalize; no auth/MCP/subdominios en MVP.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/SPEC.md
- `docs/HANDBOOK.md` — Layout backend/frontend, modelos, tests y módulos principales.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/HANDBOOK.md
- `Makefile` — Targets actuales: install, dev, test, clean.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/Makefile
- `backend/app/finalize.py` — Cierre: commit, push, PR y auto-merge dangerous.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/finalize.py
- `backend/app/schemas/project.py` — Contrato project create/patch/read.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/schemas/project.py
- `backend/app/schemas/task.py` — Contrato task create/read/respond y estados actuales.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/schemas/task.py
- `backend/app/api/tasks.py` — Endpoints de tareas, runs, respond y attachments.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/api/tasks.py
- `backend/app/api/deploy.py` — Deploy estático actual bajo /api/deploy/{slug}/.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/api/deploy.py