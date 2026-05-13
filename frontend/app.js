/* eBitrate Dashboard SPA */
const API = '';
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
let pollTimer = null;
let currentPage = 'dashboard';

// ── API helpers ──
async function api(path) {
  try {
    const r = await fetch(`${API}/api/${path}`);
    return await r.json();
  } catch { return null; }
}

// ── Router ──
function initRouter() {
  window.addEventListener('hashchange', route);
  $$('.nav-item').forEach(el => el.addEventListener('click', e => {
    const page = el.dataset.page;
    if (page) { e.preventDefault(); window.location.hash = page; }
  }));
  route();
}

function route() {
  const hash = (window.location.hash || '#dashboard').slice(1);
  currentPage = hash;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === hash));
  $('#page-title').textContent = {
    dashboard:'Dashboard', trades:'Trade Journal', bookmakers:'Bookmakers',
    treasury:'Treasury', hedges:'Hedge Journal', metrics:'System Metrics', settings:'Settings', signals:'Live Signals'
  }[hash] || 'Dashboard';
  renderPage(hash);
}

async function renderPage(page) {
  const c = $('#page-container');
  c.innerHTML = '<div class="loading-state"><div class="loader"></div><p>Loading...</p></div>';
  const renderers = { dashboard: renderDashboard, trades: renderTrades, bookmakers: renderBookmakers,
    treasury: renderTreasury, hedges: renderHedges, metrics: renderMetrics, settings: renderSettings, signals: renderSignals };
  const fn = renderers[page] || renderDashboard;
  await fn(c);
  startPolling(page);
}

function startPolling(page) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (currentPage === page) renderPage(page); }, 15000);
}

// ── Utilities ──
function badge(result) {
  const m = { full_success:['SUCCESS','success'], partial_leg1:['PARTIAL','warning'],
    partial_leg2:['PARTIAL','warning'], total_fail:['FAILED','danger'],
    MATCHED:['MATCHED','success'], PARTIAL:['PARTIAL','warning'],
    FAILED:['FAILED','danger'], ABORTED_VALIDATION:['ABORTED','muted'],
    ABORTED_TREASURY:['ABORTED','muted'] };
  const [t,c] = m[result] || [result,'muted'];
  return `<span class="badge badge-${c}">${t}</span>`;
}
function fmt(n, d=2) { return n != null ? Number(n).toFixed(d) : '—'; }
function fmtMs(n) { return n != null ? Number(n).toFixed(0) + 'ms' : '—'; }
function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('en-GB', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
function pctClass(v) { return v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral'; }
function gaugeHtml(val, max=1) {
  const pct = Math.min(100, Math.max(0, (val/max)*100));
  const cls = pct >= 70 ? 'high' : pct >= 40 ? 'medium' : 'low';
  return `<div class="gauge-wrap"><div class="gauge-bar"><div class="gauge-fill ${cls}" style="width:${pct}%"></div></div><span class="gauge-value">${fmt(val)}</span></div>`;
}
function kpi(label, value, sub='', cls='neutral') {
  return `<div class="kpi-card fade-in"><div class="kpi-label">${label}</div><div class="kpi-value ${cls}">${value}</div><div class="kpi-sub">${sub}</div></div>`;
}

// ── Dashboard ──
async function renderDashboard(c) {
  const [metrics, summary, series, status] = await Promise.all([
    api('metrics'), api('trades/summary'), api('trades/pnl-series'), api('status')
  ]);
  if (!metrics || !summary) { c.innerHTML = '<div class="empty-state"><p>No data available yet. Start the engine.</p></div>'; return; }

  const pnl = summary.total_pnl || 0;
  const running = status?.engine_running;

  c.innerHTML = `
    <div class="kpi-grid">
      ${kpi('Total PnL', 'KES ' + fmt(pnl), summary.total + ' trades', pctClass(pnl))}
      ${kpi('Win Rate', fmt(summary.win_rate,1) + '%', summary.full_success + ' wins', summary.win_rate >= 50 ? 'positive' : 'negative')}
      ${kpi('Uptime', formatUptime(metrics.uptime_sec || 0), metrics.cycles + ' cycles', 'neutral')}
      ${kpi('Avg Latency', fmtMs(summary.avg_latency), 'per trade', 'neutral')}
      ${kpi('Arbs Detected', metrics.arbs_detected || 0, metrics.arbs_rejected + ' rejected', 'neutral')}
      ${kpi('Engine', running ? '● ONLINE' : '○ OFFLINE', status?.execution_mode?.toUpperCase() || 'PAPER', running ? 'positive' : 'negative')}
    </div>
    <div class="grid-wide">
      <div class="card fade-in fade-in-delay-1">
        <div class="card-header"><span class="card-title">Cumulative PnL</span></div>
        <div class="card-body"><div class="chart-container"><canvas id="pnl-chart"></canvas></div></div>
      </div>
      <div class="card fade-in fade-in-delay-2">
        <div class="card-header"><span class="card-title">Recent Trades</span></div>
        <div class="card-body">${renderRecentTrades(series)}</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card fade-in fade-in-delay-3">
        <div class="card-header"><span class="card-title">Execution Breakdown</span></div>
        <div class="card-body">${renderBreakdown(summary)}</div>
      </div>
      <div class="card fade-in fade-in-delay-4">
        <div class="card-header"><span class="card-title">Latency Overview</span></div>
        <div class="card-body">${renderLatencies(metrics)}</div>
      </div>
    </div>`;
  if (series && series.length) drawPnlChart(series);
}

function formatUptime(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}

function renderRecentTrades(series) {
  if (!series || !series.length) return '<div class="empty-state"><p>No trades yet</p></div>';
  const recent = series.slice(-8).reverse();
  return recent.map(t =>
    `<div class="bm-stat-row"><span class="bm-stat-label">KES ${fmt(t.profit)}</span>${badge(t.result)}</div>`
  ).join('');
}

function renderBreakdown(s) {
  const items = [
    ['Full Success', s.full_success, 'success'],
    ['Partial Fill', s.partial, 'warning'],
    ['Total Fail', s.total_fail, 'danger'],
  ];
  return items.map(([label, val, cls]) => {
    const pct = s.total > 0 ? ((val/s.total)*100).toFixed(1) : 0;
    return `<div class="bm-stat-row"><span class="bm-stat-label">${label}</span>
      <span><span class="badge badge-${cls}">${val}</span> <span class="bm-stat-label">(${pct}%)</span></span></div>`;
  }).join('');
}

function renderLatencies(m) {
  return ['avg_exec_ms','avg_fetch_ms','avg_hedge_ms'].map(k => {
    const label = k.replace('avg_','').replace('_ms','').toUpperCase();
    const val = m[k] || 0;
    return `<div class="bm-stat-row"><span class="bm-stat-label">${label}</span><span class="bm-stat-value">${fmtMs(val)}</span></div>`;
  }).join('');
}

function drawPnlChart(series) {
  const canvas = document.getElementById('pnl-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * 2; canvas.height = rect.height * 2;
  ctx.scale(2, 2);
  const W = rect.width, H = rect.height;
  const vals = series.map(s => s.cumulative_pnl);
  const mn = Math.min(...vals, 0), mx = Math.max(...vals, 1);
  const pad = { t: 20, b: 30, l: 50, r: 20 };
  const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;

  // Grid
  ctx.strokeStyle = 'rgba(99,102,241,0.08)'; ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ch / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    const lbl = fmt(mx - ((mx - mn) / 4) * i, 0);
    ctx.fillStyle = '#5a6380'; ctx.font = '10px Inter'; ctx.textAlign = 'right';
    ctx.fillText(lbl, pad.l - 8, y + 3);
  }

  // Zero line
  if (mn < 0) {
    const zy = pad.t + ((mx - 0) / (mx - mn)) * ch;
    ctx.strokeStyle = 'rgba(239,68,68,0.3)'; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(pad.l, zy); ctx.lineTo(W - pad.r, zy); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Line
  const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
  grad.addColorStop(0, '#6366f1'); grad.addColorStop(1, '#06b6d4');
  ctx.strokeStyle = grad; ctx.lineWidth = 2; ctx.lineJoin = 'round';
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = pad.l + (i / Math.max(1, vals.length - 1)) * cw;
    const y = pad.t + ((mx - v) / (mx - mn || 1)) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Area fill
  const areaGrad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
  areaGrad.addColorStop(0, 'rgba(99,102,241,0.15)'); areaGrad.addColorStop(1, 'rgba(6,182,212,0.02)');
  ctx.lineTo(pad.l + cw, H - pad.b); ctx.lineTo(pad.l, H - pad.b); ctx.closePath();
  ctx.fillStyle = areaGrad; ctx.fill();
}

// ── Trades ──
async function renderTrades(c) {
  const [data, summary] = await Promise.all([api('trades?limit=200'), api('trades/summary')]);
  if (!data) { c.innerHTML = '<div class="empty-state"><p>No trade data</p></div>'; return; }
  const trades = data.trades || [];

  c.innerHTML = `
    <div class="kpi-grid">
      ${kpi('Total Trades', summary?.total || 0, '', 'neutral')}
      ${kpi('Total PnL', 'KES ' + fmt(summary?.total_pnl), '', pctClass(summary?.total_pnl))}
      ${kpi('Win Rate', fmt(summary?.win_rate,1) + '%', '', summary?.win_rate >= 50 ? 'positive' : 'negative')}
      ${kpi('Avg PnL', 'KES ' + fmt(summary?.avg_pnl), 'per trade', pctClass(summary?.avg_pnl))}
    </div>
    <div class="card fade-in">
      <div class="card-header"><span class="card-title">Trade History</span>
        <div class="filter-bar" id="trade-filters">
          <button class="filter-btn active" data-filter="all">All</button>
          <button class="filter-btn" data-filter="full_success">Success</button>
          <button class="filter-btn" data-filter="partial">Partial</button>
          <button class="filter-btn" data-filter="total_fail">Failed</button>
        </div>
      </div>
      <div class="table-scroll"><table class="data-table"><thead><tr>
        <th>Event</th><th>Match</th><th>Result</th><th>Expected</th><th>Realized</th><th>Slippage</th><th>Latency</th><th>Time</th>
      </tr></thead><tbody id="trades-tbody">
        ${trades.map(tradeRow).join('')}
      </tbody></table></div>
    </div>`;

  $$('#trade-filters .filter-btn').forEach(btn => btn.addEventListener('click', () => {
    $$('#trade-filters .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.filter;
    const rows = $$('#trades-tbody tr');
    rows.forEach(r => {
      if (f === 'all') r.style.display = '';
      else if (f === 'partial') r.style.display = r.dataset.result?.includes('partial') ? '' : 'none';
      else r.style.display = r.dataset.result === f ? '' : 'none';
    });
  }));
}

function tradeRow(t) {
  return `<tr data-result="${t.result}">
    <td class="mono">${(t.event_id||'').slice(0,12)}</td><td>${t.match||'—'}</td>
    <td>${badge(t.result)}</td><td class="mono">${fmt(t.expected_profit)}</td>
    <td class="mono" style="color:${t.realized_profit>=0?'var(--green)':'var(--red)'}">${fmt(t.realized_profit)}</td>
    <td class="mono" style="color:${t.slippage<0?'var(--red)':'var(--text-muted)'}">${fmt(t.slippage)}</td>
    <td class="mono">${fmtMs(t.latency_ms)}</td><td>${fmtTime(t.timestamp)}</td></tr>`;
}

// ── Bookmakers ──
async function renderBookmakers(c) {
  const data = await api('bookmakers');
  if (!data) { c.innerHTML = '<div class="empty-state"><p>No bookmaker data</p></div>'; return; }
  const profiles = data.profiles || {};
  const burned = data.burned_accounts || [];
  const names = Object.keys(profiles);

  c.innerHTML = `
    <div class="grid-3 fade-in">${names.map(name => {
      const p = profiles[name];
      return `<div class="bm-card">
        <div class="bm-card-name"><span class="dot" style="background:${p.health_score>=0.7?'var(--green)':p.health_score>=0.4?'var(--amber)':'var(--red)'}"></span>${name}</div>
        <div class="bm-stat-row"><span class="bm-stat-label">Health Score</span></div>${gaugeHtml(p.health_score)}
        <div class="bm-stat-row"><span class="bm-stat-label">Success Rate</span><span class="bm-stat-value">${fmt(p.success_rate*100,1)}%</span></div>
        <div class="bm-stat-row"><span class="bm-stat-label">Avg Latency</span><span class="bm-stat-value">${fmtMs(p.avg_latency)}</span></div>
        <div class="bm-stat-row"><span class="bm-stat-label">Rejection Rate</span><span class="bm-stat-value">${fmt(p.rejection_rate*100,1)}%</span></div>
      </div>`;
    }).join('')}</div>
    ${burned.length ? `<div class="card fade-in fade-in-delay-2"><div class="card-header"><span class="card-title">🔥 Burned Accounts</span></div>
      <div class="card-body">${burned.map(b => `<span class="badge badge-danger" style="margin:4px">${b}</span>`).join('')}</div></div>` : ''}`;
}

// ── Treasury ──
async function renderTreasury(c) {
  const data = await api('treasury');
  if (!data) { c.innerHTML = '<div class="empty-state"><p>No treasury data</p></div>'; return; }
  const bms = data.bookmakers || {};

  c.innerHTML = `
    <div class="kpi-grid">
      ${kpi('Bankroll', 'KES ' + fmt(data.bankroll,0), 'configured', 'neutral')}
      ${kpi('Max Exposure', 'KES ' + fmt(data.max_daily_exposure,0), 'daily limit', 'neutral')}
      ${kpi('Exchange', 'KES ' + fmt(data.exchange?.balance,0), data.exchange?.currency || '', 'positive')}
    </div>
    <div class="grid-3 fade-in">
      ${Object.entries(bms).map(([name, info]) => `
        <div class="treasury-card">
          <div class="treasury-bm-name">${name}</div>
          <div class="treasury-balance">${fmt(info.balance, 0)}</div>
          <div class="treasury-currency">${info.currency || 'KES'}</div>
        </div>`).join('')}
    </div>`;
}

// ── Hedges ──
async function renderHedges(c) {
  const data = await api('hedges');
  if (!data || !data.length) { c.innerHTML = '<div class="empty-state"><p>No hedge journal entries yet</p></div>'; return; }

  c.innerHTML = `<div class="card fade-in"><div class="card-header"><span class="card-title">Hedge History</span>
    <span class="badge badge-info">${data.length} entries</span></div>
    <div class="table-scroll"><table class="data-table"><thead><tr>
      <th>Event</th><th>Match</th><th>Leg</th><th>Back Stake</th><th>Lay Odds</th><th>Liability</th><th>Outcome</th><th>Time</th>
    </tr></thead><tbody>
      ${data.slice().reverse().map(h => `<tr>
        <td class="mono">${(h.event_id||'').slice(0,12)}</td><td>${h.match||'—'}</td>
        <td class="mono">#${(h.exposed_leg||0)+1}</td><td class="mono">${fmt(h.back_stake)}</td>
        <td class="mono">${fmt(h.lay_odds,3)}</td><td class="mono">${fmt(h.max_liability)}</td>
        <td>${badge(h.outcome)}</td><td>${fmtTime(h.timestamp)}</td></tr>`).join('')}
    </tbody></table></div></div>`;
}

// ── Metrics ──
async function renderMetrics(c) {
  const m = await api('metrics');
  if (!m) { c.innerHTML = '<div class="empty-state"><p>No metrics data</p></div>'; return; }

  c.innerHTML = `
    <div class="kpi-grid">
      ${kpi('Cycles', m.cycles || 0, '', 'neutral')}
      ${kpi('Total PnL', 'KES ' + fmt(m.total_pnl), '', pctClass(m.total_pnl))}
      ${kpi('Captchas', m.captchas_hit || 0, 'detected', m.captchas_hit > 0 ? 'negative' : 'neutral')}
      ${kpi('Burned Accts', m.accounts_burned || 0, '', m.accounts_burned > 0 ? 'negative' : 'neutral')}
    </div>
    <div class="grid-2">
      <div class="card fade-in"><div class="card-header"><span class="card-title">Execution Stats</span></div>
        <div class="card-body">
          ${metricRow('Arbs Detected', m.arbs_detected)}
          ${metricRow('Arbs Rejected', m.arbs_rejected)}
          ${metricRow('Arbs Attempted', m.arbs_attempted)}
          ${metricRow('Executed %', fmt(m.executed_pct,1) + '%')}
          ${metricRow('Partial %', fmt(m.partial_pct,1) + '%')}
          ${metricRow('Fail %', fmt(m.fail_pct,1) + '%')}
        </div></div>
      <div class="card fade-in fade-in-delay-1"><div class="card-header"><span class="card-title">Hedge Performance</span></div>
        <div class="card-body">
          ${metricRow('Hedges Triggered', m.hedges_triggered || 0)}
          ${metricRow('Hedge Trigger %', fmt(m.hedge_trigger_pct,1) + '%')}
          ${metricRow('Hedge Success %', fmt(m.hedge_success_pct,1) + '%')}
          ${metricRow('Avg Exec Latency', fmtMs(m.avg_exec_ms))}
          ${metricRow('Avg Fetch Latency', fmtMs(m.avg_fetch_ms))}
          ${metricRow('Avg Hedge Latency', fmtMs(m.avg_hedge_ms))}
        </div></div>
    </div>
    ${Object.keys(m.bookmaker_rejection_rates||{}).length ? `
    <div class="card fade-in fade-in-delay-2"><div class="card-header"><span class="card-title">Bookmaker Rejection Rates</span></div>
      <div class="card-body">${Object.entries(m.bookmaker_rejection_rates).map(([bm, rate]) =>
        `<div class="bm-stat-row"><span class="bm-stat-label">${bm}</span><span class="bm-stat-value" style="color:${rate>0.3?'var(--red)':'var(--green)'}">${fmt(rate*100,1)}%</span></div>`
      ).join('')}</div></div>` : ''}
    <div class="card fade-in fade-in-delay-3" style="margin-top:16px"><div class="card-header"><span class="card-title">Snapshot</span>
      <span class="bm-stat-label">${m.snapshot_at || '—'}</span></div>
      <div class="card-body"><pre style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-secondary);white-space:pre-wrap">${JSON.stringify(m, null, 2)}</pre></div></div>`;
}
function metricRow(label, val) {
  return `<div class="bm-stat-row"><span class="bm-stat-label">${label}</span><span class="bm-stat-value">${val}</span></div>`;
}

// ── Settings ──
async function renderSettings(c) {
  const cfg = await api('config');
  if (!cfg) { c.innerHTML = '<div class="empty-state"><p>Could not load config</p></div>'; return; }

  const sections = {
    'Execution': ['execution_mode','dry_run','bankroll','max_daily_exposure','max_trades_per_min','max_consecutive_losses','max_hedge_loss'],
    'Detection': ['min_edge','max_odds_age_sec','edge_strong_min','edge_marginal_min','edge_max_age_sec','edge_min_bm_health'],
    'Infrastructure': ['poll_interval','session_pool_size','graceful_degradation_threshold'],
    'Targets': ['execution_order','target_bookmakers','markets','sports'],
  };

  c.innerHTML = Object.entries(sections).map(([title, keys]) => `
    <div class="card fade-in" style="margin-bottom:20px">
      <div class="card-header"><span class="card-title">${title}</span></div>
      <div class="card-body"><div class="settings-grid">
        ${keys.map(k => {
          let v = cfg[k];
          if (Array.isArray(v)) v = v.join(', ');
          if (typeof v === 'boolean') v = v ? 'TRUE' : 'FALSE';
          return `<div class="setting-item"><span class="setting-key">${k}</span><span class="setting-value">${v ?? '—'}</span></div>`;
        }).join('')}
      </div></div></div>`).join('');
}

// ── Signals ──
async function renderSignals(c) {
  const [arbs, cfg] = await Promise.all([api('signals'), api('config')]);
  const signalsList = arbs || [];
  
  const totalSignals = signalsList.length;
  const strongMin = (cfg && cfg.edge_strong_min) ? cfg.edge_strong_min : 2.0;
  const strongSignals = signalsList.filter(a => a.margin_pct >= strongMin).length;

  c.innerHTML = `
    <div style="max-width: 700px; margin: 0 auto;">
      <div style="margin-bottom: 24px;">
        <h2 style="margin: 0 0 4px 0; font-size: 1.5rem;">Your Signals</h2>
        <div style="color: #9ca3af; font-size: 0.9rem;">Monitor live arbitrage odds detected by the engine</div>
      </div>

      <div class="card fade-in" style="background: #111827; border: 1px solid #1f2937; border-radius: 16px; margin-bottom: 20px; padding: 16px 20px; display:flex; justify-content:space-between; align-items:center;">
        <div style="display:flex; align-items:center; gap: 12px;">
          <div style="width: 32px; height: 32px; border-radius: 8px; background: rgba(34, 197, 94, 0.1); color: #22c55e; display:flex; align-items:center; justify-content:center;">
             <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
          </div>
          <div style="font-weight: 600;">Auto Odds Monitor</div>
        </div>
        <div style="font-size: 0.8rem; color: #9ca3af;">Checks continuously · Alerts via Telegram</div>
      </div>

      <div class="grid-2 fade-in fade-in-delay-1" style="gap: 16px; margin-bottom: 24px;">
        <div style="background: rgba(34, 197, 94, 0.05); border: 1px solid rgba(34, 197, 94, 0.2); padding: 20px; border-radius: 16px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <svg width="20" height="20" fill="none" stroke="#22c55e" stroke-width="2" viewBox="0 0 24 24" style="margin-bottom: 8px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            <div style="color: #22c55e; font-size: 0.9rem; font-weight: 500;">Active Arbs</div>
          </div>
          <div style="font-size: 1.8rem; font-weight: 700; color: #fff;">${totalSignals}</div>
        </div>
        <div style="background: #111827; border: 1px solid #1f2937; padding: 20px; border-radius: 16px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <svg width="20" height="20" fill="none" stroke="#9ca3af" stroke-width="2" viewBox="0 0 24 24" style="margin-bottom: 8px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
            <div style="color: #9ca3af; font-size: 0.9rem; font-weight: 500;">Strong Edge (>${strongMin}%)</div>
          </div>
          <div style="font-size: 1.8rem; font-weight: 700; color: #fff;">${strongSignals}</div>
        </div>
      </div>

      <div style="display:flex; flex-direction:column; gap: 16px;" class="fade-in fade-in-delay-2">
        ${totalSignals === 0 ? '<div class="empty-state"><p>Scanning markets...</p></div>' : signalsList.map(arb => renderSignalCard(arb)).join('')}
      </div>
    </div>
  `;
}

function renderSignalCard(arb) {
  const [leg1, leg2] = arb.legs;
  const timeStr = new Date(arb.detected_at * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
  
  return `
    <div style="background: #111827; border: 1px solid #1f2937; border-radius: 16px; padding: 20px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 16px;">
        <div>
          <span class="pulse-active" style="display:inline-block; padding: 4px 10px; background: rgba(34, 197, 94, 0.1); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.2); border-radius: 20px; font-size: 0.75rem; font-weight: 600; margin-bottom: 12px; letter-spacing: 0.05em;"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="vertical-align:-2px; margin-right:4px;"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg> ACTIVE</span>
          <div style="font-weight: 600; font-size: 1.1rem; margin-bottom: 4px; color: #fff;">${arb.match}</div>
          <div style="color: #9ca3af; font-size: 0.85rem; display:flex; align-items:center; gap:6px;">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> ${timeStr}
          </div>
        </div>
      </div>

      <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 20px;">
        <div style="background: #1a222f; padding: 12px; border-radius: 12px; text-align:center;">
           <div style="font-size: 0.7rem; color: #9ca3af; margin-bottom: 4px; text-transform:uppercase; letter-spacing:0.05em;">Market</div>
           <div style="color: #22c55e; font-weight: 600;">${arb.market_type} ${arb.line}</div>
        </div>
        <div style="background: #1a222f; padding: 12px; border-radius: 12px; text-align:center;">
           <div style="font-size: 0.7rem; color: #9ca3af; margin-bottom: 4px; text-transform:uppercase; letter-spacing:0.05em;">Edge</div>
           <div style="color: #fff; font-weight: 600;">${fmt(arb.margin_pct)}%</div>
        </div>
        <div style="background: #1a222f; padding: 12px; border-radius: 12px; text-align:center;">
           <div style="font-size: 0.7rem; color: #9ca3af; margin-bottom: 4px; text-transform:uppercase; letter-spacing:0.05em;">Profit</div>
           <div style="color: #fff; font-weight: 600;">KES ${fmt(arb.profit)}</div>
        </div>
      </div>

      <!-- Legs Breakdown -->
      <div style="background: #1a222f; border-radius: 12px; border: 1px solid #1f2937; overflow:hidden;">
        <div style="display:flex; justify-content:space-between; align-items:center; padding: 12px 16px; border-bottom: 1px solid #1f2937;">
           <div style="display:flex; align-items:center; gap: 8px;">
             <span style="color:#9ca3af; font-size:0.8rem;">Leg 1:</span>
             <span class="badge badge-neutral">${leg1.bookmaker}</span>
           </div>
           <div style="display:flex; align-items:center; gap: 12px;">
             <span style="color:#fff; font-size:0.9rem; font-weight:500;">${leg1.outcome}</span>
             <span style="color:#22c55e; font-weight:700; font-family:var(--font-mono);">@ ${fmt(leg1.odds, 2)}</span>
           </div>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; padding: 12px 16px;">
           <div style="display:flex; align-items:center; gap: 8px;">
             <span style="color:#9ca3af; font-size:0.8rem;">Leg 2:</span>
             <span class="badge badge-neutral">${leg2.bookmaker}</span>
           </div>
           <div style="display:flex; align-items:center; gap: 12px;">
             <span style="color:#fff; font-size:0.9rem; font-weight:500;">${leg2.outcome}</span>
             <span style="color:#22c55e; font-weight:700; font-family:var(--font-mono);">@ ${fmt(leg2.odds, 2)}</span>
           </div>
        </div>
      </div>
    </div>
  `;
}

// ── Engine status ──
async function updateStatus() {
  const s = await api('status');
  const dot = $('.status-dot');
  const txt = $('.status-text');
  if (!dot || !txt) return;
  if (s?.engine_running) {
    dot.className = 'status-dot running';
    txt.textContent = 'Engine Running';
  } else {
    dot.className = 'status-dot stopped';
    txt.textContent = 'Engine Stopped';
  }
}

// ── Clock ──
function updateClock() {
  const el = $('#top-clock');
  if (el) el.textContent = new Date().toLocaleTimeString('en-GB');
}

// ── Mobile menu ──
function initMenu() {
  const toggle = $('#menu-toggle');
  const sidebar = $('#sidebar');
  if (toggle && sidebar) {
    toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
    $$('.nav-item').forEach(n => n.addEventListener('click', () => sidebar.classList.remove('open')));
  }
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  initRouter();
  initMenu();
  updateStatus();
  updateClock();
  setInterval(updateStatus, 10000);
  setInterval(updateClock, 1000);
});
