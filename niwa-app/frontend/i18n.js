/**
 * i18n.js — Lightweight internationalization for Niwa
 * Usage: t('key') returns the translated string for the current locale.
 * Supports interpolation: t('greeting', {name: 'World'}) → "Hola, World"
 */

const I18N = {
  _locale: localStorage.getItem('niwa_locale') || 'es',
  _strings: {},

  get locale() { return this._locale; },

  setLocale(lang) {
    this._locale = lang;
    localStorage.setItem('niwa_locale', lang);
  },

  register(lang, strings) {
    this._strings[lang] = { ...(this._strings[lang] || {}), ...strings };
  },

  t(key, params) {
    const dict = this._strings[this._locale] || this._strings['es'] || {};
    let s = dict[key];
    if (s === undefined) {
      // Fallback to English, then to key itself
      const en = this._strings['en'] || {};
      s = en[key] !== undefined ? en[key] : key;
    }
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
      });
    }
    return s;
  },
};

function _t(key, params) { return I18N.t(key, params); }

// ── Spanish ──
I18N.register('es', {
  // Nav
  'nav.dashboard': 'Dashboard',
  'nav.kanban': 'Kanban',
  'nav.projects': 'Proyectos',
  'nav.system': 'Sistema',
  'nav.settings': 'Ajustes',
  'nav.new_task': 'Nueva tarea',

  // Dashboard KPIs
  'dash.fleet': 'Inteligencia de flota',
  'dash.total_tasks': 'tareas totales',
  'dash.active_tasks': 'Tareas activas',
  'dash.completed': 'Completadas',
  'dash.all_time': 'total',
  'dash.today': 'hoy',
  'dash.velocity': 'Velocidad (7d)',
  'dash.activity': 'Actividad reciente',
  'dash.loading': 'cargando...',

  // Kanban
  'kanban.all_statuses': 'Todos los estados',
  'kanban.all_areas': 'Todas las áreas',
  'kanban.all_projects': 'Todos los proyectos',
  'kanban.add_task': '+ Añadir tarea...',
  'kanban.change_view': 'Cambiar vista',

  // Statuses
  'status.inbox': 'Bandeja',
  'status.pendiente': 'Pendiente',
  'status.en_progreso': 'En progreso',
  'status.bloqueada': 'Bloqueada',
  'status.revision': 'Revisión',
  'status.hecha': 'Hecha',
  'status.archivada': 'Archivada',

  // Priorities
  'priority.baja': 'Baja',
  'priority.media': 'Media',
  'priority.alta': 'Alta',
  'priority.critica': 'Crítica',

  // Areas
  'area.personal': 'Personal',
  'area.empresa': 'Empresa',
  'area.proyecto': 'Proyecto',

  // Task modal
  'task.new': 'Nueva tarea',
  'task.edit': 'Editar tarea',
  'task.title': 'Título',
  'task.description': 'Descripción',
  'task.status': 'Estado',
  'task.priority': 'Prioridad',
  'task.category': 'Área / Proyecto',
  'task.area': 'Área',
  'task.project': 'Proyecto',
  'task.due_date': 'Fecha límite',
  'task.start_date': 'Fecha inicio',
  'task.labels': 'Etiquetas',
  'task.add_label': 'Añadir etiqueta...',
  'task.attachments': 'Adjuntos',
  'task.add_files': 'Añadir archivos...',
  'task.notes': 'Notas',
  'task.urgent': 'Urgente',
  'task.auto_execute': 'Auto-ejecutar',
  'task.save': 'Guardar tarea',
  'task.delete': 'Eliminar',
  'task.none': '— Ninguno —',
  'task.created': 'Tarea creada',
  'task.updated': 'Tarea actualizada',
  'task.deleted': 'Tarea eliminada',
  'task.delete_confirm': '¿Eliminar esta tarea?',
  'task.moved': 'Tarea movida a {status}',
  'task.not_found': 'Tarea no encontrada',
  'task.save_first': 'Guarda la tarea primero, luego añade adjuntos',
  'task.upload_failed': 'Error al subir archivo',

  // Projects
  'proj.no_projects': 'No hay proyectos. Las tareas con campo "proyecto" aparecerán aquí.',
  'proj.project': 'Proyecto: {name}',
  'proj.loading_tree': 'Cargando árbol...',
  'proj.empty_dir': 'Directorio vacío.',
  'proj.error_tree': 'No se pudo cargar el árbol de archivos.',
  'proj.error_files': 'Error cargando archivos.',
  'proj.files': '{n} archivo(s)',
  'proj.active': '{n} activo(s)',
  'proj.tasks': 'tareas',

  // System
  'sys.overview': 'General',
  'sys.logs': 'Logs',
  'sys.config': 'Config',
  'sys.stats': 'Stats',
  'sys.routines': 'Rutinas',
  'sys.no_logs': 'No hay logs disponibles.',
  'sys.no_routines': 'No hay rutinas configuradas.',
  'sys.no_config': 'No se pudo cargar la configuración.',
  'sys.routine_enabled': 'Rutina activada',
  'sys.routine_disabled': 'Rutina desactivada',
  'sys.routine_executed': 'Rutina ejecutada',
  'sys.notify_muted': 'Notificaciones silenciadas',
  'sys.notify_active': 'Notificaciones activadas',
  'sys.run_audit': 'Ejecutar auditoría',
  'sys.auto_mode': 'Modo auto: tareas pasan al executor',
  'sys.manual_mode': 'Modo manual: tú decides qué ejecutar',

  // Search
  'search.placeholder': 'Buscar tareas, proyectos...',
  'search.no_results': 'Sin resultados.',
  'error.loading_dashboard': 'Error al cargar el dashboard',
  'search.esc': 'ESC para cerrar',
  'search.enter': 'ENTER para seleccionar',

  // Misc
  'misc.copied': 'Copiado: {text}',
  'misc.refreshed': 'Actualizado',
  'misc.no_data': 'Sin datos',
  'misc.cancel': 'Cancelar',
  'misc.save': 'Guardar',
  'misc.delete': 'Eliminar',
  'misc.close': 'Cerrar',

  // Settings
  'settings.title': 'Ajustes',
  'settings.language': 'Idioma',
  'settings.language_desc': 'Idioma de la interfaz',
  'settings.saved': 'Ajustes guardados',
  'settings.idle_review': 'Idle review: auto-asignar tareas',
  'settings.notify_completed': 'Avisos: tareas completadas',
  'settings.notify_completed_desc': 'Telegram al completar una tarea',
  'settings.notify_errors': 'Avisos: errores y bloqueos',
  'settings.notify_errors_desc': 'Telegram si una tarea falla o un servicio cae',
  'settings.notify_warnings': 'Avisos: warnings del executor',
  'settings.notify_warnings_desc': 'Telegram en errores transitorios y reintentos',
  'settings.notification_format': 'Formato de notificaciones',
  'settings.notification_format_desc': 'Elige cómo recibir las notificaciones del executor',
  'settings.notification_format_text': 'Solo texto',
  'settings.notification_format_audio': 'Solo audio (TTS)',
  'settings.notification_format_both': 'Texto y audio',
  'settings.deactivated': 'Desactivado',
  'settings.activated': 'Activado',
  'proj.idle_review': 'Idle review',
  'proj.idle_review_enabled': 'Activado: se generarán mejoras automáticas',
  'proj.idle_review_disabled': 'Desactivado: no se generarán mejoras',

  // Dashboard
  'dashboard.my_day': 'Mi día',

  // Dashboard extra
  'dash.pending_blocked': '{p} pendientes · {b} bloqueadas',
  'dash.completed_summary': '{n} completadas total · ~{avg}/día media',
  'dash.buy_signals': '{buys} comprar · {holds} mantener',
  'dash.hold_signals': '{holds} mantener',
  'dash.unavailable': 'no disponible',
  'dash.all_clear': 'Todo en orden — sin bloqueos ni revisiones pendientes.',
  'dash.done_of_total': '/{total} hechas',
  'dash.open_count': '{n} abiertas',
  'dash.no_completions': 'Sin datos de completados',

  // Kanban columns
  'kanban.col_todo': 'PENDIENTE',
  'kanban.col_doing': 'EN CURSO',
  'kanban.col_review': 'REVISIÓN',
  'kanban.col_blocked': 'BLOQUEADA',
  'kanban.col_done': 'HECHA',

  // Projects extra
  'proj.no_area': 'Sin área',
  'proj.status_active': 'ACTIVO',
  'proj.status_stable': 'ESTABLE',
  'proj.no_activity': 'Sin actividad para este proyecto.',
  'proj.tree_truncated': 'Árbol truncado — proyecto grande. Usa carpetas para navegar.',

  // System extra
  'sys.last_run': 'Última ejecución:',
  'sys.next_run': 'Próxima:',
  'sys.never': 'nunca',
  'sys.error_msg': 'Error: {msg}',
  'sys.running_audit': 'Ejecutando auditoría...',

  // Stats
  'stats.total': 'Total',
  'stats.open': 'Abiertas',
  'stats.done': 'Hechas',
  'stats.overdue': 'Vencidas',

  // Task extra
  'task.save_error': 'Error al guardar tarea',
  'task.reject_reason': 'Motivo del rechazo',
  'task.rejected': 'Tarea rechazada',
  'task.reject_failed': 'Error al rechazar tarea',
  'task.create_failed': 'Error al crear tarea',
  'task.delete_failed': 'Error al eliminar tarea',
  'task.move_failed': 'Error al mover tarea',
  'task.no_attachments': 'Sin adjuntos',
  'task.upload_error': 'Error al subir',
  'task.labels_sync_warning': 'Error al sincronizar etiquetas',
  'task.delete_attachment_failed': 'Error al eliminar adjunto',

  // Search extra
  'search.tasks': 'Tareas',
  'search.projects': 'Proyectos',
  'search.no_area': 'sin área',

  // Misc extra
  'misc.copied_short': '¡Copiado!',

  // Time ago
  'time.just_now': 'ahora',
  'time.minutes_ago': 'hace {n}m',
  'time.hours_ago': 'hace {n}h',
  'time.days_ago': 'hace {n}d',

  // Kanban card phases
  'phase.executing': 'Fase 1: Ejecutando',
  'phase.reviewing': 'Fase 2: Revisando',
  'phase.review_rejected': 'Fase 2: Revisión rechazada (iter {n})',
  'phase.fixing': 'Fase 3: Corrigiendo (iter {n})',
  'phase.waiting_agent': 'Esperando agente',
  'phase.no_agent': 'Sin agente',
  'phase.requires_action': 'Requiere acción',
  'phase.reviewed': 'Revisada: {msg}',

  // Pipeline / Bottlenecks
  'pipeline.no_data': 'Sin datos de pipeline',
  'pipeline.summary': 'Resumen del pipeline',
  'pipeline.no_tasks': 'No hay tareas completadas en este periodo',
  'pipeline.total_time': 'Tiempo medio total',
  'pipeline.queue_time': 'Tiempo en cola',
  'pipeline.execution_time': 'Tiempo de ejecución',
  'pipeline.review_time': 'Tiempo de revisión',
  'pipeline.all_projects': 'Todos los proyectos',
  'pipeline.stage_pendiente': 'Pendiente',
  'pipeline.stage_en_progreso': 'En progreso',
  'pipeline.stage_revision': 'Revisión',
  'pipeline.stage_hecha': 'Hecha',
  'pipeline.tasks': '{n} tareas',

  // Overdue badge
  'task.overdue': 'Vencida',

  // Notes
  'nav.notes': 'Notas',
  'notes.title': 'Notas',
  'notes.subtitle': 'Base de conocimiento y notas del proyecto.',
  'notes.new_note': 'Nueva nota',
  'notes.edit_note': 'Editar nota',
  'notes.no_project': 'Sin proyecto',
  'notes.empty': 'No hay notas. Crea tu primera nota.',
  'notes.created': 'Nota creada',
  'notes.updated': 'Nota actualizada',
  'notes.deleted': 'Nota eliminada',
  'notes.delete_confirm': '¿Eliminar esta nota?',
  'notes.title_required': 'El título es obligatorio',
});

// ── English ──
I18N.register('en', {
  // Nav
  'nav.dashboard': 'Dashboard',
  'nav.kanban': 'Kanban',
  'nav.projects': 'Projects',
  'nav.system': 'System',
  'nav.settings': 'Settings',
  'nav.new_task': 'New Task',

  // Dashboard KPIs
  'dash.fleet': 'Fleet Intelligence',
  'dash.total_tasks': 'total tasks',
  'dash.active_tasks': 'Active Tasks',
  'dash.completed': 'Completed',
  'dash.all_time': 'all time',
  'dash.today': 'today',
  'dash.velocity': 'Velocity (7d)',
  'dash.activity': 'Recent Activity',
  'dash.loading': 'loading...',

  // Kanban
  'kanban.all_statuses': 'All Statuses',
  'kanban.all_areas': 'All Areas',
  'kanban.all_projects': 'All Projects',
  'kanban.add_task': '+ Add task...',
  'kanban.change_view': 'Change view',

  // Statuses
  'status.inbox': 'Inbox',
  'status.pendiente': 'To-Do',
  'status.en_progreso': 'In Progress',
  'status.bloqueada': 'Blocked',
  'status.revision': 'Review',
  'status.hecha': 'Done',
  'status.archivada': 'Archived',

  // Priorities
  'priority.baja': 'Low',
  'priority.media': 'Medium',
  'priority.alta': 'High',
  'priority.critica': 'Critical',

  // Areas
  'area.personal': 'Personal',
  'area.empresa': 'Business',
  'area.proyecto': 'Project',

  // Task modal
  'task.new': 'New Task',
  'task.edit': 'Edit Task',
  'task.title': 'Title',
  'task.description': 'Description',
  'task.status': 'Status',
  'task.priority': 'Priority',
  'task.category': 'Area / Project',
  'task.area': 'Area',
  'task.project': 'Project',
  'task.due_date': 'Due Date',
  'task.start_date': 'Start Date',
  'task.labels': 'Labels',
  'task.add_label': 'Add label...',
  'task.attachments': 'Attachments',
  'task.add_files': 'Add files...',
  'task.notes': 'Notes',
  'task.urgent': 'Urgent',
  'task.auto_execute': 'Auto-execute',
  'task.save': 'Save Task',
  'task.delete': 'Delete',
  'task.none': '— None —',
  'task.created': 'Task created',
  'task.updated': 'Task updated',
  'task.deleted': 'Task deleted',
  'task.delete_confirm': 'Delete this task?',
  'task.moved': 'Task moved to {status}',
  'task.not_found': 'Task not found',
  'task.save_first': 'Save the task first, then add attachments',
  'task.upload_failed': 'Upload failed',

  // Projects
  'proj.no_projects': 'No projects found. Tasks with a "project" field will appear here.',
  'proj.project': 'Project: {name}',
  'proj.loading_tree': 'Loading tree...',
  'proj.empty_dir': 'Empty directory.',
  'proj.error_tree': 'Could not load file tree.',
  'proj.error_files': 'Error loading files.',
  'proj.files': '{n} file(s)',
  'proj.active': '{n} active',
  'proj.tasks': 'tasks',

  // System
  'sys.overview': 'Overview',
  'sys.logs': 'Logs',
  'sys.config': 'Config',
  'sys.stats': 'Stats',
  'sys.routines': 'Routines',
  'sys.no_logs': 'No logs available.',
  'sys.no_routines': 'No routines configured.',
  'sys.no_config': 'Could not load config.',
  'sys.routine_enabled': 'Routine enabled',
  'sys.routine_disabled': 'Routine disabled',
  'sys.routine_executed': 'Routine executed',
  'sys.notify_muted': 'Notifications muted',
  'sys.notify_active': 'Notifications enabled',
  'sys.run_audit': 'Run Audit',
  'sys.auto_mode': 'Auto mode: tasks go to the executor',
  'sys.manual_mode': 'Manual mode: you decide what to execute',

  // Search
  'search.placeholder': 'Search tasks, projects...',
  'search.no_results': 'No results found.',
  'error.loading_dashboard': 'Error loading dashboard',
  'search.esc': 'ESC to close',
  'search.enter': 'ENTER to select',

  // Misc
  'misc.copied': 'Copied: {text}',
  'misc.refreshed': 'Refreshed',
  'misc.no_data': 'No data',
  'misc.cancel': 'Cancel',
  'misc.save': 'Save',
  'misc.delete': 'Delete',
  'misc.close': 'Close',

  // Settings
  'settings.title': 'Settings',
  'settings.language': 'Language',
  'settings.language_desc': 'Interface language',
  'settings.saved': 'Settings saved',
  'settings.idle_review': 'Idle review: auto-assign tasks',
  'settings.notify_completed': 'Notifications: completed tasks',
  'settings.notify_completed_desc': 'Telegram when a task is completed',
  'settings.notify_errors': 'Notifications: errors and blocks',
  'settings.notify_errors_desc': 'Telegram if a task fails or a service goes down',
  'settings.notify_warnings': 'Notifications: executor warnings',
  'settings.notify_warnings_desc': 'Telegram on transient errors and retries',
  'settings.notification_format': 'Notification format',
  'settings.notification_format_desc': 'Choose how to receive executor notifications',
  'settings.notification_format_text': 'Text only',
  'settings.notification_format_audio': 'Audio only (TTS)',
  'settings.notification_format_both': 'Text and audio',
  'settings.deactivated': 'Deactivated',
  'settings.activated': 'Activated',
  'proj.idle_review': 'Idle review',
  'proj.idle_review_enabled': 'Enabled: automatic improvements will be generated',
  'proj.idle_review_disabled': 'Disabled: no improvements will be generated',

  // Dashboard
  'dashboard.my_day': 'My Day',

  // Dashboard extra
  'dash.pending_blocked': '{p} pending · {b} blocked',
  'dash.completed_summary': '{n} completed total · ~{avg}/day avg',
  'dash.buy_signals': '{buys} buy · {holds} hold',
  'dash.hold_signals': '{holds} hold',
  'dash.unavailable': 'unavailable',
  'dash.all_clear': 'All clear — no blocks or pending reviews.',
  'dash.done_of_total': '/{total} done',
  'dash.open_count': '{n} open',
  'dash.no_completions': 'No completion data',

  // Kanban columns
  'kanban.col_todo': 'TO-DO',
  'kanban.col_doing': 'DOING',
  'kanban.col_review': 'REVIEW',
  'kanban.col_blocked': 'BLOCKED',
  'kanban.col_done': 'DONE',

  // Projects extra
  'proj.no_area': 'No area',
  'proj.status_active': 'ACTIVE',
  'proj.status_stable': 'STABLE',
  'proj.no_activity': 'No activity for this project.',
  'proj.tree_truncated': 'Tree truncated — large project. Use folders to browse.',

  // System extra
  'sys.last_run': 'Last run:',
  'sys.next_run': 'Next:',
  'sys.never': 'never',
  'sys.error_msg': 'Error: {msg}',
  'sys.running_audit': 'Running security audit...',

  // Stats
  'stats.total': 'Total',
  'stats.open': 'Open',
  'stats.done': 'Done',
  'stats.overdue': 'Overdue',

  // Task extra
  'task.save_error': 'Failed to save task',
  'task.reject_reason': 'Rejection reason',
  'task.rejected': 'Task rejected',
  'task.reject_failed': 'Failed to reject task',
  'task.create_failed': 'Failed to create task',
  'task.delete_failed': 'Failed to delete task',
  'task.move_failed': 'Failed to move task',
  'task.no_attachments': 'No attachments',
  'task.upload_error': 'Upload error',
  'task.labels_sync_warning': 'Error syncing labels',
  'task.delete_attachment_failed': 'Error deleting attachment',

  // Search extra
  'search.tasks': 'Tasks',
  'search.projects': 'Projects',
  'search.no_area': 'no area',

  // Misc extra
  'misc.copied_short': 'Copied!',

  // Time ago
  'time.just_now': 'just now',
  'time.minutes_ago': '{n}m ago',
  'time.hours_ago': '{n}h ago',
  'time.days_ago': '{n}d ago',

  // Kanban card phases
  'phase.executing': 'Phase 1: Executing',
  'phase.reviewing': 'Phase 2: Reviewing',
  'phase.review_rejected': 'Phase 2: Review rejected (iter {n})',
  'phase.fixing': 'Phase 3: Fixing (iter {n})',
  'phase.waiting_agent': 'Waiting for agent',
  'phase.no_agent': 'No agent',
  'phase.requires_action': 'Requires action',
  'phase.reviewed': 'Reviewed: {msg}',

  // Pipeline / Bottlenecks
  'pipeline.no_data': 'No pipeline data',
  'pipeline.summary': 'Pipeline summary',
  'pipeline.no_tasks': 'No completed tasks in this period',
  'pipeline.total_time': 'Average total time',
  'pipeline.queue_time': 'Queue time',
  'pipeline.execution_time': 'Execution time',
  'pipeline.review_time': 'Review time',
  'pipeline.all_projects': 'All projects',
  'pipeline.stage_pendiente': 'To-Do',
  'pipeline.stage_en_progreso': 'In Progress',
  'pipeline.stage_revision': 'Review',
  'pipeline.stage_hecha': 'Done',
  'pipeline.tasks': '{n} tasks',

  // Overdue badge
  'task.overdue': 'Overdue',

  // Notes
  'nav.notes': 'Notes',
  'notes.title': 'Notes',
  'notes.subtitle': 'Knowledge base and project notes.',
  'notes.new_note': 'New note',
  'notes.edit_note': 'Edit note',
  'notes.no_project': 'No project',
  'notes.empty': 'No notes yet. Create your first note.',
  'notes.created': 'Note created',
  'notes.updated': 'Note updated',
  'notes.deleted': 'Note deleted',
  'notes.delete_confirm': 'Delete this note?',
  'notes.title_required': 'Title is required',
});
