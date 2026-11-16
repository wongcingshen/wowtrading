const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const gold = c => {
  if (c == null) return '–';
  c = Math.round(c); const g = Math.floor(c / 10000), s = Math.floor(c / 100) % 100, cp = c % 100;
  return g ? `${g.toLocaleString()}g ${s}s` : s ? `${s}s ${cp}c` : `${cp}c`;
};
const pct = (x, d = 0) => x == null ? '–' : `${x > 0 ? '+' : ''}${(x * 100).toFixed(d)}%`;
const num = (x, d = 0) => x == null ? '–' : (Math.abs(x) < 0.5 / 10 ** d ? 0 : Number(x)).toLocaleString(undefined, { maximumFractionDigits: d });
const ago = iso => { const m = (Date.now() - new Date(iso)) / 60000; return m < 90 ? `${Math.round(m)} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
let DATA, dirFilter = 'all', open = null;

function badge(it) {
  if (it.score == null) return '<span class="badge none">NO SCORE YET</span>';
  if (it.score >= 30) return '<span class="badge buy">▲ BUY</span>';
  if (it.score <= -30) return '<span class="badge sell">▼ SELL / AVOID</span>';
  return '<span class="badge none">● NEUTRAL</span>';
}

function chart(vals, t0, fmt, color, ref, refLabel, zero) {
  const W = 340, H = 120, L = 6, R = 6, T = 14, B = 18;
  const pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '<p class="muted">Not enough history yet.</p>';
  let lo = Math.min(...pts.map(p => p[1]), ref ?? Infinity), hi = Math.max(...pts.map(p => p[1]), ref ?? -Infinity);
  if (hi === lo) { hi += 1; lo = Math.max(0, lo - 1); }
  if (zero) lo = 0;
  const pad = (hi - lo) * 0.08; if (!zero) lo -= pad; hi += pad;
  const x = i => L + i / (vals.length - 1) * (W - L - R), y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const d = pts.map((p, k) => `${k ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  const tick = i => new Date(new Date(t0).getTime() + i * 3600e3).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric' });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" data-t0="${t0}" data-vals='${JSON.stringify(vals)}' data-fmt="${fmt}" data-lo="${lo}" data-hi="${hi}">
    <line x1="${L}" x2="${W - R}" y1="${y(hi - pad)}" y2="${y(hi - pad)}" stroke="var(--grid)"/>
    <line x1="${L}" x2="${W - R}" y1="${y(zero ? 0 : lo + pad)}" y2="${y(zero ? 0 : lo + pad)}" stroke="var(--axis)"/>
    <text x="${L}" y="${y(hi - pad) - 3}">${fmt === 'gold' ? gold(hi - pad) : num(hi - pad)}</text>
    <text x="${L}" y="${H - 5}">${zero ? '0' : fmt === 'gold' ? gold(lo + pad) : num(lo + pad)} · ${tick(0)}</text>
    <text x="${W - R}" y="${H - 5}" text-anchor="end">${tick(vals.length - 1)}</text>
    ${ref != null ? `<line x1="${L}" x2="${W - R}" y1="${y(ref)}" y2="${y(ref)}" stroke="var(--text-secondary)" stroke-dasharray="3 3"/>
      <text x="${L}" y="${y(ref) + 12}">${refLabel}</text>` : ''}
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(last[0])}" cy="${y(last[1])}" r="4" fill="${color}" stroke="var(--surface-1)" stroke-width="2"/>
    <g class="hover" style="display:none"><line y1="${T}" y2="${H - B}" stroke="var(--axis)"/><circle r="4" fill="${color}" stroke="var(--surface-1)" stroke-width="2"/></g>
  </svg>`;
}

function detail(it) {
  const s = it.series;
  return `<div class="detail">
    ${it.event ? `<p class="sub">Event: ${esc(it.event)}</p>` : ''}
    <div class="kv">
      <div>Floor price<b>${gold(it.floor)}</b></div><div>Price vs normal<b>${num(it.z_price, 1)} σ</b></div><div>Supply vs normal<b>${num(it.z_supply, 1)} σ</b></div>
      <div>Listed units<b>${num(it.qty)}</b></div><div>Est. sold / day<b>${num(it.sold24)}</b></div><div>Max units<b>${num(it.max_units)}</b></div>
      <div>Expected 24h return<b>${pct(it.exp_ret, 1)}</b></div><div>Daily volatility<b>${it.vol == null ? '–' : (it.vol * 100).toFixed(1) + '%'}</b></div><div>Reversion half-life<b>${it.half_life == null ? '–' : num(it.half_life) + ' h'}</b></div>
      ${it.alt_qty != null ? `<div>Substitute units<b>${num(it.alt_qty)}</b></div>` : ''}
    </div>
    ${s ? `<h3>Price, last 72 hours</h3>${chart(s.p, s.t0, 'gold', 'var(--series-1)', it.normal, 'normal ' + gold(it.normal))}
    <h3>Listed units, last 72 hours</h3>${chart(s.q, s.t0, 'num', 'var(--series-2)', null, null, true)}` : ''}
    <p><a href="https://www.wowhead.com/classic/item=${it.id}" target="_blank" rel="noopener">Item #${it.id} on Wowhead</a></p></div>`;
}

function card(it, key) {
  const isOpen = open === key;
  return `<div class="card"><button data-key="${key}" aria-expanded="${isOpen}">
    <div class="row1"><span class="name">${esc(it.name)}</span>${badge(it)}<span class="score">${it.score == null ? '' : (it.score > 0 ? '+' : '') + Math.round(it.score)}</span></div>
    <div class="sub">${esc(it.signals || it.cls || '')}</div>
    <div class="kv"><div>Price<b>${gold(it.price)}</b></div>
      <div>${it.score != null && it.score < 0 ? 'Normal price' : 'Net margin'}<b>${it.score != null && it.score < 0 ? gold(it.normal) : pct(it.net_margin)}</b></div>
      <div>Days of supply<b>${num(it.dos, 1)}</b></div>
      <div>Price 24h<b class="${it.chg24 > 0 ? 'up' : it.chg24 < 0 ? 'down' : ''}">${it.chg24 > 0 ? '▲ ' : it.chg24 < 0 ? '▼ ' : ''}${pct(it.chg24)}</b></div>
      <div>Supply 24h<b>${pct(it.qchg24)}</b></div><div>Listings<b>${num(it.listings)}</b></div></div>
    </button>${isOpen ? detail(it) : ''}</div>`;
}

function render() {
  const m = DATA.meta;
  $('#status').textContent = `${m.faction} · ${m.region.toUpperCase()} · snapshot ${ago(m.snapshot)} · ${m.n_snapshots} hourly snapshots · ${num(m.items_tracked)} items`;
  let b = '';
  if (m.warmup) b += `<div class="banner"><b>Collecting history.</b> ${m.n_snapshots} of ${m.warmup_snapshots} snapshots needed before email alerts start. Scores appear per item after ${m.min_obs} snapshots.
    <div class="bar"><i style="width:${Math.min(100, m.n_snapshots / m.warmup_snapshots * 100)}%"></i></div></div>`;
  if (!m.has_sales) b += `<div class="banner">Sales estimates need about 6 hourly snapshots.</div>`;
  if (m.ambiguous && DATA.house_check) {
    const hc = DATA.house_check, hs = hc.candidates.filter(c => c.listings > 0);
    b += `<div class="banner"><b>Confirm your auction house.</b> Blizzard's data lists ${hs.length} ${esc(m.faction)} houses without saying which ruleset each belongs to. All are being recorded. Showing house ${m.house} for now. Compare these floor prices with your in-game auction house and tell Claude which column matches.
      <table><tr><th>Item</th>${hs.map(h => `<th>House ${h.id}</th>`).join('')}</tr>
      ${hc.samples.map(s => `<tr><td>${esc(s.name)}</td>${hs.map(h => `<td>${gold(s.floor[h.id])}</td>`).join('')}</tr>`).join('')}
      <tr><td>Listings</td>${hs.map(h => `<td>${num(h.listings)}</td>`).join('')}</tr></table></div>`;
  }
  if ((Date.now() - new Date(m.snapshot)) > 3 * 3600e3) b += `<div class="banner"><b>Data is stale.</b> The last snapshot is ${ago(m.snapshot)}. Check the collector run in GitHub Actions.</div>`;
  $('#banners').innerHTML = b;

  const sig = DATA.signals.filter(s => dirFilter === 'all' || (dirFilter === 'buy' ? s.score > 0 : s.score < 0));
  $('#signal-list').innerHTML = sig.length ? sig.map(s => card(s, 's' + s.id)).join('')
    : `<div class="empty">${m.n_snapshots < m.min_obs ? 'No scores yet. The indicator needs ' + m.min_obs + ' hourly snapshots per item.' : 'No signals right now.'}</div>`;
  const q = $('#search').value.trim().toLowerCase();
  const mk = DATA.market.filter(i => !q || i.name.toLowerCase().includes(q));
  $('#market-list').innerHTML = mk.length ? mk.slice(0, 80).map(i => card(i, 'm' + i.id)).join('') : '<div class="empty">No items match.</div>';
  $('#event-list').innerHTML = DATA.events.length ? DATA.events.map(e => `<div class="card"><button disabled>
    <div class="row1"><span class="name">${esc(e.name)}</span><span class="score">${e.days >= 0 ? 'in ' + e.days + ' d' : Math.abs(e.days) + ' d ago'}</span></div>
    <div class="sub">${e.date} · accumulation window starts ${e.lead_days} days before${e.source ? ' · ' + esc(e.source) : ''}</div></button></div>`).join('')
    : '<div class="empty">No events configured.</div>';
  renderLearning();
}

const LABEL = { reversion: 'Price below normal', supply: 'Supply below normal', momentum: 'Rising price while supply contracts', trend: 'Trend-following', cover: 'Low days of cover', event: 'Event ahead', alternatives: 'Cheap vs alternatives' };
function renderLearning() {
  const md = DATA.model, tr = DATA.track || [];
  if (!md) { $('#learning-body').innerHTML = '<div class="empty">No model data yet.</div>'; return; }
  const w = k => (md.used[k] ?? 0).toFixed(2), f = (o, k) => o ? o[k].toFixed(2) : '–';
  const rr = r => r.n ? `${Math.round(r.hit * 100)}% · ${pct(r.mean, 1)}` : '–';
  $('#learning-body').innerHTML = `
    <h2>Model weights</h2>
    <p class="note">${Math.round(md.alpha * 100)}% learned from outcomes, ${Math.round((1 - md.alpha) * 100)}% starting assumptions. Based on ${num(md.n_eff)} item-hours of evidence, each scored on the net return ${md.horizon_hours} hours later. Evidence older than ${md.half_life_days} days counts half.</p>
    <div class="bar"><i style="width:${md.alpha * 100}%"></i></div>
    <table class="t"><tr><th>Component</th><th>Start</th><th>Learned</th><th>In use</th></tr>
    ${Object.keys(md.prior).map(k => `<tr><td>${LABEL[k] || k}</td><td>${md.prior[k].toFixed(2)}</td><td>${f(md.learned, k)}</td><td><b>${w(k)}</b></td></tr>`).join('')}</table>
    <p class="note">A negative learned weight means that component has predicted losses, and the score now counts it against an item.</p>
    <h2>Track record of signals shown</h2>
    <p class="note">Every signal with an absolute score of 30 or more is logged when it appears, then checked 24 and 72 hours later. Buy: share with a positive net return after the auction house cut, and the average net return. Sell: share where the price fell, and the average price change.</p>
    <table class="t"><tr><th>Signal</th><th>Count</th><th>After 24h</th><th>After 72h</th></tr>
    ${tr.map(r => `<tr><td>${r.dir === 'buy' ? '▲ Buy' : '▼ Sell'} ${r.bucket}</td><td>${r.signals}</td><td>${rr(r.r24)}</td><td>${rr(r.r72)}</td></tr>`).join('')}</table>`;
}

document.addEventListener('click', e => {
  const tab = e.target.closest('[role=tab]');
  if (tab) {
    document.querySelectorAll('[role=tab]').forEach(t => t.setAttribute('aria-selected', t === tab));
    ['signals', 'market', 'events', 'learning', 'help'].forEach(id => $('#' + id).hidden = id !== tab.dataset.tab);
    return;
  }
  const chip = e.target.closest('.chip');
  if (chip) { dirFilter = chip.dataset.dir; document.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', c === chip)); return render(); }
  const btn = e.target.closest('.card>button[data-key]');
  if (btn) { open = open === btn.dataset.key ? null : btn.dataset.key; render(); }
});
$('#search').addEventListener('input', render);

const tip = $('#tip');
function hover(e) {
  const svg = e.target.closest && e.target.closest('svg.chart');
  if (!svg) { tip.hidden = true; document.querySelectorAll('svg .hover').forEach(g => g.style.display = 'none'); return; }
  const vals = JSON.parse(svg.dataset.vals), r = svg.getBoundingClientRect(), W = 340, H = 120, L = 6, R = 6, T = 14, B = 18;
  const fx = (e.clientX - r.left) / r.width * W;
  let i = Math.round((fx - L) / (W - L - R) * (vals.length - 1)); i = Math.max(0, Math.min(vals.length - 1, i));
  while (i > 0 && vals[i] == null) i--;
  if (vals[i] == null) return;
  const lo = +svg.dataset.lo, hi = +svg.dataset.hi, x = L + i / (vals.length - 1) * (W - L - R), y = T + (1 - (vals[i] - lo) / (hi - lo)) * (H - T - B);
  const g = $('.hover', svg); g.style.display = '';
  $('line', g).setAttribute('x1', x); $('line', g).setAttribute('x2', x); $('circle', g).setAttribute('cx', x); $('circle', g).setAttribute('cy', y);
  const when = new Date(new Date(svg.dataset.t0).getTime() + i * 3600e3).toLocaleString(undefined, { weekday: 'short', hour: 'numeric' });
  tip.textContent = `${when}: ${svg.dataset.fmt === 'gold' ? gold(vals[i]) : num(vals[i])}`;
  tip.hidden = false;
  tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 6, Math.max(6, e.clientX - tip.offsetWidth / 2)) + 'px';
  tip.style.top = (r.top + y / H * r.height - 34) + 'px';
}
document.addEventListener('pointermove', hover);
document.addEventListener('pointerdown', hover);

fetch('data/latest.json?_=' + Date.now()).then(r => { if (!r.ok) throw 0; return r.json(); }).then(d => { DATA = d; render(); })
  .catch(() => { $('#status').textContent = 'No data yet. The first hourly collection has not run.'; });
