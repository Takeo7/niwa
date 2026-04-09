// ======================== STATE ========================
const AGENT_THEME = {
  colors: { auto: 'primary', claude_code: 'agent-claude' },
  icons:  { auto: 'play_arrow', claude_code: 'code' },
  fallbackColor(name) {
    if (name?.toLowerCase() === 'auto') return 'primary';
    if (name?.toLowerCase().includes('claude')) return 'agent-claude';
    return 'secondary';
  },
  fallbackIcon(name) {
    if (name?.toLowerCase() === 'auto') return 'play_arrow';
    if (name?.toLowerCase().includes('claude')) return 'code';
    return 'neurology';
  },
  color(a) { return AGENT_THEME.colors[a.id] || AGENT_THEME.fallbackColor(a.name); },
  icon(a)  { return AGENT_THEME.icons[a.id]  || AGENT_THEME.fallbackIcon(a.name); },
};

let S = {
  view: 'dashboard',
  tasks: [],
  agents: [],
  projects: [],
  stats: null,
  dashboard: null,
  currentProject: null,
  systemTab: 'overview',
  editingTaskLabels: [],
  pollTimer: null,
  pollFailCount: 0,
  timelineCache: {},  // task_id -> timeline array
  settings: null,     // cached settings from /api/settings
};

// ======================== API HELPERS ========================
async function api(path, opts = {}) {
  try {
    const r = await fetch('/api/' + path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (r.status === 401) {
      window.location.href = '/login';
      return null;
    }
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  } catch (e) {
    console.error('API Error:', path, e);
    return null;
  }
}

// ======================== SETTINGS HELPERS ========================
async function loadSettings() {
  S.settings = await api('settings') || {};
  return S.settings;
}

async function saveSetting(key, val) {
  const res = await api('settings', { method: 'POST', body: JSON.stringify({ [key]: val }) });
  if (!res || !res.ok) { toast('Error saving setting'); return false; }
  if (S.settings) S.settings[key] = val; else S.settings = { [key]: val };
  return true;
}

// ======================== TIMELINE ========================
const TIMELINE_COLORS = {
  inbox: 'on-surface-variant', pendiente: 'on-surface-variant',
  en_progreso: 'primary', revision: 'tertiary', bloqueada: 'error',
  hecha: 'green-500', archivada: 'on-surface-variant',
};
const TIMELINE_LABELS = {
  inbox: 'Inbox', pendiente: 'Pendiente', en_progreso: 'En progreso',
  revision: 'Revisión', bloqueada: 'Bloqueada', hecha: 'Hecha', archivada: 'Archivada',
};

async function fetchTaskTimelines(taskIds) {
  if (!taskIds.length) return;
  const res = await api('tasks/timelines?ids=' + taskIds.join(','));
  if (!res || typeof res !== 'object') return;
  // Backend returns raw events {type, payload, at} — compute segments client-side
  const now = Date.now();
  const statusMap = {};
  if (S.tasks) S.tasks.forEach(t => { statusMap[t.id] = t.status; });
  for (const [tid, events] of Object.entries(res)) {
    if (Array.isArray(events) && events.length && events[0].duration_minutes !== undefined) {
      // Already computed segments (future-proof if backend changes)
      S.timelineCache[tid] = events;
      continue;
    }
    const segments = [];
    let curStatus = null, curStart = null;
    for (const ev of events) {
      const evTime = new Date(ev.at).getTime();
      if (ev.type === 'created') {
        curStatus = (ev.payload && (ev.payload.status || (ev.payload.changes && ev.payload.changes.status))) || 'inbox';
        curStart = evTime;
      } else if (ev.type === 'status_changed') {
        const p = ev.payload || {};
        const newStatus = p.new_status || p.to || p.status || (p.changes && p.changes.status);
        if (curStatus && curStart) {
          segments.push({ status: curStatus, duration_minutes: Math.round((evTime - curStart) / 60000 * 10) / 10, started_at: new Date(curStart).toISOString(), is_current: false });
        }
        curStatus = newStatus;
        curStart = evTime;
      } else if (ev.type === 'completed') {
        if (curStatus && curStart) {
          segments.push({ status: curStatus, duration_minutes: Math.round((evTime - curStart) / 60000 * 10) / 10, started_at: new Date(curStart).toISOString(), is_current: false });
        }
        curStatus = 'hecha';
        curStart = evTime;
      }
    }
    if (curStatus && curStart) {
      const taskCur = statusMap[tid];
      const isTerminal = taskCur === 'hecha' || taskCur === 'archivada';
      segments.push({ status: curStatus, duration_minutes: Math.round((now - curStart) / 60000 * 10) / 10, started_at: new Date(curStart).toISOString(), is_current: !isTerminal });
    }
    if (segments.length) S.timelineCache[tid] = segments;
  }
}

function formatDuration(value, unit) {
  if (value == null) return '—';
  var mins;
  if (unit === 'hours') mins = value * 60;
  else if (unit === 'seconds') mins = value / 60;
  else mins = value;
  if (mins < 1) return unit === 'seconds' ? Math.round(value) + 's' : '<1m';
  if (mins < 60) return Math.round(mins) + 'm';
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h < 24) return m > 0 ? h + 'h ' + m + 'm' : h + 'h';
  const d = Math.floor(h / 24);
  const rh = h % 24;
  return rh > 0 ? d + 'd ' + rh + 'h' : d + 'd';
}

function renderTimelineBar(taskId, currentStatus) {
  const tl = S.timelineCache[taskId];
  if (!tl || !tl.length) return '';
  const totalMins = tl.reduce((s, seg) => s + (seg.duration_minutes || 0), 0);
  if (totalMins <= 0) return '';
  var segments = tl.map(function(seg) {
    var pct = Math.max(2, (seg.duration_minutes / totalMins) * 100);
    var color = TIMELINE_COLORS[seg.status] || 'on-surface-variant';
    var label = TIMELINE_LABELS[seg.status] || seg.status;
    var dur = formatDuration(seg.duration_minutes);
    var isLive = seg.is_current;
    return '<div class="timeline-seg bg-' + color + '" style="width:' + pct.toFixed(1) + '%" title="' + label + ': ' + dur + (isLive ? ' (activo)' : '') + '"></div>';
  }).join('');
  // Compact summary for the last/current segment — only show liveLabel when actively executing (en_progreso)
  var last = tl[tl.length - 1];
  var liveLabel = (last.is_current && last.status === 'en_progreso' && currentStatus === 'en_progreso') ? formatDuration(last.duration_minutes) : '';
  var out = '<div class="timeline-bar-wrap mt-1.5 mb-0.5">';
  out += '<div class="timeline-bar flex rounded-full overflow-hidden">' + segments + '</div>';
  if (liveLabel) {
    out += '<span class="text-[8px] text-on-surface-variant/50 leading-none">' + (TIMELINE_LABELS[last.status] || last.status) + ' ' + liveLabel + '</span>';
  }
  out += '</div>';
  return out;
}

// ======================== THEME ========================
function toggleTheme() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('niwa_theme', isDark ? 'dark' : 'light');
  const icon = document.getElementById('theme-toggle-icon');
  if (icon) icon.textContent = isDark ? 'light_mode' : 'dark_mode';
  _applySavedStyles(); // Re-apply custom colors for the new mode
  // If styles tab is open, reload it to show correct mode colors
  if (S.view === 'system' && S.systemTab === 'styles') loadStyles();
}

// Set initial icon
window.addEventListener('DOMContentLoaded', () => {
  const icon = document.getElementById('theme-toggle-icon');
  if (icon) icon.textContent = localStorage.getItem('niwa_theme') === 'dark' ? 'light_mode' : 'dark_mode';
});

// ======================== I18N ========================
function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = _t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = _t(el.dataset.i18nPlaceholder);
  });
}

function changeLocale(lang) {
  I18N.setLocale(lang);
  applyI18n();
  // Reload current view to re-render dynamic strings
  loadViewData(S.view);
  toast(_t('settings.saved'));
}

// ======================== VIEW ROUTING ========================
function switchView(view, pushState = true) {
  // Evict timelineCache to prevent memory leak in long sessions
  if (Object.keys(S.timelineCache).length > 100) {
    S.timelineCache = {};
  }
  S.view = view;
  document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
  const el = document.getElementById('view-' + view);
  if (el) el.classList.add('active');
  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.remove('nav-active');
    a.classList.add('text-on-surface-variant');
  });
  const active = document.querySelector(`[data-view="${view}"]`);
  if (active) { active.classList.add('nav-active'); active.classList.remove('text-on-surface-variant'); }
  // Close mobile sidebar
  document.getElementById('sidebar').classList.remove('open');
  // Update URL hash — include system sub-tab when applicable
  if (pushState) {
    S._skipHashRoute = true;
    const hash = view === 'system' ? '/system/' + (S.systemTab || 'overview') : '/' + view;
    window.location.hash = hash;
  }
  // Clear project detail when navigating back to project list via sidebar
  if (view === 'projects') S.currentProject = null;
  loadViewData(view);
}

// Hash routing — load view from URL on page load and back/forward
function handleHashRoute() {
  // Skip if triggered by switchSystemTab (sub-tab change already handled)
  if (S._skipHashRoute) { S._skipHashRoute = false; return; }
  const raw = window.location.hash.replace('#/', '').replace('#', '') || 'dashboard';
  const parts = raw.split('/');
  const validViews = ['dashboard','kanban','projects','notes','history','system'];
  const view = validViews.includes(parts[0]) ? parts[0] : 'dashboard';
  // Restore system sub-tab from hash (e.g. #/system/logs)
  if (view === 'system' && parts[1]) {
    const validTabs = ['overview','routines','logs','config','stats','kpis','docs','styles'];
    if (validTabs.includes(parts[1])) S.systemTab = parts[1];
  }
  switchView(view, false);
}
window.addEventListener('hashchange', handleHashRoute);
// Initial route
window.addEventListener('DOMContentLoaded', () => { applyI18n(); setTimeout(handleHashRoute, 100); });

document.querySelectorAll('.nav-link').forEach(a => {
  a.addEventListener('click', () => switchView(a.dataset.view));
});

async function loadViewData(view) {
  switch (view) {
    case 'dashboard': await loadDashboard(); break;
    case 'kanban': await loadKanban(); break;
    case 'projects': await loadProjects(); break;
    case 'system': await loadSystem(); break;
    case 'history': await loadHistory(); break;
    case 'notes': await loadNotes(); break;
  }
}

// ======================== DASHBOARD ========================
async function loadDashboard() {
  const [dash, stats, activity, projects] = await Promise.all([
    api('dashboard'), api('stats'),
    api('activity?limit=8'), api('projects'),
    S.settings ? Promise.resolve(S.settings) : loadSettings()
  ]);
  S.dashboard = dash;

  renderDashboardKPIs(dash, stats);
  await renderAttentionItems(dash);
  renderProjectsOverview(projects);

  // Mi día
  loadMyDay();

  if (activity) renderActivityFeed(activity);

  // Routines KPI
  api('routines').then(r => {
    const count = r ? r.filter(x => x.enabled).length : 0;
    const el = document.getElementById('kpi-routines-count');
    if (el) el.textContent = count;
    const sub = document.getElementById('kpi-routines-sub');
    if (sub) sub.textContent = count === 1 ? 'activa' : 'activas';
  });

  // Pipeline / Bottlenecks (non-blocking)
  loadPipelineChart().catch(() => {});
}

function renderDashboardKPIs(dash, stats) {
  if (!(dash && stats)) return;
  const c = dash.counts || {};
  const pending = (c.inbox||0) + (c.pending||0);
  const blocked = c.blocked || 0;
  const review = c.review || 0;
  const doneToday = stats.done_today || 0;
  document.getElementById('kpi-today').textContent = doneToday;
  document.getElementById('kpi-today-sub').textContent = _t('dash.pending_blocked', {p: pending, b: blocked});
  const cbd = stats.completions_by_day || [];
  renderVelocityChart(cbd);
  const days = Array.isArray(cbd) ? cbd.map(d => d.count) : Object.values(cbd);
  const avg = days.length ? (days.reduce((a,b)=>a+b,0)/days.length).toFixed(1) : 0;
  const el = document.getElementById('velocity-summary');
  if (el) el.textContent = _t('dash.completed_summary', {n: stats.done || 0, avg});
}


async function renderAttentionItems(dash) {
  if (!dash) return;
  const allTasks = await api('tasks');
  const attention = (allTasks||[]).filter(t =>
    t.status === 'bloqueada' || t.status === 'revision' ||
    (t.due_at && new Date(t.due_at) < new Date() && !['hecha','archivada'].includes(t.status))
  );
  const box = document.getElementById('dash-attention');
  if (attention.length === 0) {
    box.innerHTML = '<p class="text-on-surface-variant text-sm py-4 text-center">' + _t('dash.all_clear') + '</p>';
  } else {
    box.innerHTML = attention.slice(0,8).map(function(t) {
      var icon = t.status === 'bloqueada' ? 'block' : t.status === 'revision' ? 'rate_review' : 'schedule';
      var color = t.status === 'bloqueada' ? 'error' : t.status === 'revision' ? '[#ac8aff]' : 'primary';
      var r = '<div class="flex items-center gap-3 p-3 rounded-lg bg-surface-dim/50 hover:bg-surface-bright/50 transition-all cursor-pointer" onclick="openTaskById(\'' + escJsAttr(t.id) + '\')">';
      r += '<span class="material-symbols-outlined text-' + color + ' text-base">' + icon + '</span>';
      r += '<div class="flex-1 min-w-0">';
      r += '<p class="text-sm text-on-surface truncate">' + escHtml(t.title) + '</p>';
      r += '<p class="text-[10px] text-on-surface-variant">' + escHtml(t.project_name || '') + ' &middot; ' + statusLabel(t.status) + '</p>';
      r += '</div>';
      r += '</div>';
      return r;
    }).join('');
  }
}

function renderProjectsOverview(projects) {
  if (!projects) return;
  const box = document.getElementById('dash-projects');
  box.innerHTML = projects.map(function(p) {
    var open = p.open_tasks || 0;
    var done = p.done_tasks || 0;
    var total = p.total_tasks || 0;
    var pct = total > 0 ? Math.round(done / total * 100) : 0;
    var r = '<div class="bg-surface-dim/50 p-4 rounded-lg hover:bg-surface-bright/50 transition-all cursor-pointer" onclick="switchView(\'projects\');setTimeout(function(){openProject(\'' + encodeURIComponent(p.name) + '\')},200)">';
    r += '<div class="flex items-center gap-2 mb-3">';
    r += '<span class="material-symbols-outlined text-primary text-base">folder</span>';
    r += '<span class="text-sm font-bold text-on-surface truncate">' + escHtml(p.name) + '</span>';
    r += '</div>';
    r += '<div class="flex items-baseline gap-1 mb-1">';
    r += '<span class="text-xl font-headline font-bold text-on-surface">' + done + '</span>';
    r += '<span class="text-[10px] text-on-surface-variant">' + _t('dash.done_of_total', {total: total}) + '</span>';
    if (open > 0) {
      r += '<span class="ml-auto text-[10px] font-bold text-primary">' + _t('dash.open_count', {n: open}) + '</span>';
    }
    r += '</div>';
    r += '<div class="h-1 bg-surface-container-highest rounded-full overflow-hidden mb-2">';
    r += '<div class="h-full bg-tertiary rounded-full" style="width:' + pct + '%"></div>';
    r += '</div>';
    if (p.url) {
      var _hn = p.url; try { _hn = new URL(p.url).hostname; } catch(e) {}
      r += '<a href="' + escHtml(p.url) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()" class="text-[10px] text-primary hover:underline block truncate">' + escHtml(_hn) + '</a>';
    }
    r += '</div>';
    return r;
  }).join('');
}


function renderVelocityChart(data) {
  const box = document.getElementById('velocity-chart');
  // Handle both array [{day,count}] and object {day: count} formats
  let days;
  if (Array.isArray(data)) {
    days = data.map(d => [d.day, d.count]).sort((a,b) => a[0].localeCompare(b[0])).slice(-7);
  } else {
    days = Object.entries(data).sort((a,b) => a[0].localeCompare(b[0])).slice(-7);
  }
  const max = Math.max(...days.map(d => d[1]), 1);
  if (days.length === 0) {
    box.innerHTML = '<p class="text-on-surface-variant text-sm w-full text-center">' + _t('dash.no_completions') + '</p>';
    return;
  }
  const chartH = 128;
  box.innerHTML = days.map(function(d) {
    var day = d[0], count = d[1];
    var h = Math.max(4, Math.round((count / max) * chartH));
    var label = day.slice(5);
    var r = '<div class="flex-1 flex flex-col items-end justify-end group" style="height:' + (chartH + 24) + 'px">';
    r += '<div style="font-size:10px;color:var(--c-tertiary);opacity:0;margin-bottom:4px;text-align:center;width:100%" class="group-hover:opacity-100 transition-opacity">' + count + '</div>';
    r += '<div class="transition-all rounded-t-lg" style="height:' + h + 'px;width:100%;background:color-mix(in srgb,var(--c-tertiary) 25%,transparent)"></div>';
    r += '<span class="text-[9px] text-on-surface-variant">' + label + '</span>';
    r += '</div>';
    return r;
  }).join('');
}

function renderActivityFeed(items) {
  const box = document.getElementById('activity-feed');
  const typeColors = { status_change: 'primary', created: 'tertiary', assignment: 'secondary', comment: 'on-surface-variant' };
  box.innerHTML = items.map(function(item) {
    var color = typeColors[item.type] || 'on-surface-variant';
    var typeLabel = (item.type || 'event').replace(/_/g, ' ');
    var ago = timeAgo(item.created_at);
    var agent = (item.payload && item.payload.agent_name) || '';
    var r = '<div class="p-4 rounded-lg bg-surface-container-high/50 hover:bg-surface-bright transition-all cursor-pointer" onclick="openTaskById(\'' + escJsAttr(item.task_id) + '\')">';
    r += '<div class="flex justify-between items-start mb-2">';
    r += '<span class="text-[10px] font-bold text-' + color + ' tracking-widest uppercase">' + typeLabel + '</span>';
    r += '<span class="text-[10px] text-on-surface-variant">' + ago + '</span>';
    r += '</div>';
    r += '<h5 class="text-sm font-medium text-on-surface mb-1">' + escHtml(item.task_title || 'Task') + '</h5>';
    if (agent) {
      r += '<span class="text-[10px] text-on-surface-variant">by ' + escHtml(agent) + '</span>';
    }
    r += '</div>';
    return r;
  }).join('');
}

// ── Pipeline / Bottleneck Chart ─────────────────────────────────────
// PIPELINE_COLORS and renderPipelineChart() moved to pipeline-view.js

async function loadPipelineChart() {
  const daysSelect = document.getElementById('pipeline-days');
  const days = daysSelect ? daysSelect.value : '7';
  try {
    const data = await api('dashboard/pipeline?days=' + days);
    if (!data) return;
    renderPipelineChart(data);
  } catch (e) {
    const chart = document.getElementById('pipeline-chart');
    if (chart) chart.innerHTML = `<p class="text-on-surface-variant text-sm text-center py-4">${_t('pipeline.no_data')}</p>`;
  }
}



function computeTimeTag(t) {
  if (t.status === 'pendiente' || t.status === 'inbox') {
    return '<span class="text-[9px] text-on-surface-variant/40">en cola</span>';
  }
  if (t.status === 'en_progreso') {
    var tl = S.timelineCache && S.timelineCache[t.id];
    var progSeg = null;
    if (tl && tl.length) {
      for (var si = tl.length - 1; si >= 0; si--) {
        if (tl[si].status === 'en_progreso') { progSeg = tl[si]; break; }
      }
    }
    var refTime = (progSeg && progSeg.started_at) ? new Date(progSeg.started_at).getTime() : 0;
    if (refTime) {
      var mins = Math.round((Date.now() - refTime) / 60000);
      var hh = Math.floor(mins / 60); var mm = mins % 60;
      return '<span class="text-[9px] text-on-surface-variant/40">' + (hh > 0 ? hh + 'h ' + mm + 'm' : mm + 'm') + '</span>';
    }
    return '';
  }
  if (t.status === 'hecha') {
    var tl2 = S.timelineCache && S.timelineCache[t.id];
    if (tl2 && tl2.length) {
      var totalMins = tl2.reduce(function(acc, seg) { return acc + (seg.status === 'en_progreso' && seg.duration_minutes ? seg.duration_minutes : 0); }, 0);
      if (totalMins > 0) {
        var hh2 = Math.floor(totalMins / 60); var mm2 = Math.round(totalMins % 60);
        return '<span class="text-[9px] text-on-surface-variant/40">' + (hh2 > 0 ? hh2 + 'h ' + mm2 + 'm' : mm2 + 'm') + '</span>';
      }
    }
    return '';
  }
  return '';
}

// ======================== KANBAN ========================

function getKanbanColumns() {
  return [
    { key: 'todo', label: _t('kanban.col_todo'), statuses: ['inbox', 'pendiente'], color: 'primary' },
    { key: 'doing', label: _t('kanban.col_doing'), statuses: ['en_progreso'], color: 'tertiary' },
    { key: 'review', label: _t('kanban.col_review'), statuses: ['revision'], color: 'secondary' },
    { key: 'blocked', label: _t('kanban.col_blocked'), statuses: ['bloqueada'], color: 'error' },
    { key: 'done', label: _t('kanban.col_done'), statuses: ['hecha', 'archivada'], color: 'on-surface-variant' },
  ];
}

function groupTasksByColumn(tasks) {
  var columns = getKanbanColumns();
  var grouped = {};
  columns.forEach(function(col) {
    var colTasks = tasks.filter(function(t) { return col.statuses.includes(t.status); });
    if (col.key === 'done') {
      colTasks.sort(function(a, b) {
        return new Date(b.completed_at || b.updated_at || 0) - new Date(a.completed_at || a.updated_at || 0);
      });
    }
    grouped[col.key] = colTasks;
  });
  return grouped;
}

function renderKanbanColumns(grouped) {
  var columns = getKanbanColumns();
  if (!window._kanbanCollapsed) {
    try { window._kanbanCollapsed = JSON.parse(sessionStorage.getItem('kanban-collapsed') || '{}'); } catch(e) { window._kanbanCollapsed = {}; }
  }
  return columns.map(function(col) {
    var colTasks = grouped[col.key] || [];
    var isDone = col.key === 'done';
    var collapsed = window._kanbanCollapsed[col.key] && colTasks.length > 0;
    var chevron = collapsed ? 'expand_more' : 'expand_less';
    var r = '<div class="flex flex-col gap-3 kanban-column" data-col-key="' + col.key + '">';
    r += '<div class="flex items-center justify-between px-2 cursor-pointer select-none kanban-col-header" onclick="toggleKanbanCol(\'' + col.key + '\')">';
    r += '<div class="flex items-center gap-3">';
    r += '<span class="material-symbols-outlined text-on-surface-variant/50 lg:hidden" style="font-size:18px">' + chevron + '</span>';
    r += '<h3 class="font-headline font-bold text-lg uppercase tracking-widest text-on-surface-variant">' + col.label + '</h3>';
    r += '<span class="px-2 py-0.5 bg-surface-container-high rounded text-xs font-bold text-' + col.color + '">' + colTasks.length + '</span>';
    r += '</div>';
    r += '<div class="flex items-center gap-2">';
    if (col.key === 'todo') {
      r += '<button class="text-on-surface-variant hover:text-primary transition-colors" onclick="event.stopPropagation();openNewTaskModal()"><span class="material-symbols-outlined">add</span></button>';
    }
    r += '</div>';
    r += '</div>';
    r += '<div class="flex flex-col gap-3 min-h-[40px] kanban-col ' + (isDone ? 'opacity-60 hover:opacity-100 transition-all' : '') + ' ' + (collapsed ? 'kanban-col-collapsed' : '') + '" data-statuses="' + col.statuses.join(',') + '" data-col="' + col.key + '">';
    r += colTasks.map(function(t) { return renderKanbanCard(t, isDone); }).join('');
    r += '</div>';
    r += '</div>';
    return r;
  }).join('');
}

function initKanbanDrag() {
  document.querySelectorAll('.kanban-col').forEach(el => {
    new Sortable(el, {
      group: 'kanban',
      animation: 200,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      handle: '.drag-handle',
      onEnd: async function(evt) {
        const taskId = evt.item.dataset.taskId;
        const targetCol = evt.to.dataset.col;
        const statusMap = { todo: 'pendiente', doing: 'en_progreso', review: 'revision', blocked: 'bloqueada', done: 'hecha' };
        const newStatus = statusMap[targetCol] || 'pendiente';
        try {
          const res = await api('tasks/' + taskId, { method: 'PATCH', body: JSON.stringify({ status: newStatus }) });
          if (!res || res.error) throw new Error(res?.error || 'API error');
          toast(_t('task.moved', {status: targetCol.toUpperCase()}));
        } catch (e) {
          toast(_t('task.move_failed') || 'Error al mover tarea', 'error');
          loadViewData(S.view);
        }
      }
    });
  });
}

async function loadKanban() {
  const showDone = document.getElementById('kanban-show-done')?.checked;
  const tasks = await api('tasks' + (showDone ? '?include_done=1' : ''));
  if (!tasks) return;
  S.tasks = tasks;

  // Fetch timelines for all visible tasks
  const taskIds = tasks.map(t => t.id);
  fetchTaskTimelines(taskIds).then(() => {
    document.querySelectorAll('[data-task-id]').forEach(card => {
      const tid = card.dataset.taskId;
      if (S.timelineCache[tid]) {
        const task = tasks.find(tt => tt.id === tid);
        if (!task) return;
        const barEl = card.querySelector('.timeline-bar-wrap');
        if (!barEl) {
          const h4 = card.querySelector('h4');
          if (h4) h4.insertAdjacentHTML('afterend', renderTimelineBar(tid, task.status));
        }
        const tagEl = card.querySelector('.card-time-tag');
        if (tagEl) tagEl.innerHTML = computeTimeTag(task);
      }
    });
  });

  // Populate filter options
  const projects = [...new Set(tasks.map(t => t.project_name).filter(Boolean))].sort();
  const projSel = document.getElementById('kanban-filter-project');
  const currentProj = projSel.value;
  projSel.innerHTML = `<option value="">${_t('kanban.all_projects')}</option>` + projects.map(p => `<option value="${escHtml(p)}" ${p===currentProj?'selected':''}>${escHtml(p)}</option>`).join('');

  const filterProject = document.getElementById('kanban-filter-project').value;
  let filtered = tasks;
  if (filterProject) filtered = filtered.filter(t => t.project_name === filterProject);

  const grouped = groupTasksByColumn(filtered);
  const board = document.getElementById('kanban-board');
  board.innerHTML = renderKanbanColumns(grouped);
  initKanbanDrag();
}

function renderAssigneeBadges(t) {
  var badge = '';
  if (t.assigned_to_yume) {
    badge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/15 text-primary text-[10px] font-bold uppercase tracking-tighter"><span class="material-symbols-outlined" style="font-size:11px">play_arrow</span>Auto</span>';
  }
  if (t.assigned_to_claude) {
    badge += '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-agent-claude/15 text-agent-claude text-[10px] font-bold uppercase tracking-tighter"><span class="material-symbols-outlined" style="font-size:11px">code</span>Claude</span>';
  }
  if (t.active_agent && (t.active_agent.agent_name || t.active_agent.agent_id)) {
    var agentName = t.active_agent.agent_name || t.active_agent.agent_id || 'Agent';
    badge += '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-tertiary/15 text-tertiary text-[10px] font-bold uppercase tracking-tighter animate-pulse"><span class="material-symbols-outlined" style="font-size:11px">precision_manufacturing</span>' + escHtml(agentName) + '</span>';
  } else if (!t.assigned_to_yume && t.completed_by_agent && (t.completed_by_agent.agent_name || t.completed_by_agent.agent_id)) {
    var doneAgent = t.completed_by_agent.agent_name || t.completed_by_agent.agent_id || 'Agent';
    badge += '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-on-surface-variant/10 text-on-surface-variant text-[10px] font-medium tracking-tighter"><span class="material-symbols-outlined" style="font-size:11px">check_circle</span>' + escHtml(doneAgent) + '</span>';
  }
  return badge;
}

// renderExecPhase, renderCardFooter → task-card-utils.js

function renderKanbanCard(t, isDone) {
  // Normalize legacy priority values
  var prioMap = { low: 'baja', medium: 'media', high: 'alta', critical: 'critica' };
  var prio = prioMap[t.priority] || t.priority || 'media';

  // Area badge
  var areaColors = { personal: 'primary', empresa: 'secondary', proyecto: 'tertiary' };
  var areaIcons = { personal: 'person', empresa: 'business', proyecto: 'folder' };
  var ac = areaColors[t.area] || 'on-surface-variant';
  var areaIcon = areaIcons[t.area] || 'label';
  var areaLabel = t.area || 'personal';
  var areaBadge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-' + ac + '/10 text-' + ac + ' text-[10px] font-bold uppercase tracking-wider"><span class="material-symbols-outlined" style="font-size:11px">' + areaIcon + '</span>' + areaLabel + '</span>';

  // Project name badge (only for proyecto area)
  var projectBadge = '';
  if (t.area === 'proyecto' && t.project_name) {
    projectBadge = '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-tertiary/20 text-tertiary text-[10px] font-medium truncate max-w-[140px]"><span class="material-symbols-outlined" style="font-size:11px">deployed_code</span>' + escHtml(t.project_name) + '</span>';
  }

  var assigneeBadge = renderAssigneeBadges(t);

  // Agent border: orange for Claude, blue for auto-execute
  var agentBorder = t.assigned_to_claude ? 'border-l-4 border-agent-claude' : t.assigned_to_yume ? 'border-l-4 border-primary' : '';
  var statusBorder = agentBorder || (t.status === 'bloqueada' ? 'border-l-4 border-red-500' : '');

  var execStatus = renderExecPhase(t);

  var r = '<div class="group relative bg-surface-container-high p-5 rounded-lg hover:bg-surface-bright transition-all duration-300 cursor-pointer ' + statusBorder + (isDone ? ' bg-surface-container-high/50' : '') + '" data-task-id="' + escHtml(String(t.id)) + '" onclick="openTaskById(\'' + escJsAttr(t.id) + '\')">';
  r += '<div class="flex justify-between items-start mb-2">';
  r += '<span class="material-symbols-outlined text-on-surface-variant/30 cursor-grab active:cursor-grabbing group-hover:text-primary/50 drag-handle" onclick="event.stopPropagation()">drag_indicator</span>';
  r += '<div class="flex items-center gap-1.5 flex-wrap justify-end">' + areaBadge + projectBadge + '</div>';
  r += '</div>';
  r += '<h4 class="font-headline font-bold text-on-surface text-sm mb-2 ' + (isDone ? 'line-through opacity-70' : '') + '">' + escHtml(t.title) + '</h4>';
  r += renderTimelineBar(t.id, t.status);
  if (t.description) {
    r += '<p class="text-xs text-on-surface-variant line-clamp-2 mb-2">' + escHtml(t.description) + '</p>';
  }
  if (assigneeBadge) {
    r += '<div class="flex items-center gap-1.5 flex-wrap mb-2">' + assigneeBadge + '</div>';
  }
  r += execStatus;
  r += renderCardFooter(t, prio);
  r += '</div>';
  return r;
}

function toggleKanbanCol(colKey) {
  if (window.innerWidth >= 1024) return; // Only collapse on mobile/tablet
  if (!window._kanbanCollapsed) window._kanbanCollapsed = {};
  window._kanbanCollapsed[colKey] = !window._kanbanCollapsed[colKey];
  try { sessionStorage.setItem('kanban-collapsed', JSON.stringify(window._kanbanCollapsed)); } catch(e) {}
  const col = document.querySelector(`.kanban-column[data-col-key="${colKey}"]`);
  if (!col) return;
  const body = col.querySelector('.kanban-col');
  const addInput = col.querySelector('.kanban-col ~ .px-2');
  const chevron = col.querySelector('.kanban-col-header .material-symbols-outlined');
  if (window._kanbanCollapsed[colKey]) {
    body.classList.add('kanban-col-collapsed');
    if (addInput) addInput.classList.add('hidden');
    if (chevron) chevron.textContent = 'expand_more';
  } else {
    body.classList.remove('kanban-col-collapsed');
    if (addInput) addInput.classList.remove('hidden');
    if (chevron) chevron.textContent = 'expand_less';
  }
}

// ======================== TASK HISTORY ========================
let _historySort = 'completed_at';
let _historyOrder = 'desc';
let _historyPage = 1;
let _historyDebounceTimer = null;

async function loadHistory() {
  const params = new URLSearchParams();
  const project = document.getElementById('history-filter-project');
  const from = document.getElementById('history-filter-from');
  const to = document.getElementById('history-filter-to');
  const source = document.getElementById('history-filter-source');
  const result = document.getElementById('history-filter-result');
  const search = document.getElementById('history-filter-search');

  if (project && project.value) params.set('project', project.value);
  if (from && from.value) params.set('from', from.value);
  if (to && to.value) params.set('to', to.value);
  if (source && source.value) params.set('source', source.value);
  if (result && result.value) params.set('result', result.value);
  if (search && search.value) params.set('search', search.value);
  params.set('sort', _historySort);
  params.set('order', _historyOrder);
  params.set('page', _historyPage);

  const data = await api('tasks/history?' + params.toString());
  if (!data) return;

  renderHistoryStats(data.stats);
  renderHistoryTable(data.items || []);

  // Pagination
  const pageInfo = document.getElementById('history-page-info');
  const prevBtn = document.getElementById('history-prev');
  const nextBtn = document.getElementById('history-next');
  if (pageInfo) pageInfo.textContent = 'Página ' + (data.page || 1) + ' de ' + (data.total_pages || 1) + ' (' + (data.total || 0) + ' tareas)';
  if (prevBtn) prevBtn.disabled = (data.page || 1) <= 1;
  if (nextBtn) nextBtn.disabled = (data.page || 1) >= (data.total_pages || 1);
}

function renderHistoryStats(stats) {
  if (!stats) return;
  const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  el('history-stat-total', stats.total ?? 0);
  el('history-stat-success', stats.success ?? 0);
  el('history-stat-failed', stats.failed ?? 0);
  const avgDur = stats.avg_duration;
  el('history-stat-avg-duration', formatDuration(avgDur, 'hours'));
}

function renderHistoryTable(items) {
  const box = document.getElementById('history-table-body');
  if (!box) return;

  if (items.length === 0) {
    box.innerHTML = '<tr><td colspan="8" class="p-6 text-center text-on-surface-variant text-sm">Sin tareas en este período</td></tr>';
    return;
  }


  const fmtDate = (d) => {
    if (!d) return '—';
    const dt = new Date(d);
    return dt.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: '2-digit' }) +
      ' ' + dt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  };


  const truncate = (s, max) => s && s.length > max ? s.substring(0, max) + '…' : (s || '—');

  var rows = items.map(function(t) {
    var row = '<tr class="border-b border-outline-variant/10 hover:bg-surface-bright/50 transition-colors">';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant">' + escHtml(t.id || '') + '</td>';
    row += '<td class="px-4 py-3"><p class="text-on-surface font-medium truncate max-w-xs">' + escHtml(truncate(t.title, 60)) + '</p></td>';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant">' + escHtml(t.project_name || '—') + '</td>';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant">' + escHtml(t.agent || '—') + '</td>';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant">' + escHtml(t.source || '—') + '</td>';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant whitespace-nowrap">' + fmtDate(t.completed_at) + '</td>';
    row += '<td class="px-4 py-3 text-[11px] text-on-surface-variant">' + formatDuration(t.duration_hours, 'hours') + '</td>';
    row += '<td class="px-4 py-3 text-[11px]">' + (t.attempts != null ? '<span class="text-on-surface-variant mr-2">' + t.attempts + ' int.</span>' : '') + statusBadge(t.status) + '</td>';
    row += '</tr>';
    return row;
  }).join('');

  box.innerHTML = rows;
}

// History sort click handlers
document.querySelectorAll('#view-history th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.sort;
    if (_historySort === col) {
      _historyOrder = _historyOrder === 'asc' ? 'desc' : 'asc';
    } else {
      _historySort = col;
      _historyOrder = 'asc';
    }
    _historyPage = 1;
    loadHistory();
  });
});

// History pagination
document.getElementById('history-prev')?.addEventListener('click', () => {
  if (_historyPage > 1) { _historyPage--; loadHistory(); }
});
document.getElementById('history-next')?.addEventListener('click', () => {
  _historyPage++; loadHistory();
});

// History filter listeners
['history-filter-project', 'history-filter-source', 'history-filter-result',
 'history-filter-from', 'history-filter-to'].forEach(id => {
  document.getElementById(id)?.addEventListener('change', () => { _historyPage = 1; loadHistory(); });
});

// Search with debounce
document.getElementById('history-filter-search')?.addEventListener('input', () => {
  clearTimeout(_historyDebounceTimer);
  _historyDebounceTimer = setTimeout(() => { _historyPage = 1; loadHistory(); }, 300);
});

// Date presets
function setHistoryDatePreset(preset) {
  const from = document.getElementById('history-filter-from');
  const to = document.getElementById('history-filter-to');
  if (!from || !to) return;
  const today = new Date();
  const fmt = d => d.toISOString().split('T')[0];
  to.value = fmt(today);
  if (preset === 'today') {
    from.value = fmt(today);
  } else if (preset === 'week') {
    const d = new Date(today); d.setDate(d.getDate() - 7);
    from.value = fmt(d);
  } else if (preset === 'month') {
    const d = new Date(today); d.setMonth(d.getMonth() - 1);
    from.value = fmt(d);
  }
  _historyPage = 1;
  loadHistory();
}

// ======================== PROJECTS ========================
function renderIdleToggle(projectId, settings) {
  try {
    var idleKey = 'idle_review_proj_' + projectId;
    var idleEnabled = !(settings && settings[idleKey] === '0');
    var iconColor = idleEnabled ? 'text-tertiary' : 'text-on-surface-variant';
    var iconOpacity = idleEnabled ? '' : ' style="opacity:0.5"';
    var labelColor = idleEnabled ? 'text-on-surface-variant' : 'text-on-surface-variant';
    var labelOpacity = idleEnabled ? '' : ' style="opacity:0.5"';
    var btnBg = idleEnabled ? 'bg-tertiary' : 'bg-outline-variant';
    var knobLeft = idleEnabled ? '16px' : '2px';
    var btnTitle = idleEnabled ? _t('proj.idle_review_enabled') : _t('proj.idle_review_disabled');
    var h = '';
    h += '<div class="flex items-center justify-between pt-3 border-t border-outline-variant/10" style="cursor:default" onclick="event.stopPropagation()">';
    h += '<div class="flex items-center gap-1.5">';
    h += '<span class="material-symbols-outlined text-xs ' + iconColor + '"' + iconOpacity + '>auto_awesome</span>';
    h += '<span class="text-[10px] font-medium ' + labelColor + '"' + labelOpacity + '>' + _t('proj.idle_review') + '</span>';
    h += '</div>';
    h += '<div role="switch" aria-checked="' + (idleEnabled ? 'true' : 'false') + '" tabindex="0" onclick="event.stopPropagation();toggleProjectIdleReview(\'' + escJsAttr(projectId) + '\')" class="relative w-9 h-5 rounded-full transition-colors cursor-pointer ' + btnBg + '" title="' + escHtml(btnTitle) + '" style="flex-shrink:0">';
    h += '<div style="position:absolute;top:2px;left:' + knobLeft + ';width:16px;height:16px;background:#fff;border-radius:50%;box-shadow:0 1px 3px rgba(0,0,0,.2);transition:left .2s ease"></div>';
    h += '</div>';
    h += '</div>';
    return h;
  } catch (e) {
    console.error('renderIdleToggle error:', e);
    return '';
  }
}

function renderProjectCard(p, settings) {
  var total = p.total_tasks || 0;
  var done = p.done_tasks || 0;
  var pct = total ? Math.round((done / total) * 100) : 0;
  var _hostname = '';
  if (p.url) { try { _hostname = new URL(p.url).hostname; } catch(e) { _hostname = p.url; } }
  var urlBadge = '';
  if (p.url) {
    urlBadge = '<a href="' + escHtml(p.url) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-primary/10 text-primary hover:bg-primary/20 transition-colors"><span class="material-symbols-outlined text-xs">language</span>' + escHtml(_hostname) + '</a>';
  }
  var html = '';
  html += '<div class="bg-surface-container-high rounded-xl p-6 hover:bg-surface-bright transition-all cursor-pointer group" onclick="openProject(\'' + encodeURIComponent(p.name) + '\')">';
  html += '<div class="flex justify-between items-start mb-4">';
  html += '<span class="material-symbols-outlined text-primary text-2xl">folder_open</span>';
  html += '<span class="text-[10px] font-bold text-on-surface-variant uppercase tracking-tighter">' + total + ' tasks</span>';
  html += '</div>';
  html += '<h4 class="font-headline font-bold text-on-surface text-lg mb-1">' + escHtml(p.name) + '</h4>';
  html += '<div class="flex items-center gap-2 mb-4">';
  html += '<p class="text-xs text-on-surface-variant">' + escHtml(p.area || 'No area') + '</p>';
  html += urlBadge;
  html += '</div>';
  html += '<div class="flex items-center gap-3 mb-3">';
  html += '<div class="flex-1 h-1 bg-surface-container-highest rounded-full overflow-hidden"><div class="h-full bg-tertiary" style="width:' + pct + '%"></div></div>';
  html += '<span class="text-[10px] font-bold text-on-surface-variant">' + pct + '%</span>';
  html += '</div>';
  html += renderIdleToggle(p.id, settings);
  html += '</div>';
  return html;
}

async function loadProjects() {
  // If a project detail is open, don't reset to list view (poll-safe)
  if (S.currentProject) return;
  document.getElementById('projects-list-view').classList.remove('hidden');
  document.getElementById('project-detail-view').classList.add('hidden');
  const [projects] = await Promise.all([api('projects'), S.settings ? Promise.resolve() : loadSettings()]);
  if (!projects) return;
  S.projects = projects;
  const grid = document.getElementById('projects-grid');
  if (S.projects.length === 0) {
    grid.innerHTML = '<p class="text-on-surface-variant col-span-3">' + _t('proj.no_projects') + '</p>';
    return;
  }
  grid.innerHTML = S.projects.map(function(p) { return renderProjectCard(p, S.settings); }).join('');
}

async function toggleProjectIdleReview(projectId) {
  try {
    const key = 'idle_review_proj_' + projectId;
    const current = (S.settings && S.settings[key]) || '1';
    const newVal = current === '0' ? '1' : '0';
    if (!await saveSetting(key, newVal)) return;
    toast(newVal === '1' ? _t('proj.idle_review_enabled') : _t('proj.idle_review_disabled'));
    // Update toggle in-place without re-rendering the whole grid
    var cards = document.querySelectorAll('#projects-grid > div');
    var proj = S.projects.find(function(p) { return p.id === projectId; });
    if (proj) {
      var idx = S.projects.indexOf(proj);
      if (cards[idx]) {
        var tmp = document.createElement('div');
        tmp.innerHTML = renderProjectCard(proj, S.settings);
        cards[idx].replaceWith(tmp.firstElementChild);
      }
    }
  } catch(e) {
    toast('Error: ' + e.message);
  }
}

async function doToggleIdle(projectId) {
  var key = 'idle_review_proj_' + projectId;
  var current = (S.settings && S.settings[key]) || '1';
  var newVal = current === '0' ? '1' : '0';
  await saveSetting(key, newVal);
  // Update button directly
  var btn = document.getElementById('idle-toggle-btn');
  if (btn) {
    btn.className = 'relative w-10 h-5 rounded-full transition-colors ' + (newVal === '1' ? 'bg-tertiary' : 'bg-outline-variant');
    btn.firstElementChild.className = 'absolute top-0.5 ' + (newVal === '1' ? 'left-5' : 'left-0.5') + ' w-4 h-4 bg-white rounded-full shadow transition-all';
  }
  toast(newVal === '1' ? _t('proj.idle_review_enabled') : _t('proj.idle_review_disabled'));
}

function renderProjectPreview(proj) {
  const previewBox = document.getElementById('project-live-preview');
  const isMobileView = window.innerWidth < 1024;
  if (!previewBox) return;
  if (proj && proj.url) {
    const wrapClass = isMobileView ? 'inline-preview-mobile' : 'inline-preview-desktop';
    previewBox.innerHTML = '<div class="rounded-2xl overflow-hidden border border-outline-variant/10 mb-6 ' + wrapClass + '">' +
      '<div class="flex items-center justify-between px-4 py-2 bg-surface-bright/60 border-b border-outline-variant/10">' +
      '<span class="text-xs text-on-surface-variant truncate max-w-[80%]">' + escHtml(proj.url) + '</span>' +
      '<a href="' + escHtml(proj.url) + '" target="_blank" rel="noopener" class="flex items-center gap-1 text-xs text-primary hover:text-primary-dim transition-colors">' +
      '<span class="material-symbols-outlined text-sm">open_in_new</span>Abrir en nueva pestaña</a></div>' +
      '<iframe src="' + escHtml(proj.url) + '" class="w-full" style="height:calc(100% - 40px)" frameborder="0"></iframe></div>';
  } else {
    previewBox.innerHTML = '';
  }
}

function renderProjectPreviewSection(proj) {
  const previewSection = document.getElementById('project-preview-section');
  const previewUrl = proj && proj.url ? proj.url : null;
  if (previewUrl) {
    previewSection.classList.remove('hidden');
    const pl = document.getElementById('preview-loader');
    if (pl) pl.style.display = 'flex';
    document.getElementById('project-preview-iframe').src = previewUrl;
    S._previewUrl = previewUrl;
    if (window.innerWidth < 1024) {
      setPreviewDevice('mobile');
    } else {
      setPreviewDevice('desktop');
    }
  } else {
    previewSection.classList.add('hidden');
    document.getElementById('project-preview-iframe').src = '';
    S._previewUrl = null;
  }
}

function renderProjectTypeChart(projectTasks, total, done) {
  const typeCounts = { bugfix: 0, feature: 0, refactor: 0, test: 0, other: 0 };
  const typeLabels = { bugfix: 'Bugs', feature: 'Features', refactor: 'Refactors', test: 'Tests', other: 'Otros' };
  const typeHexColors = { bugfix: '#f06253', feature: '#85adff', refactor: '#c9a84c', test: '#34adbf', other: '#999' };
  const typeIcons = { bugfix: 'bug_report', feature: 'add_circle', refactor: 'autorenew', test: 'science', other: 'more_horiz' };
  for (const t of projectTasks) {
    const txt = ((t.title || '') + ' ' + (t.description || '')).toLowerCase();
    if (/\b(fix|bug|corregir|crash|error|roto|broken)\b/.test(txt)) typeCounts.bugfix++;
    else if (/\b(test|cobertura|vitest|unittest)\b/.test(txt)) typeCounts.test++;
    else if (/\b(extraer|refactor|duplica|consolidar|mover|eliminar.*dead|cleanup)\b/.test(txt)) typeCounts.refactor++;
    else if (/\b(implementar|crear|añadir|add|feature|nuevo|nueva|connect|integr)\b/.test(txt)) typeCounts.feature++;
    else typeCounts.other++;
  }

  const activeTypes = Object.entries(typeCounts).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const donutEl = document.getElementById('project-type-donut');
  if (total === 0) {
    donutEl.innerHTML = '<div class="w-full h-full rounded-full bg-outline-variant/20 flex items-center justify-center"><span class="text-on-surface-variant text-xs">Sin tareas</span></div>';
  } else {
    var gradientParts = [];
    var cumPct = 0;
    for (var _i = 0; _i < activeTypes.length; _i++) {
      var type = activeTypes[_i][0], count = activeTypes[_i][1];
      var slicePct = (count / total) * 100;
      gradientParts.push(typeHexColors[type] + ' ' + cumPct + '% ' + (cumPct + slicePct) + '%');
      cumPct += slicePct;
    }
    var pct = Math.round((done / total) * 100);
    var _d = '<div style="width:120px;height:120px;border-radius:50%;background:conic-gradient(' + gradientParts.join(',') + ');" class="flex items-center justify-center">';
    _d += '<div class="w-[76px] h-[76px] rounded-full bg-[rgb(var(--c-card))] flex flex-col items-center justify-center">';
    _d += '<span class="text-lg font-headline font-bold text-on-surface leading-none">' + pct + '%</span>';
    _d += '<span class="text-[9px] text-on-surface-variant uppercase">hecho</span>';
    _d += '</div>';
    _d += '</div>';
    donutEl.innerHTML = _d;
  }

  const legendEl = document.getElementById('project-type-legend');
  legendEl.innerHTML = activeTypes.map(function(entry) {
    var type = entry[0], count = entry[1];
    var slicePct = total ? Math.round((count / total) * 100) : 0;
    var r = '<div class="flex items-center gap-2">';
    r += '<span class="w-2.5 h-2.5 rounded-sm flex-shrink-0" style="background:' + typeHexColors[type] + '"></span>';
    r += '<span class="text-[11px] text-on-surface flex-1">' + typeLabels[type] + '</span>';
    r += '<span class="text-[11px] font-bold text-on-surface-variant">' + count + '</span>';
    r += '<span class="text-[10px] text-on-surface-variant">' + slicePct + '%</span>';
    r += '</div>';
    return r;
  }).join('');

  const chartBox = document.getElementById('project-task-type-chart');
  const maxType = Math.max(...Object.values(typeCounts), 1);
  chartBox.innerHTML = activeTypes.map(([type, count]) => {
    const w = Math.max(8, Math.round((count / maxType) * 100));
    return `<div class="flex items-center gap-3">
      <span class="material-symbols-outlined text-sm" style="color:${typeHexColors[type]};width:20px">${typeIcons[type]}</span>
      <span class="text-[10px] font-bold text-on-surface-variant uppercase" style="width:64px">${typeLabels[type]}</span>
      <div class="flex-1 bg-outline-variant/10 rounded-full h-5 overflow-hidden">
        <div class="h-full rounded-full flex items-center px-2 transition-all" style="width:${w}%;background:${typeHexColors[type]}">
          <span class="text-[10px] font-bold text-white">${count}</span>
        </div>
      </div>
    </div>`;
  }).join('');
}

function renderProjectActivity(activity, allTasks, projectName) {
  const projActivity = activity.filter(a => {
    const task = allTasks.find(t => t.id === a.task_id);
    return task && task.project_name === projectName;
  });
  const actBox = document.getElementById('project-activity');
  const actTypeColors = { status_change: 'primary', created: 'tertiary', assignment: 'secondary' };
  actBox.innerHTML = projActivity.slice(0, 5).map(item => {
    const color = actTypeColors[item.type] || 'primary';
    return `<div class="relative pl-10">
      <div class="absolute left-0 top-1.5 w-6 h-6 rounded-full bg-surface-container-highest flex items-center justify-center z-10" style="border:1px solid var(--tw-colors-${color},#85adff)">
        <span class="material-symbols-outlined text-xs text-${color}">commit</span>
      </div>
      <div>
        <p class="text-sm font-medium text-on-surface">${escHtml(item.task_title || '')}: ${escHtml((item.type||'').replace(/_/g,' '))}</p>
        <p class="text-xs text-on-surface-variant mt-1">${escHtml(item.payload?.agent_name||'Sistema')} - ${timeAgo(item.created_at)}</p>
      </div>
    </div>`;
  }).join('') || '<p class="text-on-surface-variant text-sm">' + _t('proj.no_activity') + '</p>';
}

async function openProject(name) {
  name = decodeURIComponent(name);
  S.currentProject = name;
  // Look up the real slug from project data instead of deriving it client-side
  const proj = S.projects.find(p => p.name === name);
  const slug = proj ? proj.slug : name.toLowerCase().replace(/\s+/g, '-');
  S.currentProjectSlug = slug;
  document.getElementById('projects-list-view').classList.add('hidden');
  document.getElementById('project-detail-view').classList.remove('hidden');
  document.getElementById('project-title').textContent = _t('proj.project', {name});
  document.getElementById('project-path').textContent = proj && proj.directory ? proj.directory : '/projects/' + slug;

  // Fire all data fetches in parallel (including file tree + uploads)
  const filesPromise = loadProjectFiles(slug);
  loadProjectUploads(slug);
  const [allTasks, activity] = await Promise.all([
    api('tasks?include_done=1').then(r => r || []),
    api('activity?limit=20').then(r => r || []),
    S.settings ? Promise.resolve() : loadSettings()
  ]);

  const projectTasks = allTasks.filter(t => t.project_name === name);

  // Idle review toggle
  var idleToggleBox = document.getElementById('project-idle-toggle');
  if (idleToggleBox && proj) {
    var _idleKey = 'idle_review_proj_' + proj.id;
    var _idleOn = !(S.settings && S.settings[_idleKey] === '0');
    idleToggleBox.innerHTML = '<span class="text-xs text-on-surface-variant mr-2">' + _t('proj.idle_review') + '</span>' +
      '<button id="idle-toggle-btn" onclick="doToggleIdle(\'' + escJsAttr(proj.id) + '\')" class="relative w-10 h-5 rounded-full transition-colors ' + (_idleOn ? 'bg-tertiary' : 'bg-outline-variant') + '">' +
      '<div class="absolute top-0.5 ' + (_idleOn ? 'left-5' : 'left-0.5') + ' w-4 h-4 bg-white rounded-full shadow transition-all"></div>' +
      '</button>';
  }

  renderProjectPreview(proj);

  renderProjectStatusBadge(projectTasks);
  renderProjectTasks(projectTasks);
  renderProjectKanban(projectTasks);

  // Stats + task type breakdown
  const total = projectTasks.length;
  const done = projectTasks.filter(t => ['hecha','archivada'].includes(t.status)).length;
  document.getElementById('project-stat-total').textContent = total + ' tareas';

  renderProjectTypeChart(projectTasks, total, done);

  renderProjectActivity(activity, allTasks, name);
  renderProjectPreviewSection(proj);
}

function renderProjectStatusBadge(projectTasks) {
  const badge = document.getElementById('project-status-badge');
  const anyDoing = projectTasks.some(t => t.status === 'en_progreso');
  var _bc = anyDoing ? 'tertiary' : 'primary';
  var _bs = anyDoing ? '#9bffce' : '#85adff';
  badge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-' + _bc + ' shadow-[0_0_8px_' + _bs + ']"></span>' +
    '<span class="text-' + _bc + ' font-bold text-xs">' + (anyDoing ? _t('proj.status_active') : _t('proj.status_stable')) + '</span>';
}

function renderProjectTasks(projectTasks) {
  const tbody = document.getElementById('project-tasks-table');
  tbody.innerHTML = projectTasks.map(function(t) {
    var r = '<tr class="group hover:bg-surface-bright/50 transition-colors cursor-pointer" onclick="openTaskById(\'' + escJsAttr(t.id) + '\')">';
    r += '<td class="py-2.5 px-2 flex items-center gap-3">';
    r += '<span class="material-symbols-outlined text-on-surface-variant text-sm">task_alt</span>';
    r += '<span class="text-on-surface/90">' + escHtml(t.title) + '</span>';
    r += '</td>';
    r += '<td class="py-2.5 px-2"><span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ' + statusBadgeClass(t.status) + '">' + statusLabel(t.status) + '</span></td>';
    r += '<td class="py-2.5 px-2 text-on-surface-variant text-xs">' + (t.updated_at ? timeAgo(t.updated_at) : '--') + '</td>';
    r += '</tr>';
    return r;
  }).join('');
}

function renderProjectKanban(projectTasks) {
  const kanbanBox = document.getElementById('project-kanban-tasks');
  kanbanBox.innerHTML = projectTasks.slice(0, 6).map(function(t) {
    var r = '<div class="bg-surface-bright/40 p-4 rounded-lg hover:bg-surface-bright/60 transition-all cursor-pointer" onclick="openTaskById(\'' + escJsAttr(t.id) + '\')">';
    r += '<div class="flex justify-between items-start mb-1">';
    r += '<h4 class="text-sm font-medium ' + (t.status === 'hecha' ? 'line-through opacity-70' : '') + '">' + escHtml(t.title) + '</h4>';
    r += '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ' + statusBadgeClass(t.status) + '">' + statusLabel(t.status) + '</span>';
    r += '</div>';
    r += '</div>';
    return r;
  }).join('');
}

let _previewExpanded = false;
let _previewDevice = 'desktop';

function setPreviewDevice(mode) {
  _previewDevice = mode;
  const container = document.getElementById('project-preview-container');
  const btnDesktop = document.getElementById('preview-btn-desktop');
  const btnMobile = document.getElementById('preview-btn-mobile');
  if (!container) return;
  container.classList.remove('preview-desktop', 'preview-mobile');
  container.classList.add(mode === 'mobile' ? 'preview-mobile' : 'preview-desktop');
  if (btnDesktop && btnMobile) {
    btnDesktop.classList.toggle('preview-device-active', mode === 'desktop');
    btnMobile.classList.toggle('preview-device-active', mode === 'mobile');
  }
}

function togglePreviewSize() {
  _previewExpanded = !_previewExpanded;
  const container = document.getElementById('project-preview-container');
  const icon = document.getElementById('preview-size-icon');
  if (_previewExpanded) {
    container.style.maxHeight = '90vh';
    container.style.aspectRatio = _previewDevice === 'mobile' ? '9/16' : '16/9';
    icon.textContent = 'fullscreen_exit';
  } else {
    container.style.maxHeight = '';
    container.style.aspectRatio = '';
    icon.textContent = 'fullscreen';
  }
}

function openPreviewExternal() {
  if (S._previewUrl) window.open(S._previewUrl, '_blank');
}

function showProjectsList() {
  document.getElementById('projects-list-view').classList.remove('hidden');
  document.getElementById('project-detail-view').classList.add('hidden');
  S.currentProject = null;
}

function escHtml(s) {
  s = String(s == null ? '' : s);
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* Escape a value for use inside a single-quoted JS string within an HTML attribute.
   Prevents XSS via onclick="fn('${val}')" by escaping at both layers. */
function escJsAttr(s) {
  var js = String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/\n/g,'\\n').replace(/\r/g,'\\r');
  return js.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const map = {
    js: 'javascript', ts: 'javascript', py: 'code', html: 'html', css: 'css',
    json: 'data_object', md: 'description', txt: 'article', yml: 'settings',
    yaml: 'settings', sql: 'database', sh: 'terminal', png: 'image',
    jpg: 'image', jpeg: 'image', svg: 'image', gif: 'image', webp: 'image',
    pdf: 'picture_as_pdf', zip: 'folder_zip', gz: 'folder_zip', tar: 'folder_zip',
    env: 'lock', lock: 'lock', toml: 'settings', cfg: 'settings', ini: 'settings',
  };
  return map[ext] || 'draft';
}

function renderFileTree(nodes, depth = 0, slug = '', parentPath = '') {
  if (!nodes || !nodes.length) return '';
  return nodes.map(n => {
    const pad = depth * 20;
    const nodePath = parentPath ? parentPath + '/' + n.name : n.name;
    if (n.type === 'dir') {
      const id = 'ftree-' + nodePath.replace(/[^a-zA-Z0-9]/g, '-');
      const childFiles = (n.children || []).filter(c => c.type === 'file').length;
      const childDirs = (n.children || []).filter(c => c.type === 'dir').length;
      return `<div>
        <div class="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-surface-bright/50 cursor-pointer transition-colors" style="padding-left:${pad + 8}px" onclick="toggleFolderTree(this, '${escJsAttr(id)}', '${escJsAttr(slug)}', '${escJsAttr(nodePath)}')">
          <span class="material-symbols-outlined text-xs text-on-surface-variant ftree-arrow transition-transform duration-150">chevron_right</span>
          <span class="material-symbols-outlined text-sm text-primary/80">folder</span>
          <span class="text-on-surface/90">${escHtml(n.name)}</span>
          ${childFiles > 0 ? `<span class="text-on-surface-variant/50 text-[10px] ml-auto">${childFiles}</span>` : ''}
        </div>
        <div id="${id}" class="hidden" data-loaded="0">${renderFileTree(n.children, depth + 1, slug, nodePath)}</div>
      </div>`;
    }
    return `<div class="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-surface-bright/50 transition-colors" style="padding-left:${pad + 28}px">
      <span class="material-symbols-outlined text-sm text-on-surface-variant/60">${fileIcon(n.name)}</span>
      <span class="text-on-surface/80">${escHtml(n.name)}</span>
      <span class="text-on-surface-variant/40 text-[10px] ml-auto">${formatFileSize(n.size)}</span>
    </div>`;
  }).join('');
}

async function toggleFolderTree(el, containerId, slug, folderPath) {
  const container = document.getElementById(containerId);
  const arrow = el.querySelector('.ftree-arrow');
  if (!container || !arrow) return;
  const isHidden = container.classList.contains('hidden');
  container.classList.toggle('hidden');
  arrow.classList.toggle('rotate-90', isHidden);
  // Lazy-load files on first open
  if (isHidden && container.dataset.loaded === '0') {
    container.dataset.loaded = '1';
    try {
      const data = await api('projects/' + encodeURIComponent(slug) + '/folder-files/' + folderPath.split('/').map(encodeURIComponent).join('/'));
      if (data && data.files && data.files.length > 0) {
        const depth = folderPath.split('/').length;
        const pad = depth * 20;
        const filesHtml = data.files.map(f => `<div class="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-surface-bright/50 transition-colors" style="padding-left:${pad + 28}px">
          <span class="material-symbols-outlined text-sm text-on-surface-variant/60">${fileIcon(f.name)}</span>
          <span class="text-on-surface/80">${escHtml(f.name)}</span>
          <span class="text-on-surface-variant/40 text-[10px] ml-auto">${formatFileSize(f.size)}</span>
        </div>`).join('');
        container.insertAdjacentHTML('beforeend', filesHtml);
      }
    } catch (e) { /* ignore lazy load errors */ }
  }
}

function countFiles(nodes) {
  let count = 0;
  for (const n of nodes) {
    if (n.type === 'file') count++;
    else if (n.children) count += countFiles(n.children);
  }
  return count;
}

async function loadProjectUploads(slug) {
  const box = document.getElementById('project-uploads-list');
  if (!box) return;
  const data = await api('projects/' + encodeURIComponent(slug) + '/uploads');
  if (!data || !data.length) {
    box.innerHTML = '<p class="text-on-surface-variant/50 text-xs italic">Sin archivos subidos</p>';
    return;
  }
  box.innerHTML = data.map(f => `<div class="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-surface-bright/50 transition-colors">
    <span class="material-symbols-outlined text-sm text-primary/60">attachment</span>
    <span class="text-sm text-on-surface/80">${escHtml(f.name)}</span>
    <span class="text-on-surface-variant/40 text-[10px] ml-auto">${formatFileSize(f.size)}</span>
  </div>`).join('');
}

async function uploadProjectFiles(fileList) {
  if (!fileList || !fileList.length || !S.currentProjectSlug) return;
  const form = new FormData();
  let totalSize = 0;
  for (const f of fileList) { form.append('files', f); totalSize += f.size; }
  const names = Array.from(fileList).map(f => f.name).join(', ');

  // Show progress bar
  const bar = document.getElementById('upload-progress');
  const barFill = document.getElementById('upload-progress-fill');
  const barText = document.getElementById('upload-progress-text');
  if (bar) { bar.classList.remove('hidden'); barFill.style.width = '0%'; barText.textContent = 'Subiendo ' + names.substring(0, 60) + '...'; }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/projects/' + encodeURIComponent(S.currentProjectSlug) + '/upload');
    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable && barFill) {
        const pct = Math.round((e.loaded / e.total) * 100);
        barFill.style.width = pct + '%';
        barText.textContent = pct + '% — ' + names.substring(0, 40);
      }
    };
    xhr.onload = function() {
      if (bar) bar.classList.add('hidden');
      if (xhr.status >= 400) {
        reject(new Error('Upload failed with status ' + xhr.status));
        return;
      }
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.ok) {
          toast(data.count + ' archivo(s) subido(s)', 'primary');
          loadProjectFiles(S.currentProjectSlug);
          loadProjectUploads(S.currentProjectSlug);
        } else {
          toast(data.error || 'Error al subir', 'error');
        }
      } catch (e) {
        toast('Error al procesar respuesta', 'error');
      }
      resolve();
    };
    xhr.onerror = function() {
      if (bar) bar.classList.add('hidden');
      toast('Error de conexión al subir', 'error');
      reject(new Error('Upload failed'));
    };
    xhr.send(form);
  });
}

async function loadProjectFiles(slug) {
  const container = document.getElementById('project-files-tree');
  const counter = document.getElementById('project-files-count');
  container.innerHTML = '<p class="text-on-surface-variant text-sm animate-pulse">' + _t('proj.loading_tree') + '</p>';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15000);
    const data = await api('projects/' + encodeURIComponent(slug) + '/tree?mode=folders', { signal: ctrl.signal });
    clearTimeout(timer);
    if (!data || !data.tree) {
      container.innerHTML = '<p class="text-on-surface-variant text-sm">' + _t('proj.error_tree') + '</p>';
      return;
    }
    if (data.tree.length === 0 && (data.root_file_count || 0) === 0) {
      container.innerHTML = '<p class="text-on-surface-variant text-sm italic">' + _t('proj.empty_dir') + '</p>';
      counter.textContent = '';
      return;
    }
    if (data.tree.length === 0 && data.root_file_count > 0) {
      // No subfolders but root has files — load them directly
      counter.textContent = data.root_file_count + ' archivo' + (data.root_file_count !== 1 ? 's' : '');
      try {
        const rootFiles = await api('projects/' + encodeURIComponent(slug) + '/folder-files/');
        if (rootFiles && rootFiles.files && rootFiles.files.length > 0) {
          container.innerHTML = rootFiles.files.map(f => `<div class="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-surface-bright/50 transition-colors" style="padding-left:8px">
            <span class="material-symbols-outlined text-sm text-on-surface-variant/60">${fileIcon(f.name)}</span>
            <span class="text-on-surface/80">${escHtml(f.name)}</span>
            <span class="text-on-surface-variant/40 text-[10px] ml-auto">${formatFileSize(f.size)}</span>
          </div>`).join('');
        } else {
          container.innerHTML = '<p class="text-on-surface-variant text-sm italic">' + _t('proj.empty_dir') + '</p>';
        }
      } catch (e) {
        container.innerHTML = '<p class="text-on-surface-variant text-sm">' + _t('proj.error_files') + '</p>';
      }
      return;
    }
    const total = data.tree.reduce(function countDirs(acc, n) {
      return acc + 1 + (n.children ? n.children.reduce(countDirs, 0) : 0);
    }, 0);
    const rfc = data.root_file_count || 0;
    let label = total + ' carpeta' + (total !== 1 ? 's' : '');
    if (rfc > 0) label += ', ' + rfc + ' archivo' + (rfc !== 1 ? 's' : '');
    if (data.truncated) label += ' (truncated)';
    counter.textContent = label;
    container.innerHTML = renderFileTree(data.tree, 0, slug);
    if (data.truncated) {
      container.insertAdjacentHTML('beforeend', '<p class="text-on-surface-variant/50 text-xs italic mt-2 px-2">' + _t('proj.tree_truncated') + '</p>');
    }
  } catch (e) {
    container.innerHTML = '<p class="text-on-surface-variant text-sm">' + _t('proj.error_files') + '</p>';
  }
}

// ======================== AGENTS ========================

// ======================== SYSTEM ========================
function switchSystemTab(tab) {
  S.systemTab = tab;
  // Update hash to persist sub-tab in URL (suppresses redundant hashchange reload)
  S._skipHashRoute = true;
  window.location.hash = '/system/' + tab;
  restoreSystemTabUI(tab);
}

function restoreSystemTabUI(tab) {
  // Highlight the correct button via data attribute
  document.querySelectorAll('.sys-tab').forEach(b => {
    b.classList.remove('sys-tab-active','bg-surface-container-high','text-on-surface');
    b.classList.add('text-on-surface-variant');
  });
  const activeBtn = document.querySelector(`.sys-tab[data-systab="${tab}"]`);
  if (activeBtn) {
    activeBtn.classList.add('sys-tab-active','bg-surface-container-high','text-on-surface');
    activeBtn.classList.remove('text-on-surface-variant');
  }
  // Show the correct panel
  document.querySelectorAll('.sys-panel').forEach(p => p.classList.add('hidden'));
  const panel = document.getElementById('sys-' + tab);
  if (panel) panel.classList.remove('hidden');
  // Load tab data
  loadSystemTabData(tab);
}

async function loadSystem() {
  const tab = S.systemTab || 'overview';
  // If system view was already rendered, only refresh data — never re-render tabs
  if (S._systemRendered) {
    loadSystemTabData(tab);
    return;
  }
  // First render: set up the tab UI and mark as initialized
  S._systemRendered = true;
  restoreSystemTabUI(tab);
}

function loadSystemTabData(tab) {
  switch (tab) {
    case 'overview': loadSystemOverview(); break;
    case 'routines': loadRoutines(); break;
    case 'logs': loadLogs(); break;
    case 'config': loadConfig(); break;
    case 'stats': loadStats(); break;
    case 'kpis': loadKpis(); break;
    case 'docs': loadDocs(); break;
    case 'styles': loadStyles(); break;
  }
}

async function loadSystemOverview() {
  const stats = await api('stats');
  if (!stats) return;
  S.stats = stats;
  document.getElementById('sys-total').textContent = stats.total || 0;
  document.getElementById('sys-open').textContent = stats.open || 0;
  document.getElementById('sys-done-today').textContent = stats.done_today || 0;
  const byStatus = stats.by_status || {};
  const statusBox = document.getElementById('sys-by-status');
  statusBox.innerHTML = Object.entries(byStatus).map(([status, count]) => `
    <div class="bg-surface-dim/40 p-4 rounded-lg">
      <p class="text-[10px] text-on-surface-variant uppercase font-bold mb-1">${statusLabel(status)}</p>
      <p class="text-xl font-headline font-bold">${count}</p>
    </div>`).join('');

  // Routines scheduler info
  api('routines').then(r => {
    const enabled = r ? r.filter(x => x.enabled).length : 0;
    const total = r ? r.length : 0;
    const el = document.getElementById('sys-scheduler-status');
    if (el) el.textContent = enabled + '/' + total;
    const sub = document.getElementById('sys-scheduler-sub');
    if (sub) sub.textContent = 'routines activas';
  });
}

async function loadLogs() {
  const source = document.getElementById('log-source')?.value || 'all';
  const data = await api('logs?source=' + source);
  const box = document.getElementById('logs-container');
  if (!data || !data.length) { box.innerHTML = '<p class="text-on-surface-variant">' + _t('sys.no_logs') + '</p>'; return; }
  const sourceColors = { gateway: 'primary', sync: 'tertiary', bridge: 'secondary', executor: 'agent-claude', watchdog: 'warning' };
  box.innerHTML = data.slice(-200).map(l => {
    const color = sourceColors[l.source] || 'on-surface-variant';
    return `<p class="text-on-surface/80"><span class="text-on-surface-variant/40">[${l.source}]</span> <span class="text-${color}/80">${escHtml(l.line)}</span></p>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

async function loadDocs() {
  const data = await api('docs');
  const box = document.getElementById('docs-content');
  if (!box || !data) return;
  const docs = [
    {key: 'architecture', title: 'Arquitectura del Sistema', icon: 'architecture'},
    {key: 'error-standard', title: 'Error Handling Standard', icon: 'error'},
    {key: 'refactor-plan', title: 'Plan de Refactor', icon: 'construction'},
    {key: 'api', title: 'API Reference', icon: 'api'},
  ];
  let html = '<div class="space-y-4">';
  for (const doc of docs) {
    const content = data[doc.key];
    if (!content) continue;
    const lines = content.split('\n').length;
    const preview = content.split('\n').slice(0, 3).join(' ').substring(0, 150);
    html += `<details class="bg-[rgb(var(--c-card))] rounded-2xl shadow-sm overflow-hidden">
      <summary class="p-5 cursor-pointer hover:bg-surface-bright/30 transition-colors flex items-center gap-3">
        <span class="material-symbols-outlined text-primary">${doc.icon}</span>
        <div class="flex-1">
          <p class="font-headline font-bold text-on-surface">${doc.title}</p>
          <p class="text-xs text-on-surface-variant">${lines} líneas</p>
        </div>
        <span class="material-symbols-outlined text-on-surface-variant text-sm">expand_more</span>
      </summary>
      <div class="px-5 pb-5 border-t border-outline-variant/20 pt-4">
        <pre class="text-xs text-on-surface whitespace-pre-wrap font-mono leading-relaxed max-h-[600px] overflow-y-auto">${escHtml(content)}</pre>
      </div>
    </details>`;
  }
  html += '</div>';
  box.innerHTML = html;
}



async function loadConfig() {
  const [data, integrations] = await Promise.all([api('config'), api('settings/integrations'), loadSettings()]);
  const box = document.getElementById('config-panels');
  if (!data && !integrations) { box.innerHTML = '<p class="text-on-surface-variant">' + _t('sys.no_config') + '</p>'; return; }

  const idleMode = (S.settings && S.settings.idle_review_mode) || 'manual';
  const isAuto = idleMode === 'auto';
  const notifFormat = (S.settings && S.settings.notification_format) || 'text';
  const currentLang = I18N.locale;
  const ig = integrations || {};
  if (ig.terminal_port) S._terminalPort = ig.terminal_port;

  // Integrations panel
  let integrationsHtml = `
    <div class="bg-surface-container-high rounded-lg p-6 mb-4">
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-secondary">integration_instructions</span>
          <h3 class="text-sm font-semibold uppercase tracking-wider">Integraciones</h3>
        </div>
        <button onclick="openTerminal()" class="flex items-center gap-2 px-3 py-1.5 bg-surface-bright hover:bg-surface-container-high text-on-surface-variant text-xs font-medium rounded-lg transition-all" title="Abrir terminal del servidor">
          <span class="material-symbols-outlined text-sm">terminal</span> Terminal
        </button>
      </div>

      <!-- Telegram -->
      <div class="mb-6 pb-5 border-b border-outline-variant/10">
        <div class="flex items-center gap-2 mb-3">
          <span class="material-symbols-outlined text-primary text-base">send</span>
          <span class="text-sm font-medium">Telegram</span>
          ${ig.telegram_bot_token_set ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-tertiary/10 text-tertiary font-bold">Configurado</span>' : '<span class="text-[10px] px-2 py-0.5 rounded-full bg-outline-variant/20 text-on-surface-variant font-bold">No configurado</span>'}
        </div>
        ${!ig.telegram_bot_token_set ? '<div class="bg-surface-dim/50 rounded-lg p-3 mb-3 text-xs text-on-surface-variant space-y-1"><p><b>Setup:</b> 1. Abre @BotFather en Telegram y crea un bot con /newbot</p><p>2. Copia el token que te da (ej: 123456:ABC-DEF...)</p><p>3. Abre @userinfobot para obtener tu Chat ID numérico</p><p>4. Pega ambos aquí y dale a Guardar, luego Test</p></div>' : ''}
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Bot Token ${ig.telegram_bot_token_set ? '<span class="text-tertiary">(guardado)</span>' : ''}</label>
            <input id="int-telegram-token" type="password" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="${ig.telegram_bot_token_set ? 'Guardado — deja vacío para mantener' : '123456:ABC-DEF1234...'}" value="">
          </div>
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Chat ID</label>
            <input id="int-telegram-chatid" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="123456789" value="${escHtml(ig.telegram_chat_id || '')}">
          </div>
        </div>
        <div class="flex gap-2">
          <button onclick="saveIntegration('telegram')" class="px-3 py-1.5 bg-primary text-on-primary text-xs font-bold rounded-lg hover:opacity-90">Guardar</button>
          <button onclick="testTelegram()" class="px-3 py-1.5 bg-surface-bright text-on-surface-variant text-xs font-medium rounded-lg hover:bg-surface-container-high">Test</button>
        </div>
        <div id="telegram-test-result" class="mt-2 text-xs hidden"></div>
      </div>

      <!-- Webhook -->
      <div class="mb-6 pb-5 border-b border-outline-variant/10">
        <div class="flex items-center gap-2 mb-3">
          <span class="material-symbols-outlined text-secondary text-base">webhook</span>
          <span class="text-sm font-medium">Webhook</span>
        </div>
        <div class="mb-3">
          <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">URL</label>
          <input id="int-webhook-url" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="${ig.webhook_url || 'https://example.com/hook'}" value="${ig.webhook_url || ''}">
        </div>
        <button onclick="saveIntegration('webhook')" class="px-3 py-1.5 bg-primary text-on-primary text-xs font-bold rounded-lg hover:opacity-90">Guardar</button>
      </div>

      <!-- LLM Provider -->
      <div class="mb-6 pb-5 border-b border-outline-variant/10">
        <div class="flex items-center gap-2 mb-3">
          <span class="material-symbols-outlined text-tertiary text-base">smart_toy</span>
          <span class="text-sm font-medium">LLM Provider</span>
          <span class="text-[10px] text-on-surface-variant">(ejecuta tareas automáticamente)</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Provider</label>
            <select id="int-llm-provider" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface" onchange="updateLlmHelp()">
              <option value="" ${!ig.llm_provider?'selected':''}>No configurado</option>
              <option value="claude" ${ig.llm_provider==='claude'?'selected':''}>Claude (Anthropic)</option>
              <option value="llm" ${ig.llm_provider==='llm'?'selected':''}>llm CLI (Simon Willison)</option>
              <option value="gemini" ${ig.llm_provider==='gemini'?'selected':''}>Gemini (Google)</option>
              <option value="custom" ${ig.llm_provider==='custom'?'selected':''}>Custom</option>
            </select>
          </div>
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Autenticación</label>
            <select id="int-llm-auth" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface" onchange="updateLlmHelp()">
              <option value="api_key" ${(ig.llm_auth_method||'api_key')==='api_key'?'selected':''}>API Key</option>
              <option value="setup_token" ${ig.llm_auth_method==='setup_token'?'selected':''}>Setup Token (Claude Max/Team)</option>
              <option value="oauth" ${ig.llm_auth_method==='oauth'?'selected':''}>OAuth (ya autenticado en terminal)</option>
            </select>
          </div>
        </div>
        <div id="llm-auth-fields" class="mb-3">
          <div id="llm-auth-apikey" class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">API Key</label>
              <input id="int-llm-apikey" type="password" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="${ig.llm_api_key_set ? ig.llm_api_key : 'sk-ant-...'}" value="">
            </div>
            <div>
              <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Comando</label>
              <input id="int-llm-command" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="claude -p --output-format text" value="${escHtml(ig.llm_command || '')}">
            </div>
          </div>
          <div id="llm-auth-token" class="hidden">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Setup Token</label>
                <input id="int-llm-setup-token" type="password" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="Pega el token de claude.ai/settings">
              </div>
              <div>
                <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Comando</label>
                <input id="int-llm-command-token" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="claude -p --max-turns 50 --output-format text" value="${escHtml(ig.llm_command || '')}">
              </div>
            </div>
            <button onclick="applySetupToken()" class="mt-2 px-3 py-1.5 bg-secondary text-on-secondary text-xs font-bold rounded-lg hover:opacity-90">Aplicar token</button>
            <span id="setup-token-result" class="ml-2 text-xs"></span>
          </div>
          <div id="llm-auth-oauth" class="hidden">
            <div class="mb-2">
              <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Comando</label>
              <input id="int-llm-command-oauth" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface font-mono" placeholder="claude -p --max-turns 50 --output-format text" value="${escHtml(ig.llm_command || '')}">
            </div>
          </div>
        </div>
        <div id="llm-setup-help" class="bg-surface-dim/50 rounded-lg p-3 mb-3 text-xs text-on-surface-variant space-y-1"></div>
        <div id="llm-status" class="mb-3 text-xs"></div>
        <div class="flex gap-2">
          <button onclick="saveIntegration('llm')" class="px-3 py-1.5 bg-primary text-on-primary text-xs font-bold rounded-lg hover:opacity-90">Guardar</button>
          <button onclick="checkLlmStatus()" class="px-3 py-1.5 bg-surface-bright text-on-surface-variant text-xs font-medium rounded-lg hover:bg-surface-container-high">Verificar</button>
        </div>
      </div>

      <!-- Executor -->
      <div>
        <div class="flex items-center gap-2 mb-3">
          <span class="material-symbols-outlined text-primary text-base">play_circle</span>
          <span class="text-sm font-medium">Task Executor</span>
        </div>
        <div class="bg-surface-dim/50 rounded-lg p-3 mb-3 text-xs text-on-surface-variant">
          <p>El executor recoge tareas en estado <b>pendiente</b> y las ejecuta con el LLM configurado arriba.</p>
          <p>Corre como daemon en el host (no en Docker). Poll = cada cuántos segundos busca tareas. Timeout = máximo por tarea.</p>
          <p>Cambios aquí se guardan en la DB. Para que el executor los lea, reinícialo: <code>niwa restart</code></p>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Estado</label>
            <select id="int-executor-enabled" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface">
              <option value="1" ${ig.executor_enabled==='1'?'selected':''}>Activado</option>
              <option value="0" ${ig.executor_enabled!=='1'?'selected':''}>Desactivado</option>
            </select>
          </div>
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Poll (seg)</label>
            <input id="int-executor-poll" type="number" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface" value="${ig.executor_poll_seconds || '30'}" min="5" max="3600">
          </div>
          <div>
            <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">Timeout (seg)</label>
            <input id="int-executor-timeout" type="number" class="w-full bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-2 px-3 text-sm text-on-surface" value="${ig.executor_timeout_seconds || '1800'}" min="60" max="7200">
          </div>
        </div>
        <button onclick="saveIntegration('executor')" class="px-3 py-1.5 bg-primary text-on-primary text-xs font-bold rounded-lg hover:opacity-90">Guardar</button>
      </div>
    </div>`;

  let settingsHtml = `
    <div class="bg-surface-container-high rounded-lg p-6 mb-4">
      <div class="flex items-center gap-3 mb-4">
        <span class="material-symbols-outlined text-tertiary">tune</span>
        <h3 class="text-sm font-semibold uppercase tracking-wider">${_t('settings.title')}</h3>
      </div>
      <div class="flex items-center justify-between mb-5 pb-5 border-b border-outline-variant/10">
        <div>
          <div class="text-sm font-medium">${_t('settings.language')}</div>
          <div class="text-xs text-on-surface-variant mt-1">${_t('settings.language_desc')}</div>
        </div>
        <select onchange="changeLocale(this.value)" class="bg-surface-container-low border border-outline-variant/20 rounded-lg px-3 py-1.5 text-sm text-on-surface">
          <option value="es" ${currentLang==='es'?'selected':''}>Español</option>
          <option value="en" ${currentLang==='en'?'selected':''}>English</option>
        </select>
      </div>
      ${_renderSettingToggle(_t('settings.idle_review'), isAuto ? _t('sys.auto_mode') : _t('sys.manual_mode'), isAuto, 'toggleIdleReviewMode()')}
    </div>`;

  box.innerHTML = integrationsHtml + settingsHtml + (data ? Object.entries(data).map(([key, val]) => `
    <div class="bg-surface-container-high rounded-lg p-6 mb-4">
      <div class="flex items-center gap-3 mb-4">
        <span class="material-symbols-outlined text-primary">settings</span>
        <h3 class="text-sm font-semibold uppercase tracking-wider">${key}</h3>
        <span class="text-[10px] text-on-surface-variant font-mono">${val.path || ''}</span>
      </div>
      <pre class="bg-black/20 p-4 rounded-lg text-[11px] font-mono text-on-surface/80 overflow-x-auto max-h-64 overflow-y-auto">${escHtml(JSON.stringify(val.data, null, 2))}</pre>
    </div>`).join('') : '');
  // Initialize contextual help
  updateLlmHelp();
}

function _renderSettingToggle(label, desc, isOn, onclickExpr, opts) {
  opts = opts || {};
  var color = opts.color || 'primary';
  var cls = opts.className || 'mb-5 pb-5 border-b border-outline-variant/10';
  return `<div class="flex items-center justify-between ${cls}">
    <div>
      <div class="text-sm font-medium ${opts.dimLabel ? 'text-on-surface-variant' : ''}">${label}</div>
      <div class="text-xs text-on-surface-variant mt-0.5">${desc}</div>
    </div>
    <button onclick="${onclickExpr}" class="relative w-12 h-6 rounded-full transition-colors ${isOn ? 'bg-' + color : 'bg-outline-variant'}">
      <div class="absolute top-0.5 ${isOn ? 'left-6' : 'left-0.5'} w-5 h-5 bg-white rounded-full shadow transition-all"></div>
    </button>
  </div>`;
}

function _renderNotifyToggle(settings, key, label, desc, isMaster) {
  var muted = settings && settings[key] === '1';
  return _renderSettingToggle(label, desc, !muted, "toggleSetting('" + key + "')", {
    color: isMaster ? 'primary' : 'tertiary',
    className: isMaster ? 'mb-4 pb-4 border-b border-outline-variant/10' : 'mb-3 pl-2',
    dimLabel: !isMaster
  });
}

async function saveIntegration(group) {
  const payload = {};
  if (group === 'telegram') {
    const token = document.getElementById('int-telegram-token').value.trim();
    const chatId = document.getElementById('int-telegram-chatid').value.trim();
    // Only send values the user actually typed — empty means "keep current"
    if (token) payload.telegram_bot_token = token;
    if (chatId) payload.telegram_chat_id = chatId;
    if (!token && !chatId) { toast('Nada que guardar — los campos vacíos mantienen el valor actual'); return; }
  } else if (group === 'webhook') {
    payload.webhook_url = document.getElementById('int-webhook-url').value.trim();
  } else if (group === 'llm') {
    payload.llm_provider = document.getElementById('int-llm-provider').value;
    const authMethod = document.getElementById('int-llm-auth').value;
    payload.llm_auth_method = authMethod;
    // Read command from whichever panel is visible
    const cmdEl = authMethod === 'setup_token' ? document.getElementById('int-llm-command-token') :
                  authMethod === 'oauth' ? document.getElementById('int-llm-command-oauth') :
                  document.getElementById('int-llm-command');
    payload.llm_command = (cmdEl ? cmdEl.value.trim() : '');
    if (authMethod === 'api_key') {
      const apiKey = document.getElementById('int-llm-apikey').value.trim();
      if (apiKey) payload.llm_api_key = apiKey;
    }
  } else if (group === 'executor') {
    payload.executor_enabled = document.getElementById('int-executor-enabled').value;
    payload.executor_poll_seconds = document.getElementById('int-executor-poll').value;
    payload.executor_timeout_seconds = document.getElementById('int-executor-timeout').value;
  }
  if (!Object.keys(payload).length) { toast('Nada que guardar'); return; }
  const res = await api('settings/integrations', { method: 'POST', body: JSON.stringify(payload) });
  if (res && res.ok) {
    toast('Configuración guardada', 'success');
    // Show restart banner for settings that need a service restart
    if (['llm', 'executor'].includes(group)) showRestartBanner();
  } else {
    toast('Error al guardar', 'error');
  }
}

async function testTelegram() {
  const resultEl = document.getElementById('telegram-test-result');
  if (resultEl) { resultEl.classList.remove('hidden'); resultEl.innerHTML = '<span class="text-on-surface-variant">Enviando test...</span>'; }
  const res = await api('settings/integrations/test-telegram', { method: 'POST', body: '{}' });
  if (res && res.ok) {
    toast('Mensaje de test enviado');
    if (resultEl) resultEl.innerHTML = '<span class="text-tertiary">OK — revisa tu Telegram</span>';
  } else {
    const err = (res && res.error) || 'Error desconocido';
    toast(err, 'error');
    if (resultEl) resultEl.innerHTML = '<span class="text-error">' + escHtml(err) + '</span>';
  }
}

function updateLlmHelp() {
  const provider = document.getElementById('int-llm-provider').value;
  const authMethod = document.getElementById('int-llm-auth').value;
  const helpEl = document.getElementById('llm-setup-help');

  // Show/hide auth fields based on method
  document.getElementById('llm-auth-apikey').classList.toggle('hidden', authMethod !== 'api_key');
  document.getElementById('llm-auth-token').classList.toggle('hidden', authMethod !== 'setup_token');
  document.getElementById('llm-auth-oauth').classList.toggle('hidden', authMethod !== 'oauth');

  if (!helpEl) return;

  const guides = {
    'api_key': {
      '': '<p>Selecciona un provider para ver las instrucciones.</p>',
      'claude': '<p><b>1.</b> Ve a <a href="https://console.anthropic.com/settings/keys" target="_blank" class="text-primary underline">console.anthropic.com/settings/keys</a> y crea una API key</p><p><b>2.</b> Pégala en el campo "API Key" de arriba</p><p><b>3.</b> Instala el CLI en el servidor (abre el <a href="#" onclick="openTerminal();return false" class="text-primary underline">Terminal</a>): <code>npm install -g @anthropic-ai/claude-code</code></p><p class="mt-1">Funciona con todos los planes. La key se inyecta como ANTHROPIC_API_KEY.</p>',
      'llm': '<p><b>1.</b> Ve a <a href="https://platform.openai.com/api-keys" target="_blank" class="text-primary underline">platform.openai.com/api-keys</a> y crea una key</p><p><b>2.</b> Pégala arriba</p><p><b>3.</b> Instala en el servidor: <code>pip install llm</code></p><p class="mt-1">Se inyecta como OPENAI_API_KEY. Para Anthropic/Gemini vía llm, instala plugins.</p>',
      'gemini': '<p><b>1.</b> Ve a <a href="https://aistudio.google.com/apikey" target="_blank" class="text-primary underline">aistudio.google.com/apikey</a></p><p><b>2.</b> Pégala arriba</p><p><b>3.</b> Instala: <code>pip install google-generativeai</code></p>',
      'custom': '<p>Pega tu API key y escribe el comando. La key se inyecta como env var al subprocess.</p>',
    },
    'setup_token': {
      '': '<p>El setup token es solo para Claude Pro/Max.</p>',
      'claude': '<p><b>1.</b> En tu laptop (con navegador), ejecuta: <code>claude setup-token</code></p><p><b>2.</b> Se abre el navegador para autenticarte. Te da un token (empieza por <code>sk-ant-oat01-</code>)</p><p><b>3.</b> Pega ese token aquí arriba y pulsa "Aplicar token"</p><p><b>4.</b> Instala el CLI en el servidor: <code>npm install -g @anthropic-ai/claude-code</code></p><p class="mt-1">Solo para planes Pro/Max. El token dura 1 año. Si tienes API key, usa mejor el método "API Key" — funciona con todos los planes.</p>',
    },
    'oauth': {
      '': '<p>OAuth requiere terminal + navegador en el servidor.</p>',
      'claude': '<p><b>1.</b> Instala el CLI: <code>npm install -g @anthropic-ai/claude-code</code></p><p><b>2.</b> Ejecuta <code>claude</code> en el terminal del servidor</p><p><b>3.</b> Abre el enlace que te da en un navegador y autoriza</p><p class="mt-1">Solo necesitas hacerlo una vez. La sesión se guarda en ~/.claude/. Usa "Verificar" para comprobar. Si el servidor no tiene navegador, usa "API Key" en su lugar.</p>',
    },
  };

  const methodGuides = guides[authMethod] || guides['api_key'];
  helpEl.innerHTML = methodGuides[provider] || methodGuides[''] || '<p>Selecciona provider y método de auth.</p>';

  // Update command placeholder
  const defaults = { claude: 'claude -p --max-turns 50 --output-format text', llm: 'llm -m gpt-4 --no-stream', gemini: 'gemini chat --model gemini-1.5-pro', custom: '' };
  const cmdInputs = document.querySelectorAll('#int-llm-command, #int-llm-command-token, #int-llm-command-oauth');
  cmdInputs.forEach(el => { if (provider && defaults[provider] && !el.value) el.placeholder = defaults[provider]; });
}

async function applySetupToken() {
  const token = document.getElementById('int-llm-setup-token').value.trim();
  const resultEl = document.getElementById('setup-token-result');
  if (!token) { if (resultEl) resultEl.innerHTML = '<span class="text-error">Token vacío</span>'; return; }
  if (resultEl) resultEl.innerHTML = '<span class="text-on-surface-variant">Aplicando...</span>';
  const res = await api('settings/llm/setup-token', { method: 'POST', body: JSON.stringify({ token }) });
  if (res && res.ok) {
    if (resultEl) resultEl.innerHTML = '<span class="text-tertiary">' + escHtml(res.message || 'OK') + '</span>';
    toast('Token aplicado', 'success');
  } else {
    const err = (res && res.error) || 'Error';
    if (resultEl) resultEl.innerHTML = '<span class="text-error">' + escHtml(err) + '</span>';
    toast(err, 'error');
  }
}

function openTerminal() {
  // Open the web terminal (ttyd) in a new tab, same host different port
  const port = S._terminalPort || '7681';
  const url = window.location.protocol + '//' + window.location.hostname + ':' + port;
  window.open(url, '_blank');
}

async function checkLlmStatus() {
  const el = document.getElementById('llm-status');
  if (el) el.innerHTML = '<span class="text-on-surface-variant">Verificando...</span>';
  const res = await api('settings/llm-status');
  if (!res || !el) return;
  const icons = { ready: '✓', cli_missing: '⚠', needs_auth: '⚠', needs_oauth: '⚠', not_configured: '—' };
  const colors = { ready: 'text-tertiary', cli_missing: 'text-warning', needs_auth: 'text-warning', needs_oauth: 'text-warning', not_configured: 'text-on-surface-variant' };
  const msgs = {
    ready: 'Listo — CLI instalado y autenticado',
    cli_missing: 'CLI no instalado en el servidor' + (res.provider === 'claude' ? ' (npm install -g @anthropic-ai/claude-code)' : ''),
    needs_auth: 'CLI instalado pero no autenticado — aplica un setup token',
    needs_oauth: 'CLI instalado pero no autenticado — ejecuta claude en el terminal',
    not_configured: 'No configurado',
  };
  const s = res.status || 'not_configured';
  el.innerHTML = '<span class="' + (colors[s]||'') + '">' + (icons[s]||'') + ' ' + escHtml(msgs[s] || s) + '</span>' +
    (res.cli_path ? '<span class="text-[10px] text-on-surface-variant ml-2">(' + escHtml(res.cli_path) + ')</span>' : '');
}

async function toggleSetting(key) {
  const current = (S.settings && S.settings[key]) || '0';
  const newVal = current === '1' ? '0' : '1';
  await saveSetting(key, newVal);
  toast(newVal === '1' ? _t('settings.activated') : _t('settings.deactivated'));
  loadConfig();
}

async function toggleIdleReviewMode() {
  const current = (S.settings && S.settings.idle_review_mode) || 'manual';
  const newMode = current === 'auto' ? 'manual' : 'auto';
  await saveSetting('idle_review_mode', newMode);
  toast(newMode === 'auto' ? _t('sys.auto_mode') : _t('sys.manual_mode'));
  loadConfig();
}

async function changeNotificationFormat(format) {
  await saveSetting('notification_format', format);
  toast(_t('settings.saved'));
  loadConfig();
}

async function triggerIdleReview() {
  const btn = document.getElementById('btn-run-review');
  const txt = document.getElementById('review-btn-text');
  const icon = document.getElementById('review-icon');
  if (!btn) return;
  btn.disabled = true;
  txt.textContent = 'Ejecutando…';
  icon.classList.add('animate-spin');
  try {
    const r = await fetch('/api/trigger/idle-review', { method: 'POST' });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      toast(data.message || 'Review completado', 'info');
      loadKanban();
    } else {
      toast(data.error || 'Review fallido', 'error');
    }
  } catch (e) {
    toast('No se pudo conectar al servicio de review: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    txt.textContent = 'Ejecutar Review';
    icon.classList.remove('animate-spin');
  }
}

async function loadStats() {
  const stats = await api('stats');
  if (!stats) return;
  const cards = document.getElementById('stats-cards');
  cards.innerHTML = [
    { label: _t('stats.total'), val: stats.total, icon: 'assignment', color: 'primary' },
    { label: _t('stats.open'), val: stats.open, icon: 'pending', color: 'secondary' },
    { label: _t('stats.done'), val: stats.done, icon: 'check_circle', color: 'tertiary' },
    { label: _t('stats.overdue'), val: stats.overdue, icon: 'warning', color: 'error' },
  ].map(c => `<div class="bg-surface-container-high p-6 rounded-lg">
    <div class="flex justify-between items-start mb-3"><span class="material-symbols-outlined text-${c.color}">${c.icon}</span></div>
    <p class="text-[10px] text-on-surface-variant uppercase font-bold mb-1">${c.label}</p>
    <p class="text-3xl font-headline font-bold">${c.val||0}</p>
  </div>`).join('');

  const byPriority = stats.by_priority || {};
  document.getElementById('stats-priority').innerHTML = Object.entries(byPriority).map(([p, c]) => `
    <div class="bg-surface-dim/40 p-4 rounded-lg">
      <p class="text-[10px] text-on-surface-variant uppercase font-bold mb-1">${p}</p>
      <p class="text-xl font-headline font-bold">${c}</p>
    </div>`).join('');
}


// ======================== KPIs ========================
async function loadKpis() {
  const data = await api('kpis');
  if (!data) return;

  // Overall summary
  const ov = data.overall || {};
  document.getElementById('kpi-completed-today').textContent = ov.tasks_completed_today || 0;
  document.getElementById('kpi-blocked-today').textContent = ov.tasks_blocked_today || 0;
  const avgSec = ov.avg_pipeline_duration || 0;
  document.getElementById('kpi-avg-pipeline').textContent = formatDuration(avgSec, 'seconds');

  renderKpiPhaseCards(data);
  renderKpiBarChart(data);
  renderKpiLimitTable(data);
}

function renderKpiPhaseCards(data) {
  const phases = ['triage', 'execute', 'review', 'deploy'];
  const phaseIcons = { triage: 'filter_alt', execute: 'play_arrow', review: 'rate_review', deploy: 'rocket_launch' };
  const phaseColors = { triage: 'primary', execute: 'tertiary', review: 'secondary', deploy: 'green-500' };
  const cardsEl = document.getElementById('kpi-phase-cards');
  cardsEl.innerHTML = phases.map(p => {
    const s = (data.per_phase || {})[p] || {};
    const successPct = s.success_rate || 0;
    const limitPct = s.limit_hit_rate || 0;
    const barW = Math.min(100, Math.max(0, successPct));
    return `<div class="bg-[rgb(var(--c-card))] rounded-2xl shadow-sm p-5">
      <div class="flex items-center gap-2 mb-3">
        <span class="material-symbols-outlined text-${phaseColors[p]} text-lg">${phaseIcons[p]}</span>
        <h4 class="text-sm font-headline font-bold uppercase">${p}</h4>
        <span class="ml-auto text-[10px] text-on-surface-variant">${s.total_runs || 0} runs</span>
      </div>
      <div class="mb-3">
        <div class="flex justify-between text-xs mb-1"><span class="text-on-surface-variant">Success rate</span><span class="font-bold text-${successPct >= 80 ? 'green-500' : successPct >= 50 ? 'primary' : 'error'}">${successPct}%</span></div>
        <div class="h-1.5 bg-surface-variant/40 rounded-full overflow-hidden"><div class="h-full bg-${successPct >= 80 ? 'green-500' : successPct >= 50 ? 'primary' : 'error'} rounded-full" style="width:${barW}%"></div></div>
      </div>
      <div class="grid grid-cols-2 gap-2 text-xs">
        <div><span class="text-on-surface-variant block text-[10px]">Avg Turns</span><span class="font-bold">${s.avg_turns || 0}/${s.max_turns || 0}</span></div>
        <div><span class="text-on-surface-variant block text-[10px]">Avg Duration</span><span class="font-bold">${formatDuration(s.avg_duration || 0, 'seconds')}</span></div>
        <div class="col-span-2"><span class="text-on-surface-variant text-[10px]">Limit hit: </span><span class="font-bold text-${limitPct > 20 ? 'error' : 'on-surface-variant'}">${limitPct}%</span></div>
      </div>
    </div>`;
  }).join('');
}

function renderKpiBarChart(data) {
  const ts = data.time_series || {};
  const compMap = {}; (ts.completions_by_day || []).forEach(r => compMap[r.day] = r.count);
  const blockMap = {}; (ts.blocks_by_day || []).forEach(r => blockMap[r.day] = r.count);
  const limitMap = {}; (ts.limit_hits_by_day || []).forEach(r => limitMap[r.day] = r.count);
  const days = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  const maxVal = Math.max(1, ...days.map(d => (compMap[d]||0) + (blockMap[d]||0) + (limitMap[d]||0)));
  const chartEl = document.getElementById('kpi-bar-chart');
  const labelsEl = document.getElementById('kpi-bar-labels');
  chartEl.innerHTML = days.map(d => {
    const c = compMap[d] || 0, b = blockMap[d] || 0, l = limitMap[d] || 0;
    const cH = Math.round(c / maxVal * 128), bH = Math.round(b / maxVal * 128), lH = Math.round(l / maxVal * 128);
    return `<div class="flex flex-col items-center gap-0.5 flex-1 min-w-[18px]" title="${d}: ${c} done, ${b} blocked, ${l} limit hits">
      <div class="w-full rounded-t bg-amber-500" style="height:${lH}px"></div>
      <div class="w-full bg-red-500" style="height:${bH}px"></div>
      <div class="w-full rounded-b bg-green-500" style="height:${cH}px"></div>
    </div>`;
  }).join('');
  labelsEl.innerHTML = days.map(d => `<div class="flex-1 min-w-[18px] text-center">${d.slice(8)}</div>`).join('');
}

function renderKpiLimitTable(data) {
  const hits = data.recent_limit_hits || [];
  const tableEl = document.getElementById('kpi-limit-table');
  if (!hits.length) {
    tableEl.innerHTML = '<p class="text-on-surface-variant text-sm">No limit-hit events recorded.</p>';
  } else {
    tableEl.innerHTML = `<table class="w-full text-xs">
      <thead><tr class="text-[10px] text-on-surface-variant uppercase">
        <th class="text-left py-2 px-2">Task</th><th class="text-left py-2 px-2">Phase</th>
        <th class="text-right py-2 px-2">Turns</th><th class="text-left py-2 px-2">Error</th>
        <th class="text-right py-2 px-2">When</th>
      </tr></thead>
      <tbody>${hits.map(h => `<tr class="border-t border-outline-variant/10">
        <td class="py-2 px-2 max-w-[200px] truncate" title="${escHtml(h.title)}">${escHtml(h.title || h.task_id)}</td>
        <td class="py-2 px-2 font-mono">${h.phase}</td>
        <td class="py-2 px-2 text-right font-bold">${h.turns_used}/${h.max_turns}</td>
        <td class="py-2 px-2 max-w-[200px] truncate text-on-surface-variant" title="${escHtml(h.error)}">${escHtml(h.error || '-')}</td>
        <td class="py-2 px-2 text-right text-on-surface-variant whitespace-nowrap">${h.at ? new Date(h.at).toLocaleString() : '-'}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  }
}


// ======================== TASK MODAL ========================
async function loadCategoryOptions(selected) {
  const sel = document.getElementById('task-category');
  const projects = await api('projects') || [];
  let html = `<option value="personal">${_t('area.personal')}</option>`;
  html += `<option value="empresa">${_t('area.empresa')}</option>`;
  if (projects.length) {
    html += `<option disabled>───────────</option>`;
    html += projects.map(p =>
      `<option value="project:${p.id}">${escHtml(p.name)}</option>`
    ).join('');
  }
  sel.innerHTML = html;
  if (selected) sel.value = selected;
}

async function openNewTaskModal() {
  document.getElementById('task-id').value = '';
  document.getElementById('task-modal-title').textContent = _t('task.new');
  document.getElementById('task-form').reset();
  document.getElementById('task-delete-btn').classList.add('hidden');
  const _rejectBtn = document.getElementById('task-reject-btn');
  if (_rejectBtn) _rejectBtn.classList.add('hidden');
  document.getElementById('task-status').closest('div').classList.add('hidden');
  document.getElementById('task-labels').innerHTML = '';
  S.editingTaskLabels = [];
  S.editingTaskAttachments = [];
  renderTaskAttachments();
  await loadCategoryOptions('personal');
  document.getElementById('task-modal').classList.remove('hidden');
}

async function openTaskById(id) {
  if (!id) return;
  const tasks = S.tasks.length ? S.tasks : await api('tasks?include_done=1');
  if (!tasks) return;
  const task = (Array.isArray(tasks) ? tasks : []).find(t => t.id === id);
  if (!task) { toast(_t('task.not_found')); return; }
  openEditTaskModal(task);
}

async function openEditTaskModal(t) {
  document.getElementById('task-id').value = t.id;
  document.getElementById('task-modal-title').textContent = _t('task.edit');
  document.getElementById('task-title').value = t.title || '';
  document.getElementById('task-desc').value = t.description || '';
  document.getElementById('task-status').closest('div').classList.remove('hidden');
  document.getElementById('task-status').value = t.status || 'inbox';
  document.getElementById('task-priority').value = t.priority || 'media';
  document.getElementById('task-due').value = t.due_at || '';
  document.getElementById('task-start').value = t.scheduled_for || '';
  document.getElementById('task-urgent').checked = !!t.urgent;
  document.getElementById('task-yume').checked = !!t.assigned_to_yume;
  document.getElementById('task-notes').value = t.notes || '';
  document.getElementById('task-delete-btn').classList.remove('hidden');
  const rejectBtn = document.getElementById('task-reject-btn');
  if (rejectBtn) {
    if (t.status === 'hecha') rejectBtn.classList.remove('hidden');
    else rejectBtn.classList.add('hidden');
  }

  // Load projects, labels, attachments, and pipeline in parallel
  const [labels, attachments, pipeline] = await Promise.all([
    api('tasks/' + t.id + '/labels'),
    api('tasks/' + t.id + '/attachments'),
    api('tasks/' + t.id + '/pipeline'),
  ]);
  await loadCategoryOptions(t.project_id ? `project:${t.project_id}` : (t.area || 'personal'));
  S.editingTaskLabels = labels || [];
  renderTaskLabels();
  S.editingTaskAttachments = attachments || [];
  renderTaskAttachments();

  // Render pipeline tracker
  renderTaskPipeline(pipeline);

  document.getElementById('task-modal').classList.remove('hidden');
}

// renderTaskPipeline → task-card-utils.js

function renderTaskLabels() {
  const box = document.getElementById('task-labels');
  box.innerHTML = S.editingTaskLabels.map(l =>
    `<span class="px-2 py-1 rounded-full bg-primary/10 text-primary text-[10px] font-bold flex items-center gap-1">${escHtml(l)}
      <button type="button" onclick="removeLabel('${escJsAttr(l)}')" class="hover:text-error"><span class="material-symbols-outlined text-xs">close</span></button>
    </span>`).join('');
}

function addLabel() {
  const input = document.getElementById('task-label-input');
  const val = input.value.trim();
  if (val && !S.editingTaskLabels.includes(val)) {
    S.editingTaskLabels.push(val);
    renderTaskLabels();
  }
  input.value = '';
}

function removeLabel(l) {
  S.editingTaskLabels = S.editingTaskLabels.filter(x => x !== l);
  renderTaskLabels();
}

async function syncTaskLabels(taskId, selectedLabels) {
  const currentLabels = await api('tasks/' + taskId + '/labels') || [];
  const errors = [];
  for (const l of selectedLabels) {
    if (!currentLabels.includes(l)) {
      try { await api('tasks/' + taskId + '/labels', { method: 'POST', body: JSON.stringify({ label: l }) }); }
      catch (e) { errors.push(l); }
    }
  }
  for (const l of currentLabels) {
    if (!selectedLabels.includes(l)) {
      try { await api('tasks/' + taskId + '/labels/' + encodeURIComponent(l), { method: 'DELETE' }); }
      catch (e) { errors.push(l); }
    }
  }
  return errors;
}

async function saveTask(e) {
  e.preventDefault();
  const id = document.getElementById('task-id').value;
  // Parse category selector: 'personal', 'empresa', or 'project:<id>'
  const catVal = document.getElementById('task-category').value || 'personal';
  let area = catVal, project_id = null;
  if (catVal.startsWith('project:')) {
    area = 'proyecto';
    project_id = catVal.slice('project:'.length);
  }
  const body = {
    title: document.getElementById('task-title').value,
    description: document.getElementById('task-desc').value,
    status: document.getElementById('task-status').value,
    priority: document.getElementById('task-priority').value,
    area,
    project_id,
    due_at: document.getElementById('task-due').value || null,
    scheduled_for: document.getElementById('task-start').value || null,
    urgent: document.getElementById('task-urgent').checked ? 1 : 0,
    assigned_to_yume: document.getElementById('task-yume').checked ? 1 : 0,
    notes: document.getElementById('task-notes').value,
  };

  // New tasks from UI enter as pendiente (To-Do) — workflows move them to doing
  if (!id) {
    body.status = 'pendiente';
  }

  try {
    let taskId;
    if (id) {
      const patchRes = await api('tasks/' + id, { method: 'PATCH', body: JSON.stringify(body) });
      if (!patchRes || patchRes.error) throw new Error(patchRes?.error || 'Failed to update task');
      taskId = id;
      toast(_t('task.updated'));
    } else {
      const res = await api('tasks', { method: 'POST', body: JSON.stringify(body) });
      if (!res || res.error) throw new Error(res?.error || 'Failed to create task');
      taskId = res.id;
      toast(_t('task.created'));
    }
    if (taskId) {
      const labelErrors = await syncTaskLabels(taskId, S.editingTaskLabels);
      if (labelErrors.length) toast(_t('task.labels_sync_warning') || 'Some labels failed to sync', 'warning');
    }
    closeTaskModal();
    loadViewData(S.view);
  } catch (err) {
    toast(_t('task.save_error') || 'Error saving task', 'error');
  }
}

async function deleteTask() {
  const id = document.getElementById('task-id').value;
  if (!id || !confirm(_t('task.delete_confirm') || 'Delete this task?')) return;
  try {
    const res = await api('tasks/' + id, { method: 'DELETE' });
    if (!res || res.error) throw new Error(res?.error || 'API error');
    toast(_t('task.deleted'));
    closeTaskModal();
    loadViewData(S.view);
  } catch (e) {
    toast(_t('task.delete_failed') || 'Error al eliminar tarea', 'error');
  }
}

async function rejectTask() {
  const id = document.getElementById('task-id').value;
  if (!id) return;
  const reason = prompt(_t('task.reject_reason') || 'Motivo del rechazo: ¿qué no se resolvió correctamente?');
  if (reason === null) return;
  try {
    const res = await api('tasks/' + id + '/reject', { method: 'POST', body: JSON.stringify({ reason: reason || 'Sin motivo especificado' }) });
    if (!res || res.error) throw new Error(res?.error || 'API error');
    toast(_t('task.rejected') || 'Tarea rechazada y devuelta a pendiente');
    closeTaskModal();
    loadViewData(S.view);
  } catch (e) {
    toast(_t('task.reject_failed') || 'Error al rechazar tarea', 'error');
  }
}

function closeTaskModal() { document.getElementById('task-modal').classList.add('hidden'); S.editingTaskLabels = []; S.editingTaskAttachments = []; }

// ======================== TASK ATTACHMENTS ========================
S.editingTaskAttachments = [];

function renderTaskAttachments() {
  const box = document.getElementById('task-attachments');
  if (!box) return;
  if (!S.editingTaskAttachments.length) {
    box.innerHTML = `<span class="text-xs text-on-surface-variant/50">${_t('task.no_attachments')}</span>`;
    return;
  }
  box.innerHTML = S.editingTaskAttachments.map(a => {
    const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(a.filename);
    const taskId = document.getElementById('task-id').value;
    const src = `/api/tasks/${taskId}/attachments/${encodeURIComponent(a.filename)}`;
    return `<div class="relative group">
      ${isImage
        ? `<a href="${src}" target="_blank"><img src="${src}" alt="${escHtml(a.filename)}" class="w-20 h-20 object-cover rounded-lg border border-outline/10"></a>`
        : `<a href="${src}" target="_blank" class="flex items-center gap-1 px-3 py-2 bg-surface-dim rounded-lg text-xs text-on-surface-variant hover:text-on-surface"><span class="material-symbols-outlined text-sm">description</span>${escHtml(a.filename)}</a>`
      }
      <button type="button" onclick="removeTaskAttachment('${escJsAttr(a.filename)}')"
        class="absolute -top-1 -right-1 w-5 h-5 bg-error text-on-error rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
        <span class="material-symbols-outlined text-xs">close</span>
      </button>
    </div>`;
  }).join('');
}

async function uploadTaskAttachments(fileList) {
  const taskId = document.getElementById('task-id').value;
  if (!taskId) {
    toast(_t('task.save_first'));
    document.getElementById('task-attachment-input').value = '';
    return;
  }
  for (const file of fileList) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`/api/tasks/${taskId}/attachments`, { method: 'POST', body: fd });
      const data = await r.json();
      if (data.ok && data.attachments) {
        S.editingTaskAttachments.push(...data.attachments);
      } else {
        toast(data.error || _t('task.upload_failed'));
      }
    } catch (e) {
      toast(_t('task.upload_error'));
    }
  }
  renderTaskAttachments();
  document.getElementById('task-attachment-input').value = '';
}

async function removeTaskAttachment(filename) {
  const taskId = document.getElementById('task-id').value;
  if (!taskId) return;
  try {
    const r = await fetch(`/api/tasks/${taskId}/attachments/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (!r.ok) {
      toast(_t('task.delete_attachment_failed') || 'Error removing attachment');
      return;
    }
  } catch (e) {
    toast(_t('task.delete_attachment_failed') || 'Error removing attachment');
    return;
  }
  S.editingTaskAttachments = S.editingTaskAttachments.filter(a => a.filename !== filename);
  renderTaskAttachments();
}

// ======================== SEARCH ========================
function openSearchOverlay() {
  document.getElementById('search-overlay').classList.remove('hidden');
  document.getElementById('search-input').focus();
  document.getElementById('topbar-search').blur();
}
function closeSearchOverlay() {
  clearTimeout(searchTimer);
  document.getElementById('search-overlay').classList.add('hidden');
  document.getElementById('search-results').innerHTML = '';
}

let searchTimer = null;
async function performSearch(q) {
  clearTimeout(searchTimer);
  if (!q || q.length < 2) { document.getElementById('search-results').innerHTML = ''; return; }
  searchTimer = setTimeout(async () => {
    const data = await api('search?q=' + encodeURIComponent(q));
    if (!data) return;
    const box = document.getElementById('search-results');
    let html = '';
    if (data.tasks?.length) {
      html += '<p class="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold mb-2">Tasks</p>';
      html += data.tasks.map(t => `<div class="p-3 rounded-lg bg-surface-container-high/50 hover:bg-surface-bright cursor-pointer transition-all" onclick="closeSearchOverlay();openTaskById('${escJsAttr(t.id)}')">
        <p class="text-sm font-medium">${escHtml(t.title)}</p>
        <p class="text-xs text-on-surface-variant">${statusLabel(t.status)} - ${escHtml(t.area||'no area')}</p>
      </div>`).join('');
    }
    if (data.projects?.length) {
      html += '<p class="text-[10px] text-on-surface-variant uppercase tracking-widest font-bold mb-2 mt-4">Projects</p>';
      html += data.projects.map(p => `<div class="p-3 rounded-lg bg-surface-container-high/50 hover:bg-surface-bright cursor-pointer transition-all" onclick="closeSearchOverlay();switchView('projects');setTimeout(()=>openProject('${encodeURIComponent(p.name)}'),300)">
        <p class="text-sm font-medium">${escHtml(p.name)}</p>
      </div>`).join('');
    }
    if (!html) html = `<p class="text-on-surface-variant text-sm">${_t('search.no_results')}</p>`;
    box.innerHTML = html;
  }, 300);
}

// ======================== TOAST ========================
function toast(msg, type = 'info') {
  const colors = { info: 'primary', success: 'tertiary', error: 'error' };
  const c = colors[type] || 'primary';
  const el = document.createElement('div');
  el.className = `toast-enter glass-card px-4 py-3 rounded-lg text-sm text-on-surface flex items-center gap-3 max-w-sm`;
  el.innerHTML = `<span class="material-symbols-outlined text-${c} text-sm">${type==='error'?'error':type==='success'?'check_circle':'info'}</span>${escHtml(msg)}`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => { el.style.animation = 'toastOut .3s ease forwards'; setTimeout(() => el.remove(), 300); }, 3000);
}

// ======================== UTILS ========================
function statusLabel(s) {
  return _t('status.' + s) || s;
}
function statusBadge(status) {
  const colors = { success: 'tertiary', failed: 'error', partial: 'warning', running: 'primary' };
  const icons = { success: 'check_circle', failed: 'cancel', partial: 'warning', running: 'play_circle' };
  const c = colors[status] || 'on-surface-variant';
  const icon = icons[status] || 'help';
  return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-' + c + '/10 text-' + c + ' text-[10px] font-bold">' +
    '<span class="material-symbols-outlined" style="font-size:12px">' + icon + '</span>' +
    escHtml(status) + '</span>';
}
function statusBadgeClass(s) {
  const map = {
    inbox:'bg-primary/10 text-primary', pendiente:'bg-primary/10 text-primary',
    en_progreso:'bg-tertiary/10 text-tertiary', bloqueada:'bg-error/10 text-error',
    revision:'bg-[#ac8aff]/10 text-[#ac8aff]', hecha:'bg-on-surface-variant/10 text-on-surface-variant', archivada:'bg-on-surface-variant/10 text-on-surface-variant'
  };
  return map[s] || 'bg-outline-variant/20 text-on-surface-variant';
}
function timeAgo(dt) {
  if (!dt) return '';
  const d = new Date(dt);
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  if (diff < 60) return _t('time.just_now');
  if (diff < 3600) return _t('time.minutes_ago', { n: Math.floor(diff / 60) });
  if (diff < 86400) return _t('time.hours_ago', { n: Math.floor(diff / 3600) });
  return _t('time.days_ago', { n: Math.floor(diff / 86400) });
}

// ======================== KEYBOARD SHORTCUTS ========================

document.addEventListener('keydown', e => {
  // Don't trigger when typing in inputs
  if (['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)) {
    if (e.key === 'Escape') { e.target.blur(); closeSearchOverlay(); closeTaskModal(); }
    return;
  }
  switch(e.key) {
    case '/': e.preventDefault(); openSearchOverlay(); break;
    case 'n': openNewTaskModal(); break;
    case 'd': switchView('dashboard'); break;
    case 'y': switchView('history'); break;
    case 't': case 'k': switchView('kanban'); break;
    case 'p': switchView('projects'); break;
    case 's': switchView('system'); break;
    case 'r': loadViewData(S.view); toast(_t('misc.refreshed')); break;
    case 'Escape': closeSearchOverlay(); closeTaskModal(); break;
  }
});

// ======================== POLLING ========================
let _pollInProgress = false;
function _shouldSkipPoll() {
  // Don't reload while user is editing forms — it wipes input values
  if (S.view === 'system' && (S.systemTab === 'config' || S.systemTab === 'styles')) return true;
  // Don't poll while any modal is open
  const modals = ['task-modal', 'note-editor-modal', 'routine-editor-modal', 'search-overlay'];
  for (const id of modals) {
    const el = document.getElementById(id);
    if (el && !el.classList.contains('hidden')) return true;
  }
  return false;
}
function startPolling() {
  if (S.pollTimer) clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    if (_pollInProgress || _shouldSkipPoll()) return;
    _pollInProgress = true;
    try {
      await loadViewData(S.view);
      if (S.pollFailCount > 0) {
        S.pollFailCount = 0;
        dismissDisconnectBanner();
      }
    } catch (err) {
      S.pollFailCount++;
      console.warn(`[polling] fail #${S.pollFailCount}:`, err);
      if (S.pollFailCount >= 3) showDisconnectBanner();
    } finally {
      _pollInProgress = false;
    }
  }, 15000);
}

function showDisconnectBanner() {
  if (document.getElementById('disconnect-banner')) return;
  const el = document.createElement('div');
  el.id = 'disconnect-banner';
  el.className = 'fixed top-0 left-0 right-0 z-50 bg-error text-on-surface text-center py-2 px-4 text-sm flex items-center justify-center gap-2';
  el.innerHTML = '<span class="material-symbols-outlined text-sm">cloud_off</span> Connection lost — retrying…';
  document.body.prepend(el);
}

function dismissDisconnectBanner() {
  const el = document.getElementById('disconnect-banner');
  if (el) el.remove();
}

function showRestartBanner() {
  if (document.getElementById('restart-banner')) return;
  const el = document.createElement('div');
  el.id = 'restart-banner';
  el.className = 'fixed top-0 left-0 right-0 z-50 bg-secondary text-on-secondary text-center py-3 px-4 text-sm flex items-center justify-center gap-3';
  el.innerHTML = '<span class="material-symbols-outlined text-sm">restart_alt</span>' +
    '<span>Configuración actualizada. Reinicia Niwa para aplicar los cambios.</span>' +
    '<button onclick="restartNiwa()" class="px-3 py-1 bg-white/20 hover:bg-white/30 rounded-lg text-xs font-bold transition-all">Reiniciar</button>' +
    '<button onclick="this.parentElement.remove()" class="p-1 hover:bg-white/20 rounded-lg transition-all"><span class="material-symbols-outlined text-sm">close</span></button>';
  document.body.prepend(el);
}

async function restartNiwa() {
  const banner = document.getElementById('restart-banner');
  if (banner) banner.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">refresh</span> Reiniciando...';
  const res = await api('system/restart', { method: 'POST', body: '{}' });
  if (res && res.ok) {
    toast('Niwa reiniciado', 'success');
    if (banner) banner.remove();
    setTimeout(() => location.reload(), 3000);
  } else {
    toast((res && res.error) || 'Error al reiniciar', 'error');
    if (banner) banner.innerHTML = '<span class="text-error">Error al reiniciar</span>';
  }
}

// ======================== STYLES ========================
const STYLE_COLORS = [
  { key: 'primary', label: 'Primary', light: '#3b6eb5', dark: '#85adff' },
  { key: 'secondary', label: 'Secondary', light: '#7c5cc7', dark: '#ac8aff' },
  { key: 'tertiary', label: 'Success', light: '#1a9a5c', dark: '#9bffce' },
  { key: 'error', label: 'Error', light: '#d94444', dark: '#ff716c' },
  { key: 'warning', label: 'Warning', light: '#f59e0b', dark: '#fbbf24' },
  { key: 'bg', label: 'Fondo', light: '#e8edf5', dark: '#060e20' },
  { key: 'surface', label: 'Surface', light: '#eef1f6', dark: '#0a1122' },
  { key: 'card', label: 'Tarjetas', light: '#ffffff', dark: '#0f1930' },
  { key: 'sidebar', label: 'Sidebar/Topbar', light: '#ffffff', dark: '#091328' },
  { key: 'on-surface', label: 'Texto', light: '#1a2234', dark: '#dee5ff' },
  { key: 'btn-primary', label: 'Botón principal', light: '#3b6eb5', dark: '#85adff' },
  { key: 'btn-text', label: 'Texto botón', light: '#ffffff', dark: '#001a40' },
];

function _hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return r+','+g+','+b;
}
function _rgbToHex(rgb) {
  const [r,g,b] = rgb.split(',').map(Number);
  return '#' + [r,g,b].map(x => x.toString(16).padStart(2,'0')).join('');
}

const STYLE_PRESETS = [
  { name: 'Default', light: {}, dark: {} },
  { name: 'Ocean',
    light: { primary:'#0077b6', secondary:'#00b4d8', tertiary:'#06d6a0', bg:'#edf6f9', surface:'#e0f2f7', card:'#ffffff', sidebar:'#f0f9fc' },
    dark:  { primary:'#48cae4', secondary:'#00b4d8', tertiary:'#06d6a0', bg:'#001219', surface:'#001824', card:'#002233', sidebar:'#001a2c', 'on-surface':'#caf0f8' } },
  { name: 'Forest',
    light: { primary:'#2d6a4f', secondary:'#74c69d', tertiary:'#40916c', bg:'#f0f7f4', surface:'#e8f5ee', card:'#ffffff', sidebar:'#eef7f2' },
    dark:  { primary:'#74c69d', secondary:'#95d5b2', tertiary:'#52b788', bg:'#0a1f14', surface:'#0d2818', card:'#112e1e', sidebar:'#0a2416', 'on-surface':'#d8f3dc' } },
  { name: 'Sunset',
    light: { primary:'#e76f51', secondary:'#f4a261', tertiary:'#2a9d8f', bg:'#fdf5ef', surface:'#fceee4', card:'#ffffff', sidebar:'#fdf5ef' },
    dark:  { primary:'#f4845f', secondary:'#f4a261', tertiary:'#2a9d8f', bg:'#1a0f09', surface:'#231510', card:'#2e1a12', sidebar:'#211008', 'on-surface':'#fde8d8' } },
  { name: 'Monochrome',
    light: { primary:'#374151', secondary:'#6b7280', tertiary:'#4b5563', bg:'#f3f4f6', surface:'#e5e7eb', card:'#ffffff', sidebar:'#f9fafb' },
    dark:  { primary:'#9ca3af', secondary:'#d1d5db', tertiary:'#6b7280', bg:'#0a0a0a', surface:'#141414', card:'#1e1e1e', sidebar:'#111111', 'on-surface':'#e5e7eb' } },
  { name: 'Lavender',
    light: { primary:'#7c3aed', secondary:'#a78bfa', tertiary:'#06b6d4', bg:'#f5f3ff', surface:'#ede9fe', card:'#ffffff', sidebar:'#f5f3ff' },
    dark:  { primary:'#a78bfa', secondary:'#c4b5fd', tertiary:'#22d3ee', bg:'#0f0720', surface:'#150a2e', card:'#1e0f3d', sidebar:'#120828', 'on-surface':'#e0d6ff' } },
  { name: 'Rose',
    light: { primary:'#e11d48', secondary:'#f472b6', tertiary:'#10b981', bg:'#fff1f2', surface:'#ffe4e6', card:'#ffffff', sidebar:'#fff5f6' },
    dark:  { primary:'#fb7185', secondary:'#f9a8d4', tertiary:'#34d399', bg:'#1a0a10', surface:'#2a0f18', card:'#351420', sidebar:'#220a12', 'on-surface':'#ffe4e6' } },
];

function _getStylesData() {
  return JSON.parse(localStorage.getItem('niwa_styles') || '{}');
}

function loadStyles() {
  const saved = _getStylesData();
  const isDark = document.documentElement.classList.contains('dark');
  const mode = isDark ? 'dark' : 'light';

  // Mode indicator
  const modeLabel = document.getElementById('style-mode-label');
  if (modeLabel) modeLabel.innerHTML = isDark
    ? '<span class="material-symbols-outlined text-sm">dark_mode</span> Editando modo oscuro'
    : '<span class="material-symbols-outlined text-sm">light_mode</span> Editando modo claro';
  const switchLabel = document.getElementById('style-mode-switch-label');
  if (switchLabel) switchLabel.textContent = isDark ? 'claro' : 'oscuro';

  // Render color pickers
  const colorsEl = document.getElementById('style-colors');
  if (colorsEl) {
    colorsEl.innerHTML = STYLE_COLORS.map(c => {
      const savedVal = saved[mode + '.' + c.key];
      const defaultVal = c[mode];
      const currentVal = savedVal || defaultVal;
      return `<div>
        <label class="text-[10px] text-on-surface-variant uppercase tracking-widest block mb-1">${c.label}</label>
        <div class="flex items-center gap-2">
          <input type="color" data-style-key="${c.key}" value="${currentVal}" onchange="onStyleColorChange(this)" class="w-8 h-8 rounded-lg border border-outline-variant/30 cursor-pointer" style="padding:0">
          <input type="text" value="${currentVal}" oninput="this.previousElementSibling.value=this.value;onStyleColorChange(this.previousElementSibling)" class="flex-1 bg-[var(--c-input-bg)] border border-outline-variant/30 rounded-lg py-1 px-2 text-xs text-on-surface font-mono">
        </div>
      </div>`;
    }).join('');
  }

  // Restore selects
  const fontBody = document.getElementById('style-font-body');
  const fontHead = document.getElementById('style-font-headline');
  const fontSize = document.getElementById('style-font-size');
  const radius = document.getElementById('style-radius');
  if (fontBody && saved.fontBody) fontBody.value = saved.fontBody;
  if (fontHead && saved.fontHeadline) fontHead.value = saved.fontHeadline;
  if (fontSize && saved.fontSize) fontSize.value = saved.fontSize;
  if (radius && saved.radius) radius.value = saved.radius;

  // Render presets
  const presetsEl = document.getElementById('style-presets');
  if (presetsEl) {
    let presetsHtml = '';
    // Custom preset if saved
    const customPreset = saved._customPreset;
    if (customPreset) {
      const cColors = customPreset[mode] || {};
      const cSwatches = Object.values(cColors).slice(0, 4);
      const cPreview = cSwatches.map(c => `<span class="w-4 h-4 rounded-full border border-outline-variant/20" style="background:${c}"></span>`).join('');
      presetsHtml += `<div class="flex items-center gap-2">
        <button onclick="applyPreset('Custom')" class="flex-1 flex items-center justify-between p-3 rounded-lg bg-secondary/10 hover:bg-secondary/20 transition-all text-left border border-secondary/30">
          <span class="text-sm font-bold text-secondary">Custom</span>
          <div class="flex gap-1">${cPreview}</div>
        </button>
        <button onclick="deleteCustomPreset()" class="p-2 hover:bg-error/10 rounded-lg text-on-surface-variant" title="Eliminar">
          <span class="material-symbols-outlined text-sm">delete</span>
        </button>
      </div>`;
    }
    presetsHtml += STYLE_PRESETS.map(p => {
      const pColors = p[mode] || {};
      const swatches = Object.values(pColors).slice(0, 4);
      const preview = swatches.length
        ? swatches.map(c => `<span class="w-4 h-4 rounded-full border border-outline-variant/20" style="background:${c}"></span>`).join('')
        : '<span class="text-[10px] text-on-surface-variant">default</span>';
      return `<button onclick="applyPreset('${escJsAttr(p.name)}')" class="w-full flex items-center justify-between p-3 rounded-lg bg-surface-dim/50 hover:bg-surface-bright transition-all text-left">
        <span class="text-sm font-medium">${escHtml(p.name)}</span>
        <div class="flex gap-1">${preview}</div>
      </button>`;
    }).join('');
    presetsEl.innerHTML = presetsHtml;
  }
}

// Keys that use rgb triplet format (r,g,b) instead of hex
const _RGB_KEYS = { card: '--c-card', sidebar: '--c-sidebar' };

// All style overrides go through a single <style> element for maximum specificity
let _styleOverrideState = {};

function _applyColor(key, val) {
  _styleOverrideState[key] = val;
  _flushStyleOverrides();
}

function _flushStyleOverrides() {
  let sheet = document.getElementById('niwa-style-override');
  if (!sheet) { sheet = document.createElement('style'); sheet.id = 'niwa-style-override'; document.head.appendChild(sheet); }

  const s = _styleOverrideState;
  let vars = '';
  for (const [key, val] of Object.entries(s)) {
    if (key in _RGB_KEYS) {
      const rgb = _hexToRgb(val);
      vars += _RGB_KEYS[key] + ':' + rgb + '!important;';
      if (key === 'sidebar') vars += '--c-topbar:' + rgb + '!important;';
    } else if (key === 'bg') { vars += '--c-bg:' + val + '!important;';
    } else if (key === 'surface') { vars += '--c-surface:' + val + '!important;';
    } else if (key === 'on-surface') { vars += '--c-on-surface:' + val + '!important;--c-on-bg:' + val + '!important;';
    } else if (key === 'btn-primary') { vars += '--c-primary:' + val + '!important;--c-tint:' + val + '!important;';
    } else if (key === 'btn-text') { vars += '--c-on-primary:' + val + '!important;';
    } else { vars += '--c-' + key + ':' + val + '!important;'; }
  }
  sheet.textContent = vars ? 'html,html.dark{' + vars + '}' : '';
}

function onStyleColorChange(input) {
  const key = input.dataset.styleKey;
  const val = input.value;
  const textInput = input.parentElement.querySelector('input[type="text"]');
  if (textInput && textInput !== input) textInput.value = val;
  _applyColor(key, val);
}

function applyStyleChange() {
  const fontBody = document.getElementById('style-font-body');
  const fontHead = document.getElementById('style-font-headline');
  const fontSize = document.getElementById('style-font-size');
  const radius = document.getElementById('style-radius');

  let sheet = document.getElementById('niwa-typo-override');
  if (!sheet) { sheet = document.createElement('style'); sheet.id = 'niwa-typo-override'; document.head.appendChild(sheet); }

  let css = '';
  if (fontBody && fontBody.value !== 'Inter') {
    css += `body,.font-body{font-family:${fontBody.value},system-ui,sans-serif!important}`;
  }
  if (fontHead && fontHead.value !== 'DM Serif Display') {
    css += `.font-headline{font-family:${fontHead.value},system-ui,serif!important}`;
  }
  if (fontSize && fontSize.value !== '13px') {
    css += `body{font-size:${fontSize.value}!important}`;
    // Scale all relative text sizes
    const scale = parseFloat(fontSize.value) / 13;
    css += `.text-xs{font-size:${(12*scale).toFixed(1)}px!important}`;
    css += `.text-sm{font-size:${(14*scale).toFixed(1)}px!important}`;
    css += `.text-base{font-size:${(16*scale).toFixed(1)}px!important}`;
    css += `.text-lg{font-size:${(18*scale).toFixed(1)}px!important}`;
    css += `.text-xl{font-size:${(20*scale).toFixed(1)}px!important}`;
    css += `.text-2xl{font-size:${(24*scale).toFixed(1)}px!important}`;
    css += `.text-\\[10px\\]{font-size:${(10*scale).toFixed(1)}px!important}`;
    css += `.text-\\[11px\\]{font-size:${(11*scale).toFixed(1)}px!important}`;
    css += `.text-\\[13px\\]{font-size:${(13*scale).toFixed(1)}px!important}`;
  }
  sheet.textContent = css;

  if (radius) _applyRadius(radius.value);
}

function _applyRadius(r) {
  let sheet = document.getElementById('niwa-radius-override');
  if (!sheet) {
    sheet = document.createElement('style');
    sheet.id = 'niwa-radius-override';
    document.head.appendChild(sheet);
  }
  if (!r || r === '8px') { sheet.textContent = ''; return; }
  // Scale radius classes proportionally
  const base = parseInt(r);
  sheet.textContent = `.rounded-2xl{border-radius:${Math.round(base*1.5)}px!important}`
    + `.rounded-xl{border-radius:${base}px!important}`
    + `.rounded-lg{border-radius:${Math.round(base*0.75)}px!important}`
    + `.rounded-full{border-radius:9999px!important}`
    + `input,select,textarea{border-radius:${Math.round(base*0.75)}px!important}`
    + `button{border-radius:${Math.round(base*0.75)}px!important}`;
}

function saveStyles() {
  const isDark = document.documentElement.classList.contains('dark');
  const mode = isDark ? 'dark' : 'light';
  const saved = _getStylesData();

  // Save colors for current mode
  document.querySelectorAll('[data-style-key]').forEach(input => {
    saved[mode + '.' + input.dataset.styleKey] = input.value;
  });

  // Save shared settings
  const fontBody = document.getElementById('style-font-body');
  const fontHead = document.getElementById('style-font-headline');
  const fontSize = document.getElementById('style-font-size');
  const radius = document.getElementById('style-radius');
  if (fontBody) saved.fontBody = fontBody.value;
  if (fontHead) saved.fontHeadline = fontHead.value;
  if (fontSize) saved.fontSize = fontSize.value;
  if (radius) saved.radius = radius.value;

  localStorage.setItem('niwa_styles', JSON.stringify(saved));
  toast('Estilos guardados (' + (isDark ? 'oscuro' : 'claro') + ')', 'success');
}

function saveAsCustomPreset() {
  // First save current picker values for the active mode
  saveStyles();
  // Then build the preset from saved data (includes both modes if previously saved)
  const saved = _getStylesData();
  const isDark = document.documentElement.classList.contains('dark');
  const activeMode = isDark ? 'dark' : 'light';
  const otherMode = isDark ? 'light' : 'dark';
  const custom = { light: {}, dark: {} };
  // Active mode: read from pickers (freshest)
  document.querySelectorAll('[data-style-key]').forEach(input => {
    custom[activeMode][input.dataset.styleKey] = input.value;
  });
  // Other mode: read from saved (if exists), else defaults
  STYLE_COLORS.forEach(c => {
    custom[otherMode][c.key] = saved[otherMode + '.' + c.key] || c[otherMode];
  });
  saved._customPreset = custom;
  localStorage.setItem('niwa_styles', JSON.stringify(saved));
  toast('Preset Custom guardado con los colores actuales', 'success');
  loadStyles();
}

function deleteCustomPreset() {
  const saved = _getStylesData();
  delete saved._customPreset;
  localStorage.setItem('niwa_styles', JSON.stringify(saved));
  toast('Preset Custom eliminado');
  loadStyles();
}

function resetStyles() {
  localStorage.removeItem('niwa_styles');
  document.documentElement.style.cssText = '';
  document.body.style.fontSize = '';
  document.body.style.fontFamily = '';
  toast('Estilos restaurados', 'success');
  loadStyles();
}

function applyPreset(name) {
  let preset;
  if (name === 'Custom') {
    const saved = _getStylesData();
    preset = saved._customPreset;
    if (!preset) return;
  } else {
    preset = STYLE_PRESETS.find(p => p.name === name);
  }
  if (!preset) return;
  const isDark = document.documentElement.classList.contains('dark');
  const saved = _getStylesData();

  // Save BOTH modes from preset
  ['light', 'dark'].forEach(mode => {
    const pColors = preset[mode] || {};
    STYLE_COLORS.forEach(c => {
      saved[mode + '.' + c.key] = pColors[c.key] || c[mode];
    });
  });

  localStorage.setItem('niwa_styles', JSON.stringify(saved));
  _applySavedStyles();
  loadStyles();
  toast('Preset: ' + name, 'success');
}

// Apply saved styles — called on load and on theme toggle
function _applySavedStyles() {
  const saved = _getStylesData();
  if (!Object.keys(saved).length) return;
  const isDark = document.documentElement.classList.contains('dark');
  const mode = isDark ? 'dark' : 'light';
  const root = document.documentElement.style;

  // Reset all color overrides and rebuild from saved
  _styleOverrideState = {};
  STYLE_COLORS.forEach(c => {
    const val = saved[mode + '.' + c.key];
    if (val) _styleOverrideState[c.key] = val;
  });
  _flushStyleOverrides();

  // Apply fonts/radius via style sheet (works even before DOM selects exist)
  let typoCss = '';
  if (saved.fontBody && saved.fontBody !== 'Inter') typoCss += `body,.font-body{font-family:${saved.fontBody},system-ui,sans-serif!important}`;
  if (saved.fontHeadline && saved.fontHeadline !== 'DM Serif Display') typoCss += `.font-headline{font-family:${saved.fontHeadline},system-ui,serif!important}`;
  if (saved.fontSize && saved.fontSize !== '13px') {
    const scale = parseFloat(saved.fontSize) / 13;
    typoCss += `body{font-size:${saved.fontSize}!important}`;
    typoCss += `.text-xs{font-size:${(12*scale).toFixed(1)}px!important}`;
    typoCss += `.text-sm{font-size:${(14*scale).toFixed(1)}px!important}`;
    typoCss += `.text-\\[10px\\]{font-size:${(10*scale).toFixed(1)}px!important}`;
    typoCss += `.text-\\[11px\\]{font-size:${(11*scale).toFixed(1)}px!important}`;
    typoCss += `.text-\\[13px\\]{font-size:${(13*scale).toFixed(1)}px!important}`;
  }
  if (typoCss) {
    let sheet = document.getElementById('niwa-typo-override');
    if (!sheet) { sheet = document.createElement('style'); sheet.id = 'niwa-typo-override'; document.head.appendChild(sheet); }
    sheet.textContent = typoCss;
  }
  if (saved.radius) _applyRadius(saved.radius);
}
// Defer to after DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _applySavedStyles);
} else {
  _applySavedStyles();
}

// ======================== NOTES ========================
let _notesCache = [];

async function loadNotes() {
  const projectFilter = document.getElementById('notes-project-filter');
  const search = (document.getElementById('notes-search') || {}).value || '';
  const projectId = projectFilter ? projectFilter.value : '';

  // Populate project filter
  if (projectFilter && projectFilter.options.length <= 1 && S.projects.length) {
    S.projects.forEach(function(p) {
      if (!projectFilter.querySelector('option[value="' + p.id + '"]')) {
        var opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;
        projectFilter.appendChild(opt);
      }
    });
  }
  // Ensure projects loaded for filter
  if (!S.projects.length) {
    var projs = await api('dashboard');
    if (projs && projs.projects) S.projects = projs.projects;
    if (projectFilter && S.projects.length) {
      S.projects.forEach(function(p) {
        if (!projectFilter.querySelector('option[value="' + p.id + '"]')) {
          var opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.name;
          projectFilter.appendChild(opt);
        }
      });
    }
  }

  var params = [];
  if (projectId) params.push('project_id=' + encodeURIComponent(projectId));
  if (search.trim()) params.push('search=' + encodeURIComponent(search.trim()));
  var qs = params.length ? '?' + params.join('&') : '';

  var notes = await api('notes' + qs);
  if (!notes) notes = [];
  _notesCache = notes;
  renderNotesList(notes);
}

function renderNotesList(notes) {
  var container = document.getElementById('notes-list');
  if (!container) return;
  if (!notes.length) {
    container.innerHTML = '<div class="col-span-full text-center py-16 text-on-surface-variant">' +
      '<span class="material-symbols-outlined text-5xl mb-4 block opacity-40">description</span>' +
      '<p class="text-sm">' + _t('notes.empty') + '</p></div>';
    return;
  }
  container.innerHTML = notes.map(function(n) {
    var tags = [];
    try { tags = typeof n.tags === 'string' ? JSON.parse(n.tags) : (n.tags || []); } catch(e) {}
    var preview = (n.content || '').substring(0, 150).replace(/</g, '&lt;');
    if ((n.content || '').length > 150) preview += '…';
    var updated = n.updated_at ? new Date(n.updated_at).toLocaleDateString() : '';
    var r = '<div class="bg-[rgb(var(--c-card))] rounded-2xl shadow-sm p-5 hover:shadow-md transition-all cursor-pointer group" onclick="openNoteEditor(\'' + escJsAttr(n.id) + '\')">';
    r += '<div class="flex justify-between items-start mb-2">';
    r += '<h4 class="font-bold text-sm text-on-surface truncate flex-1">' + escHtml(n.title || 'Sin título') + '</h4>';
    r += '<button onclick="event.stopPropagation();deleteNoteConfirm(\'' + escJsAttr(n.id) + '\')" class="opacity-0 group-hover:opacity-100 p-1 hover:bg-error-container rounded-lg transition-all" title="Eliminar">';
    r += '<span class="material-symbols-outlined text-error text-sm">delete</span></button></div>';
    if (n.project_name) {
      r += '<div class="flex items-center gap-1 mb-2"><span class="material-symbols-outlined text-primary text-xs">folder</span>';
      r += '<span class="text-[10px] text-primary font-medium">' + escHtml(n.project_name) + '</span></div>';
    }
    if (preview) {
      r += '<p class="text-xs text-on-surface-variant leading-relaxed mb-3">' + preview + '</p>';
    }
    r += '<div class="flex items-center justify-between">';
    if (tags.length) {
      r += '<div class="flex flex-wrap gap-1">';
      tags.slice(0, 3).forEach(function(t) {
        r += '<span class="text-[9px] px-2 py-0.5 bg-secondary-container text-on-secondary-container rounded-full">' + escHtml(t) + '</span>';
      });
      if (tags.length > 3) r += '<span class="text-[9px] text-on-surface-variant">+' + (tags.length - 3) + '</span>';
      r += '</div>';
    } else {
      r += '<div></div>';
    }
    r += '<span class="text-[10px] text-on-surface-variant">' + updated + '</span>';
    r += '</div></div>';
    return r;
  }).join('');
}

var _notesFilterTimer = null;
function filterNotes() {
  clearTimeout(_notesFilterTimer);
  _notesFilterTimer = setTimeout(function() { loadNotes(); }, 300);
}

function openNoteEditor(noteId) {
  var modal = document.getElementById('note-editor-modal');
  if (!modal) return;
  document.getElementById('note-editor-id').value = '';
  document.getElementById('note-editor-name').value = '';
  document.getElementById('note-editor-content').value = '';
  document.getElementById('note-editor-tags').value = '';
  document.getElementById('note-editor-title').textContent = _t('notes.new_note');

  // Populate project dropdown
  var projSelect = document.getElementById('note-editor-project');
  projSelect.innerHTML = '<option value="">' + _t('notes.no_project') + '</option>';
  S.projects.forEach(function(p) {
    var opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    projSelect.appendChild(opt);
  });

  if (noteId) {
    var note = _notesCache.find(function(n) { return n.id === noteId; });
    if (note) {
      document.getElementById('note-editor-id').value = note.id;
      document.getElementById('note-editor-name').value = note.title || '';
      document.getElementById('note-editor-content').value = note.content || '';
      document.getElementById('note-editor-title').textContent = _t('notes.edit_note');
      if (note.project_id) projSelect.value = note.project_id;
      var tags = [];
      try { tags = typeof note.tags === 'string' ? JSON.parse(note.tags) : (note.tags || []); } catch(e) {}
      document.getElementById('note-editor-tags').value = tags.join(', ');
    }
  }
  modal.classList.remove('hidden');
}

function closeNoteEditor() {
  var modal = document.getElementById('note-editor-modal');
  if (modal) modal.classList.add('hidden');
}

async function saveNote() {
  var id = document.getElementById('note-editor-id').value;
  var title = document.getElementById('note-editor-name').value.trim();
  var content = document.getElementById('note-editor-content').value;
  var projectId = document.getElementById('note-editor-project').value || null;
  var tagsRaw = document.getElementById('note-editor-tags').value;
  var tags = tagsRaw ? tagsRaw.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];

  if (!title) { toast(_t('notes.title_required'), 'error'); return; }

  var payload = { title: title, content: content, project_id: projectId, tags: tags };

  if (id) {
    await api('notes/' + id, { method: 'PATCH', body: JSON.stringify(payload) });
    toast(_t('notes.updated'));
  } else {
    await api('notes', { method: 'POST', body: JSON.stringify(payload) });
    toast(_t('notes.created'));
  }
  closeNoteEditor();
  await loadNotes();
}

async function deleteNoteConfirm(noteId) {
  if (!confirm(_t('notes.delete_confirm'))) return;
  await api('notes/' + noteId, { method: 'DELETE' });
  toast(_t('notes.deleted'));
  await loadNotes();
}

// ======================== ROUTINES ========================
async function loadRoutines() {
  const data = await api('routines');
  const box = document.getElementById('routines-list');
  if (!data || !data.length) { box.innerHTML = '<p class="text-on-surface-variant">No hay rutinas configuradas.</p>'; return; }
  box.innerHTML = data.map(r => {
    const statusBadge = r.last_status === 'ok' ? '<span class="text-tertiary text-xs">OK</span>' :
                        r.last_status === 'error' ? '<span class="text-error text-xs">Error</span>' :
                        '<span class="text-on-surface-variant text-xs">\u2014</span>';
    const lastRun = r.last_run_at ? new Date(r.last_run_at).toLocaleString() : 'Nunca';
    return `<div class="bg-[rgb(var(--c-card))] rounded-xl p-4 flex items-center justify-between gap-4">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-medium text-sm text-on-surface truncate">${escHtml(r.name)}</span>
          ${statusBadge}
        </div>
        <div class="flex items-center gap-3 mt-1 text-[10px] text-on-surface-variant">
          <span class="font-mono">${escHtml(r.schedule)}</span>
          <span>${escHtml(r.action)}</span>
          <span>Ultima: ${lastRun}</span>
          ${r.last_error ? '<span class="text-error truncate max-w-[200px]" title="'+escHtml(r.last_error)+'">'+escHtml(r.last_error.substring(0,60))+'</span>' : ''}
        </div>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <button onclick="runRoutine('${r.id}')" class="p-1.5 hover:bg-surface-bright rounded-lg text-on-surface-variant" title="Ejecutar ahora">
          <span class="material-symbols-outlined text-sm">play_arrow</span>
        </button>
        <button onclick="openRoutineEditor('${r.id}')" class="p-1.5 hover:bg-surface-bright rounded-lg text-on-surface-variant" title="Editar">
          <span class="material-symbols-outlined text-sm">edit</span>
        </button>
        <button onclick="deleteRoutine('${r.id}')" class="p-1.5 hover:bg-error/10 rounded-lg text-on-surface-variant" title="Eliminar">
          <span class="material-symbols-outlined text-sm">delete</span>
        </button>
        <button onclick="toggleRoutine('${r.id}')" class="relative w-10 h-5 rounded-full transition-colors ${r.enabled ? 'bg-tertiary' : 'bg-outline-variant'}" title="${r.enabled ? 'Desactivar' : 'Activar'}">
          <span class="absolute top-0.5 ${r.enabled ? 'left-5' : 'left-0.5'} w-4 h-4 bg-white rounded-full shadow transition-all"></span>
        </button>
      </div>
    </div>`;
  }).join('');
}

async function toggleRoutine(id) {
  await api('routines/toggle', { method: 'POST', body: JSON.stringify({ id }) });
  loadRoutines();
}

async function runRoutine(id) {
  const res = await api('routines/run', { method: 'POST', body: JSON.stringify({ id }) });
  if (res && res.ok) toast('Rutina ejecutada');
  setTimeout(loadRoutines, 2000);
}

function openRoutineEditor(id) {
  const modal = document.getElementById('routine-editor-modal');
  modal.classList.remove('hidden');
  document.getElementById('routine-editor-id').value = '';
  document.getElementById('routine-editor-name').value = '';
  document.getElementById('routine-editor-desc').value = '';
  document.getElementById('routine-editor-schedule').value = '';
  document.getElementById('routine-editor-tz').value = 'UTC';
  document.getElementById('routine-editor-action').value = 'script';
  document.getElementById('routine-editor-command').value = '';
  document.getElementById('routine-editor-task-title').value = '';
  document.getElementById('routine-editor-webhook-url').value = '';
  document.getElementById('routine-editor-notify').value = 'none';
  toggleRoutineActionFields();
  if (id) {
    api('routines/' + id).then(r => {
      if (!r) return;
      document.getElementById('routine-editor-id').value = r.id;
      document.getElementById('routine-editor-name').value = r.name || '';
      document.getElementById('routine-editor-desc').value = r.description || '';
      document.getElementById('routine-editor-schedule').value = r.schedule || '';
      document.getElementById('routine-editor-tz').value = r.tz || 'UTC';
      document.getElementById('routine-editor-action').value = r.action || 'script';
      const cfg = typeof r.action_config === 'string' ? JSON.parse(r.action_config || '{}') : (r.action_config || {});
      document.getElementById('routine-editor-command').value = cfg.command || '';
      document.getElementById('routine-editor-task-title').value = cfg.title || '';
      document.getElementById('routine-editor-webhook-url').value = cfg.url || '';
      document.getElementById('routine-editor-notify').value = r.notify_channel || 'none';
      document.getElementById('routine-editor-title').textContent = 'Editar rutina';
      toggleRoutineActionFields();
    });
  } else {
    document.getElementById('routine-editor-title').textContent = 'Nueva rutina';
  }
}

function closeRoutineEditor() {
  document.getElementById('routine-editor-modal').classList.add('hidden');
}

function toggleRoutineActionFields() {
  const action = document.getElementById('routine-editor-action').value;
  document.getElementById('routine-action-script').classList.toggle('hidden', action !== 'script');
  document.getElementById('routine-action-task').classList.toggle('hidden', action !== 'create_task');
  document.getElementById('routine-action-webhook').classList.toggle('hidden', action !== 'webhook');
}

async function saveRoutine() {
  const id = document.getElementById('routine-editor-id').value;
  const action = document.getElementById('routine-editor-action').value;
  let action_config = {};
  if (action === 'script') action_config = { command: document.getElementById('routine-editor-command').value };
  else if (action === 'create_task') action_config = { title: document.getElementById('routine-editor-task-title').value, area: 'sistema', priority: 'media' };
  else if (action === 'webhook') action_config = { url: document.getElementById('routine-editor-webhook-url').value };
  const payload = {
    name: document.getElementById('routine-editor-name').value,
    description: document.getElementById('routine-editor-desc').value,
    schedule: document.getElementById('routine-editor-schedule').value,
    tz: document.getElementById('routine-editor-tz').value,
    action,
    action_config,
    notify_channel: document.getElementById('routine-editor-notify').value,
  };
  if (id) {
    await api('routines/' + id, { method: 'PATCH', body: JSON.stringify(payload) });
  } else {
    await api('routines', { method: 'POST', body: JSON.stringify(payload) });
  }
  closeRoutineEditor();
  loadRoutines();
  toast(id ? 'Rutina actualizada' : 'Rutina creada');
}

async function deleteRoutine(id) {
  if (!confirm('¿Eliminar esta rutina?')) return;
  await api('routines/' + id, { method: 'DELETE' });
  loadRoutines();
  toast('Rutina eliminada');
}

// ======================== MI DIA ========================
async function loadMyDay() {
  const data = await api('my-day');
  const dateEl = document.getElementById('dash-myday-date');
  const summaryEl = document.getElementById('dash-myday-summary');
  const tasksEl = document.getElementById('dash-myday-tasks');
  const emptyEl = document.getElementById('dash-myday-empty');
  if (!data) return;
  if (dateEl) dateEl.textContent = data.day || '';
  if (data.summary && summaryEl) {
    summaryEl.textContent = data.summary;
    summaryEl.classList.remove('hidden');
  }
  if (!data.tasks || !data.tasks.length) {
    if (tasksEl) tasksEl.innerHTML = '';
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');
  if (tasksEl) tasksEl.innerHTML = data.tasks.map(t => `
    <div class="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-bright/50 cursor-pointer" onclick="openTaskById('${escJsAttr(t.id)}')">
      <span class="w-2 h-2 rounded-full shrink-0" style="background:var(--c-${t.status === 'hecha' ? 'tertiary' : t.status === 'en_progreso' ? 'primary' : 'outline'})"></span>
      <span class="text-xs text-on-surface truncate flex-1">${escHtml(t.title)}</span>
      <span class="text-[10px] text-on-surface-variant shrink-0">${t.priority}</span>
    </div>
  `).join('');
}

// ======================== INIT ========================
(async function init() {
  await loadDashboard();
  startPolling();
})().catch(err => {
  console.error('Init failed:', err);
  toast(_t('error.loading_dashboard'), 'error');
});