// ======================== HEALTH VIEW ========================
// Extracted from app.js — loadHealth() and helpers

function _timeSince(isoDate) {
  try {
    const ms = Date.now() - new Date(isoDate).getTime();
    const h = Math.floor(ms / 3600000);
    if (h < 1) return Math.floor(ms / 60000) + 'min';
    if (h < 24) return h + 'h';
    return Math.floor(h / 24) + 'd';
  } catch(e) { return ''; }
}

async function loadHealth() {
  const data = await api('health/full');
  if (!data) return;
  const box = document.getElementById('health-dashboard');
  if (!box) return;
  const dot = (ok) => ok ? 'bg-tertiary shadow-[0_0_6px_#9bffce]' : 'bg-error shadow-[0_0_6px_#ff716c]';

  // Count totals for summary
  const svcOk = (data.services || []).filter(s => s.ok).length;
  const svcTotal = (data.services || []).length;
  const tunOk = (data.tunnel || []).filter(t => t.ok).length;
  const tunTotal = (data.tunnel || []).length;
  const wrkOk = (data.workers || []).filter(w => w.running).length;
  const wrkTotal = (data.workers || []).length;
  const allOk = svcOk === svcTotal && tunOk === tunTotal && wrkOk === wrkTotal;
  const sys = data.system || {};
  const tasks = data.tasks || {};

  const card = (icon, iconColor, title, content) => `
    <div class="bg-[rgb(var(--c-card))] rounded-2xl shadow-sm p-5">
      <div class="flex items-center gap-3 mb-4">
        <span class="material-symbols-outlined ${iconColor}">${icon}</span>
        <h4 class="text-xs font-label text-on-surface uppercase tracking-widest">${title}</h4>
      </div>
      ${content}
    </div>`;

  const row = (dotOk, name, right) => `<div class="flex items-center justify-between py-2 px-3 rounded-lg bg-surface-dim/40">
    <div class="flex items-center gap-2.5"><span class="w-2 h-2 rounded-full ${dot(dotOk)}"></span><span class="text-sm font-medium text-on-surface">${name}</span></div>
    <div class="flex items-center gap-2">${right}</div>
  </div>`;

  let html = '';

  // -- Summary banner --
  html += `<div class="mb-6 p-4 rounded-xl ${allOk ? 'bg-tertiary/10 border border-tertiary/30' : 'bg-error/10 border border-error/30'}">
    <div class="flex items-center gap-3">
      <span class="material-symbols-outlined text-2xl ${allOk ? 'text-tertiary' : 'text-error'}">${allOk ? 'check_circle' : 'error'}</span>
      <div>
        <p class="font-headline font-bold ${allOk ? 'text-tertiary' : 'text-error'}">${allOk ? 'Todo operativo' : 'Hay problemas'}</p>
        <p class="text-xs text-on-surface-variant">${svcOk}/${svcTotal} servicios · ${tunOk}/${tunTotal} tunnels · ${wrkOk}/${wrkTotal} workers</p>
      </div>
      <div class="ml-auto text-right text-xs text-on-surface-variant">${data.checked_at ? new Date(data.checked_at).toLocaleTimeString('es') : ''}</div>
    </div>
  </div>`;

  // -- Row 1: Services + Workers --
  let svcHtml = '<div class="space-y-2">';
  for (const s of (data.services || [])) {
    const latency = s.latency_ms > 0 ? s.latency_ms + 'ms' : '--';
    const uptime = s.started_at ? _timeSince(s.started_at) : '';
    svcHtml += row(s.ok, escHtml(s.name),
      (uptime ? `<span class="text-[10px] text-on-surface-variant">${escHtml(uptime)}</span>` : '') +
      `<span class="text-[10px] px-1.5 py-0.5 rounded ${s.ok ? 'bg-tertiary/10 text-tertiary' : 'bg-error/10 text-error'}">${s.http_status || '--'} · ${latency}</span>`
    );
  }
  svcHtml += '</div>';

  let wrkHtml = '<div class="space-y-2">';
  for (const w of (data.workers || [])) {
    wrkHtml += row(w.running, escHtml(w.name),
      `<span class="text-[10px] text-on-surface-variant">${w.running ? (w.pid ? 'PID ' + w.pid : 'activo') : 'detenido'}</span>`
    );
  }
  wrkHtml += '</div>';

  html += '<div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">';
  html += card('dns', 'text-primary', 'Servicios', svcHtml);
  html += card('memory', 'text-secondary', 'Workers', wrkHtml);
  html += '</div>';

  // -- Row 2: Tunnels + Pipeline --
  let tunHtml = '<div class="space-y-2">';
  for (const t of (data.tunnel || [])) {
    const latency = t.latency_ms > 0 ? t.latency_ms + 'ms' : '--';
    tunHtml += row(t.ok,
      `<a href="https://${escHtml(t.hostname)}" target="_blank" class="text-primary hover:underline">${escHtml(t.hostname)}</a>`,
      `<span class="text-[10px] text-on-surface-variant">${latency}</span>`
    );
  }
  tunHtml += '</div>';

  let taskHtml = '<div class="space-y-2">';
  const taskItems = [
    {label: 'Pendientes', value: tasks.pending || 0, icon: 'hourglass_top', color: tasks.pending > 0 ? 'text-primary' : 'text-on-surface-variant'},
    {label: 'En progreso', value: tasks.in_progress || 0, icon: 'play_circle', color: 'text-primary'},
    {label: 'Bloqueadas', value: tasks.blocked || 0, icon: 'block', color: tasks.blocked > 0 ? 'text-error' : 'text-on-surface-variant'},
    {label: 'Hoy', value: tasks.done_today || 0, icon: 'task_alt', color: 'text-tertiary'},
    {label: 'Total', value: tasks.total_done || 0, icon: 'done_all', color: 'text-on-surface-variant'},
  ];
  for (const ti of taskItems) {
    taskHtml += `<div class="flex items-center gap-3 py-2 px-3 rounded-lg bg-surface-dim/40">
      <span class="material-symbols-outlined text-sm text-on-surface-variant">${ti.icon}</span>
      <span class="flex-1 text-sm text-on-surface">${ti.label}</span>
      <span class="text-sm font-bold ${ti.color}">${ti.value}</span>
    </div>`;
  }
  taskHtml += '</div>';

  html += '<div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">';
  html += card('vpn_lock', 'text-tertiary', 'Tunnels Externos', tunHtml);
  html += card('assignment', 'text-primary', 'Pipeline de Tareas', taskHtml);
  html += '</div>';

  // -- Row 3: System + Git --
  let sysHtml = '<div class="space-y-2">';
  if (sys.disk_total_gb) {
    const dp = sys.disk_pct || 0;
    const dc = dp > 80 ? 'text-error' : dp > 60 ? 'text-primary' : 'text-tertiary';
    sysHtml += `<div class="flex items-center gap-3 py-2 px-3 rounded-lg bg-surface-dim/40">
      <span class="material-symbols-outlined text-sm text-on-surface-variant">hard_drive</span>
      <span class="flex-1 text-sm">Disco</span>
      <span class="text-sm font-bold ${dc}">${sys.disk_avail_gb}GB libres (${dp}%)</span>
    </div>`;
  }
  if (sys.last_backup && sys.last_backup !== 'none') {
    sysHtml += `<div class="flex items-center gap-3 py-2 px-3 rounded-lg bg-surface-dim/40">
      <span class="material-symbols-outlined text-sm text-on-surface-variant">backup</span>
      <span class="flex-1 text-sm">Backup</span>
      <span class="text-xs text-on-surface-variant">${escHtml(sys.last_backup)}</span>
    </div>`;
  }
  if (sys.uptime) {
    sysHtml += `<div class="flex items-center gap-3 py-2 px-3 rounded-lg bg-surface-dim/40">
      <span class="material-symbols-outlined text-sm text-on-surface-variant">schedule</span>
      <span class="flex-1 text-sm">Uptime</span>
      <span class="text-xs text-on-surface-variant">${escHtml(sys.uptime)}</span>
    </div>`;
  }
  sysHtml += '</div>';

  let gitHtml = '<div class="space-y-2">';
  for (const g of (data.git || [])) {
    const clean = g.dirty_files === 0;
    const unknown = g.dirty_files === -1;
    gitHtml += row(unknown ? true : clean, escHtml(g.name),
      (unknown ? '<span class="text-[10px] text-on-surface-variant">no verificable</span>' :
       !clean ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-error/10 text-error">${g.dirty_files} cambios</span>` :
       '<span class="text-[10px] text-tertiary">limpio</span>') +
      (g.has_remote ? '' : ' <span class="text-[10px] text-error">sin remote</span>')
    );
  }
  gitHtml += '</div>';

  html += '<div class="grid grid-cols-1 lg:grid-cols-2 gap-5">';
  html += card('monitor_heart', 'text-tertiary', 'Sistema', sysHtml);
  html += card('folder_copy', 'text-on-surface-variant', 'Repositorios', gitHtml);
  html += '</div>';

  box.innerHTML = html;
}
