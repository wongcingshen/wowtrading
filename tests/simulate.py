"""Offline end-to-end test: runs the real pipeline against a fake Blizzard API
that simulates an auction house for N hours. Usage: python -m tests.simulate [hours] [outdir]"""
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from collector import run
from collector.blizzard import NotFound

ROOT = Path(__file__).resolve().parents[1]
CLASSES = [("Consumable", "Potion", None), ("Trade Goods", "Herb", None), ("Armor", "Plate", "CHEST"),
           ("Weapon", "Sword", "WEAPON"), ("Trade Goods", "Cloth", None)]


class FakeApi:
    def __init__(self, n_items=250, seed=7):
        self.rng = np.random.default_rng(seed)
        self.ids = np.arange(1000, 1000 + n_items)
        self.base = np.exp(self.rng.normal(8, 1.5, n_items))       # copper
        self.drift = np.zeros(n_items)
        self.supply = self.rng.integers(20, 2000, n_items).astype(float)
        self.book = {}      # auction id -> [item, unit, qty, hours_left, commodity]
        self.next_id = 1
        self.hour = 0

    def step(self):
        self.hour += 1
        r = self.rng
        self.drift = 0.9 * self.drift + r.normal(0, 0.02, len(self.ids))
        shock = np.zeros(len(self.ids))
        if self.hour > 80:
            shock[0] = -0.45          # item 1000: sudden dip -> expect a Dip buy signal
            self.supply[1] = 15       # item 1001: supply collapse -> expect a Squeeze
            self.drift[1] += 0.03
            self.supply[2] = 9000     # item 1002: supply flood, falling price
            self.drift[2] -= 0.03
        price = self.base * np.exp(self.drift + shock)
        for aid in list(self.book):   # sales (cheap listings go first), expiry
            b = self.book[aid]
            b[3] -= 1
            k = int(np.where(self.ids == b[0])[0][0])
            if b[3] <= 0 or (b[1] <= price[k] * 1.03 and r.random() < 0.35) or \
               (b[0] in (1001, 1002) and self.hour > 80 and r.random() < (0.5 if b[0] == 1001 else 0.0)):
                del self.book[aid]
        have = {}
        for b in self.book.values():
            have[b[0]] = have.get(b[0], 0) + b[2]
        for k, item in enumerate(self.ids):
            com = k % 5 in (0, 1, 4)
            while have.get(item, 0) < self.supply[k]:
                qty = int(r.integers(1, 20)) if com else 1
                unit = int(max(1, price[k] * np.exp(abs(r.normal(0, 0.12)))))
                self.book[self.next_id] = [int(item), unit, qty, int(r.integers(2, 48)), com]
                self.next_id += 1
                have[item] = have.get(item, 0) + qty

    def get(self, path, namespace, retries=4):
        if path.endswith("/auctions/"):
            return {"auctions": [{"id": h, "name": f"{f} Auction House"} for h, f in
                                 [(110, "Alliance"), (111, "Horde"), (112, "Alliance"), (113, "Alliance")]]}
        m = re.search(r"/auctions/(\d+)(/commodities)?(\?.*)?$", path)
        if m:
            hid = int(m.group(1))
            if hid == 112:
                return {"id": hid, "name": "Alliance Auction House", "ruleset": {"id": 1}}
            tl = lambda h: "SHORT" if h < 1 else "MEDIUM" if h <= 2 else "LONG" if h <= 12 else "VERY_LONG"
            scale = 1 if hid == 110 else 2   # 113 is "another ruleset" with different prices
            rows = [(a, b) for a, b in self.book.items() if hid == 110 or a % 3 == 0]
            if m.group(2):
                return {"auctions": [{"id": a, "item": {"id": b[0]}, "quantity": b[2], "unit_price": b[1] * scale,
                                      "time_left": tl(b[3])} for a, b in rows if b[4]]}
            return {"id": hid, "name": "Alliance Auction House", "ruleset": {"id": 1},   # echoes the request
                    "commodities": {"href": f"https://x/data/wow/ruleset/1/auctions/{hid}/commodities?namespace=d"},
                    "auctions": [{"id": a, "item": {"id": b[0]}, "quantity": b[2], "buyout": b[1] * b[2] * scale,
                                  "time_left": tl(b[3])} for a, b in rows if not b[4]] + [{"id": 0, "item": {"id": 1}, "bid": 5}]}
        m = re.search(r"/item/(\d+)$", path)
        if m:
            i = int(m.group(1))
            if i % 7 == 0 and "forever" in namespace:
                raise NotFound(path)
            if i % 14 == 0:
                raise NotFound(path)
            c, s, inv = CLASSES[(i - 1000) % 5]
            return {"name": f"Test {s} {i}", "quality": {"type": "UNCOMMON"}, "item_class": {"name": c},
                    "item_subclass": {"name": s}, "inventory_type": {"type": inv} if inv else {"type": "NON_EQUIP"},
                    "level": 40, "required_level": 35 + (i % 3), "sell_price": 100}
        raise NotFound(path)


def main(hours=100, outdir=None):
    tmp = Path(outdir or tempfile.mkdtemp())
    for d in ("config", "site"):
        shutil.copytree(ROOT / d, tmp / d, dirs_exist_ok=True)
    api = FakeApi()
    for _ in range(30):
        api.step()
    t0 = datetime(2026, 11, 20, 0, 5, tzinfo=timezone.utc)
    out = None
    for h in range(hours):
        api.step()
        out = run.main(tmp, api, t0 + timedelta(hours=h))
    return tmp, out


if __name__ == "__main__":
    tmp, out = main(int(sys.argv[1]) if len(sys.argv) > 1 else 100, sys.argv[2] if len(sys.argv) > 2 else None)
    print("output in", tmp)
    print(out["meta"])
    for s in out["signals"][:12]:
        print(s["id"], s["name"], s["score"], s["signals"], s["price"], s["normal"], s["net_margin"], s["dos"], s["max_units"])
