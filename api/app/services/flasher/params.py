"""What a deployment version needs from a ParamSet, and what changing one costs.

**The contract is versioned; the values are not.** That split is decision 0024,
and it keeps the one from 2026-07-27 that put values outside the version:
rotating a WiFi password must not mint a new version of every deployment that
uses it. What 0024 adds is the other half — a version that SAYS which keys it
needs, so an edit to a project's parameters can be refused before it breaks a
version published months ago.

Before it, the only record of a dependency was the `{MqttHost}` inside a step.
`Dongle_V2 config` v10 needs seven keys and v18 needs four, both pointing at the
same set; removing the three v18 stopped using broke v10 and nothing said so
until a run was attempted with a device already in the socket.

One implementation of "which keys does this version use", called from three
places that must never disagree: the publish gate (`validate.check`), the
parameter editor (which keys are in use, and by what), and publishing itself
(freezing the contract).
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ... import models as M
from .. import crypto
from . import bundle

PLACEHOLDER = re.compile(r"\{(\w+)\}")

# A key whose VALUE must never be written anywhere outside the encrypted set:
# not into a revision row, not into a run snapshot, not into a log. Same
# spelling as `engine.SECRET_RE` — a key that is a secret in one place is a
# secret in all of them.
SECRET_RE = re.compile(r"password|pin|salt|secret|token", re.I)

# Names an op supplies to its own url template, once per item it fetches. They
# are not parameters and no step captures them. Mirrors `validate.OP_LOCAL_VARS`
# because both walk the same steps; keep the two in step.
OP_LOCAL_VARS = {"download_files": {"file_version_id", "filename"}}

# Ops that ADD names mid-run, and what each adds.
OP_CAPTURES = {
    "derive_credentials": {"mqtt_user", "mqtt_password"},
    "esp_connect": {"mac", "serial", "chip"},
}

# Ops that consume a parameter by NAME instead of interpolating `{it}`, as
# (step field that may rename it, the default name). Walking the strings misses
# these entirely: `derive_credentials` reads the salt straight out of the run's
# variables and raises without it, so `creds_salt` read as "no published
# version needs this — safe to remove" while being the one key whose loss
# cannot even be recovered from at the bench (found 2026-09-17, building the
# Parameters page).
#
# THIS IS A DECLARATION SITE. An op that reads a param directly must be listed
# here in the same change that adds it, or the guard silently under-reports.
OP_PARAM_FIELDS = {
    "derive_credentials": [("salt_param", "creds_salt")],
}


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def required_keys(version: M.DeploymentVersion) -> set[str]:
    """Parameter names this version's procedure cannot run without.

    A `{name}` that an EARLIER step captures is not a parameter, which is why
    this walks in order rather than collecting every placeholder in the file.
    """
    needed: set[str] = set()
    available = set(bundle.RUNTIME_VARS)
    for step in version.steps or []:
        local = OP_LOCAL_VARS.get(step.get("op"), set())
        # `label`, `note` and `capture` are prose and left-hand sides, never
        # interpolated — a placeholder written in a label is documentation.
        body = {k: v for k, v in step.items() if k not in ("label", "note", "capture")}
        for text in _walk_strings(body):
            for name in PLACEHOLDER.findall(text):
                if name not in available and name not in local:
                    needed.add(name)
        var = step.get("var")
        if var and var not in available:
            needed.add(var)
        for field, default in OP_PARAM_FIELDS.get(step.get("op"), []):
            name = str(step.get(field) or default)
            if name not in available:
                needed.add(name)
        available |= set((step.get("capture") or {}).keys())
        available |= OP_CAPTURES.get(step.get("op"), set())
    return needed


def set_keys(db, param_set_id: int | None) -> set[str]:
    """The keys a ParamSet supplies. An unreadable set reports one impossible
    key rather than none, so the caller's error says "cannot read" instead of
    listing every parameter as missing."""
    if not param_set_id:
        return set()
    ps = db.get(M.ParamSet, param_set_id)
    if ps is None or not ps.values_enc:
        return set()
    try:
        return set(json.loads(crypto.decrypt_token(ps.values_enc)).keys())
    except Exception:  # noqa: BLE001 — reported as its own error by the caller
        return {"<undecryptable>"}


def available_keys(db, version: M.DeploymentVersion) -> set[str]:
    """Everything the version can resolve: its own defaults, then its set."""
    return set((version.param_defaults or {}).keys()) | set_keys(db, version.param_set_id)


def build_schema(db, version: M.DeploymentVersion) -> dict:
    """The contract to freeze on publish: one entry per key the version needs.

    `source` records where the value came from AT PUBLISH TIME — a key the
    version carries as its own default cannot be broken by editing the project's
    set, and saying so is what stops the editor warning about keys it does not
    own.
    """
    defaults = set((version.param_defaults or {}).keys())
    out: dict[str, dict] = {}
    for name in sorted(required_keys(version)):
        out[name] = {
            "secret": bool(SECRET_RE.search(name)),
            "source": "default" if name in defaults else "set",
        }
    return out


def declared_keys(version: M.DeploymentVersion, source: str | None = None) -> set[str]:
    """What a version says it needs, falling back to walking its steps.

    A version published before 0024 has no `param_schema`. It is not treated as
    needing nothing — that would make every old version silently ignorable by
    the guard this file exists to provide.
    """
    schema = version.param_schema
    if not isinstance(schema, dict) or not schema:
        keys = required_keys(version)
        if source is None:
            return keys
        defaults = set((version.param_defaults or {}).keys())
        return {k for k in keys
                if (k in defaults) == (source == "default")}
    if source is None:
        return set(schema.keys())
    return {k for k, meta in schema.items() if (meta or {}).get("source", "set") == source}


def dependents(db, param_set_id: int) -> dict[str, list[dict]]:
    """key -> the PUBLISHED versions that need it from this set.

    Published only, deliberately. A draft is still being written and its author
    is the person editing the parameters; refusing their edit because of their
    own unfinished draft is the kind of guard people learn to force.
    """
    versions = (
        db.query(M.DeploymentVersion)
        .filter(M.DeploymentVersion.param_set_id == param_set_id,
                M.DeploymentVersion.status == "published")
        .all()
    )
    out: dict[str, list[dict]] = {}
    for v in versions:
        dep = db.get(M.Deployment, v.deployment_id)
        for key in declared_keys(v, source="set"):
            out.setdefault(key, []).append({
                "deployment": dep.name if dep else "?",
                "deployment_id": v.deployment_id,
                "version_id": v.id,
                "version_no": v.version_no,
            })
    for rows in out.values():
        rows.sort(key=lambda r: (r["deployment"], r["version_no"]))
    return out


def breaking(db, param_set_id: int, new_values: dict) -> list[str]:
    """Sentences naming every published version a write would break.

    Empty means the write is safe. This is the whole point of the contract: the
    answer used to arrive from `validate.check` at run start, with a device in
    the socket.
    """
    gone = set(dependents(db, param_set_id)) - set(new_values)
    msgs = []
    for key in sorted(gone):
        who = ", ".join(f"{r['deployment']} v{r['version_no']}"
                        for r in dependents(db, param_set_id)[key])
        msgs.append(f"removing \"{key}\" breaks {who}")
    return msgs


def record_revision(db, ps: M.ParamSet, old: dict, new: dict,
                    updated_by: str, note: str = "") -> M.ParamSetRevision:
    """Append what this edit did, and the values it left behind.

    `changed` NAMES the keys whose value moved and never prints the old one:
    the history page is read on a bench, often with other people in the room.
    The values themselves are kept encrypted in `values_enc`, the same way the
    set keeps them, which is what a revert restores.
    """
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    last = (
        db.query(M.ParamSetRevision)
        .filter(M.ParamSetRevision.param_set_id == ps.id)
        .order_by(M.ParamSetRevision.revision_no.desc())
        .first()
    )
    rev = M.ParamSetRevision(
        param_set_id=ps.id,
        revision_no=(last.revision_no + 1) if last else 1,
        keys_added=added,
        keys_removed=removed,
        changed=changed,
        values_public={k: v for k, v in new.items() if not SECRET_RE.search(k)},
        values_enc=crypto.encrypt_token(json.dumps(new)),
        note=note[:500],
        updated_by=updated_by,
    )
    db.add(rev)
    return rev


def current_revision_id(db, param_set_id: int | None) -> int | None:
    """The revision a run is about to use. None for a set nobody has edited
    since 0024 — an honest "not recorded", never a guess at revision 1."""
    if not param_set_id:
        return None
    last = (
        db.query(M.ParamSetRevision)
        .filter(M.ParamSetRevision.param_set_id == param_set_id)
        .order_by(M.ParamSetRevision.revision_no.desc())
        .first()
    )
    return last.id if last else None


def revision_values(db, revision_id: int) -> dict:
    """The full values a revision left behind. `{}` for a revision written
    before `values_enc` existed — the caller reports that rather than reverting
    to an empty set, which would erase every parameter in the project."""
    rev = db.get(M.ParamSetRevision, revision_id)
    if rev is None or not rev.values_enc:
        return {}
    return json.loads(crypto.decrypt_token(rev.values_enc))
