#!/usr/bin/env python3
"""Capture and compare the platform's stock, unit and money answers (decision 0098).

The material-ledger cut-over must not change one figure. This script calls
every read route that shows stock, lots, batches, units, devices, orders or
money, and saves each answer as JSON. Run it before the switch and after it,
then compare. It only READS: every call is a GET.

    scripts/ledger-golden.py capture --base http://127.0.0.1:8031 --out /tmp/golden-before
    scripts/ledger-golden.py capture --base https://disfunction.cc/lib --token "$TOKEN" --out ...
    scripts/ledger-golden.py compare /tmp/golden-before /tmp/golden-after

`compare` lists each route whose answer differs, with the first paths that
differ. Keys in IGNORE (timestamps of the call itself) are left out of both.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# Cloudflare refuses the default Python-urllib user agent.
UA = "python-httpx/0.27 ledger-golden"
# Timestamps of the call itself, and the fleet broker's live presence (a
# device heard a minute later is no change of stock or cost).
IGNORE = {"generated_at", "seconds", "now", "checked_at", "presence", "broker"}


class Api:
    def __init__(self, base: str, token: str = ""):
        self.base = base.rstrip("/")
        self.token = token

    def get(self, path: str, **query):
        url = self.base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        try:
            data = json.loads(body)
        except ValueError:
            data = {"$text": body.decode("utf-8", "replace")[:2000]}
        return status, data


def _ids(rows, key="id"):
    if isinstance(rows, dict):
        for k in ("items", "rows", "runs", "projects", "orders", "shipments", "devices", "companies"):
            if isinstance(rows.get(k), list):
                rows = rows[k]
                break
    return [r[key] for r in rows if isinstance(r, dict) and r.get(key) is not None] if isinstance(rows, list) else []


def routes(api: Api) -> list[tuple[str, dict]]:
    """Every (path, query) to capture, with the ids read from list routes."""
    out: list[tuple[str, dict]] = [
        ("/api/parts-stock", {}), ("/api/stock-adjustments", {}), ("/api/process-transformations", {}),
        ("/api/transfers", {}), ("/api/invoices", {}), ("/api/finished-stock", {}),
        ("/api/finished-products", {}), ("/api/demand", {}), ("/api/orders", {}), ("/api/shipments", {}),
        ("/api/runs", {}), ("/api/projects", {}), ("/api/companies", {}), ("/api/documents", {}),
    ]
    _s, companies = api.get("/api/companies")
    for cid in _ids(companies):
        for year in (2024, 2025, 2026):
            out.append((f"/api/companies/{cid}/books", {"year": year}))
    _s, projects = api.get("/api/projects")
    for pid in _ids(projects):
        out += [(f"/api/projects/{pid}", {}), (f"/api/projects/{pid}/process", {}),
                (f"/api/projects/{pid}/runs", {}), (f"/api/projects/{pid}/cost-pool", {}),
                (f"/api/projects/{pid}/stock-adjustments", {}), (f"/api/finished-stock", {"project_id": pid}),
                (f"/api/demand", {"project_id": pid})]
        _s, proc = api.get(f"/api/projects/{pid}/process")
        for v in (proc.get("versions") or []) if isinstance(proc, dict) else []:
            if isinstance(v, dict) and v.get("id"):
                out.append((f"/api/process-versions/{v['id']}", {}))
    _s, runs = api.get("/api/runs")
    devices: set[int] = set()
    for run in runs if isinstance(runs, list) else []:
        # The list route answers at most 2000 devices, so it is read batch by batch.
        q = {"run_id": run["id"], "limit": 2000}
        out.append((f"/api/projects/{run['project_id']}/devices", q))
        _s, devs = api.get(f"/api/projects/{run['project_id']}/devices", **q)
        devices |= set(_ids(devs))
    for did in sorted(devices):
        out += [(f"/api/devices/{did}/twin", {}), (f"/api/devices/{did}/history", {})]
    for rid in _ids(runs):
        for tail in ("", "/actuals", "/consumption", "/craft", "/craft/assembly/draft", "/craft/cost-by-step",
                     "/bench-stacks", "/batch-supply", "/supply-coverage", "/substitutions", "/production",
                     "/documents"):
            out.append((f"/api/runs/{rid}{tail}", {}))
    _s, orders = api.get("/api/orders")
    for oid in _ids(orders):
        out += [(f"/api/orders/{oid}", {}), (f"/api/orders/{oid}/stock-options", {})]
    _s, ships = api.get("/api/shipments")
    for sid in _ids(ships):
        out.append((f"/api/shipments/{sid}", {}))
    _s, stock = api.get("/api/parts-stock")
    for part in (stock.get("parts") or stock.get("rows") or []) if isinstance(stock, dict) else []:
        if isinstance(part, dict) and part.get("component_id"):
            out.append(("/api/parts-ledger", {"component_id": part["component_id"]}))
    seen, uniq = set(), []
    for p, q in out:
        k = (p, tuple(sorted(q.items())))
        if k not in seen:
            seen.add(k)
            uniq.append((p, q))
    return uniq


def _name(path: str, query: dict) -> str:
    s = path.strip("/").replace("/", "__")
    if query:
        s += "__" + "_".join(f"{k}-{v}" for k, v in sorted(query.items()))
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s) + ".json"


def capture(args) -> None:
    api = Api(args.base, args.token)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = routes(api)
    index = {}
    for n, (path, query) in enumerate(todo, 1):
        status, data = api.get(path, **query)
        name = _name(path, query)
        (out / name).write_text(json.dumps({"path": path, "query": query, "status": status, "data": data},
                                           sort_keys=True, indent=1, default=str))
        index[name] = status
        if n % 200 == 0:
            print(f"{n}/{len(todo)}", file=sys.stderr)
    (out / "_index.json").write_text(json.dumps(index, sort_keys=True, indent=1))
    bad = {k: v for k, v in index.items() if v != 200}
    print(f"captured {len(index)} answers into {out}; not 200: {len(bad)}")


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in IGNORE}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    if isinstance(x, float):
        return round(x, 6)
    return x


def _diffs(a, b, path="", out=None, limit=8):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path or '/'}: {str(a)[:80]!r} -> {str(b)[:80]!r}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: {'missing before' if k not in a else 'missing after'}")
            else:
                _diffs(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} items -> {len(b)} items")
        for i, (x, y) in enumerate(zip(a, b)):
            _diffs(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path or '/'}: {str(a)[:80]!r} -> {str(b)[:80]!r}")
    return out


def _canon(x):
    """The value with every list sorted, to tell an order-only difference."""
    if isinstance(x, dict):
        return {k: _canon(v) for k, v in x.items()}
    if isinstance(x, list):
        return sorted((_canon(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return x


def _drop(x, keys: set[str]):
    if isinstance(x, dict):
        return {k: _drop(v, keys) for k, v in x.items() if k not in keys}
    if isinstance(x, list):
        return [_drop(v, keys) for v in x]
    return x


#: Differences decision 0098 makes on purpose, by route: the keys that may
#: differ, and why. A click written before the switch has no journal batch
#: any more, so the batch screen offers no Undo for it.
EXPECTED = {"craft": ({"batch_id"}, "a click written before the switch has no Undo (decision 0098)")}


def classify(name: str, x, y) -> str:
    """`order` (the same values in another order), `expected` (a difference
    decision 0098 makes on purpose), `same_day` (the parts ledger: same-day
    events in another order, so the running balance between them differs),
    or `real`."""
    if _canon(x) == _canon(y):
        return "order"
    for tail, (keys, _why) in EXPECTED.items():
        if name.endswith(f"__{tail}.json") and _canon(_drop(x, keys)) == _canon(_drop(y, keys)):
            return "expected"
    if "parts-ledger" in name:
        keys = {"balance_after", "avg_usd_after", "short", "first_short"}
        if _canon(_drop(x, keys)) == _canon(_drop(y, keys)):
            return "same_day"
    return "real"


def compare(args) -> int:
    a, b = pathlib.Path(args.before), pathlib.Path(args.after)
    names = sorted({p.name for p in a.glob("*.json")} | {p.name for p in b.glob("*.json")} - {"_index.json"})
    names = [n for n in names if n != "_index.json"]
    kinds: dict[str, int] = {}
    for n in names:
        pa, pb = a / n, b / n
        if not pa.exists() or not pb.exists():
            print(f"{n}: only {'after' if not pa.exists() else 'before'}")
            kinds["real"] = kinds.get("real", 0) + 1
            continue
        x, y = _strip(json.loads(pa.read_text())), _strip(json.loads(pb.read_text()))
        if x != y:
            kind = classify(n, x, y)
            kinds[kind] = kinds.get(kind, 0) + 1
            if kind == "real" or args.all:
                print(f"{n}: [{kind}]")
                for line in _diffs(x, y):
                    print(f"    {line}")
    print(f"{len(names)} answers compared; differ: {kinds or 'none'}")
    return 1 if kinds.get("real") else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--base", required=True)
    c.add_argument("--token", default="")
    c.add_argument("--out", required=True)
    d = sub.add_parser("compare")
    d.add_argument("before")
    d.add_argument("after")
    d.add_argument("--all", action="store_true", help="print every difference, not only the real ones")
    args = ap.parse_args()
    if args.cmd == "capture":
        capture(args)
        return 0
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
