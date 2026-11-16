"""Hourly job: fetch -> aggregate -> store -> score -> publish -> alert."""
import gzip
import io
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import yaml

from . import alerts, indicator, items as itemcache, snapshot
from .blizzard import Blizzard, fetch_house, list_houses, ruleset_of


def _write_gz(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(text.encode())
    path.write_bytes(buf.getvalue())


def _num(x, nd=None):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    x = float(x)
    return round(x, nd) if nd is not None else int(round(x))


def choose_houses(api, cfg, dyn, state_path):
    """Returns (selected_id, {house_id: (detail, rows)}, state)."""
    rid = cfg["ruleset_id"]
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    forced = cfg.get("house_id")
    if forced or (state.get("selected") and not state.get("ambiguous")):
        hid = forced or state["selected"]
        state = {"selected": hid, "ambiguous": False, "candidates": state.get("candidates", []), "forced": bool(forced)}
        return hid, {hid: fetch_house(api, rid, hid, dyn)}, state
    fetched, cands = {}, []
    for h in list_houses(api, rid, dyn):
        if cfg["faction"].lower() not in h["name"].lower():
            continue
        detail, rows = fetch_house(api, rid, h["id"], dyn)
        cands.append({"id": h["id"], "name": h["name"], "listings": len(rows), "ruleset": ruleset_of(detail.get("ruleset"))})
        if rows:
            fetched[h["id"]] = (detail, rows)
    if not fetched:
        raise SystemExit(f"No non-empty {cfg['faction']} auction house found: {cands}")
    live = [c for c in cands if c["listings"] > 0]
    match = [c for c in live if c["ruleset"] == rid]
    if len(live) == 1:
        sel, amb = live[0]["id"], False
    elif len(match) == 1:
        sel, amb = match[0]["id"], False
    else:  # the API does not say which house belongs to which ruleset
        sel, amb = max(live, key=lambda c: c["listings"])["id"], True
    if not amb:
        fetched = {sel: fetched[sel]}
    return sel, fetched, {"selected": sel, "ambiguous": amb, "candidates": cands, "forced": False}


def main(root=Path("."), api=None, now=None):
    root = Path(root)
    cfg = yaml.safe_load((root / "config/settings.yaml").read_text())
    events = (yaml.safe_load((root / "config/events.yaml").read_text()) or {}).get("events", [])
    subs = (yaml.safe_load((root / "config/substitutes.yaml").read_text()) or {}).get("groups", [])
    now = now or datetime.now(timezone.utc)
    region = cfg["region"]
    dyn = f"dynamic-forever-{region}"
    if api is None:
        api = Blizzard(region, os.environ["BLIZZARD_CLIENT_ID"], os.environ["BLIZZARD_CLIENT_SECRET"])
    state_dir, cache_dir = root / "data/state", root / ".cache"
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(exist_ok=True)

    selected, fetched, hstate = choose_houses(api, cfg, dyn, state_dir / "house.json")
    (state_dir / "house.json").write_text(json.dumps(hstate, indent=1))
    print(f"house {selected} (ambiguous={hstate['ambiguous']}), collecting {list(fetched)}")

    aggs = {}
    for hid, (_, rows) in fetched.items():
        raw = snapshot.raw_frame(rows)
        agg = snapshot.aggregate(raw)
        prev_raw_p, prev_meta_p = cache_dir / f"prev_h{hid}.csv.gz", cache_dir / f"prev_h{hid}.json"
        if prev_raw_p.exists() and prev_meta_p.exists():
            pm = json.loads(prev_meta_p.read_text())
            gap = (now - datetime.fromisoformat(pm["ts"])).total_seconds() / 3600
            prev_raw = pd.read_csv(prev_raw_p, keep_default_na=False)
            sold, new = snapshot.estimate_sales(prev_raw, snapshot.aggregate(prev_raw), raw, gap)
            if sold is not None:
                agg["sold"] = agg["item"].map(sold).fillna(0).round(2)
                agg["new"] = agg["item"].map(new).fillna(0).round(2)
                # items that sold out completely still need a row for their sales
                gone = sold[(sold > 0) & ~sold.index.isin(agg["item"])]
                if hid == selected and len(gone):
                    print(f"{len(gone)} items sold out since last snapshot")
        _write_gz(root / f"data/hourly/h{hid}/{now:%Y-%m-%d}/{now:%H}.csv.gz", agg.to_csv(index=False))
        _write_gz(prev_raw_p, raw.to_csv(index=False))
        prev_meta_p.write_text(json.dumps({"ts": now.isoformat()}))
        aggs[hid] = agg
        print(f"house {hid}: {len(raw)} listings, {len(agg)} items")

    agg = aggs[selected]
    icache_p = root / "data/items.json"
    icache = itemcache.load(icache_p)
    order = agg.assign(v=agg["qty"] * agg["p15"]).sort_values("v", ascending=False)["item"].tolist()
    ns = [n.format(region=region) for n in cfg["item_namespaces"]]
    n_new = itemcache.update(api, icache, order, ns, cfg["max_item_lookups_per_run"])
    if n_new:
        itemcache.save(icache_p, icache)
    print(f"item lookups this run: {n_new}")

    hist = indicator.load_history(root / f"data/hourly/h{selected}", now, cfg["lookback_days"])
    t, wide, info = indicator.compute(hist, icache, cfg, events, subs, now)

    def name(i):
        e = icache.get(str(i)) or {}
        return e.get("n") or f"Item #{i}"

    def row(i, r, series=False):
        e = icache.get(str(i)) or {}
        d = {"id": int(i), "name": name(i), "q": e.get("q"), "cls": e.get("s") or e.get("c"),
             "score": _num(r["score"], 1), "signals": r["signals"], "price": _num(r["price"]),
             "floor": _num(r["floor"]), "normal": _num(r["normal"]), "chg24": _num(r["chg24"], 4),
             "qty": _num(r["qty"]), "qchg24": _num(r["qchg24"], 4), "z_price": _num(r["z_price"], 2),
             "z_supply": _num(r["z_supply"], 2), "dos": _num(r["dos"], 2), "sold24": _num(r["sold24"], 1),
             "net_margin": _num(r["net_margin"], 4), "max_units": _num(r["max_units"]),
             "event": r["event_name"], "alt_qty": _num(r["alt_qty"]), "listings": _num(r["listings"])}
        if series:
            p, q = wide["P"][i].iloc[-72:], wide["Q"][i].iloc[-72:]
            d["series"] = {"t0": p.index[0].isoformat(), "p": [_num(v) for v in p], "q": [_num(v) for v in q]}
        return d

    live = t[t["qty"].notna()]
    cand = live[live["liquid"] & live["score"].notna() & ((live["signals"] != "") | (live["score"].abs() >= 30))]
    cand = cand.reindex(cand["score"].abs().sort_values(ascending=False).index).head(60)
    signals = [row(i, r, True) for i, r in cand.iterrows()]
    rank = live["turnover"] if info["has_sales"] else live["qty"] * live["price"]
    market = [row(i, live.loc[i], True) for i in rank.fillna(0).sort_values(ascending=False).head(150).index]

    meta = {"generated": now.isoformat(timespec="seconds"), "snapshot": info["last"].isoformat(),
            "n_snapshots": info["n_snapshots"], "warmup": info["n_snapshots"] < cfg["warmup_snapshots"],
            "min_obs": cfg["min_obs"], "warmup_snapshots": cfg["warmup_snapshots"],
            "region": region, "ruleset_id": cfg["ruleset_id"], "faction": cfg["faction"], "house": selected,
            "ambiguous": hstate["ambiguous"], "ah_cut": cfg["ah_cut"], "has_sales": info["has_sales"],
            "items_tracked": int(len(live)), "alert_threshold": cfg["alerts"]["score_threshold"]}
    house_check = None
    if hstate["ambiguous"]:
        ref = agg.sort_values("qty", ascending=False).head(6)["item"].tolist()
        house_check = {"candidates": hstate["candidates"], "samples": [
            {"name": name(i), "id": int(i),
             "floor": {str(h): _num(a.set_index("item")["min"].get(i)) for h, a in aggs.items()}} for i in ref]}
    today = pd.Timestamp(now).normalize()
    evs = [{"name": e["name"], "date": str(e["date"]),
            "days": int((pd.Timestamp(str(e["date"]), tz="UTC") - today).days),
            "lead_days": e.get("lead_days", 14), "source": e.get("source")} for e in events]
    out = {"meta": meta, "signals": signals, "market": market, "events": evs, "house_check": house_check}
    (root / "site/data").mkdir(parents=True, exist_ok=True)
    (root / "site/data/latest.json").write_text(json.dumps(out, separators=(",", ":")))

    majors = alerts.pick_majors(signals, cfg, info["n_snapshots"], state_dir / "alerts.json", now)
    print(alerts.send(majors, meta))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))
