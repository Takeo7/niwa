# Niwa Release Runbook

Guía operativa para instalar Niwa, actualizarlo, recuperarse de un fallo y
validar una release antes de etiquetar. El objetivo del PR-58..62 fue
que este documento sea ejecutable sin adivinar.

## Flujo del update en 1 párrafo

El **CLI** (`niwa update`) es el único camino real de actualización. La
**UI** (Sistema → Actualizar) muestra estado + genera el comando a
copiar, pero no ejecuta. El motor (`bin/update_engine.py`) hace
automáticamente: guard de repo dirty → backup SQLite → git pull →
copiar ficheros → rebuild container → restart executor → health-check.
Si el health-check falla dispara auto-revert (git reset al commit
previo + restore de DB). Cada run queda anotado en
`<install>/data/update-log.json` (últimos 20). La UI consume ese log.

## 1. Instalación limpia

```bash
# En el VPS (root)
cd /root
git clone https://github.com/Takeo7/niwa.git
cd niwa
git checkout v0.2
./niwa install --quick --mode assistant --yes
```

Al terminar el install imprime el **comando canónico** — normalmente
`niwa` (symlinked a `/usr/local/bin/niwa` en sudo installs). Si el
install no pudo dejar nada en el PATH, avisa con el path absoluto a
usar; todo el resto del runbook asume el comando corto, sustitúyelo
si hace falta.

Al terminar anota:
- La contraseña generada (se imprime en el summary; **no se repite**).
- La IP/puerto del app (por defecto `http://<host>:8080`).

## 2. Comprobación post-install

```bash
# Estado de los contenedores
docker compose -f /root/.niwa/docker-compose.yml ps

# Healthcheck del app
curl -s http://127.0.0.1:8080/health

# Estado enriquecido (rama, commit, schema, último backup)
curl -s http://127.0.0.1:8080/api/version | python3 -m json.tool
```

En la UI: **Sistema → Actualizar** debe mostrar:
- Badges con versión, rama `v0.2`, commit corto, schema version.
- Banner verde "Al día con `origin/v0.2`".
- "Último backup" vacío hasta que ejecutes un update.

## 3. Actualizar

### Pre-vuelo

```bash
cd /root/niwa
git status --porcelain  # debe estar vacío
git -C /root/niwa log --oneline -3
```

Si `git status --porcelain` devuelve algo, limpia antes — `niwa
update` abortará si el repo está sucio:

```bash
git stash                  # preferible: guardar cambios
# o: git checkout .        # descartar no-stageados
# o: git reset --hard      # TODO fuera
```

### Ejecutar

```bash
niwa update
```

Al terminar se imprime un **manifest** con:

- `branch`, `before_commit`, `after_commit`.
- `backup_path` (la red de seguridad).
- `components_updated` (executor, MCP servers, app:image, etc.).
- `warnings` / `errors` si los hubiera.
- `needs_restart` si falló el systemctl.

### Verificar en la UI

**Sistema → Actualizar**:

- "Última actualización" con badge **OK** (verde).
- `before → after` visible.
- `backup_path` registrado.

## 4. Recovery de un update fallido

### 4.a — Auto-revert disparado

Si el health-check post-update falla, el motor revierte solo: `git reset
--hard <before>` + restore de DB desde el backup. En el manifest verás:

```
  success: false
  reverted: true
  errors: ["auto-revert completado: instalación restaurada..."]
```

En la UI, "Última actualización" aparece con badge **Revertida** (naranja)
+ los warnings que dispararon el revert. **No hay acción manual.**

### 4.b — Auto-revert no recuperó

Caso raro. El manifest queda:

```
  success: false
  reverted: false
  errors: ["Estado inconsistente: el update falló Y el auto-revert no recuperó..."]
```

Acción manual:

```bash
# Mira en el log qué backup tenías
cat /root/.niwa/data/update-log.json | python3 -m json.tool | tail -30

# Restora a mano (DB + código)
niwa restore --from=/root/.niwa/data/backups/niwa-<timestamp>.sqlite3
```

`niwa restore` lee la entrada del log para saber a qué commit revertir
el código. Si la entrada existe: hace `git checkout <before_commit>` +
copy ejecutor/MCP + stop app + restore DB + rebuild + health-check.
Si no existe: solo restore de DB con warning explícito (usa `--db-only`
si quieres ser explícito).

### 4.c — Solo restaurar DB (no código)

Cuando ya arreglaste el código a mano y solo quieres recuperar datos:

```bash
niwa restore --from=/path/al/backup.sqlite3 --db-only
```

## 5. Rotación de secretos (opt-in)

Reinstall same-mode **preserva** por defecto tokens, admin password y
session secret (PR-60). Para forzar rotación (por compromiso, off-boarding
de un operador, etc.):

```bash
niwa install --quick --mode <modo> --yes --rotate-secrets
```

El password nuevo se imprime al final. Hay que actualizar:
- OpenClaw / clientes MCP con el nuevo `MCP_GATEWAY_AUTH_TOKEN`.
- Marcadores/cookies: el session secret nuevo invalida los logins
  activos (forzará re-login).

## 6. Pre-release validation (antes de etiquetar)

Checklist para validar una release candidate en un VPS limpio:

- [ ] **Install limpia**: `./niwa install --quick --mode assistant --yes` (tras el primer install, todos los demás pasos usan `niwa …` ya disponible en PATH).
      completa sin errores.
- [ ] **Smoke post-install**: `docker compose ps` todos `Up`, `curl
      /health` 200, UI responde.
- [ ] **Crear data**: crea al menos 1 proyecto y 3 tareas via UI (o via
      API: `POST /api/projects`, `POST /api/tasks`).
- [ ] **Update**: `niwa update` completa, manifest muestra `success: true`.
- [ ] **Data intact**: tareas y proyectos siguen visibles post-update.
      Verifica en `GET /api/projects` y `GET /api/tasks`.
- [ ] **UI banner OK**: Sistema → Actualizar muestra "Última
      actualización: OK" y `before → after` correctos.
- [ ] **Repo-dirty guard**: modifica a mano cualquier fichero del repo y
      ejecuta `niwa update`. Debe abortar con mensaje accionable (no
      avanza).
- [ ] **Restore round-trip**: `niwa restore --from=<backup>` sobre el
      backup pre-update. `/api/version.schema_version` y el contenido
      de la DB vuelven al estado anterior.
- [ ] **Rotate secrets**: `install --rotate-secrets` rota tokens, el
      login viejo ya no funciona. Tras volver a loguearse con el nuevo
      password, todo sigue intacto.

## 7. Comandos de referencia

```bash
# Estado enriched
curl -s http://127.0.0.1:8080/api/version | python3 -m json.tool

# Backup manual (independiente del flujo de update)
niwa backup

# Rotación automática de backups la hace el engine (>14 días)

# Ver últimos updates
python3 -c "import json; print(json.dumps(json.load(open('/root/.niwa/data/update-log.json')), indent=2))"

# Restore con rollback de código
niwa restore --from=/root/.niwa/data/backups/niwa-<timestamp>.sqlite3

# Restore solo DB
niwa restore --from=/ruta/backup.sqlite3 --db-only

# Forzar rotación de secretos
niwa install --quick --mode <modo> --yes --rotate-secrets
```

## 8. Qué NO hacer

- **No ejecutes `git pull` manualmente** en el repo del host. El motor
  se encarga y hace backup antes. Hacerlo a mano se salta la red.
- **No borres** `<install>/data/backups/` completo — la rotación de 14
  días es suficiente.
- **No rotes secretos sin avisar** a los clientes MCP externos. Rompe
  integraciones. Usa `--rotate-secrets` solo cuando sea necesario.
- **No modifiques el repo del host entre updates**. Si lo haces, el
  siguiente update aborta por repo-dirty (es la intención).
