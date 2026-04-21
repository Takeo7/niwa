# PR-V1-17 — Deploy local: static handler para web-deployable

**Semana:** 5
**Esfuerzo:** M
**Depende de:** FIX-20260421 mergeado (config alineada).

## Qué

Ruta nueva en el backend FastAPI que sirve estáticamente el output
de build de cualquier proyecto `kind="web-deployable"`:

```
GET /deploy/{slug}/{path:path}
```

- Busca proyecto por slug en DB.
- Si no existe → 404.
- Si `kind != "web-deployable"` → 404 (protege contra confusiones).
- Resuelve `<project.local_path>/dist/<path>`.
- Path traversal guard: el file resuelto debe ser subpath de
  `<local_path>/dist`.
- Si el path es directorio o vacío → sirve `dist/index.html`
  (fallback SPA).
- Si file no existe → 404.
- Content-Type por extensión (FastAPI `FileResponse` lo hace).

**No hay proceso spawn.** El proyecto se construye por separado
(usuario corre `npm run build` o análogo, típicamente como parte
de una task de Niwa); este PR solo sirve lo que hay en `dist/`.

## Por qué

SPEC §1 / §9 Semana 5: "deploy a localhost:PORT/<slug>". MVP
interpreta `<slug>` como prefijo de path bajo el backend ya
corriendo en `:8000`. `deploy_port` columna queda para v1.1
(per-port deploy con proxy real).

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── api/
│       └── deploy.py                       # nuevo, ~80 LOC
└── tests/
    └── test_deploy_api.py                  # nuevo, 5 casos
```

Registro del router en `app/api/__init__.py` (~2 LOC).

**HARD-CAP 400 LOC netas código+tests.** Proyección ~180. Si
excedes, PARAS.

## Fuera de scope (explícito)

- **No spawn de procesos**. Cero gestión de daemons per project.
  El proyecto no corre su propio server; Niwa solo sirve lo que
  el build dejó en `dist/`.
- **No uso real de `project.deploy_port`**. Se mantiene en schema
  como aspiracional para v1.1 (Cloudflare/Caddy con subdominios).
  MVP documenta "el servicio queda en
  `localhost:<main_port>/deploy/<slug>`".
- **No reverse proxy** a un server de node/python del proyecto.
  Solo static files.
- **No hay build automático** post-verify. El build lo pide el
  usuario en una task o vía CI del proyecto.
- **No hay invalidación de caché**. El file resuelto se sirve
  directo; si cambia `dist/`, el siguiente GET lo refleja.
- **No hay auth** — binding local §2.
- **No hay gzip/compression**. MVP.
- **No hay UI para ver el link del deploy**. `ProjectDetail.tsx`
  podría mostrar `http://localhost:8000/deploy/<slug>/` en un
  follow-up.
- **`kind=library`** y `kind=script` → 404 silencioso. Solo
  `web-deployable` expone `/deploy/<slug>/`.
- **No se integra en `finalize.py`** — deploy no dispara nada
  adicional tras verify. Follow-up podría añadir hook.

## Dependencias nuevas

- **Ninguna**. FastAPI `FileResponse` + stdlib `Path`.

## Contrato

### Ruta

```python
@router.get("/deploy/{slug}/{path:path}")
def serve_deploy(
    slug: str,
    path: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    project = session.execute(
        select(Project).where(Project.slug == slug)
    ).scalar_one_or_none()
    if project is None or project.kind != "web-deployable":
        raise HTTPException(404, "Not found")

    dist = (Path(project.local_path) / "dist").resolve()
    # fallback a index.html para rutas vacías o directorios
    target = (dist / path).resolve() if path else dist / "index.html"
    if target.is_dir():
        target = target / "index.html"

    # path traversal guard
    try:
        target.relative_to(dist)
    except ValueError:
        raise HTTPException(404, "Not found")

    if not target.is_file():
        raise HTTPException(404, "Not found")

    return FileResponse(target)
```

**También** se registra `GET /deploy/{slug}/` (path vacío) con
redirect a `/deploy/{slug}/` + fallback a `index.html`. O se maneja
con un `path=""` default.

### Integración

`v1/backend/app/api/__init__.py` importa el router y lo registra
en `api_router`. El prefix final es `/api` por el parent, así que
la URL completa queda `/api/deploy/{slug}/{path}`.

**Alternativa**: montar en `/deploy/{slug}/*` sin el prefix `/api`
para que los links externos sean más naturales. El brief deja
decisión al implementador; **recomiendo** colgar de `/api` para
consistencia (la UI ya usa `/api/*`; el frontend de Vite pasa
todo `/api` al backend vía proxy).

### Path traversal safety

`target.resolve().relative_to(dist.resolve())` captura intentos
`../../etc/passwd`. Si falla `ValueError`, 404. No fuga de
existencia de ficheros fuera de `dist/`.

## Tests

### Nuevos backend — `tests/test_deploy_api.py` (5 casos)

Setup fixture: crea project con `kind="web-deployable"`,
`local_path=tmp_path/<proj>`, escribe
`tmp_path/<proj>/dist/index.html`, `dist/assets/app.js`,
`dist/other.txt`. Usa engine in-memory con el fixture existente.

1. `test_serves_index_for_root_path` — `GET /api/deploy/<slug>/`
   → 200 con contenido de `index.html`. Content-Type `text/html`.
2. `test_serves_asset_file` — `GET /api/deploy/<slug>/assets/app.js`
   → 200 con contenido.
3. `test_404_on_missing_project` — `GET /api/deploy/nope/x` →
   404 JSON.
4. `test_404_on_non_web_deployable_kind` — setup project con
   `kind="library"` → 404 aunque `dist/` exista.
5. `test_404_on_path_traversal_attempt` — `GET /api/deploy/<slug>/../../etc/passwd`
   → 404 sin leer fuera de `dist/`. Verifica path resolution en
   test con assertion explícita.

**Baseline tras PR-V1-17**: 113 → **118 passed**. Frontend 8 sin
cambios.

## Criterio de hecho

- [ ] `GET /api/deploy/<slug>/` devuelve `index.html` de
  `<project.local_path>/dist/` para proyectos web-deployable.
- [ ] Cualquier archivo bajo `dist/*` servido con MIME correcto.
- [ ] 404 para proyectos no-existentes, `kind != web-deployable`,
  o path traversal.
- [ ] `pytest -q tests/test_deploy_api.py` → 5 passed.
- [ ] `pytest -q` completo → ≥118 passed, 0 regresiones.
- [ ] HANDBOOK sección "Deploy local (PR-V1-17)" con URL,
  contrato, seguridad (traversal guard), known limitations
  (no per-port, no process spawn, no build automático).
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~180.

## Riesgos conocidos

- **Symlinks dentro de `dist/`**: `Path.resolve()` los sigue. Si
  un symlink apunta fuera, el traversal guard los detecta.
- **`FileResponse` y archivos muy grandes**: FastAPI usa
  streaming; OK para MVP.
- **Cache-Control no se setea**. Browser caching depende de
  defaults. Follow-up para cache busting.
- **Concurrent build durante servicio**: si el user corre `npm
  run build` mientras alguien está consumiendo `/dist/*`, puede
  servir archivos half-written. Edge case aceptado.
- **`deploy_port` inutilizado**: documentado en HANDBOOK como
  aspiracional para v1.1. No se lee ni valida en este PR.
- **`kind=library` con `dist/`**: el 404 es intencional; library
  no debe exponer dist. Si alguien quiere que una library
  exponga dist, usa `kind=web-deployable` en el proyecto.

## Notas para Claude Code

- Commits sugeridos (3-4):
  1. `feat(api): deploy static handler for web-deployable projects`
  2. `feat(api): register deploy router under /api`
  3. `test(api): deploy static handler cases`
  4. `docs(v1): handbook deploy local section`
- `deploy.py` plano: router + 1 handler + helpers privados de
  resolución de path.
- NO añadas procesos background. NO toques `finalize.py`. NO
  toques el frontend.
- Si algo ambiguo, PARA y reporta.
