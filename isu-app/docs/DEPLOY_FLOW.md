# Flujo estable de cambios en Desk

Una tarea de `Desk` no se considera terminada solo porque el código exista en local.

## Regla de cierre

Para tareas del proyecto `Desk` (`project_id = proj-desk`) el cierre correcto es:

1. código aplicado
2. validación local
3. commit
4. despliegue / recreate de Desk si aplica
5. verificación post-deploy
6. solo entonces: marcar la tarea como `hecha`

## Guardia activa en Desk

El backend ahora bloquea que una tarea de `Desk` pase a `hecha` si no lleva el marcador de cierre:

- `desk-deploy:verified`

Ese marcador lo añade el flujo de cierre, no la edición manual normal.

Si alguien intenta cerrar una tarea de Desk antes de tiempo, la API devuelve `409 desk_deploy_closure_required`.

## Script operativo

Script principal:

```bash
cd /home/yume/.openclaw/workspace/Desk
./scripts/desk_change_flow.sh --task-id <uuid> --commit-message "desk: ..."
```

Qué hace:

- compila `backend/app.py`
- intenta health-check local previo
- hace commit si hay cambios
- recrea el contenedor `desk` con Docker Compose si hay cambios o se fuerza
- verifica `/health`
- sella la tarea en SQLite con `desk-deploy:verified`
- marca la tarea como `hecha`

## Flags útiles

```bash
--skip-commit   # si el commit ya se hizo fuera
--skip-deploy   # para cambios que no requieren recreate
--force-deploy  # obliga recreate aunque no detecte cambios pendientes
```

## Ejemplos

Cambio normal con despliegue:

```bash
./scripts/desk_change_flow.sh \
  --task-id 00000000-0000-0000-0000-000000000000 \
  --commit-message "desk: mejora flujo de cierre"
```

Cambio documental o interno sin recreate:

```bash
./scripts/desk_change_flow.sh \
  --task-id 00000000-0000-0000-0000-000000000000 \
  --commit-message "desk: documenta flujo de deploy" \
  --skip-deploy
```

## Qué cambia para Yume/Samantha

- mover la tarea a revisión o en progreso cuando el código ya está hecho
- no poner `hecha` manualmente en tareas de Desk
- cerrar con `desk_change_flow.sh`
- si falla validación, commit, deploy o verify, la tarea sigue abierta
