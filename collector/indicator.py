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


def compute(hist, items, cfg, events, sub_groups, now, weights=None, model_beta=None):
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

    # days of cover = listed quantity / estimated daily sales. The commodity-market
    # equivalent is the stocks-to-use ratio: low cover means buyers compete for few units.
    cover = Q / sold24.where(sold24 > 0)
    lc = np.log(cover.where(cover > 0))
    zc = (lc - lc.rolling(W, min_periods=minobs).mean().shift(1)) / \
        lc.rolling(W, min_periods=minobs).std().shift(1).clip(lower=0.15)
    ret = lp.diff()
    vol = ret.rolling(W, min_periods=minobs).std() * np.sqrt(24)      # daily volatility of price
    # speed of mean reversion (Ornstein-Uhlenbeck style): regress the hourly price change
    # on the previous deviation from normal; half-life = hours for a deviation to halve.
    dev = (lp - mean)
    x, y = dev.shift(1).iloc[-W:], ret.iloc[-W:]
    beta = (x * y).sum() / (x * x).sum().replace(0, np.nan)
    half_life = (-np.log(2) / np.log1p(beta.clip(-0.99, -1e-4))).where(beta < 0)

    last = idx[-1]
    t = pd.DataFrame({
        "price": P.loc[last], "floor": F.loc[last], "qty": Q.loc[last],
        "depth10": D.loc[last], "listings": L.loc[last],
        "z_price": zp.loc[last], "z_supply": zq.loc[last], "mom": mom.loc[last],
        "normal": np.exp(mean.loc[last]), "sold24": sold24.loc[last],
        "obs": P.notna().sum(), "vol": vol.loc[last], "half_life": half_life,
    })
    t["chg24"] = P.loc[last] / P.shift(24).loc[last] - 1 if len(idx) > 24 else np.nan
    t["qchg24"] = (Q.loc[last] / Q.shift(24).loc[last].replace(0, np.nan) - 1) if len(idx) > 24 else np.nan
    t["dos"] = cover.loc[last]
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
    t["alt_qty"] = np.nan
    RZ = pd.DataFrame(np.nan, index=idx, columns=P.columns)
    for name, members in grp.dropna().groupby(grp.dropna()).groups.items():
        members = [m for m in members if m in lp.columns]
        if len(members) < 3:
            continue
        rel = lp[members].sub(lp[members].median(axis=1), axis=0)
        RZ[members] = (rel - rel.rolling(W, min_periods=minobs).mean().shift(1)) / \
            rel.rolling(W, min_periods=minobs).std().shift(1).clip(lower=0.05)
        t.loc[members, "alt_qty"] = Q.loc[last, members].sum() - Q.loc[last, members]
    t["z_alt"] = RZ.loc[last]

    # ---- events (as a time x item frame, so past events can be learned from) ----
    E = pd.DataFrame(0.0, index=idx, columns=P.columns)
    t["event_name"] = None
    for ev in events or []:
        days = np.asarray((pd.Timestamp(str(ev["date"]), tz="UTC") - idx.normalize()).days)
        lead = int(ev.get("lead_days", 14))
        ramp = np.where((days >= 0) & (days <= lead), (1 - days / (lead + 1)), 0.0) * (1 if ev.get("direction", "up") == "up" else -1)
        aff = ev.get("affects", {})
        ids = set(aff.get("item_ids") or [])
        if not meta.empty:
            m = meta[meta["c"].isin(aff.get("classes") or []) | meta["s"].isin(aff.get("subclasses") or [])]
            ids |= set(m.index)
        ids = [i for i in ids if i in E.columns]
        if not ids or not ramp.any():
            continue
        cur = E[ids].values
        E[ids] = np.where(np.abs(ramp[:, None]) > np.abs(cur), ramp[:, None], cur)
        if ramp[-1] != 0:
            t.loc[ids, "event_name"] = f'{ev["name"]} in {int(days[-1])}d'
    t["event"] = E.loc[last]

    # ---- components, each between -1 and +1 ------------------------------------------
    th = cfg["thresholds"]
    clip = lambda X, k: (X / k).clip(-1, 1)
    c_rev, c_sup = clip(-zp, 3), clip(-zq, 3).fillna(0)
    c_trend = clip(mom, 0.10).fillna(0)                       # plain trend-following, all regimes
    c_mom = c_trend.where(zq < -1, 0.0)                       # trend only while supply contracts
    # Regime rules. In a squeeze (supply tight, price rising) a price above normal is the
    # squeeze itself, not a sell reason, unless it is overextended (z >= 3). In a flood
    # (supply far above normal) a price below normal is not a bargain.
    squeeze = (zq <= th["z_supply_tight"]) & (mom > 0) & (zp < 3)
    c_rev = c_rev.where(~squeeze, c_rev.clip(lower=0))
    c_rev = c_rev.where(~(zq >= 1.5), c_rev.clip(upper=0))
    comps = {"reversion": c_rev.fillna(0), "supply": c_sup, "momentum": c_mom, "trend": c_trend,
             "cover": clip(-zc, 3).fillna(0), "event": E, "alternatives": clip(-RZ, 3).fillna(0)}
    valid = zp.notna() & mom.notna()

    # Divided by 0.5 so that one fully extreme core component (reversion or supply at
    # 3 standard deviations) alone reaches 60, the default alert threshold.
    w = weights or cfg["weights"]
    score = sum(float(w.get(k, 0)) * comps[k].loc[last] for k in comps)
    t["score"] = (100 * score / 0.5).clip(-100, 100).round(1)
    t.loc[~valid.loc[last] | (t["obs"] < minobs), "score"] = np.nan
    if model_beta is not None:   # learned expected net return over the learning horizon
        t["exp_ret"] = model_beta[0] + sum(model_beta[1][k] * comps[k].loc[last] for k in comps)
        t.loc[t["score"].isna(), "exp_ret"] = np.nan
    else:
        t["exp_ret"] = np.nan

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

    wide = {"P": P, "Q": Q, "L": L, "comps": comps, "valid": valid}
    info = {"n_snapshots": n_snap, "hours_span": len(idx), "last": last, "has_sales": bool(has_sales)}
    return t, wide, info
