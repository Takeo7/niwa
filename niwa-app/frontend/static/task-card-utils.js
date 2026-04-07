// ── Task Card Utilities ─────────────────────────────────────────────
// Extracted from app.js: renderExecPhase, renderCardFooter, renderTaskPipeline

function renderExecPhase(t) {
  if (t.status === 'en_progreso' && t.assigned_to_claude) {
    var notes = t.notes || '';
    var phase = '';
    var phaseIcon = '';
    var phaseToken = 'agent-claude';
    if (notes.includes('Aplicando fix')) {
      var fixMatch = notes.match(/Aplicando fix \(iteración (\d+)\)/);
      var iter = fixMatch ? fixMatch[1] : '?';
      phase = 'Fase 3: Corrigiendo (iter ' + iter + ')';
      phaseIcon = 'build';
      phaseToken = 'warning';
    } else if (notes.includes('Rechazada') || notes.includes('Iniciando revisión')) {
      var rejMatch = notes.match(/Rechazada \(iteración (\d+)\)/);
      if (rejMatch) {
        phase = 'Fase 2: Revisión rechazada (iter ' + rejMatch[1] + ')';
        phaseIcon = 'rate_review';
        phaseToken = 'error';
      } else {
        phase = 'Fase 2: Revisando';
        phaseIcon = 'rate_review';
        phaseToken = 'secondary';
      }
    } else if (notes.includes('[claude-code] Ejecución completada')) {
      phase = 'Fase 2: Revisando';
      phaseIcon = 'rate_review';
      phaseToken = 'secondary';
    } else {
      phase = 'Fase 1: Ejecutando';
      phaseIcon = 'code';
      phaseToken = 'agent-claude';
    }
    return '<div class="flex items-center gap-1.5 mt-2 px-2 py-1 rounded bg-' + phaseToken + '/10"><span class="w-1.5 h-1.5 rounded-full animate-pulse bg-' + phaseToken + '"></span><span class="material-symbols-outlined text-' + phaseToken + '" style="font-size:12px">' + phaseIcon + '</span><span class="text-[10px] font-medium text-' + phaseToken + '">' + phase + '</span></div>';
  } else if (t.status === 'en_progreso' && t.assigned_to_yume) {
    return '<div class="flex items-center gap-1.5 mt-2 px-2 py-1 rounded bg-warning/10"><span class="material-symbols-outlined text-warning" style="font-size:12px">warning</span><span class="text-[10px] text-warning">Esperando agente</span></div>';
  } else if (t.status === 'en_progreso') {
    return '<div class="flex items-center gap-1.5 mt-2 px-2 py-1 rounded bg-error/10"><span class="material-symbols-outlined text-error" style="font-size:12px">error</span><span class="text-[10px] text-error">Sin agente</span></div>';
  } else if (t.status === 'bloqueada') {
    var bNotes = t.notes || '';
    var blockMatch = bNotes.match(/Bloqueada[^:]*:\s*(.+)/);
    var reason = blockMatch ? blockMatch[1].substring(0,60) : 'Requiere acción';
    return '<div class="flex items-center gap-1.5 mt-2 px-2 py-1 rounded bg-red-500/10"><span class="material-symbols-outlined text-red-400" style="font-size:12px">block</span><span class="text-[10px] text-red-400 truncate">' + escHtml(reason) + '</span></div>';
  } else if (t.status === 'hecha' && t.notes && t.notes.includes('[reviewer]')) {
    var approvedMatch = t.notes.match(/\[reviewer\] ✅ Aprobada[^:]*:\s*(.+)/);
    if (approvedMatch) {
      return '<div class="flex items-center gap-1.5 mt-2 px-2 py-1 rounded bg-green-500/10"><span class="material-symbols-outlined text-green-400" style="font-size:12px">verified</span><span class="text-[10px] text-green-400 truncate">Revisada: ' + escHtml(approvedMatch[1].substring(0,50)) + '</span></div>';
    }
  }
  return '';
}

function renderCardFooter(t, prio) {
  var priorityColors = { critica: 'error', alta: 'secondary', media: 'on-surface-variant', baja: 'outline' };
  var priorityLabels = { critica: _t('priority.critica'), alta: _t('priority.alta'), media: _t('priority.media'), baja: _t('priority.baja') };
  var pc = priorityColors[prio] || 'on-surface-variant';
  var timeTag = computeTimeTag(t);
  var r = '<div class="flex items-center justify-between pt-2 border-t border-on-surface-variant/5 mt-2">';
  r += '<div class="flex items-center gap-2">';
  if (t.due_at) {
    var isOverdue = t.due_at < new Date().toISOString().slice(0,10) && !['hecha','archivada'].includes(t.status);
    r += '<div class="flex items-center gap-1 ' + (isOverdue ? 'text-error' : 'text-on-surface-variant') + '">';
    r += '<span class="material-symbols-outlined text-xs">calendar_today</span>';
    r += '<span class="text-[11px]">' + t.due_at.slice(5) + '</span>';
    if (isOverdue) {
      r += '<span class="ml-1 px-1.5 py-0.5 bg-error/15 text-error rounded-full text-[9px] font-bold uppercase">' + _t('task.overdue') + '</span>';
    }
    r += '</div>';
  }
  r += '<span class="card-time-tag">' + timeTag + '</span>';
  r += '</div>';
  r += '<span class="px-2 py-0.5 bg-' + pc + '/10 text-' + pc + ' rounded-full text-[10px] font-bold uppercase tracking-wider">' + (priorityLabels[prio] || 'Media') + '</span>';
  r += '</div>';
  return r;
}

function renderTaskPipeline(pipeline) {
  const container = document.getElementById('task-pipeline-container');
  const box = document.getElementById('task-pipeline');
  if (!container || !box) return;
  if (!pipeline || !pipeline.steps || !pipeline.steps.length || pipeline.steps.every(s => s.success === null)) {
    container.classList.add('hidden');
    return;
  }
  container.classList.remove('hidden');

  const PHASE_ICONS = {triage:'route', execute:'code', review:'verified', deploy:'rocket_launch',
    verify:'checklist', visual:'visibility', coverage:'bar_chart'};
  const ordered = ['triage','execute','review','deploy','verify','visual','coverage'];
  const steps = [];
  // Group by phase, keep last result per phase
  const byPhase = {};
  for (const s of pipeline.steps) {
    if (!byPhase[s.phase] || s.timestamp > (byPhase[s.phase].timestamp || '')) byPhase[s.phase] = s;
  }
  for (const phase of ordered) {
    if (byPhase[phase]) steps.push(byPhase[phase]);
  }

  const summary = pipeline.summary || {};
  let html = '';

  // Summary line
  if (summary.total_duration_s > 0) {
    const dur = summary.total_duration_s < 60 ? summary.total_duration_s + 's' : (summary.total_duration_s / 60).toFixed(1) + 'min';
    html += `<div class="flex items-center gap-2 mb-2 text-[10px] text-on-surface-variant">
      <span class="material-symbols-outlined text-xs">timer</span>
      ${dur} total · ${summary.steps_passed || 0} OK · ${summary.steps_failed || 0} fallos
    </div>`;
  }

  // Steps
  html += '<div class="flex flex-wrap gap-1.5">';
  for (const s of steps) {
    const icon = PHASE_ICONS[s.phase] || 'help';
    let bg, fg, tooltip;
    if (s.success === true) {
      bg = 'bg-tertiary/15'; fg = 'text-tertiary'; tooltip = s.label + ': OK';
    } else if (s.success === false) {
      bg = 'bg-error/15'; fg = 'text-error'; tooltip = s.label + ': ' + (s.error || 'falló');
    } else {
      bg = 'bg-surface-dim/40'; fg = 'text-on-surface-variant'; tooltip = s.label + ': pendiente';
    }
    const dur = s.duration_s > 0 ? (s.duration_s < 60 ? Math.round(s.duration_s) + 's' : (s.duration_s / 60).toFixed(1) + 'm') : '';
    html += `<div class="flex items-center gap-1 px-2 py-1 rounded-lg ${bg} cursor-default" title="${escHtml(tooltip)}">
      <span class="material-symbols-outlined text-xs ${fg}">${icon}</span>
      <span class="text-[10px] font-medium ${fg}">${escHtml(s.label)}</span>
      ${dur ? `<span class="text-[9px] text-on-surface-variant">${dur}</span>` : ''}
    </div>`;
  }
  html += '</div>';

  box.innerHTML = html;
}
