// ── Pipeline / Bottleneck Chart ─────────────────────────────────────
const PIPELINE_COLORS = {
  pendiente:   { bg: 'var(--c-warning)',    label: 'warning' },
  en_progreso: { bg: 'var(--c-primary)',    label: 'primary' },
  revision:    { bg: 'var(--c-secondary)',  label: 'secondary' },
  hecha:       { bg: 'var(--c-tertiary)',   label: 'tertiary' },
};

function renderPipelineChart(data) {
  // Summary
  const summary = document.getElementById('pipeline-summary');
  if (summary) {
    const bn = data.bottleneck;
    const bnLabel = bn ? (PIPELINE_COLORS[bn] ? _t('pipeline.stage_' + bn) : bn) : '';
    summary.textContent = data.task_count > 0
      ? _t('pipeline.summary', { n: data.task_count, days: data.days, bottleneck: bnLabel })
      : _t('pipeline.no_tasks');
  }

  // KPIs
  const kpis = document.getElementById('pipeline-kpis');
  if (kpis) {
    const items = [
      { label: _t('pipeline.total_time'),     value: formatDuration(data.avg_total_min),     icon: 'schedule',    color: 'on-surface' },
      { label: _t('pipeline.queue_time'),      value: formatDuration(data.avg_queue_min),     icon: 'hourglass_top', color: 'warning' },
      { label: _t('pipeline.execution_time'),  value: formatDuration(data.avg_execution_min), icon: 'play_circle', color: 'primary' },
      { label: _t('pipeline.review_time'),     value: formatDuration(data.avg_review_min),    icon: 'rate_review', color: 'secondary' },
    ];
    kpis.innerHTML = items.map(k => `
      <div class="bg-surface-dim/50 rounded-lg p-3">
        <div class="flex items-center gap-1.5 mb-1">
          <span class="material-symbols-outlined text-${k.color} text-sm">${k.icon}</span>
          <span class="text-[10px] text-on-surface-variant uppercase tracking-wider">${k.label}</span>
        </div>
        <div class="text-lg font-headline font-bold text-on-surface">${k.value}</div>
      </div>
    `).join('');
  }

  // Stacked horizontal bars (global + per-project)
  const chart = document.getElementById('pipeline-chart');
  if (!chart) return;

  if (data.task_count === 0) {
    chart.innerHTML = '<p class="text-on-surface-variant text-sm text-center py-4">' + _t('pipeline.no_data') + '</p>';
    return;
  }

  const rows = [];
  // Global row
  rows.push({ label: _t('pipeline.all_projects'), stages: data.stages, count: data.task_count, total: data.avg_total_min });
  // Per-project rows
  const projects = Object.entries(data.by_project || {}).sort((a, b) => b[1].avg_total_min - a[1].avg_total_min);
  for (const [name, proj] of projects) {
    rows.push({ label: name, stages: proj.stages, count: proj.task_count, total: proj.avg_total_min });
  }

  chart.innerHTML = rows.map(function(row) {
    var segments = row.stages
      .filter(function(s) { return s.avg_min > 0; })
      .map(function(s) {
        var c = PIPELINE_COLORS[s.key] || { bg: 'var(--c-outline)', label: 'outline' };
        return '<div class="pipeline-seg rounded-sm transition-all" style="width:' + Math.max(s.pct, 2) + '%;background:' + c.bg + '" title="' + s.label + ': ' + formatDuration(s.avg_min) + ' (' + s.pct + '%)"></div>';
      }).join('');
    var r = '<div class="pipeline-row">';
    r += '<div class="flex items-center justify-between mb-1">';
    r += '<span class="text-xs font-medium text-on-surface">' + escHtml(row.label) + '</span>';
    r += '<span class="text-[10px] text-on-surface-variant">' + row.count + ' ' + _t('pipeline.tasks') + ' &middot; ' + formatDuration(row.total) + '</span>';
    r += '</div>';
    r += '<div class="pipeline-bar flex rounded-lg overflow-hidden h-5">' + segments + '</div>';
    r += '</div>';
    return r;
  }).join('');

  // Legend
  var legend = document.getElementById('pipeline-legend');
  if (legend) {
    var stages = [
      { key: 'pendiente',   label: _t('pipeline.stage_pendiente') },
      { key: 'en_progreso', label: _t('pipeline.stage_en_progreso') },
      { key: 'revision',    label: _t('pipeline.stage_revision') },
      { key: 'hecha',       label: _t('pipeline.stage_hecha') },
    ];
    legend.innerHTML = stages.map(function(s) {
      var c = PIPELINE_COLORS[s.key];
      var isBn = data.bottleneck === s.key;
      var r = '<span class="flex items-center gap-1.5' + (isBn ? ' font-bold' : '') + '">';
      r += '<span class="w-2.5 h-2.5 rounded-sm inline-block" style="background:' + c.bg + '"></span>';
      r += s.label + (isBn ? ' ⚠' : '');
      r += '</span>';
      return r;
    }).join('');
  }
}
