"""Continuous learning.

Every hour, each (item, hour) observation that is now `horizon` hours old gets its
reward: the net return from buying at that hour's price and selling `horizon` hours
later, after the auction house cut. The model is a linear contextual bandit: it
regresses that reward on the indicator components, with older observations fading
out exponentially (recursive least squares with a forgetting factor). The learned
weights are blended with the starting assumptions in proportion to how much
evidence has accumulated, so the indicator moves from assumptions to data on its own.

A second, independent record logs every signal actually shown and fills in what the
price did afterwards. That is the out-of-sample track record."""
import json
import numpy as np
import pandas as pd

COMPS = ["reversion", "supply", "momentum", "trend", "cover", "event", "alternatives"]


def load(path):
    if path.exists():
        st = json.loads(path.read_text())
        if st.get("comps") == COMPS:
            return st
    k = len(COMPS) + 1
    return {"comps": COMPS, "A": np.zeros((k, k)).tolist(), "b": np.zeros(k).tolist(), "n_eff": 0.0, "last_t": None}


def update(state, wide, cfg):
    """Feed newly matured observations into the model. Returns number added."""
    lc = cfg["learning"]
    H = int(lc["horizon_hours"])
    lam = 0.5 ** (1.0 / (lc["half_life_days"] * 24))
    P, L, valid, comps = wide["P"], wide["L"], wide["valid"], wide["comps"]
    idx = P.index
    reward = (P.shift(-H) * (1 - cfg["ah_cut"]) / P - 1).clip(-0.9, 2.0)
    A, b, n_eff = np.array(state["A"]), np.array(state["b"]), float(state["n_eff"])
    last_t = pd.Timestamp(state["last_t"]) if state["last_t"] else None
    added = 0
    for i in range(len(idx) - H):
        ts = idx[i]
        if last_t is not None and ts <= last_t:
            continue
        gap = 1 if last_t is None else max(1, int((ts - last_t).total_seconds() // 3600))
        decay = lam ** gap
        A, b, n_eff = A * decay, b * decay, n_eff * decay
        last_t = ts
        y = reward.iloc[i]
        ok = (valid.iloc[i] & y.notna() & (L.iloc[i] >= cfg["liquidity"]["min_listings"])).values
        if not ok.any():
            continue
        X = np.column_stack([np.ones(ok.sum())] + [comps[k].iloc[i].values[ok] for k in COMPS])
        yv = y.values[ok]
        A += X.T @ X
        b += X.T @ yv
        n_eff += ok.sum()
        added += int(ok.sum())
    state.update(A=A.tolist(), b=b.tolist(), n_eff=n_eff, last_t=last_t.isoformat() if last_t is not None else None)
    return added


def weights(state, cfg):
    """Blend learned weights with the starting assumptions.
    Returns (weights used, summary dict, (intercept, {comp: beta}) or None)."""
    prior = {k: float(cfg["weights"].get(k, 0.0)) for k in COMPS}
    lc = cfg["learning"]
    n = float(state["n_eff"])
    alpha = n / (n + lc["prior_strength"]) if lc.get("enabled", True) else 0.0
    summary = {"alpha": round(alpha, 3), "n_eff": int(n), "horizon_hours": lc["horizon_hours"],
               "half_life_days": lc["half_life_days"], "prior": prior, "learned": None, "used": prior, "beta": None}
    if n < 500:
        return prior, summary, None
    A, b = np.array(state["A"]), np.array(state["b"])
    ridge = np.eye(len(A)) * lc["ridge"] * n
    ridge[0, 0] = 0
    try:
        beta = np.linalg.solve(A + ridge, b)
    except np.linalg.LinAlgError:
        return prior, summary, None
    bc = dict(zip(COMPS, beta[1:]))
    tot = sum(abs(v) for v in bc.values())
    if tot < 1e-9:
        return prior, summary, None
    scale = sum(abs(v) for v in prior.values()) / tot
    learned = {k: v * scale for k, v in bc.items()}
    used = {k: (1 - alpha) * prior[k] + alpha * learned[k] for k in COMPS}
    summary.update(learned={k: round(v, 3) for k, v in learned.items()}, used={k: round(v, 3) for k, v in used.items()},
                   beta={k: round(float(v), 4) for k, v in bc.items()}, intercept=round(float(beta[0]), 4))
    return used, summary, (float(beta[0]), {k: float(v) for k, v in bc.items()})


# ---- out-of-sample track record of the signals actually shown ----------------------
def log_signals(path, signals, P, cfg, now):
    log = json.loads(path.read_text()) if path.exists() else []
    cut = cfg["ah_cut"]
    recent = {(e["id"], e["dir"]): pd.Timestamp(e["ts"]) for e in log}
    ts_now = P.index[-1]
    for s in signals:
        if s["score"] is None or abs(s["score"]) < 30 or not s["price"]:
            continue
        d = "buy" if s["score"] > 0 else "sell"
        prev = recent.get((s["id"], d))
        if prev is not None and (ts_now - prev).total_seconds() < 12 * 3600:
            continue
        log.append({"id": s["id"], "name": s["name"], "dir": d, "ts": ts_now.isoformat(), "score": s["score"],
                    "signals": s["signals"], "price": s["price"], "r24": None, "r72": None})
    for e in log:
        t0 = pd.Timestamp(e["ts"])
        for h, key in ((24, "r24"), (72, "r72")):
            t1 = t0 + pd.Timedelta(hours=h)
            if e[key] is None and t1 in P.index and e["id"] in P.columns:
                p1 = P.at[t1, e["id"]]
                if p1 == p1:
                    # buys: net return after the AH cut. sells: raw price change (negative = the call was right)
                    e[key] = round(float(p1 * (1 - cut) / e["price"] - 1) if e["dir"] == "buy" else float(p1 / e["price"] - 1), 4)
    keep_after = ts_now - pd.Timedelta(days=90)
    log = [e for e in log if pd.Timestamp(e["ts"]) > keep_after]
    path.write_text(json.dumps(log, separators=(",", ":")))
    return log


def track_record(log):
    out = []
    for d in ("buy", "sell"):
        for lo, hi, label in ((30, 45, "30-45"), (45, 60, "45-60"), (60, 101, "60+")):
            rows = [e for e in log if e["dir"] == d and lo <= abs(e["score"]) < hi]
            rec = {"dir": d, "bucket": label, "signals": len(rows)}
            for key in ("r24", "r72"):
                v = [e[key] for e in rows if e[key] is not None]
                good = [x for x in v if (x > 0 if d == "buy" else x < 0)]
                rec[key] = {"n": len(v), "hit": round(len(good) / len(v), 3) if v else None,
                            "mean": round(float(np.mean(v)), 4) if v else None,
                            "median": round(float(np.median(v)), 4) if v else None}
            out.append(rec)
    return out
