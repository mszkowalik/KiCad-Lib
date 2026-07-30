"""The production-step catalog: vendor-neutral names for what money buys.

Three stages mirror the physical pipeline — `fab` (bare PCB production), `pcba`
(board assembly, what JLCPCB does), `final` (device assembly, what LIFTECH
does) — and each step is a stable key like `pcba:setup` or `final:marking`.
Vendors are just wordings on top: JLC's "Setup fee" and any future fab's
"Tooling/NRE" both mean `pcba:setup`, so cross-vendor comparison and
plan-vs-actual matching key on the STEP, never on the printed label.

This deliberately does NOT extend `RunCostLine.kind` — `kind` stays the coarse
cross-vendor money rollup (assembly is assembly whoever bills it). The step
rides in `plan_key`, which doubles as the link to the project's planned cost
items: a `ProjectCostItem` carrying the same `step_key` is the plan for every
line billed under that step (user design, 2026-07-28). `plan_key` values of the
older direct form `c<id>` (an explicit link to one cost item) remain valid —
`stage_of` simply doesn't recognise them as steps.

An invoice that is not split into fees stays honest at coarse grain with the
`<stage>:general` step. Add new steps here (enclosure milling, UV print, laser
marking, programming, ...) — one entry serves every vendor and every plan item.
"""
from __future__ import annotations

STAGES = {
    "parts": "Components / materials",
    "fab": "PCB production",
    "pcba": "PCB assembly",
    "final": "Final assembly",
    "logistics": "Freight & customs",
    "other": "Other",
}

# key -> (display label, default RunCostLine.kind)
STEPS: dict[str, tuple[str, str]] = {
    "parts:pool":         ("Components bought into the shared pool", "part"),
    "parts:prepaid":      ("Prepaid components (already pooled — excluded)", "part"),
    "parts:attrition":    ("Component attrition charged to the run", "part"),

    "fab:pcb":            ("Bare PCB fabrication", "fab"),
    "fab:setup":          ("PCB engineering / setup (NRE)", "tooling"),
    "fab:panel":          ("Panelization", "fab"),
    "fab:test":           ("PCB electrical test", "fab"),
    "fab:other":          ("PCB production — other / unexplained remainder", "fab"),
    "fab:general":        ("PCB production (unsplit)", "fab"),

    "pcba:setup":         ("Assembly setup", "tooling"),
    "pcba:stencil":       ("Stencil", "tooling"),
    "pcba:parts":         ("Components sourced by the assembler", "part"),
    "pcba:extended":      ("Extended / feeder fee", "assembly"),
    "pcba:smt":           ("SMT placement", "assembly"),
    "pcba:hand_solder":   ("Hand soldering", "assembly"),
    "pcba:manual":        ("Manual assembly at the fab", "assembly"),
    "pcba:special":       ("Special components handling", "assembly"),
    "pcba:fixture":       ("Assembly fixture / jig", "tooling"),
    "pcba:surcharge":     ("Per-board surcharge", "assembly"),
    "pcba:baking":        ("Component baking", "assembly"),
    "pcba:coating":       ("Conformal coating", "assembly"),
    "pcba:packaging":     ("Assembler packaging", "packaging"),
    "pcba:other":         ("PCB assembly — other / unexplained remainder", "assembly"),
    "pcba:general":       ("PCB assembly (unsplit)", "assembly"),

    "final:device":            ("Device assembly", "assembly"),
    "final:enclosure_milling": ("Enclosure modification — milling", "assembly"),
    "final:enclosure_print":   ("Enclosure modification — printing", "assembly"),
    "final:enclosure_mod":     ("Enclosure modification (unspecified)", "assembly"),
    "final:marking":           ("Individual marking (serial)", "assembly"),
    "final:programming":       ("Programming / flashing", "assembly"),
    "final:packing":           ("Packing into cartons", "packaging"),
    "final:shipping_prep":     ("Labels, manuals, dispatch", "service"),
    "final:other":             ("Final assembly — other / unexplained remainder", "assembly"),
    "final:general":           ("Final assembly (unsplit)", "assembly"),

    "logistics:inbound":  ("Inbound freight", "freight"),
    "logistics:duty":     ("Import taxes / customs (excluded, reclaimable)", "tax"),
    "other:discount":     ("Supplier discount", "other"),
}

# How a step naturally scales (user rule 2026-07-28): picking a step pre-sets
# the planned item's basis; overriding it is a conscious act. `:other` and
# `:general` carry NO default — they mean "we don't know", so nothing is
# presumed. Invoice-split children are NOT given a basis from here: their
# amounts are absolute, and `per_device` on a RunCostLine multiplies by the
# run's units (see `effective_qty`) — auto-setting it would inflate a $25 share
# to $25 x 550.
DEFAULT_BASIS: dict[str, str] = {
    "parts:pool": "per_device", "parts:prepaid": "per_device", "parts:attrition": "per_device",
    "fab:pcb": "per_device", "fab:setup": "per_run", "fab:panel": "per_run",
    "fab:test": "per_device",
    "pcba:setup": "per_run", "pcba:stencil": "per_run", "pcba:fixture": "per_run",
    "pcba:parts": "per_device", "pcba:extended": "per_run", "pcba:smt": "per_device",
    "pcba:hand_solder": "per_device", "pcba:manual": "per_device",
    "pcba:special": "per_device", "pcba:surcharge": "per_device",
    "pcba:baking": "per_run", "pcba:coating": "per_device", "pcba:packaging": "per_run",
    "final:device": "per_device", "final:enclosure_milling": "per_device",
    "final:enclosure_print": "per_device", "final:enclosure_mod": "per_device",
    "final:marking": "per_device", "final:programming": "per_device",
    "final:packing": "per_device", "final:shipping_prep": "per_run",
    "logistics:inbound": "per_run", "logistics:duty": "per_run",
    "other:discount": "per_run",
}

# How suppliers word the steps. Keyed by a lowercase substring of the printed
# fee name; first match wins. Used by the split dialog's templates and by
# imports that see a vendor's own fee list.
VENDOR_ALIASES: dict[str, list[tuple[str, str]]] = {
    "jlcpcb": [
        ("special components", "pcba:special"),   # before bare 'components'
        ("bare pcb", "fab:pcb"),
        ("pcb fabrication", "fab:pcb"),
        ("fab + assembly", "pcba:general"),
        ("populated", "pcba:general"),
        ("setup fee", "pcba:setup"),
        ("stencil", "pcba:stencil"),
        ("components", "pcba:parts"),          # after 'extended' below — order matters
        ("smt assembly", "pcba:smt"),
        ("hand-soldering", "pcba:hand_solder"),
        ("manual assembly", "pcba:manual"),
        ("packaging fee", "pcba:packaging"),
        ("surcharge", "pcba:surcharge"),
        ("baking", "pcba:baking"),
        ("coating", "pcba:coating"),
        ("unidentified", "pcba:other"),
    ],
    "liftech": [
        ("montaż", "final:device"),
        ("montaz", "final:device"),
        ("device assembly", "final:device"),
        ("batch", "final:device"),        # doc-31 "Batch N share — X units" children
        ("aqua batch", "final:device"),
    ],
    "italtronic": [
        ("dig print", "final:enclosure_print"),
        ("tooling", "final:enclosure_print"),
    ],
}
# 'extended components fee' contains 'components'; give it precedence.
VENDOR_ALIASES["jlcpcb"].insert(0, ("extended components", "pcba:extended"))

# Prefill templates for the split dialog: the vendor's EXACT wording, in the
# order their paperwork lists it, each already carrying its step. The operator
# copies figures across; identity comes for free.
VENDOR_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "JLCPCB assembly fees": [
        ("Setup fee", "pcba:setup"),
        ("Stencil", "pcba:stencil"),
        ("Components", "pcba:parts"),
        ("Extended components fee", "pcba:extended"),
        ("SMT Assembly", "pcba:smt"),
        ("Single board assembly surcharge", "pcba:surcharge"),
        ("Hand-soldering labor fee", "pcba:hand_solder"),
        ("Manual Assembly", "pcba:manual"),
        ("Packaging fee", "pcba:packaging"),
        ("Special components fee", "pcba:special"),
        ("Unidentified assembly charge", "pcba:other"),
    ],
    "Final assembly steps": [
        ("Device assembly", "final:device"),
        ("Enclosure milling", "final:enclosure_milling"),
        ("Enclosure printing", "final:enclosure_print"),
        ("Serial marking", "final:marking"),
        ("Programming", "final:programming"),
        ("Packing into cartons", "final:packing"),
        ("Labels, manuals, dispatch", "final:shipping_prep"),
    ],
}


def stage_of(plan_key: str | None) -> str | None:
    """The stage a plan_key belongs to, or None for non-step keys (`c<id>`
    direct links, empty, unknown prefixes)."""
    if not plan_key or ":" not in plan_key:
        return None
    stage = plan_key.split(":", 1)[0]
    return stage if stage in STAGES else None


def catalog_json() -> dict:
    return {
        "stages": STAGES,
        "steps": [
            {"key": k, "label": label, "default_kind": kind,
             "default_basis": DEFAULT_BASIS.get(k),
             "stage": k.split(":", 1)[0]}
            for k, (label, kind) in STEPS.items()
        ],
        "vendor_aliases": VENDOR_ALIASES,
        "templates": {
            name: [{"label": label, "step": step} for label, step in rows]
            for name, rows in VENDOR_TEMPLATES.items()
        },
    }
