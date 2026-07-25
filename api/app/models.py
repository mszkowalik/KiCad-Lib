"""Data model.

Three independently versioned artifact families (symbol, footprint, component
data) with immutable version rows. A component version PINS the exact symbol
version and footprint version it was built against (real FKs). Categories are
a tree; a component version records its category, so moving a component
between categories is itself a versioned change.

`current_version_id` pointers are plain integers (not FK constraints) to avoid
circular-dependency pain — the DB is wiped and reloaded by the import station,
and every write path goes through the service layer.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- categories
class Category(Base):
    """Tree. Top-level categories correspond to today's library names and map
    1:1 to generated .kicad_sym files; children are free-form (ICs / LDO)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Top-level only: import defaults from the YAML `defaults:` block
    # (base_component, footprint_map, ignore_packages).
    defaults: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], backref="children")

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),)


# ------------------------------------------------------------------- symbols
class Symbol(Base):
    """A base symbol identity (graphical template, e.g. 'R', 'C_Pol')."""

    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    versions: Mapped[list["SymbolVersion"]] = relationship(back_populates="symbol", order_by="SymbolVersion.version_no")


class SymbolVersion(Base):
    __tablename__ = "symbol_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    # Canonical artifact: the full .kicad_sym library text containing this one symbol.
    source_text: Mapped[str] = mapped_column(Text)
    # Derived cache for search/rules/preview: pins, units, ...
    parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(100), default="import")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    symbol: Mapped[Symbol] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("symbol_id", "version_no", name="uq_symbol_version"),)


# ---------------------------------------------------------------- footprints
class Footprint(Base):
    """A footprint and its version history.

    ``display_name`` is the short human name of the package ("0402",
    "VQFN-14-EP 3.5x3.5mm") that `ki_description` templates reference as
    ``{Footprint_Name}``. It belongs to the footprint, not to each component
    that uses it: the generator injects it, so a component never has to carry
    (and drift on) its own copy. Unversioned — it labels the footprint, not a
    revision of its geometry.
    """

    __tablename__ = "footprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    versions: Mapped[list["FootprintVersion"]] = relationship(
        back_populates="footprint", order_by="FootprintVersion.version_no"
    )


class FootprintVersion(Base):
    __tablename__ = "footprint_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    footprint_id: Mapped[int] = mapped_column(ForeignKey("footprints.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)  # full .kicad_mod text
    parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # pads, layers, ...
    models: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 3D model rel-paths referenced
    status: Mapped[str] = mapped_column(String(20), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(100), default="import")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    footprint: Mapped[Footprint] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("footprint_id", "version_no", name="uq_footprint_version"),)


# ----------------------------------------------------------------- 3D models
class Model3D(Base):
    """3D model files, content-addressed. rel_path mirrors 3DModels/<rel_path>."""

    __tablename__ = "models3d"

    id: Mapped[int] = mapped_column(primary_key=True)
    rel_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- components
class Component(Base):
    __tablename__ = "components"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Globally unique across ALL libraries — matches today's validator rule.
    name: Mapped[str] = mapped_column(String(200), unique=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # False = BOM-only part (cable, enclosure, ...): never emitted into the
    # generated KiCad libraries / HTTP catalog, but priceable and usable in
    # project BOMs. Needs no symbol/footprint. (Added by startup migration.)
    in_library: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    versions: Mapped[list["ComponentVersion"]] = relationship(
        back_populates="component", order_by="ComponentVersion.version_no"
    )


class ComponentVersion(Base):
    __tablename__ = "component_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    base_component: Mapped[str] = mapped_column(String(200))
    # The strict pins: exact symbol/footprint versions this component version uses.
    symbol_version_id: Mapped[int | None] = mapped_column(ForeignKey("symbol_versions.id"), nullable=True)
    footprint_version_id: Mapped[int | None] = mapped_column(ForeignKey("footprint_versions.id"), nullable=True)
    # Categorization is versioned data — moving a component is a new version.
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    removed_properties: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(100), default="import")
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    component: Mapped[Component] = relationship(back_populates="versions")
    category: Mapped[Category] = relationship()
    symbol_version: Mapped[SymbolVersion | None] = relationship()
    footprint_version: Mapped[FootprintVersion | None] = relationship()
    properties: Mapped[list["ComponentProperty"]] = relationship(
        back_populates="component_version", order_by="ComponentProperty.position", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("component_id", "version_no", name="uq_component_version"),)


class ComponentProperty(Base):
    """Ordered key/value rows — order matters (template resolution, BOM)."""

    __tablename__ = "component_properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_version_id: Mapped[int] = mapped_column(ForeignKey("component_versions.id"))
    position: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)  # NULL == explicit "N/A" (YAML null)
    is_null: Mapped[bool] = mapped_column(Boolean, default=False)
    hide: Mapped[bool] = mapped_column(Boolean, default=True)
    show_name: Mapped[bool] = mapped_column(Boolean, default=False)
    # Dormant per-property layout extras from YAML (position/effects/showName).
    layout: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    component_version: Mapped[ComponentVersion] = relationship(back_populates="properties")

    __table_args__ = (UniqueConstraint("component_version_id", "position", name="uq_property_position"),)


# -------------------------------------------------------- prices / datasheets
class ComponentPrice(Base):
    """Auto-managed LCSC pricing — component-scoped (NOT versioned; prices are
    robot bookkeeping refreshed on a schedule, audited rather than versioned).
    Values stay formatted strings, exactly as the legacy YAML carried them.
    They are injected back into generated symbols so KiCad output is unchanged."""

    __tablename__ = "component_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), unique=True)
    price_1: Mapped[str | None] = mapped_column(String(50), nullable=True)      # Price @1 USD
    price_100: Mapped[str | None] = mapped_column(String(50), nullable=True)    # Price @100 USD
    price_bulk: Mapped[str | None] = mapped_column(String(50), nullable=True)   # Price @Bulk USD
    bulk_qty: Mapped[str | None] = mapped_column(String(50), nullable=True)     # Price Bulk Qty
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)       # Price Source
    updated: Mapped[str | None] = mapped_column(String(50), nullable=True)      # Price Updated


class Datasheet(Base):
    """Datasheet identity — component-scoped, multiple per component. The
    first (position 0) maps to KiCad's native Datasheet field; the rest are
    emitted as hidden custom fields ("Datasheet 2", ...). The downloaded
    documents live in DatasheetVersion rows (immutable, content-addressed);
    current_version_id points at the latest fetched content."""

    __tablename__ = "datasheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    # NULL position = archived (removed from the active set, history preserved)
    position: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    label: Mapped[str] = mapped_column(String(200), default="Datasheet")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list["DatasheetVersion"]] = relationship(
        back_populates="datasheet", order_by="DatasheetVersion.version_no"
    )

    __table_args__ = (UniqueConstraint("component_id", "position", name="uq_datasheet_position"),)


class DatasheetVersion(Base):
    """An immutable downloaded copy of a datasheet. A new version is created
    only when the downloaded content's sha256 differs from the current one."""

    __tablename__ = "datasheet_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    datasheet_id: Mapped[int] = mapped_column(ForeignKey("datasheets.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Validators from the response that produced this copy, replayed as
    # If-None-Match / If-Modified-Since by the nightly re-check so an
    # unchanged document costs one 304 instead of a full download.
    # (Added by startup migration; NULL on rows fetched before it landed.)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)

    datasheet: Mapped[Datasheet] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("datasheet_id", "version_no", name="uq_datasheet_version"),)


class ComponentVersionDatasheet(Base):
    """Pin: which exact datasheet version (PDF content) a component version
    was associated with. Answers "which pdf was used in which component
    version". datasheet_version_id is NULL when no local copy existed yet."""

    __tablename__ = "component_version_datasheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_version_id: Mapped[int] = mapped_column(ForeignKey("component_versions.id"))
    datasheet_id: Mapped[int] = mapped_column(ForeignKey("datasheets.id"))
    datasheet_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasheet_versions.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("component_version_id", "datasheet_id", name="uq_cv_datasheet"),
    )


# ------------------------------------------------------------------ comments
class ComponentComment(Base):
    """LEGACY component-only notes table. Superseded by the generic ``Comment``
    table below; kept only as the source for the one-time startup migration in
    ``main.py`` (rows are copied out and the table drained). Do not write here."""

    __tablename__ = "component_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    author: Mapped[str] = mapped_column(String(100), default="user")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    """Free-form notes on any entity — future-reference remarks, gotchas,
    sourcing notes. Not versioned; Jaravis reads them as context. One table
    for all targets; ``target_type`` selects the parent family.

    target_type ∈ {"component", "symbol", "footprint"}; ``target_id`` is that
    parent's id. (No FK — the parent is polymorphic; routers validate existence.)"""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(String(100), default="user")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_comments_target", "target_type", "target_id"),)


# --------------------------------------------------------------------- rules
class Rule(Base):
    """Declarative validation rules, seeded at import from the validator's
    hardcoded global defaults and each library's validation_rules block.
    The rules engine (Phase 05) consumes these."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    scope: Mapped[str] = mapped_column(String(20))  # "global" | "library"
    library_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    block: Mapped[dict] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# -------------------------------------------------------------------- skills
class Skill(Base):
    """Jaravis skills — versioned documents, editable in the UI.

    ``description`` is when-to-use metadata, NOT part of the document: it is the
    one-liner that tells an agent whether this skill is relevant before reading
    it. Deliberately unversioned (a label on the skill, not on its text) — it
    feeds Jaravis's system prompt and the Claude Code skill mirror's frontmatter.
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    versions: Mapped[list["SkillVersion"]] = relationship(back_populates="skill", order_by="SkillVersion.version_no")


class SkillVersion(Base):
    __tablename__ = "skill_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(100), default="import")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    skill: Mapped[Skill] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("skill_id", "version_no", name="uq_skill_version"),)


# ------------------------------------------------------------ jaravis chats
class JaravisSession(Base):
    """A persisted Jaravis conversation. Survives page reloads and the user can
    keep several in parallel, returning to any of them. Messages are stored in
    order; the newest `updated_at` sorts a session to the top of the list."""

    __tablename__ = "jaravis_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["JaravisMessage"]] = relationship(
        back_populates="session", order_by="JaravisMessage.id", cascade="all, delete-orphan"
    )


class JaravisMessage(Base):
    """One turn in a JaravisSession. Only role + text are replayed to the agent;
    `trace` (the turn's tool calls) and `proposals` (drafts it created) are kept
    on assistant messages so a reloaded thread renders exactly like the live run
    (tool list + proposal notes)."""

    __tablename__ = "jaravis_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("jaravis_sessions.id"))
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, default="")
    trace: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    proposals: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[JaravisSession] = relationship(back_populates="messages")


# --------------------------------------------------------------------- audit
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(100), default="user")
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ------------------------------------------------------------- price ladders
class ComponentPricePoint(Base):
    """Full supplier price ladder, one row per quantity break. Unlike the
    legacy 3-point ComponentPrice summary (kept for KiCad symbol injection),
    these rows carry every tier with its own currency and refresh date, so
    project BOMs can price any production volume exactly. source="LCSC" rows
    are replaced wholesale on refresh; other sources (e.g. "Manual") are
    never touched by the robot."""

    __tablename__ = "component_price_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    source: Mapped[str] = mapped_column(String(50), default="LCSC")
    qty_from: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("component_id", "source", "qty_from", name="uq_price_point"),
    )


class ComponentPriceHistory(Base):
    """Append-only historical pricing. One row = the component's COMPLETE
    effective point set (all sources — LCSC ladder + manual levels, or points
    synthesized from the legacy summary for ladder-less parts) at
    `recorded_at`; `points` = [{source, qty_from, unit_price, currency}].
    A new row is appended only when the set actually changed (an empty list
    records a deletion). Production-run economics resolve prices from here by
    run date — latest row at-or-before the date, else the earliest after
    ("closest you can find"). Never mutate or delete rows."""

    __tablename__ = "component_price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    points: Mapped[list] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ComponentSupply(Base):
    """Supplier availability bookkeeping. `stock` is LCSC retail stock
    (lcsc.com webshop); `jlc_stock` is JLCPCB assembly-parts stock
    (jlcpcb.com/parts) — the two are SEPARATE pools that routinely disagree
    (a part can be sold out on LCSC while JLCPCB holds 100k+ for assembly).
    Component-scoped, refreshed with the ladder and on explicit stock checks."""

    __tablename__ = "component_supply"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), unique=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jlc_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_multiple: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------- JLC private stock
class JlcStockItem(Base):
    """One part in the user's PRIVATE JLCPCB parts library (components JLC
    holds on consignment for assembly). Replaced wholesale on each sync from
    the JLCPCB OpenAPI; `raw` keeps the untouched API payload. Valuation is
    computed at sync time from the LCSC price ladder at the held quantity."""

    __tablename__ = "jlc_stock_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    lcsc: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    mpn: Mapped[str] = mapped_column(String(200), default="")
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    package: Mapped[str] = mapped_column(String(100), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ----------------------------------------------------------- exchange rates
class ExchangeRate(Base):
    """One row per currency: how many USD one unit is worth. source="auto"
    rows are refreshed daily (frankfurter.app / ECB); source="manual" rows
    are pinned by the user and never overwritten by the robot."""

    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(10), unique=True)
    rate_usd: Mapped[float] = mapped_column(Float)  # 1 <currency> = rate_usd USD
    source: Mapped[str] = mapped_column(String(20), default="auto")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExchangeRateHistory(Base):
    """Append-only FX history — one row per (currency, change). Run economics
    convert historical prices with the rate closest to the run date, same
    resolution rule as ComponentPriceHistory. Never mutate or delete rows."""

    __tablename__ = "exchange_rate_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(10), index=True)
    rate_usd: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ----------------------------------------------------------------- projects
class Project(Base):
    """A KiCad design project tracked from a git repository."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    git_url: Mapped[str] = mapped_column(String(500))
    # Fernet-encrypted with SECRET_KEY; never returned by the API.
    git_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    # Overrides settings.default_currency for this project's cost totals.
    display_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshots: Mapped[list["ProjectSnapshot"]] = relationship(
        back_populates="project", order_by="ProjectSnapshot.created_at.desc()"
    )


class ProjectSnapshot(Base):
    """An ingested git ref (immutable — keyed by commit sha). Holds the
    discovered KiCad boards (a repo may contain several .kicad_pro), their
    variants, and the extracted BOM lines. Renders are cached in MinIO keyed
    by sha, so they never invalidate."""

    __tablename__ = "project_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    sha: Mapped[str] = mapped_column(String(40))
    # Human label at ingest time: tag name, branch name, or short sha.
    ref_name: Mapped[str] = mapped_column(String(200), default="")
    is_tag: Mapped[bool] = mapped_column(Boolean, default=False)
    commit_message: Mapped[str] = mapped_column(Text, default="")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ingesting|ready|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{name, dir, pro, sch, pcb, variants: [{name, description}], layers: [...]}]
    boards: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="snapshots")
    bom_lines: Mapped[list["SnapshotBomLine"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("project_id", "sha", name="uq_snapshot_sha"),)


class SnapshotBomLine(Base):
    """One grouped BOM line as extracted by kicad-cli for a given board and
    variant ("" = KiCad's default variant). component_id is a soft pointer to
    the matched library component (matched by ${SYMBOL_NAME}, then LCSC)."""

    __tablename__ = "snapshot_bom_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("project_snapshots.id"))
    board: Mapped[str] = mapped_column(String(200))
    variant: Mapped[str] = mapped_column(String(100), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    refs: Mapped[str] = mapped_column(Text, default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    value: Mapped[str] = mapped_column(String(500), default="")
    footprint: Mapped[str] = mapped_column(String(500), default="")
    lcsc: Mapped[str] = mapped_column(String(50), default="")
    mpn: Mapped[str] = mapped_column(String(200), default="")
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    symbol_name: Mapped[str] = mapped_column(String(200), default="")
    symbol_library: Mapped[str] = mapped_column(String(200), default="")
    dnp: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_from_bom: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_from_board: Mapped[bool] = mapped_column(Boolean, default=False)
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    snapshot: Mapped[ProjectSnapshot] = relationship(back_populates="bom_lines")


class ProjectCostRevision(Base):
    """Immutable revision of a project's manual cost data — the cost items
    AND extra BOM items visible at a given commit, versioned together.

    Each revision is anchored at the git commit (snapshot) where it was
    created and applies from that commit FORWARD: the revision in effect for
    a snapshot S is the one with the latest effective_committed_at that is
    <= S's commit date (anchor sha "" / committed_at NULL = "since the
    beginning of time" — migrated pre-versioning data and edits made with no
    snapshot context). Editing the list while viewing commit Y copies the
    items visible at Y into a new revision anchored at Y (copy-on-write);
    further edits at Y mutate that same revision in place. Commits before Y
    keep the older revision — changes never propagate backward."""

    __tablename__ = "project_cost_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    effective_sha: Mapped[str] = mapped_column(String(40), default="")
    effective_ref: Mapped[str] = mapped_column(String(200), default="")
    effective_committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "effective_sha", name="uq_cost_rev_anchor"),
    )


class ProjectExtraBomItem(Base):
    """Manually added BOM line (per device): parts that exist outside the
    schematic — cables, enclosures, fasteners. Either links a component
    (including BOM-only, in_library=False parts — priced via its ladder) or
    carries a freehand unit price. Rows belong to a ProjectCostRevision —
    the commit-anchored version of the whole manual cost list."""

    __tablename__ = "project_extra_bom_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    # Nullable only for the startup migration; every code path sets it.
    revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_cost_revisions.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(300))
    qty: Mapped[float] = mapped_column(Float, default=1.0)  # per device
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manufacturer: Mapped[str] = mapped_column(String(200), default="")
    mpn: Mapped[str] = mapped_column(String(200), default="")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectCostItem(Base):
    """Free-form manufacturing cost line — PCB fab, assembly, enclosure
    rework, programming, ... Keys are NOT hardcoded; the label is free text.
    basis: "per_device" or "per_run" (amortized over the run quantity).
    Rows belong to a ProjectCostRevision (commit-anchored list version)."""

    __tablename__ = "project_cost_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    # Nullable only for the startup migration; every code path sets it.
    revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_cost_revisions.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(300))
    basis: Mapped[str] = mapped_column(String(20), default="per_device")  # per_device|per_run
    price: Mapped[float] = mapped_column(Float, default=0.0)
    # Optional quantity breaks, mirroring ComponentPricePoint's qty_from
    # convention: [{"qty_from": int, "price": float}] sorted ascending. The
    # step with the largest qty_from <= run volume overrides `price` (which
    # acts as the qty-1 tier). Same item currency applies to all steps.
    steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    company: Mapped[str] = mapped_column(String(200), default="")
    mpn: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectNote(Base):
    """Free-form project notes — gathered information, decisions, links.
    Notes are PROJECT-scoped (never filtered by the selected revision); sha /
    ref_name only record which commit was being viewed when the note was
    written. (Columns added by startup migration on existing DBs.)"""

    __tablename__ = "project_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    author: Mapped[str] = mapped_column(String(100), default="user")
    body: Mapped[str] = mapped_column(Text)
    sha: Mapped[str] = mapped_column(String(40), default="", server_default="")
    ref_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------- production runs
class ProductionRun(Base):
    """A physical production batch. Economics are computed ON DEMAND from
    historical pricing (ComponentPriceHistory / ExchangeRateHistory) resolved
    at the run's date — see project_bom.run_effective; `overrides` layers user
    corrections (final negotiated prices, changed quantities, extra lines) on
    top by line key. `frozen` is a LEGACY blob from the old freeze-at-creation
    model — kept for archival, no longer written or read."""

    __tablename__ = "production_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    label: Mapped[str] = mapped_column(String(200))
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    board: Mapped[str] = mapped_column(String(200), default="")
    variant: Mapped[str] = mapped_column(String(100), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    run_date: Mapped[str] = mapped_column(String(20), default="")  # ISO date, free
    notes: Mapped[str] = mapped_column(Text, default="")
    frozen: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attachments: Mapped[list["RunAttachment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    devices: Mapped[list["RunDevice"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ProductionFileSet(Base):
    """Versioned set of production files (gerbers, JLC BOM/CPL) attached to a
    production run. Immutable versions: importing from the repo's production/
    dir, uploading replacements, or generating a kicad-cli fab bundle each
    create a NEW version; the highest version_no is current."""

    __tablename__ = "run_production_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))  # repo | upload | generated
    comment: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list["ProductionFile"]] = relationship(
        back_populates="pset", cascade="all, delete-orphan", order_by="ProductionFile.filename"
    )

    __table_args__ = (UniqueConstraint("run_id", "version_no", name="uq_production_set_version"),)


class ProductionFile(Base):
    """One file in a production set. kind: jlc_bom | jlc_cpl | gerber_zip |
    gerber | drill | other. Gerber zips are ALSO stored extracted (kind
    gerber/drill, extracted=True) so the gerber viewer can address layers."""

    __tablename__ = "run_production_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("run_production_sets.id"))
    filename: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="other")
    extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    minio_key: Mapped[str] = mapped_column(String(500))

    pset: Mapped[ProductionFileSet] = relationship(back_populates="files")


class RunAttachment(Base):
    """File attached to a production run (serial-number lists, invoices,
    test reports). Bytes live in MinIO under the stored key."""

    __tablename__ = "run_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    minio_key: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ProductionRun] = relationship(back_populates="attachments")


class RunDevice(Base):
    """Structured serial-number registry: one row per produced device."""

    __tablename__ = "run_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    serial: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ProductionRun] = relationship(back_populates="devices")

    __table_args__ = (UniqueConstraint("run_id", "serial", name="uq_run_serial"),)
