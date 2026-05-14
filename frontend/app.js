// ─────────────────────────────────────────────────────────────
// ARABIAN Arb Engine — app.js  (real data only)
// ─────────────────────────────────────────────────────────────
// API base URL is set in config.js — change it there before deploying
const API = (typeof API_BASE_URL !== 'undefined') ? API_BASE_URL.replace(/\/$/, '') : '';

let pollTimer        = null;
let availableBookmakers = [];
let selectedBookmakers  = new Set();
let prevTriggeredCount  = 0;
let currentFilter       = 'all';
let allSignalsData      = [];
let prevOddsMap         = {};   // key: eventId_bm → odds (for flash detection)

// ─────────────────────────────────────────────────────────────
// SOUND ENGINE
// ─────────────────────────────────────────────────────────────
const Sound = { enabled: true, tone: 'beep', volume: 0.7, customDataUrl: null };

function loadSound()  { try { const r=localStorage.getItem('arb_snd'); if(r) Object.assign(Sound, JSON.parse(r)); } catch{} }
function saveSound()  { localStorage.setItem('arb_snd', JSON.stringify(Sound)); }

let _ac = null;
function ac() {
    if (!_ac) _ac = new (window.AudioContext || window.webkitAudioContext)();
    if (_ac.state === 'suspended') _ac.resume();
    return _ac;
}

const TONES = {
    beep(v)  { const c=ac(),o=c.createOscillator(),g=c.createGain(); o.connect(g); g.connect(c.destination); o.type='sine'; o.frequency.value=880; g.gain.setValueAtTime(v,c.currentTime); g.gain.exponentialRampToValueAtTime(.001,c.currentTime+.4); o.start(); o.stop(c.currentTime+.4); },
    double(v){ const c=ac(); [0,.25].forEach(d=>{ const o=c.createOscillator(),g=c.createGain(); o.connect(g); g.connect(c.destination); o.type='sine'; o.frequency.value=1000; g.gain.setValueAtTime(0,c.currentTime+d); g.gain.linearRampToValueAtTime(v,c.currentTime+d+.02); g.gain.exponentialRampToValueAtTime(.001,c.currentTime+d+.18); o.start(c.currentTime+d); o.stop(c.currentTime+d+.2); }); },
    rising(v){ const c=ac(),o=c.createOscillator(),g=c.createGain(); o.connect(g); g.connect(c.destination); o.type='triangle'; o.frequency.setValueAtTime(400,c.currentTime); o.frequency.linearRampToValueAtTime(1200,c.currentTime+.6); g.gain.setValueAtTime(v,c.currentTime); g.gain.exponentialRampToValueAtTime(.001,c.currentTime+.65); o.start(); o.stop(c.currentTime+.65); },
    urgent(v){ const c=ac(); [0,.15,.3].forEach(d=>{ const o=c.createOscillator(),g=c.createGain(); o.connect(g); g.connect(c.destination); o.type='sawtooth'; o.frequency.value=700; g.gain.setValueAtTime(v*.6,c.currentTime+d); g.gain.exponentialRampToValueAtTime(.001,c.currentTime+d+.12); o.start(c.currentTime+d); o.stop(c.currentTime+d+.13); }); },
    chime(v) { const c=ac(); [523,659,784,1047].forEach((f,i)=>{ const o=c.createOscillator(),g=c.createGain(); o.connect(g); g.connect(c.destination); o.type='sine'; o.frequency.value=f; const t=c.currentTime+i*.14; g.gain.setValueAtTime(v,t); g.gain.exponentialRampToValueAtTime(.001,t+.5); o.start(t); o.stop(t+.55); }); },
    custom(v){ if(!Sound.customDataUrl){ TONES.beep(v); return; } const a=new Audio(Sound.customDataUrl); a.volume=v; a.play().catch(()=>TONES.beep(v)); },
};

function playAlert() {
    if (!Sound.enabled) return;
    try { (TONES[Sound.tone]||TONES.beep)(Sound.volume); } catch(e) { console.warn('sound err',e); }
}

// ─────────────────────────────────────────────────────────────
// API  +  Connection Health
// ─────────────────────────────────────────────────────────────
let _apiConnected = true;

function setBannerState(connected, msg = '') {
    const banner  = document.getElementById('api-banner');
    const bannerT = document.getElementById('api-banner-text');
    if (!banner) return;
    if (connected) {
        banner.style.display = 'none';
        _apiConnected = true;
    } else {
        banner.style.display = 'flex';
        if (bannerT) bannerT.textContent = msg || 'Cannot reach backend — check API server';
        _apiConnected = false;
    }
}

async function api(path, opts={}) {
    try {
        const headers = { ...opts.headers, 'Bypass-Tunnel-Reminder': 'true' };
        const r = await fetch(`${API}/api/${path}`, { ...opts, headers });
        if (!r.ok) {
            // HTTP error but server is reachable — hide banner, let caller handle
            setBannerState(true);
            return null;
        }
        setBannerState(true);
        return await r.json();
    } catch(err) {
        // Network error — backend unreachable
        const msg = API
            ? `Cannot reach backend at ${API}`
            : 'API server offline — run: python api_server.py';
        setBannerState(false, msg);
        return null;
    }
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────
function fmt(n, d=2) { return (n!=null && !isNaN(n)) ? Number(n).toFixed(d) : '—'; }

function dn(name) {   // display name
    if (!name) return '—';
    return String(name)
        .replace(/1xbet/i,'1xBet').replace(/melbet/i,'Melbet')
        .replace(/betika/i,'Betika').replace(/bet365/i,'Bet365')
        .replace(/pinnacle/i,'Pinnacle').replace(/sportybet/i,'SportyBet');
}

function formatDate(ts) {
    if (!ts) return '—';
    const n = parseFloat(ts);
    const d = isNaN(n) ? new Date(ts) : new Date(n * 1000);
    return d.toLocaleDateString('en-US', { month:'short', day:'numeric' })
         + ', ' + d.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', hour12:false });
}

// ─────────────────────────────────────────────────────────────
// BOOKMAKER LIST
// ─────────────────────────────────────────────────────────────
async function fetchBookmakers() {
    const list = await api('bookmaker-list');
    availableBookmakers = (list && list.length) ? list : [
        { name:'1xbet',  display:'1xBet',  status:'healthy', health:1.0, balance:null },
        { name:'melbet', display:'Melbet', status:'healthy', health:1.0, balance:null },
        { name:'betika', display:'Betika', status:'healthy', health:1.0, balance:null },
    ];
    renderDrawer();
    renderChips();
    updateSubtitle();
}

function updateSubtitle() {
    const el = document.getElementById('subtitle-text');
    if (!el) return;
    const names = availableBookmakers.filter(b => b.status !== 'offline').map(b => b.display);
    el.textContent = names.length ? `Monitoring ${names.join(', ')}` : 'Monitor arbitrage signals';
}

function renderDrawer() {
    const el = document.getElementById('bm-list');
    if (!el) return;
    el.innerHTML = availableBookmakers.map(bm => {
        const bal = bm.balance != null ? `KES ${Number(bm.balance).toLocaleString()}` : '';
        const hp  = bm.health  != null ? `${Math.round(bm.health*100)}% health` : '';
        const meta = [bal, hp].filter(Boolean).join(' · ');
        return `<div class="bm-row">
            <div class="bm-health-dot ${bm.status}"></div>
            <div class="bm-row-info">
                <div class="bm-row-name">${bm.display}</div>
                ${meta ? `<div class="bm-row-meta">${meta}</div>` : ''}
            </div>
            <span class="bm-row-status ${bm.status}">${bm.status.toUpperCase()}</span>
        </div>`;
    }).join('');
}

function renderChips() {
    const c = document.getElementById('bm-chips');
    if (!c) return;
    c.innerHTML = '';
    availableBookmakers.forEach(bm => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'bm-chip' + (bm.status==='offline' ? ' offline' : '');
        chip.textContent = bm.display;
        chip.dataset.name = bm.name;
        if (bm.status !== 'offline') {
            chip.addEventListener('click', () => {
                const sel = selectedBookmakers.has(bm.name);
                sel ? selectedBookmakers.delete(bm.name) : selectedBookmakers.add(bm.name);
                chip.classList.toggle('selected', !sel);
            });
        }
        c.appendChild(chip);
    });
}

// ─────────────────────────────────────────────────────────────
// LOAD DATA  (real signals + manual targets + trade summary)
// ─────────────────────────────────────────────────────────────
async function loadData() {
    const [signals, manualTargets, summary] = await Promise.all([
        api('signals'),
        api('manual_targets'),
        api('trades/summary'),
    ]);

    const engine = (signals || []).map(s => ({ ...s, _type:'engine' }));
    const manual = (manualTargets || []).map(t => ({
        _type:'manual', id:t.id, match:t.match,
        market_type:t.market, line:'', status:t.status||'active',
        target_odds:t.target_odds, bookmakers:t.bookmakers||[],
        detected_at:t.id, is_live:false,
    }));

    allSignalsData = [...engine, ...manual];
    updateStats(allSignalsData, manual, summary);
    updateBadge(manual);
    renderSignals(allSignalsData);
}

function updateStats(all, manual, summary) {
    // All count
    setText('stat-all',       all.length);
    // Active = engine arbs with positive margin
    const active = all.filter(s => s._type==='engine' && s.margin_pct > 0).length;
    setText('stat-active',    active);
    // Triggered / Cancelled from manual targets only
    setText('stat-triggered', manual.filter(s=>s.status==='triggered').length);
    setText('stat-cancelled', manual.filter(s=>s.status==='cancelled').length);
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function updateBadge(manual) {
    const triggered = manual.filter(s=>s.status==='triggered').length;
    const badge = document.getElementById('notif-badge');
    if (!badge) return;
    if (triggered > prevTriggeredCount) playAlert();
    prevTriggeredCount = triggered;
    badge.textContent = triggered > 9 ? '9+' : triggered;
    badge.style.display = triggered > 0 ? 'flex' : 'none';
}

// ─────────────────────────────────────────────────────────────
// RENDER SIGNAL CARDS
// ─────────────────────────────────────────────────────────────
function renderSignals(signals) {
    const container = document.getElementById('signals-list');
    const template  = document.getElementById('signal-card-template');
    if (!container || !template) return;
    container.innerHTML = '';

    let list = signals;
    if (currentFilter === 'live')     list = signals.filter(s => s.is_live === true);
    if (currentFilter === 'prematch') list = signals.filter(s => !s.is_live);

    if (!list.length) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <p class="empty-title">No signals yet</p>
            <p class="empty-sub">Tap <strong>New Signal</strong> to add a target, or wait for the engine to detect arbitrage opportunities.</p>
          </div>`;
        return;
    }

    list.forEach(arb => {
        const clone = template.content.cloneNode(true);
        const id    = arb.event_id || arb.id || '';

        // Match & time
        clone.querySelector('.signal-match').textContent     = arb.match || 'Unknown Match';
        clone.querySelector('.signal-time-text').textContent = formatDate(arb.detected_at);

        // ── Badge ──
        const badge = clone.querySelector('.signal-badge');
        if (arb._type === 'manual') {
            badge.textContent = '⊙ WATCHING';
            badge.classList.add('badge-watch');
        } else if (arb.is_live) {
            badge.textContent = '🔴 LIVE';
            badge.classList.add('badge-live');
        } else {
            badge.textContent = '⚡ ARB';
            // default green styling already in CSS
        }

        // ── Bookmaker tags ──
        const tagsEl = clone.querySelector('.bm-tags');
        const bms = arb.bookmakers?.length ? arb.bookmakers
            : arb.legs ? arb.legs.map(l => l.bookmaker) : [];
        tagsEl.innerHTML = bms.map(b => `<span class="bm-tag">${dn(b)}</span>`).join('');

        // ── Metrics row ──
        const marketText = `${arb.market_type||''} ${arb.line||''}`.trim() || '—';
        clone.querySelector('.metric-market').textContent = marketText;

        if (arb._type === 'engine') {
            clone.querySelector('.metric-edge').textContent   = arb.margin_pct != null ? `+${fmt(arb.margin_pct)}%` : '—';
            clone.querySelector('.metric-profit').textContent = arb.profit      != null ? `+$${fmt(arb.profit)}` : '—';
        } else {
            // manual target
            clone.querySelector('.metric-edge').textContent   = '—';
            clone.querySelector('.metric-profit').textContent = arb.target_odds ? `@ ${fmt(arb.target_odds)}` : '—';
        }

        // ── Odds detail block ──
        const oddsDetail = clone.querySelector('.odds-detail');
        if (arb._type === 'engine' && arb.legs && arb.legs.length >= 2) {
            const [l1, l2] = arb.legs;
            clone.querySelector('.bm1-label').textContent = dn(l1.bookmaker);
            clone.querySelector('.bm2-label').textContent = dn(l2.bookmaker);
            setOdds(clone, '.bm1-odds', '.bm1-dir', `${id}_1`, l1.odds);
            setOdds(clone, '.bm2-odds', '.bm2-dir', `${id}_2`, l2.odds);
        } else {
            oddsDetail.style.display = 'none';
        }

        // ── Update action ──
        const updateAction = clone.querySelector('.update-action');
        if (arb._type === 'engine') {
            // Engine arbs don't need manual odds input
            updateAction.style.display = 'none';
        } else {
            // Manual target: show input
            const btn   = clone.querySelector('.btn-update');
            const input = clone.querySelector('.odds-input');
            btn.addEventListener('click', () => {
                const val = input.value.trim();
                if (val) {
                    btn.textContent = 'Updated ✓';
                    btn.style.opacity = '0.7';
                    setTimeout(() => { btn.textContent='Update'; btn.style.opacity='1'; input.value=''; }, 2000);
                }
            });
        }

        // ── Delete button ──
        const delBtn = clone.querySelector('.btn-delete');
        if (arb._type === 'manual' && arb.id) {
            delBtn.addEventListener('click', async () => {
                delBtn.disabled = true; delBtn.style.opacity = '0.4';
                await api(`manual_targets/${arb.id}`, { method:'DELETE' });
                loadData();
            });
        } else {
            delBtn.style.display = 'none';
        }

        // ── Notify button ──
        const notBtn = clone.querySelector('.btn-notify');
        notBtn.addEventListener('click', () => {
            notBtn.style.color = 'var(--green)';
            setTimeout(() => notBtn.style.color = '', 1500);
        });

        container.appendChild(clone);
    });
}

// Flash odds cell if value changed
function setOdds(clone, oSel, dSel, key, newVal) {
    const oEl = clone.querySelector(oSel);
    const dEl = clone.querySelector(dSel);
    oEl.textContent = fmt(newVal);
    const prev = prevOddsMap[key];
    if (prev != null && prev !== newVal) {
        const up = newVal > prev;
        oEl.parentElement.classList.add(up ? 'flash-green' : 'flash-red');
        dEl.textContent = up ? '↑' : '↓';
        dEl.className = `odds-arrow ${up ? 'up' : 'down'}`;
        setTimeout(() => oEl.parentElement.classList.remove('flash-green','flash-red'), 1000);
    } else { dEl.textContent = ''; }
    prevOddsMap[key] = newVal;
}

// ─────────────────────────────────────────────────────────────
// ENGINE STATUS
// ─────────────────────────────────────────────────────────────
async function checkEngine() {
    const s = await api('status');
    if (!s) return;
    const btn  = document.getElementById('engine-toggle-btn');
    const span = btn?.querySelector('.status-text');
    if (!btn || !span) return;
    const online = s.engine_state !== 'offline';
    btn.classList.toggle('offline', !online);
    span.textContent = online ? 'ONLINE' : 'OFFLINE';
}

// ─────────────────────────────────────────────────────────────
// DRAWER helpers
// ─────────────────────────────────────────────────────────────
function openDrawer()  { document.getElementById('bm-drawer')?.classList.add('open');    document.getElementById('drawer-overlay')?.classList.add('active'); }
function closeDrawer() { document.getElementById('bm-drawer')?.classList.remove('open'); document.getElementById('drawer-overlay')?.classList.remove('active'); }

// ─────────────────────────────────────────────────────────────
// MODAL helpers
// ─────────────────────────────────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.add('active'); }
function closeModal(id) { document.getElementById(id)?.classList.remove('active'); }

// ─────────────────────────────────────────────────────────────
// MATCH SEARCH  (New Signal modal)
// ─────────────────────────────────────────────────────────────
let selectedMatchData = null;   // { match, market_type, bookmakers }
let searchDebounce    = null;

function initMatchSearch() {
    const input      = document.getElementById('target-match');
    const results    = document.getElementById('search-results');
    const clearBtn   = document.getElementById('search-clear');
    const selectedEl = document.getElementById('selected-match');
    const selectedTx = document.getElementById('selected-match-text');
    const deselectBtn= document.getElementById('deselect-match');
    if (!input) return;

    // Reset state
    selectedMatchData = null;
    input.value = '';
    input.disabled = false;
    input.style.borderRadius = '';
    results.style.display = 'none';
    selectedEl.style.display = 'none';
    clearBtn.style.display = 'none';

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearBtn.style.display = q ? 'block' : 'none';
        clearTimeout(searchDebounce);
        if (!q) { results.style.display = 'none'; return; }
        searchDebounce = setTimeout(() => runSearch(q), 180);
    });

    clearBtn.addEventListener('click', () => {
        input.value = ''; clearBtn.style.display = 'none';
        results.style.display = 'none';
    });

    deselectBtn?.addEventListener('click', () => {
        selectedMatchData = null;
        selectedEl.style.display = 'none';
        input.disabled = false;
        input.value = '';
        input.style.borderRadius = '';
        clearBtn.style.display = 'none';
        results.style.display = 'none';
    });

    function runSearch(q) {
        const lower = q.toLowerCase();
        // Search from currently loaded engine signals
        const hits = allSignalsData.filter(s =>
            s._type === 'engine' && s.match &&
            s.match.toLowerCase().includes(lower)
        );

        results.style.display = 'block';
        input.style.borderRadius = 'var(--r-sm) var(--r-sm) 0 0';

        if (!hits.length) {
            results.innerHTML = `
              <div class="search-empty">
                <strong>Hakuna kitu kama hiyo 🔍</strong>
                Hakuna mechi inayolingana na "${escHtml(q)}".
                Unaweza kuandika jina lolote la mechi hapa chini.
              </div>`;
            return;
        }

        results.innerHTML = hits.slice(0, 8).map((s, i) => {
            const market = `${s.market_type||''} ${s.line||''}`.trim();
            const bms    = (s.legs || []).map(l => dn(l.bookmaker)).join(' vs ');
            const edge   = s.margin_pct != null ? `+${fmt(s.margin_pct)}%` : '';
            const highlighted = s.match.replace(
                new RegExp(`(${escRegex(q)})`, 'gi'),
                '<em>$1</em>'
            );
            return `<div class="search-result-item" data-idx="${i}">
                <span class="result-match">${highlighted}</span>
                <span class="result-meta">
                    ${market ? `<span>${market}</span>` : ''}
                    ${bms    ? `<span>${bms}</span>` : ''}
                    ${edge   ? `<span style="color:var(--green)">${edge}</span>` : ''}
                </span>
            </div>`;
        }).join('');

        // Bind click on each result
        results.querySelectorAll('.search-result-item').forEach((el, i) => {
            el.addEventListener('click', () => {
                const s = hits[i];
                selectedMatchData = s;
                // Show pill, hide input & results
                selectedTx.textContent = s.match;
                selectedEl.style.display = 'flex';
                results.style.display = 'none';
                input.value = '';
                input.disabled = true;
                clearBtn.style.display = 'none';
                input.style.borderRadius = 'var(--r-sm)';
                // Auto-fill market if present
                const marketInput = document.getElementById('target-market');
                if (marketInput && s.market_type) {
                    marketInput.value = `${s.market_type} ${s.line||''}`.trim();
                }
            });
        });
    }
}

function escHtml(s)  { return s.replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':\'&#39;\'}[c])); }
function escRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'); }

// ─────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadSound();
    fetchBookmakers();
    loadData();
    checkEngine();

    // Retry button on connection banner
    document.getElementById('api-retry-btn')?.addEventListener('click', () => {
        setBannerState(true); // hide while retrying
        loadData();
        checkEngine();
    });

    // Auto-monitor toggle (start polling on)
    const toggle = document.getElementById('auto-monitor-toggle');
    if (toggle) {
        toggle.checked = true;
        pollTimer = setInterval(() => { loadData(); checkEngine(); }, 3000);
        toggle.addEventListener('change', e => {
            if (e.target.checked) {
                pollTimer = setInterval(() => { loadData(); checkEngine(); }, 3000);
                loadData();
            } else {
                clearInterval(pollTimer); pollTimer = null;
            }
        });
    }

    // Register Service Worker for PWA
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('sw.js').catch(err => {
                console.warn('Service worker registration failed:', err);
            });
        });
    }

    // Filter tabs
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.filter-tab').forEach(t=>t.classList.remove('active'));
            tab.classList.add('active');
            currentFilter = tab.dataset.filter;
            renderSignals(allSignalsData);
        });
    });

    // Engine toggle
    document.getElementById('engine-toggle-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('engine-toggle-btn');
        const isOnline = !btn.classList.contains('offline');
        const res = await api('engine/toggle', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ status: isOnline ? 'offline' : 'online' }),
        });
        if (res) checkEngine();
    });

    // Bookmaker drawer
    document.getElementById('bookmakers-btn')?.addEventListener('click', () => { fetchBookmakers(); openDrawer(); });
    document.getElementById('close-drawer-btn')?.addEventListener('click', closeDrawer);
    document.getElementById('drawer-overlay')?.addEventListener('click', closeDrawer);

    // New Signal modal
    const openSig  = () => {
        selectedBookmakers.clear();
        renderChips();
        openModal('signal-modal');
        // init search AFTER modal is visible so elements are in DOM
        setTimeout(initMatchSearch, 50);
    };
    const closeSig = () => closeModal('signal-modal');
    document.getElementById('header-new-signal-btn')?.addEventListener('click', openSig);
    document.getElementById('new-signal-btn')?.addEventListener('click', openSig);
    document.getElementById('close-modal-btn')?.addEventListener('click', closeSig);
    document.getElementById('signal-modal')?.addEventListener('click', e => { if(e.target.id==='signal-modal') closeSig(); });

    document.getElementById('submit-target-btn')?.addEventListener('click', async () => {
        // If user selected a result use that match name, otherwise use typed value
        const matchName = selectedMatchData
            ? selectedMatchData.match
            : document.getElementById('target-match').value.trim();
        const market = document.getElementById('target-market').value.trim();
        const odds   = parseFloat(document.getElementById('target-odds').value);
        if (!matchName) { alert('Tafadhali chagua au andika jina la mechi.'); return; }
        if (!market || isNaN(odds) || odds <= 0) { alert('Please fill all fields correctly.'); return; }
        const res = await api('manual_targets', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ match: matchName, market, target_odds:odds,
                auto_monitor: document.getElementById('target-auto-monitor').checked,
                bookmakers: [...selectedBookmakers] }),
        });
        if (res?.success) {
            closeSig();
            selectedMatchData = null;
            ['target-match','target-market','target-odds'].forEach(id => { const el=document.getElementById(id); if(el) el.value=''; });
            loadData();
        } else { alert('Failed to save — is the API server running?'); }
    });

    // Sound modal
    const openSnd  = () => {
        document.getElementById('sound-enabled-toggle').checked = Sound.enabled;
        document.getElementById('sound-volume').value = Math.round(Sound.volume * 100);
        document.querySelectorAll('.tone-btn').forEach(b=>b.classList.toggle('selected', b.dataset.tone===Sound.tone));
        const upg = document.getElementById('custom-upload-group');
        if (upg) upg.style.display = Sound.tone==='custom' ? 'flex' : 'none';
        openModal('sound-modal');
    };
    const closeSnd = () => closeModal('sound-modal');
    document.getElementById('notif-btn')?.addEventListener('click', openSnd);
    document.getElementById('close-sound-modal-btn')?.addEventListener('click', closeSnd);
    document.getElementById('sound-modal')?.addEventListener('click', e=>{ if(e.target.id==='sound-modal') closeSnd(); });

    document.getElementById('sound-enabled-toggle')?.addEventListener('change', e=>Sound.enabled=e.target.checked);
    document.getElementById('sound-volume')?.addEventListener('input', e=>Sound.volume=parseInt(e.target.value)/100);
    document.getElementById('preview-sound-btn')?.addEventListener('click', playAlert);

    document.querySelectorAll('.tone-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tone-btn').forEach(b=>b.classList.remove('selected'));
            btn.classList.add('selected');
            Sound.tone = btn.dataset.tone;
            const upg = document.getElementById('custom-upload-group');
            if (upg) upg.style.display = Sound.tone==='custom' ? 'flex' : 'none';
            if (Sound.tone !== 'custom') playAlert();
        });
    });

    // Custom ringtone
    const uz = document.getElementById('upload-zone');
    const fi = document.getElementById('ringtone-file');
    uz?.addEventListener('click', ()=>fi?.click());
    fi?.addEventListener('change', () => {
        const file = fi.files[0]; if (!file) return;
        const reader = new FileReader();
        reader.onload = e => {
            Sound.customDataUrl = e.target.result; Sound.tone = 'custom';
            const fn = document.getElementById('upload-filename');
            if (fn) fn.textContent = `✓ ${file.name}`;
        };
        reader.readAsDataURL(file);
    });

    document.getElementById('save-sound-btn')?.addEventListener('click', () => {
        Sound.enabled = document.getElementById('sound-enabled-toggle').checked;
        Sound.volume  = parseInt(document.getElementById('sound-volume').value)/100;
        saveSound(); closeSnd();
    });
});
