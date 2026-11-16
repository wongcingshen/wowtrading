"""Turn raw listings into one compact row per item, and estimate sales by
comparing with the previous raw snapshot."""
import numpy as np
import pandas as pd

RAW_COLS = ["aid", "item", "unit", "qty", "tl", "com"]
AGG_COLS = ["item", "min", "p15", "median", "qty", "depth10", "listings", "sold", "new", "com"]


def raw_frame(rows):
    return pd.DataFrame(rows, columns=RAW_COLS)


def aggregate(raw):
    """Per item: floor price, p15 (average price of the cheapest 15% of units,
    robust to a single mispriced listing), quantity-weighted median, total
    quantity, depth10 (units priced within 10% of the floor), listing count."""
    if raw.empty:
        return pd.DataFrame(columns=AGG_COLS)
    d = raw.sort_values(["item", "unit"], kind="mergesort").reset_index(drop=True)
    g = d.groupby("item", sort=False)
    total = g["qty"].transform("sum")
    cum = g["qty"].cumsum()
    floor = g["unit"].transform("first")
    target = np.ceil(total * 0.15).clip(lower=1)
    take = (target - (cum - d["qty"])).clip(lower=0).clip(upper=d["qty"])
    d["_p15"] = d["unit"] * take
    d["_take"] = take
    d["_d10"] = np.where(d["unit"] <= floor * 1.10, d["qty"], 0)
    d["_med"] = np.where(cum >= total / 2.0, d["unit"], np.nan)
    out = d.groupby("item", sort=False).agg(
        min=("unit", "first"), _p15=("_p15", "sum"), _take=("_take", "sum"),
        median=("_med", "min"), qty=("qty", "sum"), depth10=("_d10", "sum"),
        listings=("unit", "size"), com=("com", "max")).reset_index()
    out["p15"] = (out["_p15"] / out["_take"]).round().astype("int64")
    out["median"] = out["median"].astype("int64")
    out["sold"] = np.nan
    out["new"] = np.nan
    out["com"] = out["com"].astype(int)
    return out[AGG_COLS]


def estimate_sales(prev_raw, prev_agg, cur_raw, gap_hours):
    """Estimated units sold per item between two snapshots.

    A listing that vanished is counted as sold when it was priced near the
    cheap end of the book (<= 1.15 x previous p15) and was not about to expire
    (time_left SHORT/MEDIUM). Commodity listings that shrank count the
    difference. This is a lower-bound estimate: cancels near the floor are
    indistinguishable from sales in snapshot data.
    Returns (sold, new) Series indexed by item, or (None, None) if unusable."""
    if prev_raw is None or prev_raw.empty or gap_hours is None or not (0.4 <= gap_hours <= 2.6):
        return None, None
    m = prev_raw.merge(cur_raw[["aid", "qty"]], on="aid", how="left", suffixes=("", "_cur"))
    ref = prev_agg.set_index("item")["p15"]
    near = m["unit"] <= m["item"].map(ref) * 1.15
    gone = m["qty_cur"].isna()
    expiring = m["tl"].isin(["SHORT", "MEDIUM"])
    sold_units = np.where(gone & near & ~expiring, m["qty"], 0)
    shrink = (m["qty"] - m["qty_cur"]).clip(lower=0).fillna(0)
    sold_units = sold_units + np.where(~gone & near, shrink, 0)
    sold = pd.Series(sold_units, index=m["item"]).groupby(level=0).sum() / gap_hours
    new_rows = cur_raw[~cur_raw["aid"].isin(prev_raw["aid"])]
    new = new_rows.groupby("item")["qty"].sum() / gap_hours
    return sold, new
