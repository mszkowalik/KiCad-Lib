"""Editable runtime configuration.

`Settings` (config.py) is built from the environment once at import. This layer
lets a curated set of those fields be changed from the UI and persisted, with
precedence **DB > environment > code default**.

How the override reaches the running app: the values are written back onto the
`settings` singleton with `setattr`. Everything in the codebase reads
`settings.foo` at call time, so a change is live for anything evaluated per
request. What it cannot reach is work *armed once at startup* — the nightly
datasheet re-check, the autofetch threads, the FX and ladder refreshers. Those
knobs are marked `restart=True` and the UI says so rather than pretending.

Not editable, on purpose:
  database_url, data_dir, repo_dir, minio_*   changing these under a running
                                              platform breaks it outright
  secret_key                                  it is the Fernet key for stored
                                              git tokens; a new value makes
                                              every one of them undecryptable
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings


@dataclass(frozen=True)
class Knob:
    key: str
    group: str
    label: str
    kind: str  # "str" | "int" | "bool"
    help: str = ""
    secret: bool = False
    restart: bool = False
    choices: tuple[str, ...] = field(default=())


KNOBS: tuple[Knob, ...] = (
    # ---------------------------------------------------------------- address
    Knob("public_base_url", "Address", "Public base URL", "str",
         "How KiCad clients and browsers reach this API. Embedded in generated "
         "symbols' datasheet links, the PCM package URLs and the .kicad_httplib, "
         "so it must be reachable from wherever KiCad runs. Include the path "
         "prefix if the platform is served under one, e.g. http://host/lib."),
    Knob("cors_origins", "Address", "CORS origins", "str",
         "Comma-separated browser origins allowed to call this API directly. The "
         "deployed UI is same-origin and needs no entry; add one only for a dev "
         "server pointed at this instance."),
    # ----------------------------------------------------------------- tokens
    Knob("httplib_token", "Tokens", "KiCad HTTP library token", "str",
         "Sent by KiCad as `Authorization: Token …` on /kicad/v1/*. Changing it "
         "invalidates the .kicad_httplib files already installed — re-download "
         "and reinstall them.", secret=True),
    Knob("mcp_token", "Tokens", "Agent / MCP bearer token", "str",
         "Required on /api/agent/* , which can create draft proposals. Empty "
         "leaves those endpoints open — acceptable only on a trusted network.",
         secret=True),
    # ----------------------------------------------------------- integrations
    Knob("anthropic_api_key", "Integrations", "Anthropic API key", "str",
         "Enables the in-app Jaravis chat. Claude Code over MCP does not need "
         "it — that path runs on your subscription.", secret=True),
    Knob("jaravis_model", "Integrations", "Jaravis model", "str",
         "Model id used by the in-app chat."),
    Knob("jlc_app_id", "Integrations", "JLCPCB app id", "str",
         "JLCPCB OpenAPI credentials enable the private parts library "
         "(consigned stock) and the assembly price ladders."),
    Knob("jlc_access_key", "Integrations", "JLCPCB access key", "str", "", secret=True),
    Knob("jlc_secret_key", "Integrations", "JLCPCB secret key", "str", "", secret=True),
    # ------------------------------------------------------------------ kicad
    Knob("httplib_symbol_lib", "KiCad", "Symbol library nickname", "str",
         "Library nickname the HTTP catalog points parts at for their base "
         "drawing. Must match the client's symbol library table — the PCM "
         "install registers PCM_7Sigma_Base."),
    Knob("footprint_lib_nickname", "KiCad", "Footprint library nickname", "str",
         "Footprint refs are rewritten from 7Sigma: to this nickname. The PCM "
         "install registers PCM_7Sigma."),
    Knob("httplib_timeout_categories_s", "KiCad", "Catalog cache in KiCad (seconds)", "int",
         "How long KiCad reuses its own copy of the part lists before asking "
         "again. It re-fetches every category at once, so a low value makes the "
         "first Add Symbol click slow. Re-download the .kicad_httplib after a "
         "change — the value is embedded in that file. KiCad's default is 600."),
    Knob("httplib_timeout_parts_s", "KiCad", "Part detail cache in KiCad (seconds)", "int",
         "Same, for a single part's fields. KiCad's default is 30. Both caches "
         "are per KiCad session and always cold on startup."),
    Knob("symbol_theme", "KiCad", "Symbol preview theme", "str",
         "kicad-cli colour theme for symbol previews. The theme JSON must exist "
         "where the renderer runs. Empty = KiCad default."),
    Knob("footprint_theme", "KiCad", "Footprint preview theme", "str",
         "As above, for board and footprint previews. Empty = KiCad default."),
    # ------------------------------------------------------------- datasheets
    Knob("datasheet_autofetch", "Datasheets", "Fetch missing on startup", "bool",
         "Downloads datasheets that have no local copy yet, in the background.",
         restart=True),
    Knob("datasheet_recheck_nightly", "Datasheets", "Nightly re-check", "bool",
         "Conditional GETs (ETag / Last-Modified) against every source URL. An "
         "unchanged document costs one 304; a changed one becomes a new version "
         "and bumps its component.", restart=True),
    Knob("datasheet_recheck_hour", "Datasheets", "Re-check hour (server local)", "int",
         "0–23. Containers run UTC unless TZ is set.", restart=True),
    # ---------------------------------------------------------------- pricing
    Knob("price_ladder_autofetch", "Pricing", "Refresh price ladders", "bool",
         "Background refresh of JLCPCB and LCSC price ladders on startup.",
         restart=True),
    Knob("price_ladder_max_age_days", "Pricing", "Ladder max age (days)", "int",
         "Ladders older than this are refreshed."),
    Knob("fx_autofetch", "Pricing", "Refresh exchange rates", "bool",
         "Daily ECB rates via frankfurter.app.", restart=True),
    Knob("default_currency", "Pricing", "Display currency", "str",
         "Used for cost totals when a project sets no override."),
    # ----------------------------------------------------------------- render
    Knob("render_mode", "Render", "Render mode", "str",
         "http = the render container; local = invoke kicad-cli directly, which "
         "only works when the API runs outside a container.",
         choices=("http", "local")),
    Knob("render_url", "Render", "Render service URL", "str",
         "Where the render container listens."),
)

BY_KEY: dict[str, Knob] = {k.key: k for k in KNOBS}

# Captured before any override is applied, so "revert" can restore exactly what
# the environment or the code default produced.
_BASELINE: dict[str, object] = {k.key: getattr(settings, k.key) for k in KNOBS}


def coerce(knob: Knob, raw: str) -> object:
    """Text from the DB or an HTTP body -> the field's real type."""
    if knob.kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if knob.kind == "int":
        try:
            return int(str(raw).strip())
        except ValueError:
            raise ValueError(f"{knob.label}: expected a whole number") from None
    return str(raw)


def validate(knob: Knob, value: object) -> None:
    if knob.choices and str(value) not in knob.choices:
        raise ValueError(f"{knob.label}: must be one of {', '.join(knob.choices)}")
    if knob.key == "datasheet_recheck_hour" and not 0 <= int(value) <= 23:
        raise ValueError("Re-check hour: must be between 0 and 23")
    if knob.key == "public_base_url":
        v = str(value)
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Public base URL: must start with http:// or https://")
        if v.endswith("/"):
            raise ValueError("Public base URL: must not end with a slash — it is "
                             "concatenated with paths like /api/datasheets/1/file")
    if knob.key == "render_url" and str(value) and not str(value).startswith("http"):
        raise ValueError("Render service URL: must start with http")


def _rows(db: Session) -> dict[str, M.AppSetting]:
    return {r.key: r for r in db.query(M.AppSetting)}


def apply_overrides(db: Session) -> int:
    """Push stored overrides onto the settings singleton. Call at startup."""
    n = 0
    for key, row in _rows(db).items():
        knob = BY_KEY.get(key)
        if knob is None:
            continue  # a knob that no longer exists — leave the row, ignore it
        try:
            setattr(settings, key, coerce(knob, row.value))
            n += 1
        except ValueError:
            continue
    return n


def set_override(db: Session, key: str, raw: str, actor: str = "user") -> Knob:
    knob = BY_KEY.get(key)
    if knob is None:
        raise KeyError(key)
    value = coerce(knob, raw)
    validate(knob, value)
    row = db.get(M.AppSetting, key)
    if row is None:
        row = M.AppSetting(key=key, value=str(raw))
        db.add(row)
    else:
        row.value = str(raw)
    row.updated_by = actor
    setattr(settings, key, value)
    return knob


def clear_override(db: Session, key: str) -> Knob:
    knob = BY_KEY.get(key)
    if knob is None:
        raise KeyError(key)
    row = db.get(M.AppSetting, key)
    if row is not None:
        db.delete(row)
    setattr(settings, key, _BASELINE[key])
    return knob


def describe(db: Session) -> list[dict]:
    """The whole editable surface, grouped, for the Setup page.

    A secret's value is never returned — only whether one is set. There is no
    read-back path for it, so the UI offers "replace" rather than "edit".
    """
    rows = _rows(db)
    out = []
    for knob in KNOBS:
        overridden = knob.key in rows
        live = getattr(settings, knob.key)
        item = {
            "key": knob.key,
            "group": knob.group,
            "label": knob.label,
            "help": knob.help,
            "kind": knob.kind,
            "secret": knob.secret,
            "restart": knob.restart,
            "choices": list(knob.choices),
            "source": "database" if overridden else "environment",
            "updated_at": rows[knob.key].updated_at.isoformat() if overridden else None,
        }
        if knob.secret:
            item["value"] = None
            item["is_set"] = bool(str(live))
        else:
            item["value"] = live
            item["is_set"] = True
        out.append(item)
    return out
