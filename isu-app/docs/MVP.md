# Desk MVP

## Objetivo

Primera versión útil de `desk.yumewagener.com` como panel personal de Arturo y Yume.

## Pantallas

### 1. Home
Resumen rápido del día:
- tareas urgentes
- tareas de hoy
- próximos eventos
- bloque de foco / resumen corto

### 2. My Day
Vista centrada en ejecución diaria:
- tareas seleccionadas para hoy
- tareas vencidas
- tareas urgentes
- sugerencias de Yume
- posibilidad de marcar completadas, posponer o mover

### 3. Tareas
Vista principal de gestión:
- kanban por estado
- filtros por ámbito
- filtros por proyecto
- prioridad
- urgencia
- fecha límite
- etiquetas

### 4. Calendario
Primera versión simple:
- lista de eventos próximos
- vista día / semana más adelante
- relación entre tareas y eventos

### 5. Proyectos
Vista por proyecto con:
- resumen
- tareas activas
- próximas fechas
- notas/contexto breve

### 6. Inbox
Captura rápida de tareas o notas pendientes de clasificar.

## Ámbitos

- personal
- empresa
- proyectos

## Estados de tarea

- inbox
- pendiente
- en_progreso
- bloqueada
- hecha
- archivada

## Campos mínimos de tarea

- título
- descripción breve
- ámbito
- proyecto opcional
- estado
- prioridad (`baja`, `media`, `alta`, `critica`)
- urgente (`true/false`)
- fecha objetivo opcional
- fecha límite opcional
- etiqueta(s)
- origen
- notas

## Comportamientos clave

- promoción automática por tiempo: lo que vence sube de relevancia
- My Day se alimenta de tareas urgentes, vencidas y foco del día
- Yume puede recomendar mover tareas a hoy, semana o urgentes
- separar visualmente personal / empresa / proyectos

## Fuera del MVP

- correo bidireccional
- calendario completo con edición
- múltiples usuarios
- permisos complejos
- clientes/CRM completo
