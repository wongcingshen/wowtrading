"""Walk-forward backtest over the recorded history.

At every past hour the score is rebuilt from data available at that hour only
(all statistics are lagged), using the fixed starting weights so that nothing
learned later leaks into the past. Rules:
  enter : score >= entry_score on an item with enough listings, buy at that hour's price
  exit  : first hour the price reaches the item's normal price as it stood at entry
          (or +15% if the entry was already above normal), else after max_hold_hours
  result: sell price x (1 - auction house cut) / buy price - 1
One position per item at a time. Trades still open when the data ends are not counted."""
import warnings
import numpy as np
import pandas as pd


def run(wide, cfg, watch=()):
    bt, cut = cfg["backtest"], cfg["ah_cut"]
    entry, hold = bt["entry_score"], int(bt["max_hold_hours"])
    w, comps = cfg["weights"], wide["comps"]
    S = sum(float(w.get(k, 0)) * comps[k] for k in comps) * 200
    ok = wide["valid"] & (wide["L"] >= cfg["liquidity"]["min_listings"])
    S = S.where(ok)
    P, N, Sv, idx, cols = wide["P"].values, wide["N"].values, S.values, S.index, S.columns
    n = len(idx)
    trades, still_open = [], 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        best = np.nanmax(np.where(np.isnan(Sv), -np.inf, Sv), axis=0) if n else np.array([])
    for j in np.where(best >= entry)[0]:
        i = 0
        while i < n - 1:
            if not (Sv[i, j] >= entry and P[i, j] > 0):
                i += 1
                continue
            buy = P[i, j]
            target = N[i, j] if N[i, j] > buy * 1.02 else buy * 1.15
            end = min(i + hold, n - 1)
            k = next((x for x in range(i + 1, end + 1) if P[x, j] >= target), None)
            if k is None:
                if i + hold > n - 1:          # data ends before the holding period does
                    still_open += 1
                    break
                k = end
            if not P[k, j] > 0:
                i = k + 1
                continue
            trades.append({"id": int(cols[j]), "t": idx[i].isoformat(), "score": round(float(Sv[i, j]), 1),
                           "buy": int(buy), "sell": int(P[k, j]), "hours": k - i,
                           "ret": round(float(P[k, j] * (1 - cut) / buy - 1), 4), "hit_target": bool(P[k, j] >= target)})
            i = k + 1
    # benchmark: buy any liquid item at any hour and sell max_hold_hours later
    base = (wide["P"].shift(-hold) * (1 - cut) / wide["P"] - 1).where(ok).clip(-0.9, 2.0)
    base_mean = float(np.nanmean(base.values)) if base.notna().any().any() else None

    def stats(rows):
        r = np.array([t["ret"] for t in rows])
        if not len(r):
            return {"n": 0}
        return {"n": int(len(r)), "wins": int((r > 0).sum()), "mean": round(float(r.mean()), 4),
                "median": round(float(np.median(r)), 4), "sum": round(float(r.sum()), 3),
                "worst": round(float(r.min()), 4), "best": round(float(r.max()), 4),
                "avg_hours": round(float(np.mean([t["hours"] for t in rows])), 1)}
    out = {"from": idx[0].isoformat() if n else None, "to": idx[-1].isoformat() if n else None, "hours": int(n),
           "entry_score": entry, "max_hold_hours": hold, "open": still_open, "benchmark_mean": None if base_mean is None else round(base_mean, 4),
           "all": stats(trades), "solid": stats([t for t in trades if t["score"] < 60]),
           "strong": stats([t for t in trades if t["score"] >= 60]),
           "watch": {str(i): stats([t for t in trades if t["id"] == i]) for i in watch},
           "recent": sorted(trades, key=lambda t: t["t"])[-12:]}
    return out
