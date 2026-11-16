"""Item name / category cache. Blizzard's Forever item endpoint does not know
every item yet, so several namespaces are tried and misses are remembered."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from .blizzard import NotFound

RETRY_MISS_AFTER = 7 * 86400


def load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save(path, cache):
    path.write_text(json.dumps(cache, separators=(",", ":"), sort_keys=True))


def _lookup(api, item_id, namespaces):
    for ns in namespaces:
        try:
            d = api.get(f"/data/wow/item/{item_id}", ns)
        except NotFound:
            continue
        except Exception:
            return None  # transient problem: try again next run
        name = d.get("name")
        if isinstance(name, dict):
            name = name.get("en_US") or next(iter(name.values()), None)
        if not name:
            continue

        def nm(x):
            v = (d.get(x) or {}).get("name")
            return v.get("en_US") if isinstance(v, dict) else v
        return {"n": name, "q": (d.get("quality") or {}).get("type"),
                "c": nm("item_class"), "s": nm("item_subclass"),
                "inv": (d.get("inventory_type") or {}).get("type"),
                "lvl": d.get("level"), "req": d.get("required_level"),
                "vendor": d.get("sell_price")}
    return {"miss": int(time.time())}


def update(api, cache, wanted_ids, namespaces, limit):
    """wanted_ids: item ids ordered by importance. Fetch up to `limit` unknown ones."""
    now = time.time()
    todo = []
    for i in wanted_ids:
        e = cache.get(str(i))
        if e is None or ("miss" in e and now - e["miss"] > RETRY_MISS_AFTER):
            todo.append(i)
        if len(todo) >= limit:
            break
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda i: _lookup(api, i, namespaces), todo))
    n = 0
    for i, r in zip(todo, results):
        if r is not None:
            cache[str(i)] = r
            n += 1
    return n
