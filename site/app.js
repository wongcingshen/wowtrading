const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const parts = c => { c = Math.max(0, Math.round(c)); return [Math.floor(c / 10000), Math.floor(c / 100) % 100, c % 100]; };
// money as the game shows it: numbers followed by gold, silver and copper coins
const coin = c => {
  if (c == null) return '–';
  const [g, s, cp] = parts(c), out = [];
  if (g) out.push(`${g.toLocaleString()}<i class="g"></i>`);
  if (s || g) out.push(`${s}<i class="s"></i>`);
  if (!g) out.push(`${cp}<i class="c"></i>`);
  return `<span class="coin" aria-label="${plain(c)}">${out.join('')}</span>`;
};
const plain = c => { if (c == null) return '–'; const [g, s, cp] = parts(c); return g ? `${g.toLocaleString()}g ${s}s` : s ? `${s}s ${cp}c` : `${cp}c`; };
const pct = (x, d = 0) => { if (x == null) return '–'; const v = Math.abs(x * 100).toFixed(d); return `${+v === 0 ? '' : x > 0 ? '+' : '−'}${v}%`; };
const num = (x, d = 0) => x == null ? '–' : (Math.abs(x) < 0.5 / 10 ** d ? 0 : Number(x)).toLocaleString(undefined, { maximumFractionDigits: d });
const ago = iso => { const m = Math.max(0, (Date.now() - new Date(iso)) / 60000); return m < 1.5 ? 'just now' : m < 90 ? `${Math.round(m)} min ago` : m < 2880 ? `${Math.round(m / 60)} hours ago` : `${Math.round(m / 1440)} days ago`; };
const RULESET = { 1: 'PvP', 2: 'Normal', 3: 'Roleplay', 15: 'Roleplay PvP' };

let DATA, dirFilter = 'all', sortBy = 'traded', open = null;

const side = it => it.score == null ? 'flat' : it.score >= 30 ? 'buy' : it.score <= -30 ? 'sell' : 'flat';
const level = it => { const a = Math.abs(it.score ?? 0); return a >= 60 ? 3 : a >= 45 ? 2 : a >= 30 ? 1 : 0; };
function verdict(it) {
  const s = side(it), l = level(it);
  if (s === 'flat') return `<span class="verdict flat">${it.score == null ? 'No score yet' : 'No call'}</span>`;
  const word = ['', 'Lean', 'Solid', 'Strong'][l] + (s === 'buy' ? ' buy' : ' sell');
  return `<span class="verdict ${s}" title="Score ${Math.round(it.score)}"><span class="bars" aria-hidden="true">${[1, 2, 3].map(i => `<i class="${i <= l ? 'on' : ''}"></i>`).join('')}</span>${word}</span>`;
}

// what to do, in a sentence
function action(it) {
  const s = side(it), sq = (it.signals || '').includes('Squeeze');
  if (s === 'buy') {
    const cap = it.max_units ? `up to <b>${num(it.max_units)}</b> ` : '';
    return sq && !(it.net_margin > 0)
      ? `Buy ${cap}at ${coin(it.price)} or less. Sell when listings recover.`
      : `Buy ${cap}at ${coin(it.price)} or less. Aim to sell near ${coin(it.normal)}.`;
  }
  if (s === 'sell') return (it.signals || '').includes('Flood')
    ? `Stay out. Selling at ${coin(it.price)}, normal is ${coin(it.normal)}.`
    : `If you hold it, sell near ${coin(it.price)}. Normal is ${coin(it.normal)}.`;
  return `Selling at ${coin(it.price)}. Normal is ${it.normal ? coin(it.normal) : 'not known yet'}.`;
}
// why, in a sentence
function reason(it) {
  const sg = it.signals || '', gap = it.normal ? it.price / it.normal - 1 : null, out = [];
  if (sg.includes('Squeeze')) out.push(`Units on sale are ${it.qchg24 != null && it.qchg24 < 0 ? 'down ' + pct(Math.abs(it.qchg24)).replace('+', '') + ' in a day' : 'far below normal'} and the price is climbing.`);
  if (sg.includes('Dip')) out.push(`Price is ${pct(Math.abs(gap)).replace('+', '')} below its normal while supply is steady.`);
  if (sg.includes('Spike')) out.push(`Price is ${pct(Math.abs(gap)).replace('+', '')} above its normal.`);
  if (sg.includes('Flood')) out.push('Listings are piling up and the price is falling.');
  if (sg.includes('Cheap vs alternatives')) out.push('Cheap next to similar items.');
  if (it.event) out.push(esc(it.event.replace(/ in (\d+)d$/, (_, d) => d === '0' ? ' today' : ` in ${d} day${d === '1' ? '' : 's'}`)) + '.');
  if (!out.length && gap != null && side(it) !== 'flat') out.push(side(it) === 'buy'
    ? `Price is ${pct(Math.abs(gap)).replace('+', '')} ${gap < 0 ? 'below' : 'above'} normal and supply is ${it.z_supply < -0.5 ? 'tight' : 'steady'}.`
    : `Price is ${pct(Math.abs(gap)).replace('+', '')} ${gap < 0 ? 'below' : 'above'} normal and supply is ${it.z_supply > 0.5 ? 'building' : 'steady'}.`);
  return out.join(' ');
}

function spark(vals) {
  const p = vals.map((v, i) => [i, v]).filter(q => q[1] != null);
  if (p.length < 2) return '';
  const lo = Math.min(...p.map(q => q[1])), hi = Math.max(...p.map(q => q[1])) || 1, W = 120, H = 36, n = vals.length - 1;
  const x = i => 3 + i / n * (W - 8), y = v => 5 + (1 - (hi === lo ? .5 : (v - lo) / (hi - lo))) * (H - 10);
  const e = p[p.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="${p.map((q, k) => `${k ? 'L' : 'M'}${x(q[0]).toFixed(1)},${y(q[1]).toFixed(1)}`).join('')}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${x(e[0])}" cy="${y(e[1])}" r="3.5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/></svg>`;
}

function chart(vals, t0, fmt, color, ref, refLabel, zero) {
  const W = 340, H = 124, L = 4, R = 6, T = 16, B = 18;
  const pts = vals.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return '<p class="read">Not enough history yet.</p>';
  let lo = Math.min(...pts.map(p => p[1]), ref ?? Infinity), hi = Math.max(...pts.map(p => p[1]), ref ?? -Infinity);
  if (hi === lo) { hi += 1; lo = Math.max(0, lo - 1); }
  if (zero) lo = 0;
  const pad = (hi - lo) * 0.08; if (!zero) lo -= pad; hi += pad;
  const x = i => L + i / (vals.length - 1) * (W - L - R), y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const d = pts.map((p, k) => `${k ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
  const last = pts[pts.length - 1], f = v => fmt === 'gold' ? plain(v) : num(v);
  const tick = i => new Date(new Date(t0).getTime() + i * 3600e3).toLocaleString(undefined, { weekday: 'short', hour: 'numeric' });
  const base = zero ? 0 : lo + pad;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" data-t0="${t0}" data-vals='${JSON.stringify(vals)}' data-fmt="${fmt}" data-lo="${lo}" data-hi="${hi}">
    <line x1="${L}" x2="${W - R}" y1="${y(hi - pad)}" y2="${y(hi - pad)}" stroke="var(--grid)"/>
    <line x1="${L}" x2="${W - R}" y1="${y(base)}" y2="${y(base)}" stroke="var(--axis)"/>
    <text x="${L}" y="${y(hi - pad) - 4}">${f(hi - pad)}</text>
    <text x="${L}" y="${H - 4}">${zero ? '0' : f(base)}, ${tick(0)}</text>
    <text x="${W - R}" y="${H - 4}" text-anchor="end">${tick(vals.length - 1)}</text>
    ${ref != null ? `<line x1="${L}" x2="${W - R}" y1="${y(ref)}" y2="${y(ref)}" stroke="var(--ink-3)" stroke-dasharray="3 4"/><text x="${L}" y="${y(ref) + 12}">${refLabel}</text>` : ''}
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(last[0])}" cy="${y(last[1])}" r="4" fill="${color}" stroke="var(--surface-1)" stroke-width="2"/>
    <g class="hover" style="display:none"><line y1="${T}" y2="${H - B}" stroke="var(--axis)"/><circle r="4" fill="${color}" stroke="var(--surface-1)" stroke-width="2"/></g></svg>`;
}

function more(it) {
  const s = it.series;
  let read = '';
  if (it.exp_ret != null && it.vol != null) read = Math.abs(it.exp_ret) < it.vol
    ? `The model forecasts ${pct(it.exp_ret, 1)} over 24 hours. This item usually swings ${(it.vol * 100).toFixed(1)}% a day, so that forecast is inside the noise.`
    : `The model forecasts ${pct(it.exp_ret, 1)} over 24 hours, larger than this item's usual daily swing of ${(it.vol * 100).toFixed(1)}%.`;
  return `<div class="more">
    <div class="facts">
      <div>Cheapest listing<b>${coin(it.floor)}</b></div>
      <div>After the cut<b>${pct(it.net_margin)}</b></div>
      <div>Units on sale<b>${num(it.qty)}</b></div>
      <div>Sold per day, est.<b>${num(it.sold24)}</b></div>
      <div>Days of cover<b>${num(it.dos, 1)}</b></div>
      <div>Units, 24 hours<b>${pct(it.qchg24)}</b></div>
      <div>Usual daily swing<b>${it.vol == null ? '–' : (it.vol * 100).toFixed(1) + '%'}</b></div>
      <div>Half-life<b>${it.half_life == null ? '–' : num(it.half_life) + ' hours'}</b></div>
      ${it.alt_qty != null ? `<div>Similar items on sale<b>${num(it.alt_qty)}</b></div>` : ''}
      ${it.score != null ? `<div>Score<b>${it.score > 0 ? '+' : ''}${Math.round(it.score)}</b></div>` : ''}
    </div>
    ${read ? `<p class="read">${read}</p>` : ''}
    ${s ? `<h3>Price, last 72 hours</h3>${chart(s.p, s.t0, 'gold', 'var(--series-1)', it.normal, 'normal ' + plain(it.normal))}
    <h3>Units on sale, last 72 hours</h3>${chart(s.q, s.t0, 'num', 'var(--series-2)', null, null, true)}` : ''}
    <p><a href="https://www.wowhead.com/classic/item=${it.id}" target="_blank" rel="noopener">Look up item ${it.id} on Wowhead</a></p></div>`;
}

function call(it, key) {
  const s = side(it), isOpen = open === key, strong = level(it) === 3;
  const gain = s === 'buy' ? (it.net_margin != null && it.net_margin > 0 ? `<div class="gain buy"><b>${pct(it.net_margin)}</b>after the cut</div>` : `<div class="gain"><b>${num(it.dos, 1)}</b>days of cover</div>`)
    : `<div class="gain ${s === 'sell' ? 'sell' : ''}"><b>${pct(it.normal ? it.price / it.normal - 1 : null)}</b>vs normal</div>`;
  return `<article class="call ${strong ? 'strong' : ''}"><button data-key="${key}" aria-expanded="${isOpen}">
    <div class="head"><span class="item"><i class="gem ${esc(it.q || '')}"></i>${esc(it.name)}</span>${verdict(it)}</div>
    <p class="do">${action(it)}</p>
    <p class="why">${reason(it)}</p>
    <div class="foot">${gain}${it.series ? spark(it.series.p) : ''}</div>
  </button>${isOpen ? more(it) : ''}</article>`;
}

function mrow(it, key) {
  const isOpen = open === key, c = it.chg24;
  return `<article class="mrow"><button data-key="${key}" aria-expanded="${isOpen}">
    <span class="item"><i class="gem ${esc(it.q || '')}"></i>${esc(it.name)}</span><span class="px">${coin(it.price)}</span>
    <span class="sub">${num(it.qty)} on sale${it.sold24 != null ? ', ' + num(it.sold24) + ' sold a day' : ''}</span>
    <span class="chg ${c > 0 ? 'up' : c < 0 ? 'down' : ''}">${c == null ? '' : (c > 0 ? '▲ ' : c < 0 ? '▼ ' : '') + pct(Math.abs(c)).replace('+', '')}</span>
  </button>${isOpen ? `<div class="more"><p class="do">${action(it)}</p><p class="why">${reason(it)}</p></div>` + more(it) : ''}</article>`;
}

function today() {
  const m = DATA.meta, sig = DATA.signals, stale = Date.now() - new Date(m.snapshot) > 3 * 3600e3;
  const buys = sig.filter(s => side(s) === 'buy').length, sells = sig.filter(s => side(s) === 'sell').length, strong = sig.filter(s => level(s) === 3).length;
  $('#fresh').textContent = 'Updated ' + ago(m.snapshot);
  $('#fresh').classList.toggle('stale', stale);
  $('#where').textContent = `${m.faction} auction house, ${RULESET[m.ruleset_id] || 'ruleset ' + m.ruleset_id}, ${m.region.toUpperCase()}`;
  let h;
  if (m.n_snapshots < m.min_obs) h = `<h2>Building price history</h2><p>${m.n_snapshots} of ${m.min_obs} hours recorded. The first calls appear when an item has ${m.min_obs} hours of prices.</p>
    <div class="meter"><i style="width:${m.n_snapshots / m.min_obs * 100}%"></i></div>`;
  else if (!buys && !sells) h = `<h2>Nothing worth acting on</h2><p>${num(m.items_tracked)} items checked. No price or supply is far enough from normal.</p>`;
  else h = `<h2>${strong ? `${strong} strong call${strong > 1 ? 's' : ''} right now` : 'No strong calls, a few leans'}</h2>
    <div class="tally"><div><b>${buys}</b>to buy</div><div><b>${sells}</b>to sell or avoid</div><div><b>${num(m.items_tracked)}</b>items checked</div></div>
    ${m.warmup ? `<p>Email alerts start after ${m.warmup_snapshots} hours of history. ${m.n_snapshots} so far.</p>` : ''}`;
  $('#today').innerHTML = h;

  let n = '';
  if (stale) n += `<div class="notice"><b>Prices stopped updating ${ago(m.snapshot)}.</b> Open the Actions tab of the GitHub repo and check the latest "Collect auction snapshot" run.</div>`;
  if (m.ambiguous && DATA.house_check) {
    const hc = DATA.house_check, hs = hc.candidates.filter(c => c.listings > 0);
    n += `<div class="notice"><b>Check which auction house is yours.</b> Blizzard lists ${hs.length} ${esc(m.faction)} houses without naming their rulesets. All ${hs.length} are being recorded, and house ${m.house} is shown for now. Compare these cheapest prices with the game and tell Claude which column matches.
      <table><tr><th>Item</th>${hs.map(h => `<th>House ${h.id}</th>`).join('')}</tr>
      ${hc.samples.map(s => `<tr><td>${esc(s.name)}</td>${hs.map(h => `<td>${coin(s.floor[h.id])}</td>`).join('')}</tr>`).join('')}</table></div>`;
  }
  $('#notices').innerHTML = n;
}

function render() {
  today();
  const m = DATA.meta;
  const sig = DATA.signals.filter(s => dirFilter === 'all' || side(s) === dirFilter);
  $('#call-list').innerHTML = sig.length ? sig.map(s => call(s, 's' + s.id)).join('')
    : `<div class="empty"><b>${m.n_snapshots < m.min_obs ? 'No calls yet' : 'No calls on this side'}</b>${m.n_snapshots < m.min_obs ? 'Prices are being recorded every hour. Browse them under Market.' : 'Try another filter, or browse prices under Market.'}</div>`;

  const q = $('#search').value.trim().toLowerCase();
  let mk = DATA.market.filter(i => !q || i.name.toLowerCase().includes(q));
  const by = { up: (a, b) => (b.chg24 ?? -9) - (a.chg24 ?? -9), down: (a, b) => (a.chg24 ?? 9) - (b.chg24 ?? 9), cheap: (a, b) => (a.z_price ?? 9) - (b.z_price ?? 9) }[sortBy];
  if (by) mk = [...mk].sort(by);
  const wl = (DATA.watch || []).filter(i => !q || i.name.toLowerCase().includes(q));
  $('#watch-list').innerHTML = wl.length ? `<h2 class="sect">Watching</h2>` + wl.map(i => mrow(i, 'w' + i.id)).join('') + `<h2 class="sect">Everything else</h2>` : '';
  $('#market-list').innerHTML = mk.length ? mk.slice(0, 80).map(i => mrow(i, 'm' + i.id)).join('') : `<div class="empty"><b>No item called "${esc(q)}"</b>Only the 150 most traded items are listed here.</div>`;

  $('#event-list').innerHTML = DATA.events.length ? DATA.events.map(e => {
    const openNow = e.days >= 0 && e.days <= e.lead_days, until = e.days - e.lead_days;
    return `<div class="event"><div class="count"><b>${Math.abs(e.days)}</b>${e.days >= 0 ? 'days to go' : 'days ago'}</div><div>
      <div class="item">${esc(e.name)}</div><p class="quiet">${new Date(e.date + 'T00:00:00Z').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' })}${e.source ? ', ' + esc(e.source) : ''}</p>
      <span class="phase ${openNow ? 'open' : ''}">${e.days < 0 ? 'Passed' : openNow ? 'Stock-up window is open' : `Stock-up window opens in ${until} day${until === 1 ? '' : 's'}`}</span></div></div>`;
  }).join('') : '<div class="empty"><b>No events on the calendar</b>Raid openings and patches go in config/events.yaml.</div>';
  learning();
}

const LABEL = { reversion: 'Price below normal', supply: 'Supply below normal', momentum: 'Rising price, shrinking supply', trend: 'Following the trend', cover: 'Few days of cover', event: 'Event coming', alternatives: 'Cheap vs similar items' };
function learning() {
  const md = DATA.model, tr = DATA.track || [];
  if (!md) { $('#learning-body').innerHTML = '<div class="empty"><b>No model yet</b>It starts after the first day of prices.</div>'; return; }
  const a = Math.round(md.alpha * 100), keys = Object.keys(md.prior);
  const max = Math.max(0.05, ...keys.flatMap(k => [Math.abs(md.prior[k]), Math.abs(md.used[k] ?? 0)]));
  const bar = (v, color) => { const w = Math.abs(v) / max * 50; return `<rect x="${v < 0 ? 50 - w : 50}" width="${Math.max(w, .6)}" height="7" rx="2" fill="${color}"/>`; };
  const rr = (r, d) => r.n ? `${Math.round(r.hit * r.n)} of ${r.n} ${d === 'buy' ? 'paid' : 'fell'}<small>average ${pct(r.mean, 1)}</small>` : '–';
  const name = { '30-45': 'Lean', '45-60': 'Solid', '60+': 'Strong' };
  $('#learning-body').innerHTML = `
    <div class="trust"><div class="big">${a}% learned</div>
      <p class="quiet">The rest is the starting assumptions. The model has scored ${num(md.n_eff)} item-hours against what the price did ${md.horizon_hours} hours later.</p>
      <div class="split"><i class="l" style="width:${Math.max(a, 1)}%"></i><i style="flex:1"></i></div>
      <div class="legend"><span class="l">Learned from outcomes</span><span>Starting assumptions</span></div></div>
    <h2>What drives a call</h2>
    <p class="lede">How much each reason counts toward the score. Bars to the left of the line count against an item.</p>
    <div class="legend" style="margin:8px 0 2px"><span class="l">In use now</span><span>At the start</span></div>
    ${keys.map(k => `<div class="wrow"><div class="lab">${LABEL[k] || k}<span>${(md.used[k] ?? 0).toFixed(2)}, was ${md.prior[k].toFixed(2)}</span></div>
      <svg viewBox="0 0 100 18" preserveAspectRatio="none" style="width:100%;height:22px;margin-top:6px" role="img" aria-label="${LABEL[k]}: ${(md.used[k] ?? 0).toFixed(2)} now, ${md.prior[k].toFixed(2)} at the start">
      <g transform="translate(0,1)">${bar(md.used[k] ?? 0, 'var(--series-1)')}</g><g transform="translate(0,10)">${bar(md.prior[k], 'var(--ghost)')}</g>
      <line x1="50" x2="50" y1="0" y2="18" stroke="var(--axis)" stroke-width=".4"/></svg></div>`).join('')}
    ${backtestHtml()}
    <h2>Did past calls pay?</h2>
    <p class="lede">Every call is logged when it appears and checked 24 and 72 hours later. Buys count as paid when they made money after the cut. Sells count when the price then fell.</p>
    <table class="track"><tr><th>Call</th><th>Made</th><th>After 24 hours</th><th>After 72 hours</th></tr>
    ${tr.map(r => `<tr><td>${name[r.bucket]} ${r.dir}</td><td>${r.signals}</td><td>${rr(r.r24, r.dir)}</td><td>${rr(r.r72, r.dir)}</td></tr>`).join('')}</table>`;
}

function backtestHtml() {
  const b = DATA.backtest;
  if (!b) return '';
  const days = (b.hours / 24).toFixed(b.hours < 48 ? 1 : 0), a = b.all;
  const line = (label, st) => `<tr><td>${label}</td><td>${st.n || 0}</td><td>${st.n ? st.wins + ' of ' + st.n : '–'}</td><td>${st.n ? pct(st.mean, 1) : '–'}</td><td>${st.n ? pct(st.worst, 0) : '–'}</td></tr>`;
  const head = `<h2>Would it have made money?</h2>
    <p class="lede">A replay of the ${days} days of prices recorded so far. It buys when the score reaches ${b.entry_score}, sells when the price is back to normal or after ${b.max_hold_hours} hours, and takes off the auction house cut. It uses the starting weights, so nothing learned later leaks into the past.</p>`;
  if (!a.n) return head + `<div class="empty"><b>No finished trades yet</b>${b.hours < 96 ? 'The replay needs about four days of history: one to learn each item\'s normal price, and up to three to close a trade.' : 'No score reached ' + b.entry_score + ' in this period.'}${b.open ? ' ' + b.open + ' trades are still open.' : ''}</div>`;
  return head + `<table class="track"><tr><th>Trades</th><th>Count</th><th>Paid</th><th>Average</th><th>Worst</th></tr>
    ${line('All', a)}${line('Solid, 45 to 60', b.solid)}${line('Strong, 60 and up', b.strong)}
    ${Object.values(b.watch || {}).map(w => line(esc(w.name), w)).join('')}</table>
    <p class="read">Buying any item at any hour and selling ${b.max_hold_hours} hours later returned ${pct(b.benchmark_mean, 1)} on average. The calls have to beat that to be worth anything.${b.open ? ' ' + b.open + ' trades are still open and not counted.' : ''}</p>`;
}

document.addEventListener('click', e => {
  const nav = e.target.closest('.nav button');
  if (nav) {
    $$('.nav button').forEach(b => b === nav ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
    $$('.view').forEach(v => v.hidden = v.id !== nav.dataset.view);
    $('#today').hidden = $('#notices').hidden = nav.dataset.view !== 'calls';
    open = null; if (DATA) render(); window.scrollTo(0, 0); return;
  }
  const seg = e.target.closest('.seg button');
  if (seg) {
    if (seg.dataset.dir) dirFilter = seg.dataset.dir; else sortBy = seg.dataset.sort;
    $$('button', seg.parentNode).forEach(b => b.setAttribute('aria-pressed', b === seg));
    return render();
  }
  const btn = e.target.closest('button[data-key]');
  if (btn) { open = open === btn.dataset.key ? null : btn.dataset.key; render(); }
});
$('#search').addEventListener('input', () => { open = null; render(); });

const tip = $('#tip');
function hover(e) {
  const svg = e.target.closest && e.target.closest('svg.chart');
  if (!svg) { tip.hidden = true; $$('svg .hover').forEach(g => g.style.display = 'none'); return; }
  const vals = JSON.parse(svg.dataset.vals), r = svg.getBoundingClientRect(), W = 340, H = 124, L = 4, R = 6, T = 16, B = 18;
  let i = Math.round(((e.clientX - r.left) / r.width * W - L) / (W - L - R) * (vals.length - 1)); i = Math.max(0, Math.min(vals.length - 1, i));
  while (i > 0 && vals[i] == null) i--;
  if (vals[i] == null) return;
  const lo = +svg.dataset.lo, hi = +svg.dataset.hi, x = L + i / (vals.length - 1) * (W - L - R), y = T + (1 - (vals[i] - lo) / (hi - lo)) * (H - T - B);
  const g = $('.hover', svg); g.style.display = '';
  $('line', g).setAttribute('x1', x); $('line', g).setAttribute('x2', x); $('circle', g).setAttribute('cx', x); $('circle', g).setAttribute('cy', y);
  const when = new Date(new Date(svg.dataset.t0).getTime() + i * 3600e3).toLocaleString(undefined, { weekday: 'short', hour: 'numeric' });
  tip.textContent = `${when}: ${svg.dataset.fmt === 'gold' ? plain(vals[i]) : num(vals[i]) + ' units'}`;
  tip.hidden = false;
  tip.style.left = Math.min(window.innerWidth - tip.offsetWidth - 6, Math.max(6, e.clientX - tip.offsetWidth / 2)) + 'px';
  tip.style.top = (r.top + y / H * r.height - 36) + 'px';
}
document.addEventListener('pointermove', hover);
document.addEventListener('pointerdown', hover);

fetch('data/latest.json?_=' + Date.now()).then(r => { if (!r.ok) throw 0; return r.json(); }).then(d => { DATA = d; render(); })
  .catch(() => {
    $('#today').innerHTML = '<h2>Waiting for the first prices</h2><p>The hourly collector has not run yet. In the GitHub repo, open Actions and run "Collect auction snapshot".</p>';
  });
