"""Rebuild old batches into twins from their records only (decision 0060,
after the switch of decision 0098).

    python3 -I scripts/ledger-rebuild-old-batches.py BASE [TOKEN] [--runs=6,5,7] [--write]

Without --write it only dry-runs. The statements it makes move no money and
no stock: a part drawn for a board never programmed stays in the batch's own
cost (`loss`), a part the records show short stays short (`short`), and a
bench label step whose label the stock did not hold that day is `short`. No
step without a record is stated as done. A batch the dry run still refuses
is not written. Default runs: CE_Dongle_V2 Batches 1-7."""
import json, re, sys, urllib.request
base = sys.argv[1]; token = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else ""
write = "--write" in sys.argv
def call(path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "python-httpx/0.27 rebuild"})
    if token: req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=900) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
out = {}
RUNS = [int(x) for x in next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--runs=")), "6,5,7,8,9,10,11").split(",")]
for rid in RUNS:
    st, d = call(f"/api/runs/{rid}/rebuild", {"dry_run": True})
    settle = [{"step": u["step"], "part": u["part"], "how": "loss" if u["surplus"] > 0 else "short"}
              for u in d.get("unsettled", [])]
    for r in d.get("refusals", []):
        m = re.match(r".*: '(.+)' cannot draw its parts on .* \((\S+) short", r.get("message", ""))
        if m:
            step = next((s for s in ("label",) if "label" in m.group(1).lower()), None)
            if step and {"step": step, "part": "*", "how": "short"} not in settle:
                settle.append({"step": step, "part": "*", "how": "short"})
    st, d = call(f"/api/runs/{rid}/rebuild", {"dry_run": True, "settle": settle})
    refusals = [r.get("message") for r in d.get("refusals", [])]
    res = {"batch": d.get("batch"), "settle": settle, "refusals": refusals,
           "check_ok": (d.get("check") or {}).get("ok"), "twins": d.get("twins")}
    if write and not refusals:
        st, w = call(f"/api/runs/{rid}/rebuild", {"dry_run": False, "settle": settle})
        res["written"] = st == 200 and not w.get("refusals")
        res["batch_id"] = w.get("batch_id")
        if not res["written"]:
            res["write_answer"] = str(w)[:400]
    out[rid] = res
    print(rid, json.dumps(res)[:600], flush=True)
