"""Review checklists: the seed content, and resolution for a given subject.

A checklist item is ``{key, text, hint?, machine?, severity?, …}``. ``key`` is the
stable identity (check records reference items by key across checklist
revisions). ``machine: true`` items are answered automatically by
``services/validator.py`` on every publish; the rest are judgment calls for an
agent or a human.

**The validator owns the automatic checks, the checklist owns whether they
run.** ``validator.machine_checks(db)`` is the catalogue — key, text and hint —
so an automatic item's wording is never typed into a checklist and cannot drift
from the code. A checklist carries the machine item only to say ON or OFF. The
wording is built from the item's OWN ``params``, so the sentence a reviewer
reads and the comparison the code makes are the same fact.

``params`` is the other half: the numbers, lists and patterns a check measures
against, stored on the item that uses them. For a component they inherit
through category-scoped checklists, which is what gives a category its own
property rules with no second merge engine behind it.

``severity`` (``error`` / ``warning`` / ``ignore``) says what a FAILURE of this
check means, and ``ignore`` is also how a scope switches the check off — one
control with three values rather than a switch beside a severity. It applies at
this level **and below**: the merge is otherwise additive, so without it a
category-scoped list could add and reword items but never say "this base check
does not apply to my parts". An ignored item is dropped from
``resolve()["items"]`` and reported separately in ``resolve()["disabled"]``, so
nothing measures it, the validator is not asked for it
(`services/conformance.py`), and the editor can still show what was switched
off and where.

``disabled: true`` is the retired spelling of ``severity: "ignore"``. It is
still READ (`severity_of`) because a checklist version is immutable and
rewriting one would change what a past verification was measured against;
nothing writes it any more.

Resolution (`resolve`) merges the base checklist for the subject kind with any
category-scoped checklists on the component's category path. Seeds land once,
on startup, and only for kinds that have no base checklist yet — edits made in
the UI are never overwritten.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models as M

BASE_NAMES = {
    "component": "Component base checklist",
    "symbol": "Symbol base checklist",
    "footprint": "Footprint base checklist",
}

#: Automatic checks a FRESH install starts as WARNINGS rather than errors.
#: They used to be seeded switched off, which was "off" standing in for "on, but
#: not urgent" — the honest spelling of that is a warning (2026-09-14).
#: The two simulation checks answer `na` for anything with no sim model, and
#: whether a library wants them at error level was deliberately left to its
#: owner (validator.py note, 2026-08-25). The two category checks
#: (`cmp.property_values`, `cmp.base_symbol_allowed`) carry an empty set at the
#: base, so they have nothing to say until a CATEGORY fills one in.
#: What a failing check MEANS. One control with three values, not a switch
#: beside a severity: KiCad carries one on all 101 of its DRC and ERC rules, and
#: `ignore` is the same statement our `disabled` flag used to make.
#:
#: `error`   — a failure is a defect; it drives the subject's state.
#: `warning` — a failure is worth seeing and does NOT make the subject failed.
#: `ignore`  — the check does not run here at all (the old `disabled: true`).
#:
#: The middle value is what lets a new check ship at all. Four checks were
#: seeded switched OFF purely because turning a live machine item on re-opens
#: the whole library — `cmp.datasheet_text` moved 418 components to partial in
#: one publish. "Off" was standing in for "on, but not urgent", which is what
#: `warning` actually says.
SEVERITIES = ("error", "warning", "ignore")
DEFAULT_SEVERITY = "error"


def severity_of(item: dict) -> str:
    """An item's severity, reading the retired `disabled: true` as `ignore`.

    Rows written before 2026-09-14 carry the flag; nothing writes it any more
    and `_validate_items` converts it on the next save. Read compatibility is
    kept rather than migrated in place, because a checklist version is immutable
    and rewriting one would change what a past verification was measured
    against."""
    sev = str(item.get("severity") or "").strip()
    if sev in SEVERITIES:
        return sev
    return "ignore" if item.get("disabled") else DEFAULT_SEVERITY


SEED_AS_WARNING = {"sym.sim_link", "cmp.sim_params", "cmp.property_values",
                   "cmp.base_symbol_allowed"}

#: The JUDGMENT items only — what a person or an agent has to decide. The
#: automatic ones are composed from `validator.machine_checks` by `_seed_items`,
#: so there is one place where an automatic check's wording lives.
SEED_ITEMS: dict[str, list[dict]] = {
    "footprint": [
        {"key": "fp.land_pattern",
         "text": "Pad sizes, pitch and positions match the datasheet land-pattern drawing",
         "hint": "Compare against the recommended land pattern page, not the package outline."},
        {"key": "fp.pad_numbering", "text": "Pad numbering follows the datasheet pin numbering",
         "hint": "Connector pad numbering always follows the datasheet, never the housing."},
        {"key": "fp.body_outline", "text": "Fab body outline matches the package dimensions"},
        {"key": "fp.origin", "text": "Origin placement follows the convention (centred on the body)"},
        {"key": "fp.naming", "text": "Name follows the footprint naming standard (twelve-slot order)"},
        {"key": "fp.model_fit", "text": "The 3D model aligns with the drawn footprint"},
    ],
    "symbol": [
        {"key": "sym.pinout", "text": "Pin numbers and names match the datasheet pinout",
         "hint": "Check every pin against the datasheet pinout table, including NC pins."},
        {"key": "sym.pin_types",
         "text": "Pin electrical types are correct from the component's own viewpoint"},
        {"key": "sym.grouping", "text": "Pins are grouped by functional block with 2.54 mm gaps"},
        {"key": "sym.geometry", "text": "Box size, pin pitch and stub length follow the geometry rules",
         "hint": "Stub length is 2.54 mm unless a pin number runs to three or more characters, "
                 "which needs 5.08 mm to fit the number on the stub."},
        {"key": "sym.stacked", "text": "Shorted pins are stacked per the convention (where applicable)"},
    ],
    "component": [
        {"key": "cmp.mpn", "text": "MPN and manufacturer match the datasheet / product page",
         "hint": "EasyEDA and distributor data are leads, not facts — confirm in the datasheet."},
        {"key": "cmp.electrical", "text": "Electrical property values match the datasheet"},
        {"key": "cmp.description", "text": "ki_description follows the category template and is correct"},
        {"key": "cmp.value_field", "text": "The Value field follows the Value rule for the category"},
        {"key": "cmp.category", "text": "The component sits in the correct category"},
        {"key": "cmp.datasheet", "text": "The attached datasheet is the right document for this exact part"},
        {"key": "cmp.base_symbol", "text": "The chosen base symbol fits the part (pin count, roles)"},
    ],
}


def machine_item(db: Session, kind: str, key: str, *,
                 severity: str = DEFAULT_SEVERITY) -> dict | None:
    """One automatic item, worded by the validator's live catalogue.

    The checklist never authors this text — it stores the key, the machine flag
    and whether the check is on.
    """
    from . import validator

    entry = validator.machine_check(db, kind, key)
    if entry is None:
        return None
    item = {"key": entry["key"], "text": entry["text"], "machine": True}
    if entry.get("hint"):
        item["hint"] = entry["hint"]
    if entry.get("params"):
        # The numbers this check compares against live on the ITEM, so they
        # version with the checklist and the review record's snapshot records
        # what a past verification was measured against.
        item["params"] = dict(entry["params"])
    if severity != DEFAULT_SEVERITY:
        item["severity"] = severity
    return item


def _seed_items(db: Session, kind: str) -> list[dict]:
    """Every automatic check for the kind, then the judgment items."""
    from . import validator

    machine = [machine_item(db, kind, key,
                            severity="warning" if key in SEED_AS_WARNING else DEFAULT_SEVERITY)
               for key in validator.MACHINE_KEYS.get(kind, ())]
    return [m for m in machine if m is not None] + list(SEED_ITEMS[kind])


def seed_checklists(db: Session) -> list[str]:
    """Create the base checklist per kind where none exists. Idempotent."""
    created: list[str] = []
    for kind, name in BASE_NAMES.items():
        exists = (
            db.query(M.Checklist)
            .filter_by(subject_kind=kind, category_id=None)
            .first()
        )
        if exists is not None:
            continue
        cl = M.Checklist(name=name, subject_kind=kind, category_id=None,
                         description=f"Base verification checklist for every {kind}")
        db.add(cl)
        db.flush()
        cv = M.ChecklistVersion(checklist_id=cl.id, version_no=1,
                                items=_seed_items(db, kind), status="published",
                                created_by="seed", comment="Initial seed")
        db.add(cv)
        db.flush()
        cl.current_version_id = cv.id
        created.append(name)
    if created:
        db.commit()
    return created


def _current_items(cl: M.Checklist) -> tuple[int | None, list[dict]]:
    cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
    if cv is None:
        return None, []
    return cv.id, list(cv.items or [])


#: Every fact a `when` predicate or an `assert` may name, besides a component
#: property. A property is written bare (`comp_type`); these carry a `$` so a
#: category named "category" can never be confused with the category itself,
#: and so a misspelled fact is REFUSED at save time rather than silently
#: matching nothing. Properties cannot be validated that way — any string is a
#: legal property name — which is the asymmetry to keep in mind when writing
#: one.
#:
#: `kinds` is which SUBJECTS carry the fact. A predicate naming a fact the
#: subject has not got never matches, which is the honest outcome, but the
#: editor uses this to say so before anybody saves a rule that can match
#: nothing.
#:
#: `noun` is the phrase the generated sentence of an `assert` uses as its
#: subject. Without one the name is de-`$`-ed and de-underscored, which yields
#: "The footprint zero annulus pads is at most 0" — correct, and not a sentence
#: anybody wants on a review card.
#:
#: `lazy` marks a fact computed only when something asks for it. Parsing every
#: symbol and footprint on the coverage endpoint would turn a page into a
#: minute; `_LazyFacts` memoises each on first read, so a checklist that
#: mentions none costs nothing at all.
FACTS: tuple[dict, ...] = (
    # ------------------------------------------------------------ structural
    {"name": "$kind", "kinds": ("component", "symbol", "footprint"),
     "what": "component, symbol or footprint"},
    {"name": "$name", "kinds": ("component", "symbol", "footprint"),
     "what": "the subject's own name"},
    {"name": "$category", "kinds": ("component",),
     "what": "top-level category name"},
    {"name": "$category_path", "kinds": ("component",),
     "what": "full category path, slash separated"},
    {"name": "$base_symbol", "kinds": ("component",),
     "what": "the base symbol this component is drawn as"},
    {"name": "$footprint", "kinds": ("component",),
     "what": "the Footprint property, library prefix included"},
    {"name": "$in_library", "kinds": ("component",),
     "claim": "KiCad is served this part",
     "what": "true when KiCad is served this part"},
    {"name": "$purchasable", "kinds": ("component",),
     "claim": "The part is purchased rather than generic",
     "what": "true when the part is bought rather than generic"},
    {"name": "$lifecycle", "kinds": ("component",),
     "what": "in design / released / deprecated / obsolete"},
    # ------------------------------------------------------- fingerprints
    #: What a standing exception pins when it is scoped to the DRAWING rather
    #: than to the part (`services/exceptions.py`). `$material_sha` covers what
    #: reaches the board — pads, courtyard, pin set — and deliberately not
    #: silkscreen or a description, so a cosmetic edit never kills a waiver.
    #: `$property_sha` is the component's own data, for a waiver about a VALUE
    #: rather than about a drawing.
    {"name": "$material_sha", "kinds": ("component", "symbol", "footprint"),
     "what": "fingerprint of what reaches the board"},
    {"name": "$property_sha", "kinds": ("component",),
     "what": "fingerprint of the component's own fields"},
    # ------------------------------------------------------------- symbol
    {"name": "$symbol_reference", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol reference prefix",
     "what": "the Reference prefix drawn on the symbol (R, C, U…)"},
    {"name": "$symbol_pin_count", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol pin count",
     "what": "how many pins the symbol draws"},
    {"name": "$symbol_pin_numbers", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of distinct pin numbers",
     "what": "how many DISTINCT pin numbers — fewer than the pin count when pins are stacked"},
    {"name": "$symbol_unit_count", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol unit count",
     "what": "how many units (gates) the symbol has"},
    {"name": "$symbol_on_board", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol's on-board flag",
     "claim": "The symbol is placed on the board",
     "what": "false for a symbol excluded from the board"},
    {"name": "$symbol_sim_link", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "simulation link",
     "claim": "A simulation model is linked",
     "what": "true when a simulation model is linked"},
    {"name": "$symbol_pin_types", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "set of pin types",
     "what": "the distinct electrical pin types present, comma separated and sorted"},
    #: `conventions-symbols` §3 — nothing electrical on the top edge, with one
    #: documented exception (§5.6 digital blocks, where the top and bottom
    #: edges carry the asynchronous controls). A COUNT, so the exception lives
    #: in the checklist as a `when` rather than inside Python.
    {"name": "$symbol_top_edge_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of signal or supply pins on the top edge",
     "what": "signal or supply pins on the TOP edge"},
    {"name": "$symbol_bottom_edge_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of signal or supply pins on the bottom edge",
     "what": "signal or supply pins on the BOTTOM edge"},
    {"name": "$symbol_stub_lengths", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of different pin stub lengths",
     "what": "how many DISTINCT pin stub lengths the drawing mixes — more than one is the defect"},
    # ---------------------------------------------------------- footprint
    {"name": "$footprint_pad_count", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "numbered pad count",
     "what": "how many DISTINCT numbered pads — paste apertures and thermal vias excluded"},
    {"name": "$footprint_has_model3d", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "3D model reference",
     "claim": "A 3D model is referenced",
     "what": "true when a 3D model is referenced"},
    {"name": "$footprint_smd_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "surface-mount pad count",
     "what": "how many pad nodes are surface mount"},
    {"name": "$footprint_th_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "plated through-hole pad count",
     "what": "how many pad nodes are plated through-hole"},
    {"name": "$footprint_npth_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "non-plated hole count",
     "what": "how many pad nodes are non-plated (mechanical) holes"},
    #: The zero-annulus defect `conventions-footprints` §6 describes: an
    #: unnamed plated hole whose copper equals its drill, which KiCad DRC
    #: raises a minimum-annular-width violation on. Counted rather than
    #: asserted here so a check can say `at_most 0` and a part can carry an
    #: exception for a hole that is genuinely plated and netted.
    {"name": "$footprint_zero_annulus_pads", "kinds": ("component", "footprint"),
     "lazy": True,
     "noun": "count of plated holes with no annular ring",
     "what": "plated holes whose copper equals their drill — each is a DRC violation"},
    #: `conventions-footprints` §5. The fine-pitch exception is real, so this
    #: is a COUNT and the rule lives in the check's threshold, not here.
    {"name": "$footprint_off_grid_pads", "kinds": ("component", "footprint"),
     "lazy": True,
     "noun": "count of pads off the 0.1 mm grid",
     "what": "pad centres off the 0.1 mm grid"},
    {"name": "$footprint_min_pitch", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "lead pitch in mm",
     "what": "nearest centre-to-centre distance between two numbered pads, in mm"},
    #: The grid exception is available BELOW 1 mm and not above — the threshold
    #: `conventions-footprints` §5 states outright, with a decided case on each
    #: side. Kept as its own fact so the rule that reads it lives in the
    #: checklist, where it can be seen, rather than inside a Python count.
    {"name": "$footprint_fine_pitch", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "fine-pitch flag",
     "claim": "The lead pitch is below 1 mm",
     "what": "true when the lead pitch is below 1 mm, where the 0.1 mm grid exception applies"},
    #: `conventions-footprints` §2. A mirrored quad passes every other check —
    #: outline, pitch, courtyard and pad count all still agree — and only the
    #: numbers are wrong, which is why one shipped. Reported as a CORNER rather
    #: than a boolean so the rule that reads it stays in the checklist.
    {"name": "$footprint_pin1_corner", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "corner pad 1 sits in",
     "what": "where pad 1 sits: top-left, top-right, bottom-left, bottom-right, "
             "or left/right/top/bottom for a pad on an axis, or center"},
    {"name": "$footprint_numbering", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "pad numbering direction",
     "what": "ccw or cw for a package with pads on four edges, empty otherwise"},
    # --------------------------------------------------------- cross-fact
    #: `assert` is deliberately one fact against one literal, so a comparison
    #: between two facts belongs HERE, in Python, and never in a boolean
    #: assertion language. The fact vocabulary is the extension point; the
    #: assertion vocabulary stays closed.
    {"name": "$pins_match_pads", "kinds": ("component",), "lazy": True,
     "noun": "pin set against the pad set",
     "claim": "The symbol's pin numbers and the footprint's pad numbers are the same set",
     "what": "true when the symbol's pin numbers and the footprint's pad numbers are the same set"},
    #: Split in two on purpose. A pin with no pad is a signal with nowhere to
    #: go; a pad with no pin is usually an exposed thermal pad or an NC lead.
    #: One mismatch number would make the second drown the first.
    {"name": "$pins_without_pads", "kinds": ("component",), "lazy": True,
     "noun": "count of pins with no pad",
     "what": "symbol pins whose number has no pad — a signal with nowhere to land"},
    {"name": "$pads_without_pins", "kinds": ("component",), "lazy": True,
     "noun": "count of pads the symbol does not draw",
     "what": "pads the symbol does not draw — often an exposed pad or an NC lead"},
    {"name": "$value_is_mpn", "kinds": ("component",), "lazy": True,
     "noun": "Value against the manufacturer part number",
     "claim": "Value is Manufacturer Part Number 1, verbatim",
     "what": "true when Value is Manufacturer Part Number 1 verbatim"},
    {"name": "$value_is_name", "kinds": ("component",), "lazy": True,
     "noun": "Value against the component name",
     "claim": "Value is the component's own name",
     "what": "true when Value is the component's own name"},
    {"name": "$value_placeholder", "kinds": ("component",), "lazy": True,
     "noun": "Value placeholder flag",
     "claim": "Value is empty or a placeholder",
     "what": "true when Value is empty, ~, N/A, -, an unresolved {Template} or a copy of ki_description"},
)

FACTS_BY_NAME = {f["name"]: f for f in FACTS}

#: Facts available without parsing anything. Kept as a name because the save
#: path and the editor both ask "may a predicate read this cheaply".
WHEN_FACTS = tuple(f["name"] for f in FACTS if not f.get("lazy"))

#: Facts DERIVED from a drawing, computed on demand.
DERIVED_FACTS = tuple(f["name"] for f in FACTS if f.get("lazy"))

#: Everything a `when` predicate or an `assert` may name, besides a property.
ALL_FACTS = tuple(f["name"] for f in FACTS)


def facts_for_kind(kind: str) -> list[dict]:
    """The vocabulary one subject kind actually carries, for the editor."""
    return [dict(f) for f in FACTS if kind in f["kinds"]]


class _LazyFacts(dict):
    """The facts of one subject, with the expensive ones computed on demand.

    `get` is overridden as well as `__missing__` because every reader uses
    `.get()` — and `dict.get` does NOT call `__missing__`, which would have made
    every derived fact silently absent. An absent fact never matches a
    predicate, so the bug would have read as "this check applies to nothing"
    rather than as a failure.
    """

    def __init__(self, base: dict, providers: dict):
        super().__init__(base)
        self._providers = providers

    def _compute(self, key):
        fn = self._providers.pop(key, None)
        if fn is None:
            return None
        try:
            value = fn()
        except Exception:  # noqa: BLE001 — a fact that cannot be read is absent
            value = None
        self[key] = value
        return value

    def get(self, key, default=None):  # type: ignore[override]
        if key in self:
            return dict.get(self, key, default)
        value = self._compute(key)
        return default if value is None else value

    def __missing__(self, key):
        value = self._compute(key)
        if value is None:
            raise KeyError(key)
        return value


def subject_facts(db: Session, kind: str, parent, version_id: int | None) -> dict:
    """What a `when` predicate is matched against, as strings.

    Only a COMPONENT has properties and a category, so a symbol or a footprint
    gets the structural facts alone — a predicate over `comp_type` on a
    footprint checklist matches nothing, which is the honest outcome.
    """
    facts: dict[str, str] = {"$kind": kind}
    if kind != "component":
        facts["$name"] = getattr(parent, "name", "") or ""
        version = db.get(M.SymbolVersion if kind == "symbol" else M.FootprintVersion,
                         version_id) if version_id else None
        # An EMPTY material_sha means "could not tell" and must never compare
        # equal to another empty one — the rule `services/signoff.py` states for
        # the carry, and an exception pinned to one would be worse: it would
        # stay live across exactly the changes nobody could fingerprint.
        if version is not None and version.material_sha:
            facts["$material_sha"] = version.material_sha
        if version is None:
            return facts
        # A symbol and a footprint carry their own drawing facts. Until
        # 2026-09-14 they carried NONE — `$kind`, `$name` and a fingerprint —
        # so a footprint checklist could not say "this rule is about quad
        # packages" and every geometry rule had to be prose in a skill for an
        # agent to read.
        def src(v=version) -> str:
            return v.source_text or ""

        providers = (_symbol_providers(src) if kind == "symbol"
                     else _footprint_providers(src))
        if kind == "symbol":
            providers["$symbol_sim_link"] = lambda v=version: (
                "true" if db.query(M.SymbolSimLink).filter_by(
                    symbol_id=v.symbol_id).first() else "false")
        else:
            providers["$footprint_has_model3d"] = lambda v=version: (
                "true" if (v.models or []) else "false")
        return _LazyFacts(facts, providers)
    cv = db.get(M.ComponentVersion, version_id) if version_id else None
    if cv is None:
        return facts
    from ..routers.util import category_path
    from .mirror import top_level_of

    for prop in cv.properties:
        if not prop.is_null and prop.value is not None:
            facts[prop.key] = str(prop.value)
    facts["$name"] = parent.name or ""
    facts["$base_symbol"] = cv.base_component or ""
    facts["$footprint"] = facts.get("Footprint", "")
    facts["$lifecycle"] = getattr(parent, "lifecycle_state", "") or ""
    facts["$in_library"] = "true" if parent.in_library else "false"
    facts["$purchasable"] = "true" if parent.purchasable else "false"
    if cv.category is not None:
        facts["$category"] = top_level_of(cv.category).name
        facts["$category_path"] = category_path(cv.category)
    # The two drawings this component pins, as one value. A component has no
    # fingerprint of its own; what reaches the board is its symbol and its
    # footprint, so a drawing-scoped exception on a component pins both.
    shas = [getattr(cv.symbol_version, "material_sha", None),
            getattr(cv.footprint_version, "material_sha", None)]
    if all(shas):
        facts["$material_sha"] = "+".join(shas)
    facts["$property_sha"] = _property_sha(cv)
    return _LazyFacts(facts, _derived_providers(db, cv))


def _property_sha(cv: M.ComponentVersion) -> str:
    """A digest of the component's own data — the same triple
    `signoff.data_carries` compares, so an exception pinned to it dies on
    exactly the edits that would have stripped a verification."""
    import hashlib

    payload = ";".join(
        f"{p.key}={'' if p.is_null else (p.value or '')}"
        for p in sorted(cv.properties, key=lambda x: x.key))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _derived_providers(db: Session, cv: M.ComponentVersion) -> dict:
    """How to compute each derived fact of a COMPONENT, if anything asks.

    Every value is a STRING, so one predicate language covers them all; the
    assertion evaluator coerces where it needs a number.

    A component's drawing facts are the SAME functions a symbol or footprint
    subject uses — one definition, so `$footprint_pad_count` cannot mean one
    thing on the footprint page and another on the component page.
    """
    def symbol_src() -> str:
        return (cv.symbol_version.source_text or "") if cv.symbol_version else ""

    def footprint_src() -> str:
        return (cv.footprint_version.source_text or "") if cv.footprint_version else ""

    out = {**_symbol_providers(symbol_src), **_footprint_providers(footprint_src)}

    def sim_link():
        sv = cv.symbol_version
        if sv is None:
            return None
        return "true" if db.query(M.SymbolSimLink).filter_by(
            symbol_id=sv.symbol_id).first() else "false"

    def has_model():
        fv = cv.footprint_version
        return None if fv is None else ("true" if (fv.models or []) else "false")

    out["$symbol_sim_link"] = sim_link
    out["$footprint_has_model3d"] = has_model

    # ---------------------------------------------------------- cross-fact
    # A comparison between two facts, in Python. `assert` is deliberately one
    # fact against one literal: the moment an assertion can name two facts it
    # has become a rules language, and the whole point of the declarative form
    # is that it is configuration a person can read.
    from . import material

    def props() -> dict:
        return {p.key: ("" if p.is_null else str(p.value or ""))
                for p in cv.properties}

    def _number_sets():
        """The symbol's pin numbers and the footprint's pad numbers, as SETS.

        Sets, never counts. Stacked pins share one number, a thermal via
        repeats the exposed pad's number, and a mechanical hole has none at
        all — so counting nodes answers a different question and answers it
        wrongly on most real parts.
        """
        if cv.symbol_version is None or cv.footprint_version is None:
            return None, None
        try:
            pin_nums = {str(p.get("number") or "").strip()
                        for p in material.symbol_material(symbol_src())["pins"]}
            pad_nums = {str(p.get("number") or "").strip()
                        for p in material.footprint_material(footprint_src())["pads"]}
        except Exception:  # noqa: BLE001 — an unparseable drawing answers nothing
            return None, None
        pin_nums.discard("")
        pad_nums.discard("")
        if not pin_nums or not pad_nums:
            return None, None
        return pin_nums, pad_nums

    def pins_match_pads():
        pin_nums, pad_nums = _number_sets()
        if pin_nums is None:
            return None
        return "true" if pin_nums == pad_nums else "false"

    def pins_without_pads():
        """Symbol pins with no pad to land on. Almost always a real defect —
        the signal has nowhere to go on the board."""
        pin_nums, pad_nums = _number_sets()
        return None if pin_nums is None else str(len(pin_nums - pad_nums))

    def pads_without_pins():
        """Pads the symbol does not draw. Usually legitimate — an exposed
        thermal pad, or a package NC lead the symbol leaves off — which is why
        it is counted SEPARATELY from the defect above rather than summed into
        one mismatch number."""
        pin_nums, pad_nums = _number_sets()
        return None if pin_nums is None else str(len(pad_nums - pin_nums))

    def value_is_mpn():
        p = props()
        value, mpn = p.get("Value", ""), p.get("Manufacturer Part Number 1", "")
        if not value or not mpn:
            return None
        return "true" if value.strip() == mpn.strip() else "false"

    def value_is_name():
        value = props().get("Value", "")
        if not value:
            return None
        # Component names are sanitised for KiCad — spaces and commas become
        # underscores — so `MCV_1,5/_2-GF-3,5-LR` and its Value differ by
        # exactly that substitution and must still count as the same.
        name = (getattr(cv, "component", None).name if getattr(cv, "component", None)
                else "") or ""
        if not name:
            return None
        norm = re.compile(r"[ ,_]+")
        return "true" if norm.sub("_", value.strip()) == norm.sub("_", name.strip()) \
            else "false"

    #: Values that are present but say nothing. `conventions-library` §3 lists
    #: them, and every one has been seen in this library.
    junk = {"", "~", "n/a", "na", "-", "--", "?"}

    def value_placeholder():
        p = props()
        value = p.get("Value", "").strip()
        if value.lower() in junk:
            return "true"
        if re.search(r"\{[^}]+\}", value):
            return "true"  # an unresolved template reference
        if value and value == p.get("ki_description", "").strip():
            return "true"
        return "false"

    out["$pins_match_pads"] = pins_match_pads
    out["$pins_without_pads"] = pins_without_pads
    out["$pads_without_pins"] = pads_without_pins
    out["$value_is_mpn"] = value_is_mpn
    out["$value_is_name"] = value_is_name
    out["$value_placeholder"] = value_placeholder
    return out


# ------------------------------------------------------------------ drawings
# Facts read off a symbol or a footprint. Every one is computed from
# `source_text` through `services/material.py`, NOT from
# `FootprintVersion.parsed` — `parsed` is an older, narrower structure that
# carries no pad position and no drill, so a fact built on it silently reports
# nothing about geometry. (It also counts paste apertures as pads: a
# QFN-16-1EP parses as 26 "pads", which is what `$footprint_pad_count` used to
# report.)

#: Pad numbers that are not a pin: an unnamed mechanical hole, and the empty
#: number a paste-only aperture carries.
def _numbered(pads: list[dict]) -> list[dict]:
    return [p for p in pads if str(p.get("number") or "").strip()]


def _grid_off(value: float, grid: float = 0.1) -> bool:
    """Is this coordinate off the grid? Tolerant to one part in 10,000 — the
    parser rounds to six places and 1.2999999 is 1.3, not a defect."""
    return abs(round(value / grid) * grid - value) > 1e-4


def _corner_of(at: list | None, tol: float = 1e-4) -> str:
    """Which corner (or edge, or centre) a pad sits in.

    A two-pad chip has both pads ON the X axis, so "bottom-left" would be a
    lie invented by a `y < 0` test — it reports `left`. The same for a pad on
    the Y axis. Only a pad genuinely off both axes gets a corner.

    KiCad Y points DOWN, so negative y is the TOP of the drawing. Getting that
    backwards is the exact mistake `conventions-footprints` §2 is about.
    """
    if not at or len(at) < 2:
        return ""
    x, y = float(at[0]), float(at[1])
    across = "" if abs(x) < tol else ("left" if x < 0 else "right")
    down = "" if abs(y) < tol else ("top" if y < 0 else "bottom")
    if not across and not down:
        return "center"
    return f"{down}-{across}" if (across and down) else (down or across)


def _footprint_providers(source_of) -> dict:
    """Facts of one footprint. `source_of` is called at most once per read."""
    from . import material

    cache: dict = {}

    def pads() -> list[dict]:
        if "pads" not in cache:
            try:
                cache["pads"] = material.footprint_material(source_of() or "")["pads"]
            except Exception:  # noqa: BLE001 — an unparseable drawing has no facts
                cache["pads"] = []
        return cache["pads"]

    def pad_count():
        nums = {p["number"] for p in _numbered(pads())}
        return str(len(nums)) if pads() else None

    def of_type(*types):
        def fn():
            return str(sum(1 for p in pads() if p.get("type") in types)) if pads() else None
        return fn

    def zero_annulus():
        """A plated hole whose copper does not exceed its drill. The rule of
        thumb `conventions-footprints` §6 states: `(size - drill) / 2 <= 0`."""
        if not pads():
            return None
        n = 0
        for p in pads():
            if p.get("type") != "thru_hole":
                continue
            size, drill = p.get("size"), p.get("drill")
            if not size or not drill:
                continue
            d = drill[0] if isinstance(drill, list) else drill
            try:
                if min(float(size[0]), float(size[1])) - float(d) <= 0:
                    n += 1
            except (TypeError, ValueError, IndexError):
                continue
        return str(n)

    def off_grid():
        if not pads():
            return None
        n = 0
        for p in _numbered(pads()):
            at = p.get("at")
            if not at or len(at) < 2:
                continue
            if _grid_off(float(at[0])) or _grid_off(float(at[1])):
                n += 1
        return str(n)

    def pin1_corner():
        one = next((p for p in pads() if str(p.get("number")) == "1"), None)
        return _corner_of(one.get("at") if one else None) or None

    def numbering():
        """ccw or cw, for a package whose numbered pads sit on four edges.

        Empty for anything else: a two-row SOIC or a two-pad chip has no
        direction to be wrong about, and reporting one would invite a rule that
        fires on parts it was never written for.
        """
        pts = []
        for p in _numbered(pads()):
            at = p.get("at")
            if not at or len(at) < 2:
                continue
            try:
                pts.append((int(p["number"]), float(at[0]), float(at[1])))
            except (TypeError, ValueError):
                continue
        if len(pts) < 8:
            return None
        pts.sort()
        corners = {_corner_of([x, y]) for _, x, y in pts}
        if len({c for c in corners if c and c != "center"}) < 4:
            return None
        # The signed area of the polygon the pads trace in number order.
        #
        # KiCad Y points DOWN, which INVERTS the usual shoelace sign: the
        # correct counter-clockwise-on-screen trace — down the left edge, right
        # along the bottom, up the right, left along the top — sums NEGATIVE.
        # Verified against `QFN-16-1EP_3x3mm_P0.5mm`, whose pads run
        # 1..4 at x=-1.4625 with y increasing, then 5,6 at y=+1.4625 with x
        # increasing: that is the layout `conventions-footprints` §2 requires,
        # and it gives a negative area.
        area = 0.0
        for i, (_, x, y) in enumerate(pts):
            _, nx, ny = pts[(i + 1) % len(pts)]
            area += x * ny - nx * y
        return "ccw" if area < 0 else "cw"

    def one_per_number() -> list[dict]:
        """One pad per distinct number, with a position.

        Thermal vias repeat the exposed pad's number and sit a via-pitch apart,
        so counting every node would report a 0.6 mm package pitch on a 0.5 mm
        QFN with vias under it.
        """
        seen: dict[str, dict] = {}
        for pad in _numbered(pads()):
            at = pad.get("at")
            if at and len(at) >= 2:
                seen.setdefault(str(pad["number"]), pad)
        return list(seen.values())

    def min_pitch():
        """Nearest centre-to-centre distance between two numbered pads, in mm.

        A proxy for the lead pitch, and a good one: on every package the
        closest two pads are adjacent leads on one edge.
        """
        pts = [(float(p["at"][0]), float(p["at"][1])) for p in one_per_number()]
        if len(pts) < 2:
            return None
        best = None
        for i, (x1, y1) in enumerate(pts):
            for x2, y2 in pts[i + 1:]:
                d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                if d > 1e-6 and (best is None or d < best):
                    best = d
        return None if best is None else f"{round(best, 4):g}"

    def fine_pitch():
        """Is the pitch-axis grid exception available to this footprint?

        `conventions-footprints` §5 states the threshold outright: "below 1 mm
        it may apply, above it does not". Two decided cases sit on each side —
        a 0.5 mm QFN keeps its datasheet pitch, a 4.5 mm tact switch and the
        0.95 mm SOT-23 are snapped — so the boundary is the fact, and the rule
        that reads it stays in the checklist where it can be seen.
        """
        p = min_pitch()
        return None if p is None else ("true" if float(p) < 1.0 else "false")

    return {
        "$footprint_pad_count": pad_count,
        "$footprint_min_pitch": min_pitch,
        "$footprint_fine_pitch": fine_pitch,
        "$footprint_smd_pads": of_type("smd"),
        "$footprint_th_pads": of_type("thru_hole"),
        "$footprint_npth_pads": of_type("np_thru_hole"),
        "$footprint_zero_annulus_pads": zero_annulus,
        "$footprint_off_grid_pads": off_grid,
        "$footprint_pin1_corner": pin1_corner,
        "$footprint_numbering": numbering,
    }


def _symbol_providers(source_of) -> dict:
    """Facts of one symbol. `source_of` is called at most once per read."""
    from . import material

    cache: dict = {}

    def pins() -> list[dict]:
        if "pins" not in cache:
            try:
                cache["pins"] = material.symbol_material(source_of() or "")["pins"]
            except Exception:  # noqa: BLE001
                cache["pins"] = []
        return cache["pins"]

    def reference():
        m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', source_of() or "")
        return m.group(1) if m else None

    #: Which edge a pin sits on, from its ANGLE. In a `.kicad_sym` the pin's
    #: `at` is its connection point and the angle is the direction its body
    #: runs toward the box — so angle 0 is the LEFT edge, 180 the right, 270
    #: the top and 90 the bottom.
    #:
    #: Symbol Y points UP, the opposite of a footprint. Both live in this file.
    _EDGE = {0: "left", 90: "bottom", 180: "right", 270: "top"}

    def edge_of(pin: dict) -> str:
        at = pin.get("at") or []
        if len(at) < 3:
            return ""
        return _EDGE.get(int(round(float(at[2]))) % 360, "")

    #: Pin types that carry a signal or a supply. `conventions-symbols` §3
    #: forbids these on the top edge; an unconnected or free pin is not what
    #: that rule is about.
    _ELECTRICAL = {"input", "output", "bidirectional", "tri_state",
                   "power_in", "power_out", "open_collector", "open_emitter"}

    def on_edge(edge: str):
        def fn():
            if not pins():
                return None
            return str(sum(1 for p in pins()
                           if edge_of(p) == edge and p.get("type") in _ELECTRICAL))
        return fn

    def stub_lengths():
        """How many DISTINCT stub lengths the drawing mixes.

        The absolute length is a judgment call on the geometry; what is
        mechanical is mixing them inside one symbol, which is what
        `sym.pin_length` was written for.
        """
        lens = {p.get("length") for p in pins() if p.get("length") is not None}
        return str(len(lens)) if lens else None

    return {
        "$symbol_reference": reference,
        "$symbol_top_edge_pins": on_edge("top"),
        "$symbol_bottom_edge_pins": on_edge("bottom"),
        "$symbol_stub_lengths": stub_lengths,
        "$symbol_pin_count": lambda: str(len(pins())) if pins() else None,
        # DISTINCT numbers, which is what compares against a pad set: stacked
        # (shorted) pins share one number and must not count twice.
        "$symbol_pin_numbers": lambda: str(len({p.get("number") for p in pins()}))
        if pins() else None,
        # `unit` is [unit, style] — a LIST, so a naive set of them raises and
        # the fact reads as absent, which is the quietest way for a declared
        # fact to never work.
        "$symbol_unit_count": lambda: str(len({(p.get("unit") or [0])[0] for p in pins()}))
        if pins() else None,
        "$symbol_pin_types": lambda: ",".join(sorted({str(p.get("type") or "")
                                                      for p in pins()})) or None,
        "$symbol_on_board": lambda: "false" if re.search(
            r"\(on_board\s+no\)", source_of() or "") else "true",
    }


def when_matches(when: dict | None, facts: dict | None) -> bool:
    """Does this item apply to the subject these facts describe?

    Every entry must match (AND), each value read as a regular expression. A
    fact that is ABSENT never matches: `{"comp_type": "^TVS$"}` excludes a part
    carrying no `comp_type` at all, which is what "apply this to TVS parts"
    means. `facts=None` is "no subject in hand" — the editor resolving a
    category to show it — and then every item applies, because the screen is
    describing the rule rather than judging one part.
    """
    if not when:
        return True
    if facts is None:
        return True
    for field, pattern in when.items():
        value = facts.get(field)
        if value is None:
            return False
        try:
            if re.match(str(pattern), value) is None:
                return False
        except re.error:
            # A pattern that does not compile matches NOTHING rather than
            # everything: the check quietly not applying is recoverable, a
            # check quietly applying to the whole library is not. The save
            # path refuses these, so this only guards rows written before it.
            return False
    return True


def _group(items: list[dict]) -> dict[str, list[dict]]:
    """Items by key, order preserved. A key may hold several VARIANTS."""
    out: dict[str, list[dict]] = {}
    for item in items:
        out.setdefault(item["key"], []).append(item)
    return out


def discriminator_of(group: list[dict]) -> str | None:
    """The one field a multi-variant key splits on, or None for a single item.

    A key with several variants must discriminate on ONE field with distinct
    literal values (`routers/reviews._validate_items` enforces it), which is
    what lets `pick` avoid an ordering rule entirely: at most one literal can
    match, and the variant with no `when` is the explicit fallback. Order is
    therefore never consulted, so a sorted table can never contradict the
    effective precedence — the failure that positional first-match-wins would
    have introduced.
    """
    if len(group) < 2:
        return None
    for item in group:
        when = item.get("when") or {}
        if len(when) == 1:
            return next(iter(when))
    return None


def pick(group: list[dict], facts: dict | None) -> tuple[dict | None, str]:
    """The one item of a key group that applies, and why.

    Returns ``(item, reason)`` where reason is ``ok``, ``disabled`` (every
    variant is switched off here) or ``no_match`` (nothing in the group is about
    a subject like this one). ``facts=None`` means no subject is in hand — the
    editor describing a rule rather than judging a part — and the first live
    variant stands in for the group.

    A variant set to `ignore` falls through to the next one rather than
    switching the whole check off (user decision 2026-09-14): ignoring the NMOS
    variant lets an NMOS part reach the fallback, which is what "this split does
    not apply here" means. Ignoring every variant is what switches the check
    off.
    """
    live = [i for i in group if severity_of(i) != "ignore"]
    if not live:
        return None, "disabled"
    if facts is None:
        return live[0], "ok"
    fallback = None
    for item in live:
        when = item.get("when")
        if not when:
            fallback = fallback or item
            continue
        if when_matches(when, facts):
            return item, "ok"
    if fallback is not None:
        return fallback, "ok"
    return None, "no_match"


def resolve(db: Session, kind: str, category_id: int | None = None,
            facts: dict | None = None) -> dict:
    """The merged checklist for one subject.

    Base checklist for the kind, plus every category-scoped checklist whose
    category sits on the subject's category path (components only — symbols
    and footprints have no category). Later (more specific) items win on a
    key collision.

    **A more specific list REPLACES a key's whole variant group** (user
    decision 2026-09-14). A category states the complete set for that key, not
    an addition to the one above it — the same rule its `required_properties`
    has always followed. To add one special case while keeping the general
    rule, switch the general one off and add a new KEY for the exception;
    restating a group you meant to extend is the mistake this prevents.

    Returns ``items`` (one per key — the variant that applies), ``disabled``
    (a key every variant of which is switched off here) and ``inapplicable``
    (a key with variants, none of them about a subject like this one). Those
    three are different statements about different people's decisions and must
    never be folded together: "the owner turned it off" and "this is not about
    parts like this one" are not the same thing, and a card that prints one
    where it means the other is lying about who decided.

    ``facts=None`` skips the judging entirely and returns every live variant,
    which is what a screen describing a category needs.
    """
    base = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
    version_id, items = _current_items(base) if base is not None else (None, [])
    merged: dict[str, list[dict]] = _group(items)

    if category_id is not None:
        path_ids: list[int] = []
        cat = db.get(M.Category, category_id)
        while cat is not None:
            path_ids.append(cat.id)
            cat = cat.parent
        scoped = (
            db.query(M.Checklist)
            .filter(M.Checklist.subject_kind == kind, M.Checklist.category_id.in_(path_ids))
            .all()
            if path_ids else []
        )
        # apply from the top of the tree down, so the most specific wins
        for cl in sorted(scoped, key=lambda c: path_ids.index(c.category_id), reverse=True):
            _vid, extra = _current_items(cl)
            for key, group in _group(extra).items():
                merged[key] = group

    out: list[dict] = []
    off: list[dict] = []
    none_match: list[dict] = []
    for key, group in merged.items():
        if facts is None:
            live = [i for i in group if severity_of(i) != "ignore"]
            out.extend(live)
            if not live:
                off.append(group[0])
            continue
        item, why = pick(group, facts)
        if why == "ok" and item is not None:
            out.append(item)
        elif why == "disabled":
            off.append(group[0])
        else:
            none_match.append(group[0])

    return {
        "checklist_version_id": version_id,
        "items": out,
        "disabled": off,
        "inapplicable": none_match,
    }



#: `rules.block` key -> (check key, parameter name). What the old engine held
#: and which check now owns it. `footprint_style` / `footprint_dimensions` /
#: `symbol_style` are flattened first, since their names were already unique.
_RULE_KEY_TO_PARAM = {
    "min_drill_diameter": ("fp.min_drill", "min_drill_diameter"),
    "min_pad_size": ("fp.min_th_pad", "min_pad_size"),
    "min_via_size": ("fp.via_dims", "min_via_size"),
    "min_via_drill": ("fp.via_dims", "min_via_drill"),
    "thermal_via_warning_only": ("fp.via_dims", "thermal_via_warning_only"),
    "crtyd_line_width_mm": ("fp.courtyard_width", "crtyd_line_width_mm"),
    "fab_line_width_mm": ("fp.fab_width", "fab_line_width_mm"),
    "silk_line_width_mm": ("fp.silk_width", "silk_line_width_mm"),
    "coordinate_grid_mm": ("fp.courtyard_grid", "coordinate_grid_mm"),
    "pin_grid_mm": ("sym.pins_grid", "pin_grid_mm"),
    "required_properties": ("cmp.required_props", "required_properties"),
    "non_empty_properties": ("cmp.required_props", "non_empty_properties"),
    "manufacturer_properties": ("cmp.manufacturer", "manufacturer_properties"),
}

#: Keys the old blocks carried that no check consumes. Named so the migration
#: can report them rather than drop them silently: `conditional_required_properties`
#: is a real per-category rule nobody has implemented, and the rest were only
#: ever restatements of what the code does anyway.
_RULE_KEYS_UNUSED = ("footprint_required", "max_property_length", "pad_shape",
                     "pad_roundrect_rratio", "require_crtyd", "require_fab_outline",
                     "no_easyeda_prefix", "exempt_base_components",
                     "conditional_required_properties")


def _flatten_block(block: dict | None) -> tuple[dict, dict, list[str]]:
    """One `rules.block` as (parameter values, property patterns, unused keys)."""
    flat: dict = {}
    for key, value in (block or {}).items():
        if key in ("footprint_dimensions", "footprint_style", "symbol_style") \
                and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    values = {k: v for k, v in flat.items() if k in _RULE_KEY_TO_PARAM}
    patterns = flat.get("property_patterns") or {}
    unused = sorted(k for k in flat if k not in _RULE_KEY_TO_PARAM
                    and k != "property_patterns")
    return values, patterns, unused


def _stamp(db: Session, kind: str, items: list[dict], values: dict,
           patterns: dict, only_missing: bool) -> bool:
    """Write `params` onto the machine items of one checklist. Returns whether
    anything moved."""
    from . import validator

    by_key = {i.get("key"): i for i in items}
    touched = False
    for spec in validator._CHECK_SPECS.get(kind, ()):
        wanted = dict(spec.get("params") or {})
        if not wanted:
            continue
        item = by_key.get(spec["key"])
        if item is None or (only_missing and item.get("params")):
            continue
        for name in wanted:
            src = next((k for k, (ck, pn) in _RULE_KEY_TO_PARAM.items()
                        if ck == spec["key"] and pn == name), None)
            if src is not None and src in values:
                wanted[name] = values[src]
            elif name == "patterns" and patterns:
                wanted[name] = dict(patterns)
            elif name == "pattern" and "LCSC Part" in patterns:
                wanted[name] = patterns["LCSC Part"]
        if item.get("params") == wanted:
            continue
        item["params"] = wanted
        entry = validator.machine_check(db, kind, spec["key"],
                                        {spec["key"]: {"params": wanted}})
        if entry is not None:
            item["text"] = entry["text"]
            if entry.get("hint"):
                item["hint"] = entry["hint"]
        touched = True
    return touched


def _publish(db: Session, cl: M.Checklist, items: list[dict], comment: str) -> str:
    # `cl.versions` is not appended to by `db.add` under `expire_on_commit=False`,
    # so number from the query, not the relationship — the trap
    # `services/repoint.py` documents.
    numbers = [n for (n,) in db.query(M.ChecklistVersion.version_no)
               .filter_by(checklist_id=cl.id)]
    new = M.ChecklistVersion(checklist_id=cl.id, version_no=max(numbers, default=0) + 1,
                             items=items, status="published", created_by="migration",
                             comment=comment)
    db.add(new)
    db.flush()
    cl.current_version_id = new.id
    return f"{cl.name} v{new.version_no}"


def migrate_rules_onto_items(db: Session) -> dict:
    """Fold the `rules` table into the checklists. Idempotent (2026-09-14).

    Validation rules used to be JSON blocks in a `rules` table: one `global` row
    holding the numbers for eleven different checks, and 15 `library` rows — one
    per top-level category, seeded by the YAML import — that **nothing ever
    read**. A category could state that a Capacitor carries Value and Voltage
    and no part was ever measured against it.

    They are now `params` on the checklist item of the check that uses them. The
    move buys four things at once and costs no new machinery: a parameter sits
    beside the switch that turns its check on, it versions with the checklist and
    carries the comment saying why it changed, it lands in
    `ReviewRecord.checklist_items` so a past verification says what it was
    measured against, and a CATEGORY states its own by putting the item on a
    category-scoped component checklist — which `resolve` already merges.

    The `rules` rows are left in place, inert. Deleting data that took a
    migration to read is not this function's job, and `_RULE_KEYS_UNUSED` names
    what nothing consumes so the report says what was NOT carried over.
    """
    from . import validator

    report: dict = {"published": [], "unused": {}}

    # --- the global row: the base checklist of every kind ---
    row = db.query(M.Rule).filter_by(scope="global", enabled=True).first()
    values, patterns, unused = _flatten_block(row.block if row else None)
    if unused:
        report["unused"]["global"] = unused
    for kind in BASE_NAMES:
        cl = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
        if cl is None:
            continue
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        if cv is None:
            continue
        items = [dict(i) for i in (cv.items or [])]
        # An automatic check the base list has never carried is added SWITCHED
        # OFF. `cmp.property_values` is new here, and adding a machine item to a
        # live base checklist un-answers it on every existing subject with no
        # backfill — that is what moved all 418 components to partial on
        # 2026-08-25. Off, it is visible in the editor and costs nothing; the
        # category lists below turn it on where there are patterns to apply.
        have = {i.get("key") for i in items}
        added = False
        for key in validator.MACHINE_KEYS.get(kind, ()):
            if key in have:
                continue
            item = machine_item(db, kind, key, severity="warning")
            if item is not None:
                items.append(item)
                added = True
        # A base item that already states its params keeps them: this has run
        # before, or somebody has edited one since.
        if _stamp(db, kind, items, values, patterns, only_missing=True) or added:
            report["published"].append(
                _publish(db, cl, items,
                         "Validation rules moved from the rules table onto the checks "
                         "that use them"))

    # --- one category row -> one category-scoped COMPONENT checklist ---
    for rule in db.query(M.Rule).filter_by(scope="library", enabled=True).all():
        if rule.category_id is None:
            continue
        cat = db.get(M.Category, rule.category_id)
        if cat is None:
            continue
        values, patterns, unused = _flatten_block(rule.block)
        if unused:
            report["unused"][cat.name] = unused
        if not values and not patterns:
            continue
        cl = (db.query(M.Checklist)
              .filter_by(subject_kind="component", category_id=rule.category_id).first())
        if cl is None:
            cl = M.Checklist(name=f"{cat.name} rules", subject_kind="component",
                             category_id=rule.category_id,
                             description=f"Property rules for {cat.name}")
            db.add(cl)
            db.flush()
            items: list[dict] = []
        else:
            cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
            items = [dict(i) for i in ((cv.items if cv else None) or [])]
        # Only the items this row has something to say about — a category
        # checklist that restated every check would look like a category that
        # means every one of them, and could never stop stating one.
        wanted_keys = {ck for k, (ck, _) in _RULE_KEY_TO_PARAM.items() if k in values}
        if patterns:
            wanted_keys.add("cmp.property_values")
            if "LCSC Part" in patterns:
                wanted_keys.add("cmp.lcsc_format")
        by_key = {i.get("key") for i in items}
        for key in wanted_keys:
            if key in by_key:
                continue
            item = machine_item(db, "component", key)
            if item is not None:
                items.append(item)
        if _stamp(db, "component", items, values, patterns, only_missing=False):
            report["published"].append(
                _publish(db, cl, items,
                         f"Property rules for {cat.name}, moved off the rules table"))

    if report["published"]:
        db.commit()
    return report


def migrate_severities(db: Session) -> list[str]:
    """Convert the retired ``disabled: true`` flag to ``severity``. Idempotent.

    Severity replaced the on/off switch on 2026-09-14: `ignore` IS "off", so a
    switch beside a severity was two controls for one decision. `severity_of`
    reads the old flag, which keeps every PAST record honest — but a stored item
    that still carries it cannot be told apart from one somebody deliberately
    set to `ignore`, and the four checks seeded off were never meant to be off.

    They were seeded off because turning a live machine item on re-opens the
    whole library (`cmp.datasheet_text` moved 418 components in one publish).
    "Off" was standing in for "on, but not urgent", and the honest spelling of
    that is `warning` — so those four are converted to warnings here and
    everything else to `ignore`.
    """
    published: list[str] = []
    for cl in db.query(M.Checklist).all():
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        if cv is None:
            continue
        items = [dict(i) for i in (cv.items or [])]
        touched = False
        for item in items:
            if "severity" in item or not item.get("disabled"):
                continue
            item.pop("disabled", None)
            sev = "warning" if item.get("key") in SEED_AS_WARNING else "ignore"
            if sev != DEFAULT_SEVERITY:
                item["severity"] = sev
            touched = True
        if not touched:
            continue
        numbers = [n for (n,) in db.query(M.ChecklistVersion.version_no)
                   .filter_by(checklist_id=cl.id)]
        new = M.ChecklistVersion(
            checklist_id=cl.id, version_no=max(numbers, default=0) + 1, items=items,
            status="published", created_by="migration",
            comment="Severity replaces the on/off switch; the four checks seeded off "
                    "become warnings, which is what 'off' was standing in for")
        db.add(new)
        db.flush()
        cl.current_version_id = new.id
        published.append(f"{cl.name} v{new.version_no}")
    if published:
        db.commit()
    return published
