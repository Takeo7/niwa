# Desk

Desk es el panel personal de Arturo y Yume.

Objetivo inicial:
- tareas con kanban
- vista My Day
- proyectos / personal / empresa
- calendario
- correo resumido y procesado
- datos locales en el VPS

## Principios

- datos en local siempre que sea posible
- integraciones con permisos mínimos
- Yume trabaja sobre datos almacenados en Desk, no sobre cuentas personales abiertas sin control
- privacidad por defecto

## Estructura

- `frontend/` interfaz web
- `backend/` API y lógica de servidor
- `db/` esquema, migraciones y base local
- `docs/` definición funcional y técnica
- `infra/` despliegue y reverse proxy
- `scripts/` utilidades de desarrollo/operación
- `storage/` importaciones, exportaciones y adjuntos locales
- `config/` configuración local del proyecto

## Agentes

El alta estable de agentes se hace con:

```bash
/home/yume/.openclaw/workspace/scripts/create-agent.sh ...
```

Referencia rápida: `/home/yume/.openclaw/workspace/docs/agent-onboarding.md`

## Flujo de cambios y cierre

Para cambios en Desk ya no vale con dejar el código hecho en local. La tarea solo se cierra después de validación, commit, deploy/recreate si aplica y verificación post-deploy.

Referencia: `docs/DEPLOY_FLOW.md`

Script operativo:

```bash
cd /home/yume/.openclaw/workspace/Desk
./scripts/desk_change_flow.sh --task-id <uuid> --commit-message "desk: ..."
```
