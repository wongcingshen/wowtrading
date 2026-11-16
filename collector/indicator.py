"""The indicator: per-item statistics from the hourly history, a composite
score from -100 (sell / avoid) to +100 (buy), and named signals."""
import gzip
import io
from datetime import timedelta
import numpy as np
import pandas as pd


def load_history(hourly_dir, now, lookback_days):
    frames = []
    start = now - timedelta(days=lookback_days)
    if not hourly_dir.exists():
        return pd.DataFrame()
    for day in sorted(p for p in hourly_dir.iterdir() if p.is_dir()):
        if day.name < start.strftime("%Y-%m-%d"):
            continue
        for f in sorted(day.glob("*.csv.gz")):
            ts = pd.Timestamp(f"{day.name} {f.name[:2]}:00", tz="UTC")
            if ts < pd.Timestamp(start).floor("h"):
                continue
            df = pd.read_csv(f)
            df["ts"] = ts
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _wide(hist, col, idx):
    return hist.pivot(index="ts", columns="item", values=col).reindex(idx)


def compute(hist, items, cfg, events, sub_groups, now):
    """Returns (table DataFrame indexed by item, dict of wide frames for charts, meta)."""
    snaps = sorted(hist["ts"].unique())
    n_snap = len(snaps)
    idx = pd.date_range(snaps[0], snaps[-1], freq="h", tz="UTC")
    have = pd.Series(idx.isin(snaps), index=idx)
    W, minobs = int(cfg["stat_window"]), int(cfg["min_obs"])

    P = _wide(hist, "p15", idx).astype(float)
    F = _wide(hist, "min", idx).astype(float)
    Q = _wide(hist, "qty", idx).astype(float)
    D = _wide(hist, "depth10", idx).astype(float)
    L = _wide(hist, "listings", idx).astype(float)
    S = _wide(hist, "sold", idx).astype(float)
    # a snapshot exists but the item is absent -> it was sold out (quantity 0)
    for X in (Q, D, L):
        X[:] = np.where(have.values[:, None] & X.isna().values, 0.0, X.values)
    S[:] = np.where(have.values[:, None] & S.isna().values & S.notna().any(axis=1).values[:, None], 0.0, S.values)
    Q, D, L = Q.ffill(limit=3), D.ffill(limit=3), L.ffill(limit=3)
    P, F = P.ffill(limit=24), F.ffill(limit=24)

    lp = np.log(P)
    mean = lp.rolling(W, min_periods=minobs).mean().shift(1)
    sd = lp.rolling(W, min_periods=minobs).std().shift(1).clip(lower=0.05)
    zp = (lp - mean) / sd
    mom = lp.ewm(span=6, min_periods=6).mean() - lp.ewm(span=24, min_periods=12).mean()
    lq = np.log1p(Q)
    zq = (lq - lq.rolling(W, min_periods=minobs).mean().shift(1)) / \
        lq.rolling(W, min_periods=minobs).std().shift(1).clip(lower=0.10)
    sold24 = S.rolling(24, min_periods=6).mean() * 24

    last = idx[-1]
    t = pd.DataFrame({
        "price": P.loc[last], "floor": F.loc[last], "qty": Q.loc[last],
        "depth10": D.loc[last], "listings": L.loc[last],
        "z_price": zp.loc[last], "z_supply": zq.loc[last], "mom": mom.loc[last],
        "normal": np.exp(mean.loc[last]), "sold24": sold24.loc[last],
        "obs": P.notna().sum(),
    })
    t["chg24"] = P.loc[last] / P.shift(24).loc[last] - 1 if len(idx) > 24 else np.nan
    t["qchg24"] = (Q.loc[last] / Q.shift(24).loc[last].replace(0, np.nan) - 1) if len(idx) > 24 else np.nan
    t["dos"] = t["qty"] / t["sold24"].where(t["sold24"] > 0)   # days of supply
    t["turnover"] = t["sold24"] * t["price"]

    # ---- alternatives: price relative to substitute items -------------------
    meta = pd.DataFrame.from_dict({int(k): v for k, v in items.items() if "miss" not in v}, orient="index")
    grp = pd.Series(index=t.index, dtype=object)
    if not meta.empty:
        gear = meta[meta["c"].isin(["Weapon", "Armor"]) & meta["inv"].notna() & meta["req"].notna()]
        key = gear["c"] + "|" + gear["s"].fillna("") + "|" + gear["inv"] + "|" + (gear["req"] // 5 * 5).astype(int).astype(str)
        grp.update(key[key.index.isin(t.index)])
    for g in sub_groups or []:
        for i in g.get("item_ids", []):
            if i in grp.index:
                grp[i] = "manual|" + g["name"]
    t["group"] = grp
    t["z_alt"] = np.nan
    t["alt_qty"] = np.nan
    for name, members in grp.dropna().groupby(grp.dropna()).groups.items():
        members = [m for m in members if m in lp.columns]
        if len(members) < 3:
            continue
        rel = lp[members].sub(lp[members].median(axis=1), axis=0)
        rz = (rel - rel.rolling(W, min_periods=minobs).mean().shift(1)) / \
            rel.rolling(W, min_periods=minobs).std().shift(1).clip(lower=0.05)
        t.loc[members, "z_alt"] = rz.loc[last]
        tot = Q.loc[last, members].sum()
        t.loc[members, "alt_qty"] = tot - Q.loc[last, members]

    # ---- events --------------------------------------------------------------
    t["event"] = 0.0
    t["event_name"] = None
    today = pd.Timestamp(now).tz_convert("UTC").normalize() if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC").normalize()
    for ev in events or []:
        days = (pd.Timestamp(str(ev["date"]), tz="UTC") - today).days
        lead = int(ev.get("lead_days", 14))
        if not (0 <= days <= lead):
            continue
        aff = ev.get("affects", {})
        ids = set(aff.get("item_ids") or [])
        if not meta.empty:
            m = meta[meta["c"].isin(aff.get("classes") or []) | meta["s"].isin(aff.get("subclasses") or [])]
            ids |= set(m.index)
        ids = [i for i in ids if i in t.index]
        ramp = (1 - days / (lead + 1)) * (1 if ev.get("direction", "up") == "up" else -1)
        better = np.abs(ramp) > t.loc[ids, "event"].abs()
        sel = [i for i, b in zip(ids, better) if b]
        t.loc[sel, "event"] = ramp
        t.loc[sel, "event_name"] = f'{ev["name"]} in {days}d'

    # ---- composite score ------------------------------------------------------
    w = cfg["weights"]
    clip = lambda s, k: (s / k).clip(-1, 1).fillna(0)
    c_rev = clip(-t["z_price"], 3)
    c_sup = clip(-t["z_supply"], 3)
    c_mom = clip(t["mom"], 0.10).where(t["z_supply"] < -1, 0)
    c_alt = clip(-t["z_alt"], 3)
    # Regime rules. In a squeeze (supply tight, price rising) a price above normal is the
    # squeeze itself, not a sell reason, unless it is overextended (z >= 3). In a flood
    # (supply far above normal) a price below normal is not a bargain.
    th = cfg["thresholds"]
    squeeze = (t["z_supply"] <= th["z_supply_tight"]) & (t["mom"] > 0) & (t["z_price"] < 3)
    c_rev = c_rev.where(~squeeze, c_rev.clip(lower=0))
    c_rev = c_rev.where(~(t["z_supply"] >= 1.5), c_rev.clip(upper=0))
    # Divided by 0.5 so that one fully extreme core component (reversion or supply at
    # 3 standard deviations) alone reaches 60, the default alert threshold.
    t["score"] = (100 * (w["reversion"] * c_rev + w["supply"] * c_sup + w["momentum"] * c_mom
                         + w["event"] * t["event"] + w["alternatives"] * c_alt) / 0.5).clip(-100, 100).round(1)
    t.loc[t["obs"] < minobs, "score"] = np.nan

    # expected gain if the price returns to its normal level, after the AH cut
    t["net_margin"] = t["normal"] * (1 - cfg["ah_cut"]) / t["price"] - 1

    # ---- named signals ---------------------------------------------------------
    sig = pd.Series("", index=t.index, dtype=object)
    def add(mask, name):
        sig[mask] = sig[mask].where(sig[mask] == "", sig[mask] + ", ") + name
    add((t["z_supply"] <= th["z_supply_tight"]) & (t["mom"] >= th["momentum_min"]), "Squeeze")
    add((t["z_price"] <= -th["z_extreme"]) & (t["z_supply"] < 1) & (t["net_margin"] >= th["min_net_margin"]), "Dip")
    add((t["z_price"] >= th["z_extreme"]), "Spike")
    add((t["z_supply"] >= th["z_extreme"]) & (t["mom"] <= -th["momentum_min"]), "Flood")
    add((t["z_alt"] <= -th["z_extreme"]), "Cheap vs alternatives")
    add((t["event"] > 0), "Event")
    t["signals"] = sig

    # ---- liquidity gate ----------------------------------------------------------
    lq_cfg = cfg["liquidity"]
    has_sales = t["sold24"].notna().any()
    gate = t["listings"] >= lq_cfg["min_listings"]
    if has_sales:
        cut = t.loc[t["turnover"] > 0, "turnover"].quantile(1 - lq_cfg["turnover_top_share"]) if (t["turnover"] > 0).any() else 0
        gate &= (t["sold24"] >= lq_cfg["min_sold_24h"]) & (t["turnover"] >= cut)
    t["liquid"] = gate
    # units you could buy without becoming the market: capped by cheap depth and a quarter of daily sales
    t["max_units"] = np.floor(np.minimum(t["depth10"], (t["sold24"] * 0.25).fillna(t["depth10"] * 0.25)))

    wide = {"P": P, "Q": Q}
    info = {"n_snapshots": n_snap, "hours_span": len(idx), "last": last, "has_sales": bool(has_sales)}
    return t, wide, info
