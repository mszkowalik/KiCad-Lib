"""Apply the sourcing the user gave on 2026-09-29 to the supplier register.

Run it AFTER the deploy that carries decision 0055 — the startup migration must
already have seeded the register and moved `Supplier N` into links. It goes
through the HTTP API, so every write is logged under the token's owner, and it
is idempotent: a supplier or link that exists is left alone, and a price that
was already attributed is not moved twice.

    KICAD_API_URL=https://disfunction.cc/lib KICAD_MCP_TOKEN=... \\
        uv run --with httpx python scripts/supplier-register-data-2026-09-29.py [--apply]

Without --apply it prints what it would do and writes nothing. The token must
belong to an admin: three suppliers are added to the register.

What the user said (Mateusz Kowalik, 2026-09-29), and what this does with it:

- Phoenix Contact parts come direct from Phoenix. The migration already linked
  the 17 parts; no price is known yet. Nothing to do.
- Italtronic is bought direct. Its three parts get an Italtronic link with the
  Italtronic part number (= the MPN, since it is bought from the maker), and
  their "Pool average (landed)" prices move onto that link unchanged.
- The Molex antennas come from DigiKey or Mouser, recently mostly Mouser: links
  to both, Mouser first. Their "Pool average (landed)" prices move onto the
  Mouser link unchanged (they are invoice averages, not a Mouser quote).
- FIX-LEMB2-4.8V0-F comes from TME, LE910R1-EU from Rutronik: the legacy
  "Manual" summary price moves onto that link unchanged.
- Hammond_1551XFLGY comes from DigiKey, TME or Mouser depending on stock: three
  links, library order. Its "Manual" price stays unattributed until the user
  says whose quote it is.
- Takachi_SIM6-12-3W comes from LC Elektronik as TKC-SIM6-12-3W: its "Manual"
  prices move onto that link unchanged.
"""
import os
import sys

import httpx

BASE = os.environ.get("KICAD_API_URL", "http://127.0.0.1:8020").rstrip("/")
TOKEN = os.environ["KICAD_MCP_TOKEN"]
APPLY = "--apply" in sys.argv

# Websites are left empty: nobody confirmed them. An admin adds them on the
# Suppliers tab.
NEW_SUPPLIERS = ["Italtronic", "Rutronik", "LC Elektronik"]

# component -> [(supplier, part number, legacy source to attribute or None)], in order
PLAN = {
    "Italtronic_05.0502530": [("Italtronic", "05.0502530", "Pool average (landed)")],
    "Italtronic_35.0207000.BL": [("Italtronic", "35.0207000.BL", "Pool average (landed)")],
    "Italtronic_P05050201P.BL": [("Italtronic", "P05050201P.BL", "Pool average (landed)")],
    "146153-0050": [("Mouser", "", "Pool average (landed)"), ("DigiKey", "", None)],
    "146153-0150": [("Mouser", "", "Pool average (landed)"), ("DigiKey", "", None)],
    "FIX-LEMB2-4.8V0-F": [("TME", "", "Manual")],
    "LE910R1-EU": [("Rutronik", "", "Manual")],
    "Hammond_1551XFLGY": [("DigiKey", "", None), ("TME", "", None), ("Mouser", "", None)],
    "Takachi_SIM6-12-3W": [("LC Elektronik", "TKC-SIM6-12-3W", "Manual")],
}
# Parts whose OWN order is set explicitly, in this order.
OWN_ORDER = {"146153-0050": ["Mouser", "DigiKey"], "146153-0150": ["Mouser", "DigiKey"]}

client = httpx.Client(base_url=BASE, timeout=60,
                      headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "python-httpx"})


def call(method: str, path: str, **kw):
    r = client.request(method, f"/api{path}", **kw)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code} {r.text[:300]}")
    return r.json()


def write(method: str, path: str, what: str, **kw):
    print(("   " if APPLY else "   (dry) ") + what)
    return call(method, path, **kw) if APPLY else None


register = {s["name"]: s for s in call("GET", "/suppliers")}
for name in NEW_SUPPLIERS:
    if name not in register:
        s = write("POST", "/suppliers", f"add supplier {name}", json={"name": name})
        if s:
            register[name] = s

comps = {c["name"]: c for c in call("GET", "/components", params={"page_size": 5000})["items"]}
for name, wanted in PLAN.items():
    comp = comps.get(name)
    if comp is None:
        print(f"!! {name}: not in the library, skipped")
        continue
    cid = comp["id"]
    print(f"{name} (#{cid})")
    state = call("GET", f"/components/{cid}/price-points")
    links = {ln["supplier"]: ln for ln in state["suppliers"]}
    for sup, pn, legacy in wanted:
        if sup not in register:
            print(f"   !! supplier {sup} is not in the register (dry run?)")
            continue
        if sup not in links:
            state = write("POST", f"/components/{cid}/suppliers", f"link {sup} {pn!r}",
                          json={"supplier_id": register[sup]["id"], "part_number": pn}) or state
            links = {ln["supplier"]: ln for ln in state["suppliers"]}
        elif pn and links[sup]["part_number"] != pn:
            state = write("PATCH", f"/components/{cid}/suppliers/{links[sup]['id']}",
                          f"set {sup} part number {pn!r}", json={"part_number": pn}) or state
        if legacy and sup in links:
            has_legacy = legacy in state["legacy_sources"] or any(
                p["source"] == legacy for p in state["legacy_summary"])
            if has_legacy:
                state = write("POST", f"/components/{cid}/price-points/attribute",
                              f"move {legacy!r} prices to {sup}",
                              json={"source": legacy, "link_id": links[sup]["id"]}) or state
    if name in OWN_ORDER and APPLY:
        links = {ln["supplier"]: ln for ln in state["suppliers"]}
        ids = [links[s]["id"] for s in OWN_ORDER[name] if s in links]
        state = write("PUT", f"/components/{cid}/supplier-order",
                      f"own order {OWN_ORDER[name]}", json={"link_ids": ids})
    if APPLY:
        print(f"   -> priced by {state['effective_source']}; order "
              f"{[ln['supplier'] for ln in state['suppliers']]}")
