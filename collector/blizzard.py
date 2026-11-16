"""Thin client for Blizzard's Game Data API (client-credentials flow)."""
import re
import time
import requests


class NotFound(Exception):
    pass


class Blizzard:
    def __init__(self, region, client_id, client_secret):
        self.region = region
        self.host = f"https://{region}.api.blizzard.com"
        self.s = requests.Session()
        r = requests.post("https://oauth.battle.net/token",
                          data={"grant_type": "client_credentials"},
                          auth=(client_id, client_secret), timeout=30)
        r.raise_for_status()
        self.s.headers["Authorization"] = "Bearer " + r.json()["access_token"]

    def get(self, path, namespace, retries=4):
        url = path if path.startswith("http") else self.host + path
        params = {} if "namespace=" in url else {"namespace": namespace, "locale": "en_US"}
        last = None
        for attempt in range(retries):
            try:
                r = self.s.get(url, params=params, timeout=120)
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                raise NotFound(url)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"{r.status_code} from {url}")
                time.sleep(2 ** attempt + 1)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"giving up on {url}: {last}")


def ruleset_of(obj):
    """Pull a ruleset id out of whatever shape the API uses for the field."""
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        if isinstance(obj.get("id"), int):
            return obj["id"]
        href = (obj.get("key") or {}).get("href") or obj.get("href") or ""
        m = re.search(r"ruleset/(\d+)", href)
        if m:
            return int(m.group(1))
    return None


def fetch_house(api, ruleset_id, house_id, dyn):
    """Return (detail_dict, listings) where listings is a list of
    (auction_id, item_id, unit_price_copper, quantity, time_left, is_commodity)."""
    base = f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}"
    detail = api.get(base, dyn)
    print(f"house {house_id}: response fields {sorted(detail.keys())}, ruleset={detail.get('ruleset')!r:.120}")
    rows = []
    for a in detail.get("auctions") or []:
        row = _row(a, False)
        if row:
            rows.append(row)
    com = detail.get("commodities")
    com_list = None
    if isinstance(com, list):
        com_list = com
    else:
        href = None
        if isinstance(com, dict):
            href = com.get("href") or (com.get("key") or {}).get("href")
        try:
            body = api.get(href or base + "/commodities", dyn)
            com_list = body.get("auctions") or body.get("commodities") or []
        except NotFound:
            print(f"warning: no commodities endpoint for house {house_id}")
            com_list = []
    for a in com_list:
        row = _row(a, True)
        if row:
            rows.append(row)
    return detail, rows


def _row(a, is_commodity):
    try:
        item = a["item"]["id"] if isinstance(a.get("item"), dict) else a.get("item")
        qty = int(a.get("quantity") or 1)
        if a.get("unit_price"):
            unit = int(a["unit_price"])
        elif a.get("buyout"):
            unit = int(a["buyout"]) // max(qty, 1)
        else:
            return None  # bid-only listing: no fixed price to trade against
        if not item or unit <= 0 or qty <= 0:
            return None
        return (int(a["id"]), int(item), unit, qty, str(a.get("time_left") or ""), is_commodity)
    except (KeyError, TypeError, ValueError):
        return None


def list_houses(api, ruleset_id, dyn):
    idx = api.get(f"/data/wow/ruleset/{ruleset_id}/auctions/", dyn)
    return [{"id": h["id"], "name": h.get("name", "")} for h in idx.get("auctions", [])]
