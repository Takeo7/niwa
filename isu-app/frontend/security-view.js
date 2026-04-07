// ======================== SECURITY VIEW ========================
// Extracted from app.js — loadSecurity(), runSecurityScan() and helpers

async function loadSecurity() {
  const data = await api('security');
  if (!data) {
    document.getElementById('security-risk-badge').innerHTML = '<span class="text-on-surface-variant">' + _t('sys.no_security') + '</span>';
    return;
  }
  const sum = data.summary || {};
  const checks = data.checks || {};

  // Risk badge
  const riskColor = sum.risk_level === 'low' ? 'tertiary' : sum.risk_level === 'medium' ? 'primary' : 'error';
  document.getElementById('security-risk-badge').innerHTML = `
    <div class="relative">
      <svg class="w-12 h-12 transform -rotate-90">
        <circle class="text-surface-bright" cx="24" cy="24" fill="transparent" r="20" stroke="currentColor" stroke-width="4"></circle>
        <circle class="text-${riskColor}" cx="24" cy="24" fill="transparent" r="20" stroke="currentColor" stroke-dasharray="125.6" stroke-dashoffset="${sum.total_issues ? 125.6 * (sum.total_issues/20) : 100}" stroke-width="4"></circle>
      </svg>
    </div>
    <div>
      <span class="text-[10px] uppercase tracking-widest text-on-surface-variant block mb-1">${_t('sec.risk_level')}</span>
      <span class="text-xl font-headline font-bold text-${riskColor} uppercase">${sum.risk_level||'unknown'}</span>
    </div>`;

  // Active issues list
  const allIssues = data.all_issues || [];
  const highIssues = allIssues.filter(i => i.severity === 'high');
  const medIssues = allIssues.filter(i => i.severity === 'medium');
  const sec = checks.secrets || {};
  const docker = checks.docker || {};
  const logins = checks.logins || {};
  const disk = checks.disk || {};
  const services = checks.services || {};
  const ssl = checks.ssl || {};

  const issueRows = allIssues.map(i => {
    const sevColor = i.severity === 'high' ? 'error' : i.severity === 'medium' ? 'primary' : 'on-surface-variant';
    return `<div class="flex items-center gap-3 text-xs px-2 py-2 border-b border-outline-variant/10 last:border-0">
      <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-${sevColor}/10 text-${sevColor}">${i.severity}</span>
      <span class="text-on-surface-variant font-mono text-[10px]">${escHtml(i.check)}</span>
      <span class="text-on-surface flex-1">${escHtml(i.detail)}</span>
    </div>`;
  }).join('');

  document.getElementById('security-threats').innerHTML = `
    <div class="flex items-center justify-between mb-6">
      <h3 class="text-lg font-headline font-bold flex items-center gap-2"><span class="material-symbols-outlined text-error">gpp_maybe</span>${_t('sec.detected_threats')}</h3>
      <span class="px-2 py-1 rounded-full bg-error/10 text-error text-[10px] font-bold uppercase tracking-widest">${sum.total_issues||0} issues</span>
    </div>
    <div class="space-y-4">
      <div class="flex gap-3 mb-4">
        <div class="flex-1 p-3 bg-error/5 rounded-lg text-center">
          <div class="text-xl font-headline font-black text-error">${sum.high||0}</div>
          <div class="text-[10px] uppercase font-bold text-error tracking-wider">HIGH</div>
        </div>
        <div class="flex-1 p-3 bg-primary/5 rounded-lg text-center">
          <div class="text-xl font-headline font-black text-primary">${sum.medium||0}</div>
          <div class="text-[10px] uppercase font-bold text-primary tracking-wider">MEDIUM</div>
        </div>
      </div>
      ${issueRows ? `<div class="glass-card rounded-lg overflow-hidden">${issueRows}</div>` : `<p class="text-xs text-on-surface-variant text-center py-4">${_t('sec.clean')}</p>`}
    </div>`;

  // Network & Infrastructure
  const ports = checks.ports || {};
  document.getElementById('security-network').innerHTML = `
    <div class="flex items-center justify-between mb-6">
      <h3 class="text-lg font-headline font-bold flex items-center gap-2"><span class="material-symbols-outlined text-secondary">lan</span>${_t('sec.network_security')}</h3>
    </div>
    <div class="flex items-center gap-4 mb-6">
      <div class="flex-1 text-center p-3 bg-surface-variant/40 rounded-lg">
        <div class="text-2xl font-headline font-extrabold text-on-surface">${ports.issues||0}</div>
        <div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest mt-1">${_t('sec.port_issues')}</div>
      </div>
      <div class="flex-1 text-center p-3 bg-surface-variant/40 rounded-lg">
        <div class="text-2xl font-headline font-extrabold text-on-surface">${(ports.open_ports||[]).length}</div>
        <div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest mt-1">Open ports</div>
      </div>
      <div class="flex-1 text-center p-3 bg-surface-variant/40 rounded-lg">
        <div class="text-2xl font-headline font-extrabold text-${(logins.desk_failures_24h||0)>5?'error':'on-surface'}">${logins.desk_failures_24h||0}</div>
        <div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-widest mt-1">Login failures 24h</div>
      </div>
    </div>
    ${(ports.open_ports||[]).length ? `<div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider mb-2">Open ports</div><div class="flex flex-wrap gap-2 mb-4">${(ports.open_ports||[]).map(p => `<span class="px-2 py-1 rounded bg-surface-variant/60 text-xs font-mono text-on-surface-variant">${escHtml(String(p))}</span>`).join('')}</div>` : ''}
    ${ssl.issues ? `<div class="glass-card p-3 rounded-lg flex items-center gap-3 mt-2"><span class="material-symbols-outlined text-error text-sm">lock_open</span><span class="text-xs text-error">SSL: ${ssl.issues} issue(s)</span></div>` : `<div class="glass-card p-3 rounded-lg flex items-center gap-3 mt-2"><span class="material-symbols-outlined text-tertiary text-sm">lock</span><span class="text-xs text-tertiary">SSL OK</span></div>`}`;

  // System status grid
  const integ = checks.integrity || {};
  document.getElementById('security-vulns').innerHTML = `
    <h3 class="text-lg font-headline font-bold mb-6 flex items-center gap-2"><span class="material-symbols-outlined text-primary">dashboard</span>${_t('sec.system_vulns')}</h3>
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="p-4 bg-surface-variant/40 rounded-lg">
        <span class="material-symbols-outlined text-primary-dim mb-3">key</span>
        <h4 class="font-bold text-sm mb-1">${_t('sec.exposed_secrets')}</h4>
        <p class="text-xs text-on-surface-variant mb-4">${sec.files_scanned||0} files scanned</p>
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-${(sec.issues||0)>0?'error':'tertiary'}">${(sec.issues||0)>0?_t('sec.flags',{n:sec.issues}):_t('sec.clean')}</span>
          <span class="material-symbols-outlined text-${(sec.issues||0)>0?'error':'tertiary'} text-sm">${(sec.issues||0)>0?'warning':'check_circle'}</span>
        </div>
      </div>
      <div class="p-4 bg-surface-variant/40 rounded-lg">
        <span class="material-symbols-outlined text-tertiary-dim mb-3">account_tree</span>
        <h4 class="font-bold text-sm mb-1">${_t('sec.integrity_checks')}</h4>
        <p class="text-xs text-on-surface-variant mb-4">${integ.files_monitored||0} files monitored</p>
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-${(integ.changes||0)>0?'primary':'tertiary'}">${(integ.changes||0)>0?_t('sec.changes',{n:integ.changes}):_t('sec.verified')}</span>
          <span class="material-symbols-outlined text-${(integ.changes||0)>0?'primary':'tertiary'} text-sm">${(integ.changes||0)>0?'warning':'check_circle'}</span>
        </div>
      </div>
      <div class="p-4 bg-surface-variant/40 rounded-lg">
        <span class="material-symbols-outlined text-secondary-dim mb-3">dns</span>
        <h4 class="font-bold text-sm mb-1">Docker</h4>
        <p class="text-xs text-on-surface-variant mb-4">${(docker.running||[]).length} containers running</p>
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-${(docker.missing||[]).length>0?'error':'tertiary'}">${(docker.missing||[]).length>0?_t('sec.flags',{n:(docker.missing||[]).length}):_t('sec.clean')}</span>
          <span class="material-symbols-outlined text-${(docker.missing||[]).length>0?'error':'tertiary'} text-sm">${(docker.missing||[]).length>0?'warning':'check_circle'}</span>
        </div>
      </div>
      <div class="p-4 bg-surface-variant/40 rounded-lg">
        <span class="material-symbols-outlined text-primary-dim mb-3">storage</span>
        <h4 class="font-bold text-sm mb-1">Disk</h4>
        <p class="text-xs text-on-surface-variant mb-4">${disk.free_gb||'?'} GB free (${disk.used_pct||'?'}% used)</p>
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-${(disk.issues||0)>0?'error':'tertiary'}">${(disk.issues||0)>0?_t('sec.flags',{n:disk.issues}):_t('sec.clean')}</span>
          <span class="material-symbols-outlined text-${(disk.issues||0)>0?'error':'tertiary'} text-sm">${(disk.issues||0)>0?'warning':'check_circle'}</span>
        </div>
      </div>
    </div>
    ${(docker.running||[]).length ? `<div class="mt-4"><div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider mb-2">Docker containers</div><div class="flex flex-wrap gap-2">${(docker.running||[]).map(c => `<span class="px-2 py-1 rounded bg-tertiary/10 text-tertiary text-xs font-mono">${escHtml(c)}</span>`).join('')}</div>${(docker.missing||[]).length ? `<div class="text-[10px] uppercase font-bold text-error tracking-wider mt-3 mb-2">Missing containers</div><div class="flex flex-wrap gap-2">${(docker.missing||[]).map(c => `<span class="px-2 py-1 rounded bg-error/10 text-error text-xs font-mono">${escHtml(c)}</span>`).join('')}</div>` : ''}</div>` : ''}
    ${(services.running||[]).length ? `<div class="mt-4"><div class="text-[10px] uppercase font-bold text-on-surface-variant tracking-wider mb-2">Active services</div><div class="flex flex-wrap gap-2">${(services.running||[]).map(s => `<span class="px-2 py-1 rounded bg-secondary/10 text-secondary text-xs font-mono">${escHtml(s)}</span>`).join('')}</div></div>` : ''}`;

  // Timeline
  document.getElementById('security-timeline').innerHTML = `
    <h3 class="text-lg font-headline font-bold mb-6 flex items-center gap-2"><span class="material-symbols-outlined text-on-surface-variant">history</span>${_t('sec.audit_timeline')}</h3>
    <div class="space-y-6 relative before:absolute before:left-[11px] before:top-2 before:bottom-0 before:w-px before:bg-outline-variant/20">
      <div class="relative pl-8">
        <div class="absolute left-0 top-1 w-[22px] h-[22px] rounded-full bg-tertiary/20 flex items-center justify-center z-10"><div class="w-1.5 h-1.5 rounded-full bg-tertiary"></div></div>
        <div class="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider mb-1">${data.timestamp ? new Date(data.timestamp).toLocaleString() : 'Now'}</div>
        <h4 class="text-sm font-bold">${_t('sec.last_audit')}</h4>
        <p class="text-xs text-on-surface-variant">${_t('sec.issues_duration', {n: sum.total_issues||0, dur: (sum.duration_seconds||0).toFixed(1)})}</p>
      </div>
    </div>`;
}

async function runSecurityScan() {
  toast(_t('sys.running_audit'));
  await api('security/scan');
  setTimeout(() => loadSecurity(), 2000);
}
