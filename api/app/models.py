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
    text,
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
    # Production sign-off support — see ComponentSignoff and services/material.py.
    # `material_sha` caches the fingerprint of the pins (derived, "" = not yet
    # computed or unparseable). `recheck_required` is the approver's answer to
    # "does this change need a new verification?"; NULL = nobody was ever asked,
    # which is every row published before this landed.
    # (Both added by startup migration.)
    material_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    recheck_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

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
    # See SymbolVersion for what these two mean. Here the fingerprint covers
    # pads, drills, layers and the courtyard — never silkscreen, fab or 3D.
    # (Both added by startup migration.)
    material_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    recheck_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

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
    # False = virtual part that is never bought (test point, logo, fiducial,
    # mounting hole): it lives in the library and lands on the board, but
    # project BOM lines matching it are excluded from totals, order
    # quantities and stock checks. (Added by startup migration.)
    purchasable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

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


# ------------------------------------------------------------ production sign-off
class ComponentSignoff(Base):
    """A human's record that they checked a component before production.

    **This is NOT `ComponentVersion.approved_by`.** That column means "this
    edit was approved into the library" — an editorial act. This table means
    "I looked at the symbol, the land pattern and the part number, and I am
    willing to build boards with it" — a manufacturing act. The two are
    deliberately separate words and separate rows: a proposal can be perfectly
    good library data and still deserve a fresh look at the drawing.

    **The row names a `component_version_id`, never just a component.** A
    component version pins the exact `symbol_version_id` and
    `footprint_version_id` it was drawn against, so naming the version names
    the exact three drawings that were checked. Version rows are immutable, so
    the record can never quietly come to mean something else. A component's
    state is therefore DERIVED (`services/signoff.py::state_for`): signed when
    a live row exists on `components.current_version_id`, stale when the live
    row sits on an older version, unsigned when there is no row at all.

    **Append-only, like everything else here.** Nothing is updated in place and
    nothing is deleted. Revoking sets `revoked_at`; signing again after a
    revoke adds another row. There is deliberately no unique constraint — the
    live sign-off of a version is the newest row for it with `revoked_at IS
    NULL`.

    `kind` records HOW the signature got here, because that is the difference
    between evidence and bookkeeping:

    - ``checked``      — a human opened the drawing and said yes.
    - ``auto-carried`` — the new geometry's material fingerprint was byte-equal
      to the signed one, so nothing that reaches the board changed. Provable,
      not a judgement.
    - ``carried``      — the fingerprint DID change and a human still waived
      the re-check on the geometry version (`recheck_required=False`). Their
      name is on it.

    `carried_from_id` is a soft pointer to the sign-off this one descends from,
    so a chain of carries leads back to the last time somebody actually looked.
    """

    __tablename__ = "component_signoffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    component_version_id: Mapped[int] = mapped_column(ForeignKey("component_versions.id"))
    kind: Mapped[str] = mapped_column(String(20), default="checked")
    carried_from_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signed_by: Mapped[str] = mapped_column(String(100), default="user")
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_signoff_component", "component_id"),
        Index("ix_signoff_version", "component_version_id"),
    )


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


class WriteBatch(Base):
    """One reversible unit of money movement.

    The audit log records that something happened; this records enough to UNDO
    it. That distinction is the whole reason eleven one-off scripts and a run of
    raw `UPDATE`s were the only way to correct the 2026-07 backfill: the
    appliers were careful, gated and idempotent, and had no way back.

    A batch wraps ONE endpoint call. `identity_before`/`identity_after` hold
    `jlc_apply.identity_snapshot`, so a reversal can re-assert the register
    against the state this batch actually started from rather than against zero —
    `_assert_identities` compares absolutely (`jlc_apply.py:67`), which is right
    going forwards and wrong for an undo, because a pre-existing gap would
    otherwise make every batch permanently irreversible.

    A reversal is itself an ordinary batch, so it is itself reversible.
    """

    __tablename__ = "write_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    # jlc.parts.import | jlc.mfg.import | jlc.decision.apply | draws.void |
    # doc.create | doc.classify | reverse | ...
    kind: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str] = mapped_column(String(200), default="")  # W… / POB… / SMT… / doc:14
    actor: Mapped[str] = mapped_column(String(100), default="")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    identity_before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    identity_after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr

    rows: Mapped[list["WriteBatchRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_write_batch_kind", "kind", "created_at"),)


class WriteBatchRow(Base):
    """One row a batch touched, with enough of its prior state to put it back.

    `after_hash` is the guard that makes an undo honest. Before reversing, every
    row is re-hashed; a mismatch means someone edited it since, and the reversal
    REFUSES and names the row. Silently discarding a later hand correction to
    satisfy an undo is exactly how the `C2837531` substitution link was destroyed
    twice during the backfill.
    """

    __tablename__ = "write_batch_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("write_batches.id", ondelete="CASCADE"))
    table_name: Mapped[str] = mapped_column(String(60))
    row_id: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = mapped_column(String(10))  # insert | update | delete
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # NULL for insert
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # NULL for delete

    batch: Mapped[WriteBatch] = relationship(back_populates="rows")

    __table_args__ = (
        Index("ix_wbr_batch", "batch_id"),
        Index("ix_wbr_row", "table_name", "row_id"),
    )


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


class ComponentConsumptionLot(Base):
    """WHICH purchase a draw actually consumed, and at what that lot really cost.

    One `ComponentConsumption` may have several of these — a draw spanning two
    lots splits, which is exactly what produces the "one averaged row / N flat
    rows" view the user asked for. The parent's `unit_cost_usd` is the
    quantity-weighted average of its children, so the two views always total the
    same figure and switching the display can never change a number.

    **The lot itself is NOT a new table.** A lot is already a row: a leaf
    `run_cost_lines` entry with `kind='part'` and no `run_id` — precisely the set
    `run_actuals._pool_events` already treats as a purchase. Mirroring those into
    a parallel table would create a second source of truth free to drift from the
    money rows, and would break the documented invariant that `_pool_events` is
    the ONE source of stock events. So lots are made first-class by being *bound
    to*, not copied.

    `lot_line_id` and `lot_adjustment_id` are alternatives: at most one is set,
    and NEITHER being set means the draw could not be attributed to any purchase
    (an unallocated slice, priced from the pool average as before). The
    adjustment pointer exists because a positive `opening_balance` adjustment
    creates real priced stock with no purchase line behind it — without it, that
    stock could never be drawn from and every such draw would be unallocated.

    `source` records HOW the binding was decided, following the
    `ComponentConsumption.basis` precedent so an inference can never be mistaken
    for a fact:
      `reported`      — the supplier said so (JLC `presaleGoodsKeyId`)
      `fifo`          — inferred, oldest eligible lot first
      `manual`        — a human pinned it
      `unallocated`   — no lot could be found; priced from the average
      `legacy_average`— a pre-lot draw, carrying its original frozen unit cost
    """

    __tablename__ = "component_consumption_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    consumption_id: Mapped[int] = mapped_column(
        ForeignKey("component_consumptions.id", ondelete="CASCADE")
    )
    lot_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    lot_adjustment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    # The LOT's landed unit cost, snapshotted at bind time — never JLC's quoted
    # component price, which excludes the sourcing fee on `buy` sub-orders.
    unit_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="fifo")
    ext_ref: Mapped[str] = mapped_column(String(120), default="")  # presaleGoodsKeyId etc.
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_cons_lot_consumption", "consumption_id"),
        Index("ix_cons_lot_line", "lot_line_id"),
        Index("ix_cons_lot_adjustment", "lot_adjustment_id"),
    )


class JlcImport(Base):
    """A fetched JLC payload, staged before anything is decided or written.

    Exists so the decision UI is not a live scraper: computing proposals for 35
    invoices means re-deriving panel factors and run candidates on every page
    load, and re-fetching them from JLC would take a minute and depend on a
    session that may be dead. The payload is kept verbatim — JLC's shape is
    undocumented and unversioned, so the raw response IS the evidence, exactly
    as `JlcStockItem.raw` is.

    `status` is the decision state of the FETCH, not of the money:
      `staged`   — fetched, nothing decided
      `imported` — a cost document was created from it
      `skipped`  — deliberately not imported
    Keyed `(kind, external_id)` so re-syncing refreshes a row rather than
    appending one.
    """

    __tablename__ = "jlc_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="assembly")  # assembly | parts
    external_id: Mapped[str] = mapped_column(String(100), default="")  # W… / POB…
    invoice_no: Mapped[str] = mapped_column(String(100), default="")
    doc_date: Mapped[str] = mapped_column(String(20), default="")
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    presale_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="staged")
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Panelisation per smtOrderCode, from `orderCenter/selectPersonOrder`. Cached
    # here because it lives on a DIFFERENT endpoint from the invoice, and the
    # decision queue would otherwise make one extra round trip per batch on every
    # page load. Shape: {smtOrderCode: {panel_factor, panels, devices, pcb_order}}.
    panel_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # JLC's own per-(order, part) BOM result, from `smtOrder/getSmtOrderDetail`.
    # It carries `componentSource` — `preSale` (drawn from YOUR consigned stock),
    # `shop` (JLC supplied and charged for it) or `preSaleAndShop`. Without it a
    # draw silently assumes every part came out of the pool, which is how parts
    # JLC supplied itself were charged to the pool twice. Shape:
    # {smtOrderCode: [{lcsc, mpn, qty, componentSource, ...}]}.
    bom_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Per-order fee breakdown from `orderCenter/selectPersonOrderDetail` — the
    # ONLY place JLC itemizes an order's price (`orderCountTolls` for PCB
    # orders, `smtPriceInfo` for assembly orders; the invoice endpoint prints
    # one figure per line). Raw tolls are kept verbatim, same policy as
    # `payload`. Shape: {"orders": {<orderCode>: {kind, board, dummy, paicl,
    # carriage, tariff, tolls|spi}}}.
    fee_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("kind", "external_id", name="uq_jlc_import_source"),
    )


class JlcOrderDecision(Base):
    """What the operator decided about ONE JLC assembly order.

    Separate from the money it moves, and keyed on the supplier's own
    `smtOrderCode`, so the decision survives re-import, re-fetch and document
    deletion — decide once, and every later invoice or credit note for the same
    order self-attributes.

    `outcome`:
      `link_run`  — charge it to `run_id`
      `external`  — a project outside this platform: stock movement only, no owner
      `pending`   — seen, not yet decided

    `panel_factor` is stored because it is DERIVED (from BOM votes) rather than
    given: JLC's own quantity is panels when the order was panelised and there is
    no field saying so, so the factor is a conclusion worth keeping alongside the
    evidence that produced it.
    """

    __tablename__ = "jlc_order_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    smt_order_code: Mapped[str] = mapped_column(String(60), default="")
    batch_num: Mapped[str] = mapped_column(String(60), default="")
    outcome: Mapped[str] = mapped_column(String(20), default="pending")
    run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    panel_factor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="")  # what the robot proposed
    decided_by: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("smt_order_code", name="uq_jlc_decision_order"),
    )


class JlcWebSession(Base):
    """Browser session for JLCPCB's WEB API — a SINGLETON row (id=1).

    Separate from the JOP credentials in `settings` because it is a different
    authority with a different lifetime: the official partner API has no PCBA
    surface at all, so per-assembly-order component consumption is reachable
    only through the endpoints the user-center SPA calls, which authenticate
    with real browser cookies (see `services/jlc_web.py`).

    `cookies_enc` holds the whole pasted blob encrypted (crypto.py Fernet,
    same as `Project.git_token_enc`) rather than parsed columns, because JLC
    can add cookies at any time and a session is only useful intact. It is
    decryptable — the client needs the cleartext to send — but never leaves
    the API: responses expose only whether a session is set and when it last
    worked.

    `last_ok_at` is the honest liveness signal. Cookies present is NOT the
    same as cookies working: the session dies server-side (HTTP 460) with no
    local warning, so the UI must distinguish "configured" from "verified".
    """

    __tablename__ = "jlc_web_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    cookies_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the session was first observed DEAD, and what JLC said. Recorded
    # because the session's real lifetime is unknown and worth learning: the
    # 30-minute figure everyone assumes belongs to `secretkey` and `XSRF-TOKEN`,
    # both of which this client already renews by itself. One session was measured
    # alive for 3.15 hours. `died_at - updated_at` is the only way to find out
    # whether JLC expires on IDLE (in which case the keep-alive below makes the
    # problem disappear) or on an ABSOLUTE cap (in which case nothing local can).
    died_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    # Successful keep-alive touches on the CURRENT session, so a long-lived one is
    # visible as evidence rather than anecdote.
    keepalive_count: Mapped[int] = mapped_column(Integer, default=0)


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
    # Production-step identity from services/cost_steps.py ("pcba:setup",
    # "final:device", ...). An invoice line billed under the same step key IS
    # this item's actual — the plan-vs-actual match keys on it, never on labels.
    # Empty = a free-form item matched only by explicit `c<id>` links.
    step_key: Mapped[str] = mapped_column(String(40), default="")
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
    # What this batch is programmed with. Soft pointers (like snapshot_id): a
    # ProgrammingRun pins its own deployment version, so re-assigning the batch
    # never rewrites what was already programmed. Either pin a version outright
    # or follow a channel by name and let it resolve at run creation.
    deployment_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deployment_channel: Mapped[str] = mapped_column(String(40), default="")
    # --- baseline pinning: without these, a later cost edit or a qty change
    # silently rewrites what a historical run "expected". All soft pointers.
    plan_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Units that actually passed. Actual per-device cost divides by THIS, not by
    # the planned qty; can be filled from ProgrammingRun outcomes.
    qty_good: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- the SALE side, so income and margin sit next to cost.
    # A price per device, not a batch total: the batch total is derived, and a
    # per-device figure survives a quantity correction. `sale_currency` empty =
    # the project's display currency. `qty_sold` is what the customer was billed
    # for, which is not always what passed test (samples, held-back stock), so
    # revenue divides by it rather than by qty_good.
    sale_unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sale_currency: Mapped[str] = mapped_column(String(10), default="")
    qty_sold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer: Mapped[str] = mapped_column(String(200), default="")
    order_ref: Mapped[str] = mapped_column(String(200), default="")  # customer's PO / order no
    order_date: Mapped[str] = mapped_column(String(20), default="")  # ISO date, like run_date
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
    """File attached to a production run OR to a supplier document (serial-number
    lists, scanned invoices, test reports). Bytes live in MinIO under the stored key.

    Exactly one owner is set. A document attachment must NOT be stored under the
    run's MinIO prefix even when the document names a run: `delete_run` wipes that
    prefix, and a financial record's evidence has to outlive the run — the same
    reason `RunCostDocument` is owned by the project rather than the run.
    """

    __tablename__ = "run_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    # Soft pointer, mirroring `RunCostDocument.attachment_id` in the other direction.
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    minio_key: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ProductionRun | None] = relationship(back_populates="attachments")


class RunDevice(Base):
    """Structured serial-number registry: one row per produced device.

    This is the batch's PLANNED list — serials entered by hand for a run. It is
    deliberately NOT the flashing identity: a device that fails programming has
    no serial yet, and the same physical unit can be reprogrammed under another
    run. Reality is recorded by DeviceUnit (keyed by MAC) + ProgrammingRun; the
    two are reconciled by serial for a per-batch coverage report.
    """

    __tablename__ = "run_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    serial: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ProductionRun] = relationship(back_populates="devices")

    __table_args__ = (UniqueConstraint("run_id", "serial", name="uq_run_serial"),)


# ------------------------------------------- production cost actuals (post factum)
class RunCostDocument(Base):
    """A supplier document whose cost is split across production runs —
    invoice, proforma, receipt or credit note.

    Owned by the PROJECT, not the run (`run_id` is optional), for three
    reasons: an invoice can cover several runs or stock for later; costs like
    certification or tooling belong to no run at all; and a financial record
    must survive `delete_run`, which hard-deletes and wipes its MinIO prefix.

    FX is pinned at entry (`fx_rate_usd`, plus the converted `display_amount`)
    because `fx.convert` pivots through USD and `Project.display_currency` is
    editable — and because historical invoices predate the rate history
    entirely (it starts 2026-07-19).
    """

    __tablename__ = "run_cost_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = a SHARED document that belongs to no single project: one JLC parts
    # invoice routinely covers several products (e.g. Dongle + Aqua), and the
    # components land in a company-wide pool that every project draws from.
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    doc_type: Mapped[str] = mapped_column(String(20), default="invoice")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    doc_number: Mapped[str] = mapped_column(String(100), default="")
    # Supplier's own order id (JLC "Batch No" POB0…) — the idempotency key on import.
    external_id: Mapped[str] = mapped_column(String(100), default="")
    doc_date: Mapped[str] = mapped_column(String(20), default="")  # ISO date, like run_date
    paid_at: Mapped[str] = mapped_column(String(20), default="")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    fx_rate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate_display: Mapped[float | None] = mapped_column(Float, nullable=True)
    display_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    attachment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr → run_attachments
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["RunCostLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="RunCostLine.position"
    )

    __table_args__ = (
        Index("ix_run_cost_doc_project", "project_id"),
        Index("ix_run_cost_doc_run", "run_id"),
        # Same supplier invoice number twice in a project is a duplicate entry.
        Index(
            "uq_run_cost_doc_number", "project_id", "supplier", "doc_number",
            unique=True, postgresql_where=text("doc_number <> ''"),
        ),
    )


class RunCostLine(Base):
    """One actual cost line off a supplier document.

    `kind="part"` with no `run_id` means the line feeds the **component cost
    pool** — runs draw from it via ComponentConsumption at a moving average.
    Every other kind (fab, assembly, freight, tooling, …) is a direct cost of
    its run. There is deliberately no separate purchases table: the pool IS the
    set of part lines.

    Rows are never deleted — `voided_at` retires one and `superseded_by_id`
    chains a correction, so a money figure always has a visible history.

    Lines form a TREE via `parent_line_id`, which is how one invoice position is
    split. Two uses, one mechanism: shares of a position charged to different
    runs, and a supplier's own sub-breakdown (JLC prints one "SMT Assembly"
    figure whose stencil / manual-assembly / surcharge components appear only on
    their website). **A line with live children is a HEADER worth zero** — only
    leaves carry money, or the same amount would be counted twice. That rule
    lives in `run_actuals.header_ids` and nowhere else.
    """

    __tablename__ = "run_cost_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("run_cost_documents.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    # A share destined for a project but not yet for a specific run (an Aqua
    # portion of a shared freight line, tooling that predates its batch). Without
    # it such a remainder could only be described in `notes` — i.e. lost.
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    # Soft pointer, deliberately not a FK: `RunCostDocument.lines` cascades
    # delete-orphan, and a self-FK inside a cascaded collection makes delete
    # ordering fragile. Same choice as `superseded_by_id` below.
    parent_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # part|fab|assembly|tooling|freight|duty|tax|rework|packaging|service|other
    kind: Mapped[str] = mapped_column(String(20), default="part")
    basis: Mapped[str] = mapped_column(String(20), default="per_run")  # per_device|per_run
    label: Mapped[str] = mapped_column(String(300), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)  # NET, in `currency`
    currency: Mapped[str] = mapped_column(String(10), default="")  # "" inherits the document
    # none|by_value|by_qty — a freight/duty line spread over the part lines of
    # the same document (derived on read; the carrier row is never consumed).
    allocate: Mapped[str] = mapped_column(String(20), default="none")
    # WHY this line is charged to nobody. `allocate='excluded'` is a legal bucket
    # in the conservation identity, so an exclusion is invisible to every check
    # the platform has: all 115 imported manufacturing lines were once excluded —
    # $14,443 charged to nobody — while the register read `gap_usd 0.0272`,
    # `pool balanced`, `0 issues`. Naming the reason is what makes the bucket
    # checkable. Closed list, enforced in the router:
    #   prepaid_components | reclaimable_vat | external_project |
    #   cancelled_order_fee | dev_bench | duplicate_superseded |
    #   legacy_unstated (backfill only) | other
    exclude_reason: Mapped[str] = mapped_column(String(40), default="")
    # The supplier's own identity for this line — for JLC, the `smtOrderCode` the
    # charge belongs to (`jlc_import.plan_manufacturing_document` computes it and
    # nothing stored it, so the line -> order join survived only inside `label`
    # text and had to be reverse-engineered by `fix_alloc.py` and
    # `mark_external.py`). With it, a decision reclassifies its own lines by key.
    external_line_id: Mapped[str] = mapped_column(String(120), default="")
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    mpn: Mapped[str] = mapped_column(String(200), default="")  # JLC invoices carry MPN, not LCSC
    lcsc: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # Link to the PLANNED line this is the actual for; "" = a genuine late position.
    plan_key: Mapped[str] = mapped_column(String(40), default="")
    plan_kind: Mapped[str] = mapped_column(String(10), default="")  # bom|extra|cost|""
    plan_ref: Mapped[str] = mapped_column(String(300), default="")  # stable natural key
    # The supplier's own per-lot key (JLC `presaleGoodsKeyId`). A LOT IS THIS
    # ROW — a leaf part line with no run — so naming it here makes lots
    # first-class without a parallel table that could drift from the money.
    # Non-empty means a draw can cite WHICH purchase it consumed as reported
    # fact; empty means lot assignment can only ever be inferred (FIFO).
    lot_ref: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # importer provenance
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[RunCostDocument] = relationship(back_populates="lines")

    __table_args__ = (
        Index("ix_run_cost_line_run", "run_id"),
        Index("ix_run_cost_line_component", "component_id"),
        Index("ix_run_cost_line_kind", "kind"),
        Index("ix_run_cost_line_parent", "parent_line_id"),
    )


class ComponentConsumption(Base):
    """What a production run drew from the component cost pool.

    The point is SPLITTING INVOICE COST, not tracking inventory (user decision
    2026-07-27) — quantities exist to apportion money. `basis` records how the
    quantity was arrived at so an estimate can never be read as a measurement:

    - `measured`   — from JLC stock deltas between syncs
    - `bom`        — BOM qty x units built
    - `allocated`  — historical backfill, anchored on purchases minus current stock
    - `manual`     — typed

    `unit_cost_usd` is the moving average SNAPSHOTTED here, so a purchase
    entered later (backfill inserts older rows) can never rewrite a closed run.
    The average itself is replayed in event-date order, never insertion order.
    """

    __tablename__ = "component_consumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    mpn: Mapped[str] = mapped_column(String(200), default="")
    lcsc: Mapped[str] = mapped_column(String(50), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    basis: Mapped[str] = mapped_column(String(20), default="bom")
    # Provenance of an IMPORTED draw, empty on every hand-made row. Backed by the
    # partial unique index `uq_consumption_import`, which is the FIRST uniqueness
    # this table has ever had — re-running an import becomes a no-op instead of a
    # second draw, which is precisely how components 324/325 were charged twice
    # across five runs.
    import_ref: Mapped[str] = mapped_column(String(120), default="")
    consumed_at: Mapped[str] = mapped_column(String(20), default="")  # ISO date; drives the replay
    note: Mapped[str] = mapped_column(String(500), default="")
    # Retiring a draw VOIDS it; it is never deleted. A forecast superseded by a
    # measurement has to be restorable, because reversing the import that
    # superseded it must put the run back exactly as it was — and `void_shop.py`
    # and `void_absent.py` deleted 10 rows that could then only come back from a
    # database backup. Every read of this table filters `voided_at IS NULL`;
    # the seven sites are listed in the Phase 1 section of
    # `docs/production-costs/design.md`.
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_consumption_run", "run_id"),
        Index("ix_consumption_component", "component_id"),
    )


class ComponentStockAdjustment(Base):
    """Attrition and reconciliation — a first-class part of the model, not an
    error path. Components get lost in production, so the platform's remaining
    quantity is never expected to match JLCPCB's stock exactly.

    `charge_run_id` decides where the money lands: set it and the loss is part
    of that run's cost (its per-device figure carries the real attrition);
    leave it NULL and the write-off sits at project level. Also used for
    opening balances when backfilling history.
    """

    __tablename__ = "component_stock_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    component_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    mpn: Mapped[str] = mapped_column(String(200), default="")
    lcsc: Mapped[str] = mapped_column(String(50), default="")
    qty_delta: Mapped[float] = mapped_column(Float, default=0.0)  # negative = lost/written off
    unit_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # snapshot; NULL = replay
    # attrition|scrap|miscount|opening_balance|correction|external_project
    reason: Mapped[str] = mapped_column(String(30), default="attrition")
    charge_run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    adjusted_at: Mapped[str] = mapped_column(String(20), default="")  # ISO date; drives the replay
    # Provenance of an IMPORTED adjustment, backed by `uq_stock_adj_import`.
    # `apply_external_movements` deduped by scanning `note LIKE '%code%'` — a text
    # scan standing in for a constraint. This is the constraint.
    import_ref: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_stock_adj_component", "component_id"),
        Index("ix_stock_adj_run", "charge_run_id"),
    )


# ------------------------------------------------- firmware releases (flasher)
class FirmwareAsset(Base):
    """A firmware binary. CONTENT-ADDRESSED: the same build uploaded twice is
    one row, because the sha256 is the identity. Bytes live in MinIO."""

    __tablename__ = "firmware_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    chip: Mapped[str] = mapped_column(String(30), default="")  # esp32 | esp32c6 | …
    # factory | app | filesystem | safeboot — what the image IS, which decides
    # the default flash offset and whether writing it wipes device settings.
    kind: Mapped[str] = mapped_column(String(20), default="factory")
    minio_key: Mapped[str] = mapped_column(String(500))
    # Free label from the build (e.g. Tasmota's BuildDateTime) for the UI.
    build_label: Mapped[str] = mapped_column(String(100), default="")
    # Is this actually writable to a device? Decided at upload from the bytes:
    # an ESP image carries magic 0xE9 at offset 0, or at 0x1000 for a padded
    # whole-flash image (ESP32 keeps its bootloader there). False for the
    # retro PLACEHOLDER assets, whose real firmware was never archived —
    # flashing one would brick a unit, so the validator refuses it.
    flashable: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[str] = mapped_column(String(100), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "sha256", name="uq_firmware_project_sha"),)


class DeviceFile(Base):
    """A payload file the device downloads during deployment (`autoexec.be`,
    driver JSONs). Versioned SEPARATELY from firmware (user decision
    2026-07-29): a script change never requires a firmware rebuild. Delivery
    is over HTTP from the platform — the deployment script has the device
    fetch each pinned version with UrlFetch and verifies the size."""

    __tablename__ = "device_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(200))  # name ON THE DEVICE, e.g. autoexec.be
    description: Mapped[str] = mapped_column(String(500), default="")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["DeviceFileVersion"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="DeviceFileVersion.version_no"
    )

    __table_args__ = (UniqueConstraint("project_id", "filename", name="uq_device_file_name"),)


class DeviceFileVersion(Base):
    """IMMUTABLE content of one device file. Text lives in Postgres (these are
    small .be/.json sources); `size_bytes` is what the device's file_size
    check must report after the download."""

    __tablename__ = "device_file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_file_id: Mapped[int] = mapped_column(ForeignKey("device_files.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|rejected
    content: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    file: Mapped[DeviceFile] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("device_file_id", "version_no", name="uq_device_file_version"),)


class Deployment(Base):
    """A named programming target for a project ("Dongle_V3 production").

    Its versions are THE unit of change: one version binds firmware images,
    berryware files, the procedure and the parameter wiring, so "what does a
    device get" has exactly one answer (user decision 2026-07-29). Channels
    point at a version by name; `current_version_id` is the newest published.
    """

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    chip: Mapped[str] = mapped_column(String(30), default="")  # esp32 | esp32c6 | …
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["DeploymentVersion"]] = relationship(
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="DeploymentVersion.version_no",
    )

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_deployment_name"),)


class DeploymentVersion(Base):
    """THE immutable revision: firmware + berryware + procedure + parameters.

    Everything a device receives is pinned here, so a programming run records
    one id and the whole truth follows from it. The two fingerprints are
    DERIVED (sha256 over the ordered image list / the file set) and stored so
    the UI can say "firmware unchanged since v5" or "3 files changed" without
    re-reading every child row — they are cache, never authority.

    Parameter VALUES stay out (user decision 2026-07-27): they come from a
    ParamSet at run time and are snapshotted per ProgrammingRun, so rotating a
    WiFi password never mints a version. The SIM PIN resolves at run time too:
    operator field on the bench, else the param set default, else a mid-run
    prompt — a deployment for PIN-less SIMs simply has no lte_sim_pin step.
    """

    __tablename__ = "deployment_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|rejected
    created_by: Mapped[str] = mapped_column(String(100), default="")
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str] = mapped_column(String(500), default="")
    # uart_bridge | usb_serial_jtag — decides reset strategy and whether the
    # monitor phase may touch DTR/RTS at all (see docs/flasher/design.md §7).
    transport_profile: Mapped[str] = mapped_column(String(40), default="uart_bridge")
    monitor_baud: Mapped[int] = mapped_column(Integer, default=115200)
    flash_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # mode/freq/size
    steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # ordered op list
    param_set_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    param_defaults: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # non-secret
    # Derived identity of the two halves — see the class docstring.
    firmware_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    files_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    # Human label for the berryware set ("release-1.3.11", "fs @ 2026-07-22").
    # The user thinks in file BUNDLES even though files version individually
    # (user decision 2026-07-29), so the set gets a name of its own. When the
    # pinned set matches a BerryBundle, `berry_bundle_id` links it and the
    # label mirrors the bundle's.
    files_label: Mapped[str] = mapped_column(String(120), default="")
    berry_bundle_id: Mapped[int | None] = mapped_column(
        ForeignKey("berry_bundles.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deployment: Mapped[Deployment] = relationship(back_populates="versions")
    images: Mapped[list["DeploymentImage"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="DeploymentImage.position",
    )
    files: Mapped[list["DeploymentFile"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="DeploymentFile.position",
    )

    __table_args__ = (
        UniqueConstraint("deployment_id", "version_no", name="uq_deployment_version"),
    )


class DeploymentImage(Base):
    """One firmware image at one flash offset inside a deployment version. A
    blank ESP32-C6 needs two (factory @0x0 + LittleFS @0x4B0000)."""

    __tablename__ = "deployment_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_version_id: Mapped[int] = mapped_column(ForeignKey("deployment_versions.id"))
    firmware_asset_id: Mapped[int] = mapped_column(ForeignKey("firmware_assets.id"))
    address: Mapped[str] = mapped_column(String(12), default="0x0")
    position: Mapped[int] = mapped_column(Integer, default=0)

    version: Mapped[DeploymentVersion] = relationship(back_populates="images")
    asset: Mapped[FirmwareAsset] = relationship()

    __table_args__ = (
        UniqueConstraint("deployment_version_id", "address", name="uq_deployment_image_addr"),
    )


class DeploymentFile(Base):
    """One pinned device file version inside a deployment version. Download
    order follows `position` (autoexec.be last, so a partial download never
    leaves a bootable-but-incomplete device — the validator enforces it)."""

    __tablename__ = "deployment_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_version_id: Mapped[int] = mapped_column(ForeignKey("deployment_versions.id"))
    device_file_version_id: Mapped[int] = mapped_column(ForeignKey("device_file_versions.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)

    version: Mapped[DeploymentVersion] = relationship(back_populates="files")
    file_version: Mapped[DeviceFileVersion] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "deployment_version_id", "device_file_version_id", name="uq_deployment_file"
        ),
    )


class BerryBundle(Base):
    """A named berryware SET — the unit the user actually receives ("the fs of
    release 1.3.11"), while files keep versioning individually underneath.

    One row per distinct file set per project: identity is the set fingerprint
    (same rule as DeploymentVersion.files_fingerprint), so re-importing the
    same folder under any name reuses the bundle instead of minting a twin.
    Immutable once created — a changed file set is a NEW bundle.
    """

    __tablename__ = "berry_bundles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    label: Mapped[str] = mapped_column(String(120))  # "release-1.3.11", "fs @ 2026-07-22"
    files_fingerprint: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list["BerryBundleFile"]] = relationship(
        back_populates="bundle", cascade="all, delete-orphan", order_by="BerryBundleFile.position"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "files_fingerprint", name="uq_berry_bundle_set"),
    )


class BerryBundleFile(Base):
    """One pinned device file version inside a bundle (autoexec.be last, same
    ordering rule as DeploymentFile)."""

    __tablename__ = "berry_bundle_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    berry_bundle_id: Mapped[int] = mapped_column(ForeignKey("berry_bundles.id"))
    device_file_version_id: Mapped[int] = mapped_column(ForeignKey("device_file_versions.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)

    bundle: Mapped[BerryBundle] = relationship(back_populates="files")
    file_version: Mapped[DeviceFileVersion] = relationship()

    __table_args__ = (
        UniqueConstraint("berry_bundle_id", "device_file_version_id", name="uq_bundle_file"),
    )


class DeploymentChannel(Base):
    """A named pointer at one deployment version ("production", "bench").

    This is what a batch or the bench follows by name, so rolling back is
    repointing a channel rather than editing history. A run always records the
    version that actually resolved, never the channel.
    """

    __tablename__ = "deployment_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id"))
    name: Mapped[str] = mapped_column(String(40))  # production | bench | …
    deployment_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployment_versions.id"), nullable=True
    )
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    version: Mapped[DeploymentVersion | None] = relationship()

    __table_args__ = (UniqueConstraint("deployment_id", "name", name="uq_deployment_channel"),)


class ParamSet(Base):
    """Scenario placeholder values for a project ("production", "bench"):
    WiFi credentials, MQTT host/port, credential salt. Fernet-encrypted at rest
    via services/crypto.py — these are the SHARED secrets whose leak affects
    every device (per-device credentials are stored in the clear by decision)."""

    __tablename__ = "param_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(100))
    values_enc: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_param_set_name"),)


# ------------------------------------------------ devices + programming runs
class DeviceUnit(Base):
    """A PHYSICAL device, identified by the MAC read out of the chip.

    The MAC is the identity on purpose: esptool reports it seconds into a run,
    long before the firmware boots, so a device that fails programming is still
    attributable. Tasmota's topic/device id is read later and kept as a label.
    """

    __tablename__ = "device_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    # NULLABLE for retroactively imported devices: the V2-era reports carry
    # only the topic's 6-hex suffix (the MAC's last 3 bytes), never the full
    # MAC. Live programming always fills it. NULLs don't collide on UNIQUE.
    mac: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "58:8c:81:2f:74:74"
    chip: Mapped[str] = mapped_column(String(60), default="")
    tasmota_id: Mapped[str] = mapped_column(String(120), default="")  # topic, e.g. dongle_588C…
    serial: Mapped[str] = mapped_column(String(60), default="")  # MAC w/o separators, for marking
    # LTE module + SIM identity, captured during programming (user requirement
    # 2026-07-29). Written by the engine when a step captures the matching
    # reserved variable name (imei, iccid, imsi, modem_model, modem_fw).
    imei: Mapped[str] = mapped_column(String(20), default="")
    iccid: Mapped[str] = mapped_column(String(24), default="")
    imsi: Mapped[str] = mapped_column(String(18), default="")
    modem_model: Mapped[str] = mapped_column(String(60), default="")
    modem_fw: Mapped[str] = mapped_column(String(60), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_status: Mapped[str] = mapped_column(String(20), default="")  # pass|fail of the newest run
    notes: Mapped[str] = mapped_column(Text, default="")

    runs: Mapped[list["ProgrammingRun"]] = relationship(
        back_populates="device", order_by="ProgrammingRun.started_at.desc()"
    )
    configs: Mapped[list["DeviceConfigValue"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("mac", name="uq_device_mac"),)


class ProgrammingRun(Base):
    """ONE ATTEMPT at programming one device — pass or fail, always kept.

    Created BEFORE the first step runs, so an attempt that dies before the MAC
    can be read still exists with its production run, station, operator, time
    and full log; `device_unit_id` stays NULL and the run shows up as an
    unidentified attempt that can be linked to a device afterwards.
    """

    __tablename__ = "programming_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_unit_id: Mapped[int | None] = mapped_column(ForeignKey("device_units.id"), nullable=True)
    # NULLABLE only for retro imports whose batch is unknown (user decision
    # 2026-07-29: never guess the batch). Live run creation still requires it.
    production_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_runs.id"), nullable=True
    )
    # Pinned, never a soft pointer: this is exactly what was executed. One id
    # carries firmware + berryware + procedure + parameter wiring.
    deployment_version_id: Mapped[int] = mapped_column(ForeignKey("deployment_versions.id"))
    # Denormalised at run start so a run stays readable even if a version is
    # later rejected: which firmware/berryware set it actually carried.
    firmware_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    files_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    # True when the bench ran a DRAFT version (allowed on the bench, never for
    # a batch) — keeps candidate testing visible instead of indistinguishable.
    draft_run: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when the operator programmed with something other than the batch's
    # assigned deployment (also written to the audit log).
    release_override_reason: Mapped[str] = mapped_column(String(300), default="")
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    operator: Mapped[str] = mapped_column(String(100), default="")
    station: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|pass|fail|aborted
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raw readings, kept on the run even when no device row could be created.
    mac_read: Mapped[str] = mapped_column(String(20), default="")
    chip_read: Mapped[str] = mapped_column(String(60), default="")
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # captured vars
    params_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # values applied
    client_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # UA, USB ids

    device: Mapped[DeviceUnit | None] = relationship(back_populates="runs")
    steps: Mapped[list["ProgrammingStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ProgrammingStep.idx"
    )

    __table_args__ = (
        Index("ix_programming_runs_prod", "production_run_id"),
        Index("ix_programming_runs_device", "device_unit_id"),
        Index("ix_programming_runs_status", "status"),
    )


class ProgrammingStep(Base):
    """One step of a run's scenario, with its own outcome and duration."""

    __tablename__ = "programming_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("programming_runs.id"))
    idx: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|pass|fail|skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # A step becomes a FUNCTIONAL CHECK by carrying `check: "relay.2"` in the
    # procedure. The name is the vocabulary key the device view groups by, so
    # the same functionality keeps one name across versions and products.
    check_name: Mapped[str] = mapped_column(String(60), default="")

    run: Mapped[ProgrammingRun] = relationship(back_populates="steps")

    __table_args__ = (UniqueConstraint("run_id", "idx", name="uq_programming_step_idx"),)


class RunCheck(Base):
    """ONE named functionality, proven or disproven by ONE run.

    DERIVED, never authored: `services.flasher.checks.recompute()` rebuilds
    every row of a run from that run's own steps and results. Drop the table and
    it comes back identical — which is what makes it safe to improve an
    extractor later. Two sources feed it:

      * a step that carries a `check` name — the live path, where the step's
        own pass/fail IS the check;
      * the `results` of an imported run, which has no steps at all: the V2-era
        reports kept the relay snapshots, the WiFi status and the download
        sizes, so the same checks are recoverable from evidence.

    `device_unit_id` is denormalised so one query paints a device's grid, and a
    roll-up over a batch is a plain GROUP BY.
    """

    __tablename__ = "run_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("programming_runs.id"))
    device_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_units.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(60))  # "relay.2", "wifi.join"
    label: Mapped[str] = mapped_column(String(120), default="")  # "Relay 2 (Switch8)"
    # identity | firmware | connectivity | berryware | hardware
    category: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # pass|fail|unknown
    detail: Mapped[str] = mapped_column(Text, default="")  # the sentence a human reads
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # the measurement
    position: Mapped[int] = mapped_column(Integer, default=0)  # order inside the category
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_run_check_name"),
        Index("ix_run_checks_device", "device_unit_id"),
        Index("ix_run_checks_name", "name"),
    )


class ProgrammingLog(Base):
    """Append-only communication log for a run: every line, in order.

    Everything is kept including esptool progress (user decision 2026-07-27),
    so expect a few thousand rows per run. `device_ts` holds the device's own
    timestamp ("00:00:04.248") when the line carries one — useful because it
    survives independently of server clock skew. Never UPDATE or DELETE rows.
    """

    __tablename__ = "programming_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("programming_runs.id"))
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device_ts: Mapped[str] = mapped_column(String(20), default="")
    dir: Mapped[str] = mapped_column(String(10))  # tx|rx|app|err|esptool
    text: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_programming_log_seq"),)


class DeviceConfigValue(Base):
    """A configuration key applied to a device (mqtt_user, mqtt_password,
    mqtt_host, …), stamped with the run that set it.

    Values are stored in the CLEAR by user decision 2026-07-27 (the broker and
    support tooling need them, matching today's reports/*.json and
    mosquitto_passwords.txt). Consequence: never include them in list
    endpoints — detail views only, fetched explicitly. History is kept:
    `current` marks the newest value per key so reprogramming leaves a trail.
    """

    __tablename__ = "device_config_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_unit_id: Mapped[int] = mapped_column(ForeignKey("device_units.id"))
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)  # mask in the UI by default
    set_by_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # soft ptr
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current: Mapped[bool] = mapped_column(Boolean, default=True)

    device: Mapped[DeviceUnit] = relationship(back_populates="configs")

    __table_args__ = (Index("ix_device_config_key", "device_unit_id", "key"),)


# ------------------------------------------------------------------- settings
class AppSetting(Base):
    """A runtime override for one `Settings` field, editable in the UI.

    Precedence is DB > environment > code default: a row here wins, and
    deleting it reverts to whatever the environment or the default gave.
    Only keys in `services/appconfig.py::KNOBS` may be written — infrastructure
    (database_url, minio_*, data_dir) and SECRET_KEY are deliberately absent,
    because changing them under a running platform either breaks it or makes
    stored git tokens undecryptable.

    Values are stored as text and coerced back by the knob's declared kind.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="user")


# ----------------------------------------------------------------------- auth
class User(Base):
    """A person who may sign in. Created by an admin only.

    There is no self-registration and no password recovery, by user decision
    2026-07-31: this is a small private platform, and an admin resetting a
    password in the Setup page is the whole recovery story.

    `username` is stored lowercase (`services/auth.py::normalize_username`) so
    a login can never fork on case. `role` is `admin` or `user`; admin is what
    gates user management and the Setup page's configuration writes.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tokens: Mapped[list["ApiToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class ApiToken(Base):
    """A user's machine credential: KiCad, the sync plugin, MCP.

    TWO copies of the secret are stored, and each has one job:

    - `token_hash` (SHA-256) is what a request is verified against. It is a
      plain digest, not a password hash, because the secret is 32 random bytes
      — there is nothing to brute-force, and verification sits on the KiCad
      symbol chooser's critical path where argon2 would cost ~100 ms a call.
    - `token_enc` (Fernet, `services/crypto.py`) exists so the Setup page can
      show a user their token AGAIN, months later. User decision 2026-07-31:
      the token is baked into a personal PCM repository URL, so "show it once
      and never again" would mean a rotation and a KiCad re-install every time
      somebody loses the link. The tradeoff is explicit — a database dump plus
      SECRET_KEY yields every token.

    `prefix` is the first 8 characters, kept in the clear for display and for
    naming a token in the audit log without revealing it.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_enc: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tokens")

    __table_args__ = (Index("ix_api_token_user", "user_id"),)


class UserSession(Base):
    """A browser session. The cookie carries only `id`, which is random.

    Server-side rows rather than a signed stateless cookie, so that deleting a
    user, deactivating one, or clicking Log out ends the session immediately
    instead of at the next expiry.
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(60), default="")

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_user_session_user", "user_id"),)


class LoginAttempt(Base):
    """Failed sign-in counter, per username. Feeds the lockout backoff.

    Keyed on the username rather than the IP: the platform sits behind
    Cloudflare and an nginx hop, so the address a request appears to come from
    is not a stable identity, while the username being guessed is exactly what
    needs protecting.
    """

    __tablename__ = "login_attempts"

    username: Mapped[str] = mapped_column(String(60), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
