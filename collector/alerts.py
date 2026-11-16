"""Email alerts for major signals, sent through Resend (https://resend.com)."""
import json
import os
from datetime import datetime, timedelta, timezone
import requests


def gold(c):
    if c is None or c != c:
        return "-"
    c = int(round(c))
    g, s, cp = c // 10000, (c // 100) % 100, c % 100
    if g:
        return f"{g}g {s}s"
    return f"{s}s {cp}c" if s else f"{cp}c"


def pick_majors(signals, cfg, n_snapshots, state_path, now):
    a, th = cfg["alerts"], cfg["thresholds"]
    if n_snapshots < cfg["warmup_snapshots"]:
        return []
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    cutoff = now - timedelta(hours=a["cooldown_hours"])
    out = []
    for s in signals:
        if abs(s["score"]) < a["score_threshold"] or not s["signals"]:
            continue
        if s["score"] > 0 and "Squeeze" not in s["signals"] and \
                (s["net_margin"] is None or s["net_margin"] < th["min_net_margin"]):
            continue
        key = f'{s["id"]}:{"buy" if s["score"] > 0 else "sell"}'
        prev = state.get(key)
        if prev and datetime.fromisoformat(prev) > cutoff:
            continue
        state[key] = now.isoformat()
        out.append(s)
        if len(out) >= a["max_items"]:
            break
    state = {k: v for k, v in state.items() if datetime.fromisoformat(v) > now - timedelta(days=3)}
    state_path.write_text(json.dumps(state, indent=0, sort_keys=True))
    return out


def send(majors, meta):
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("ALERT_EMAIL")
    if not majors:
        return "no major signals"
    if not key or not to:
        return f"{len(majors)} major signals, email not configured"
    url = os.environ.get("DASHBOARD_URL", "")
    rows = "".join(
        f"<tr><td><b>{'BUY' if s['score'] > 0 else 'SELL / AVOID'}</b></td><td>{s['name']}</td>"
        f"<td>{s['score']:+.0f}</td><td>{s['signals']}</td><td>{gold(s['price'])}</td>"
        f"<td>{gold(s['normal'])}</td><td>{'' if s['net_margin'] is None else format(s['net_margin'], '+.0%')}</td>"
        f"<td>{'' if s['max_units'] is None else int(s['max_units'])}</td></tr>" for s in majors)
    html = (f"<p>WoW Forever {meta['faction']} auction house ({meta['region'].upper()}), snapshot {meta['snapshot']}.</p>"
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
            "<tr><th>Action</th><th>Item</th><th>Score</th><th>Signal</th><th>Price now</th><th>Normal price</th>"
            "<th>Net margin</th><th>Max units</th></tr>" + rows + "</table>"
            "<p style='font-size:12px;color:#555'>Net margin = gain if price returns to its normal level, after the auction house cut. "
            "Max units = the smaller of cheap listed units and a quarter of estimated daily sales.</p>"
            + (f"<p><a href='{url}'>Open dashboard</a></p>" if url else ""))
    top = majors[0]
    subject = f"WoW AH: {'BUY' if top['score'] > 0 else 'SELL'} {top['name']} ({top['score']:+.0f})" + \
        (f" +{len(majors) - 1} more" if len(majors) > 1 else "")
    r = requests.post("https://api.resend.com/emails", timeout=30,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"from": os.environ.get("ALERT_FROM", "WoW AH Indicator <onboarding@resend.dev>"),
                            "to": [to], "subject": subject, "html": html})
    return f"email status {r.status_code}: {r.text[:200]}"
