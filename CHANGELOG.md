# Changelog

## 2026-09-14 — A rule leaves a skill only when a check has it

An earlier pass today removed 42 KB from the component-conventions document on
the assumption the new checks held that data. Audited line by line, they did
not: the rule that an RF part spells the key `VSWR` and never `V.S.W.R` had no
check at all, 15 of 31 description templates were in no check, and a decision
rule - "a family-wide deviation defends itself" - was deleted outright. That
pass was reverted.

Redone against a mechanical test: a row leaves only when a check holds its data
AND the row carries nothing else. That removed **60 of 81** manufacturer rows
(a spelling plus a list of feed misspellings, and the check holds the spelling)
and **9 of 31** template rows. The other 21 and 22 stayed, because each carries
a decision, a reason, or has no check.

51 KB to 47 KB. That is the compression actually available: the bulk of that
document is reasoning, and reasoning is what a check cannot hold.

### New

**`absent`** - the assertion for a rule that says there must be no X. Every
other assertion reads a value, so a subject without one is answered "does not
apply" before the assertion runs, which made "this key must not exist"
inexpressible. `cmp.vswr_key` is the first to use it.

[what-a-check-can-hold.md](docs/reference/what-a-check-can-hold.md) records the
mapping and the order - build the check, measure it, then cut.

### Found, not fixed

`Inductors`, `RF` and `Circuit_Protection` carry no `comp_type`, so their Value
and description rules cannot become checks: a fixed inductor, a ferrite bead and
a LAN transformer are three rules sharing one category with nothing in the data
to tell them apart. `Connectors` has the same problem differently - `Pluggable
terminal block; {Pitch}` and `Pluggable terminal block; 3.5mm` coexist in one
family. Work list row 24.

## 2026-09-14 — The conventions point at the checks, and Zener has one n

**Four skill documents were republished** so an agent stops hand-verifying what
the platform already decides. `platform-workflow` v11 was the urgent one: it
still told agents to answer `skipped`, retired in September, and still described
the automatic checks as something recorded on publish. It now says what the
platform does — checks are worked out on read, "does not apply" is a standing
exception that outlives the version and needs a note, notes are capped, a
warning does not fail a part, and a switched-off check is not the same as one
that is not about this part.

The three convention skills now mark the rules the platform enforces —
`fp.quad_numbering`, `fp.zero_annulus`, `sym.top_edge`, `sym.pin_length`,
`cmp.value_placeholder` and `cmp.value_field` — and keep the prose, which says
why the mistake happens and what to do when a check fires. A check cannot
explain itself.

**Zener is spelled with one n, everywhere.** All six Zener diodes were
republished: the property key `Zenner Voltage`, `comp_type=ZENNER` and the
template word "Zenner Diode" all moved together, because they have to — a
dangling `{Zenner Voltage}` fails the template check. No `Zenner` remains on any
live version. The six lost their verification, as a property edit always does.

**The Diodes Value rule is now three rules.** The base list splits on category
and cannot reach inside one, so the Diodes category carries its own variants
split on `comp_type`: the reverse stand-off voltage for a TVS, an RKM V code for
a Zener, the part number for a rectifier.

It found two parts carrying their MPN where the stand-off voltage belongs —
`SMF28A` and `SMF6V0A-E3-08`, now `28V` and `6V`. Both were read off each part's
own **Reverse Stand-Off Voltage** property, not decoded from the part number.
The work list had recorded seven such parts; there were two.

## 2026-09-14 — Changing a check changes the lists, without a restart

Editing a checklist re-fingerprints every subject it reaches, but nothing acted
on that: list surfaces read the cache without re-checking the fingerprint, and a
detail page worked out the new answer and then threw it away. So a check edited
on the platform changed nothing anybody could see until the API happened to
restart. Found by shipping the new checks to production and watching the
numbers not move.

Saving a checklist now re-evaluates that kind in the background, and the pages
that recompute keep what they worked out. Revoke a standing decision and the
list of parts failing that check reports it on the next request.

## 2026-09-14 — Fix: an empty table took the page down

Any list with a default sort crashed when it had no rows. The sort asks the
first row what type it holds to decide between numeric and text ordering, and
on an empty list there is no first row, so the question threw and the whole
page went blank.

It surfaced on Reviews -> Exceptions, which is the first list that is
legitimately empty on a library with no standing decisions recorded yet. It
worked in testing because the test library had six.

## 2026-09-14 — An explanation has a length now

Every field that holds a written reason is capped, and an over-long one is
refused rather than quietly cut.

| Field | Limit |
|---|---|
| a note on a checklist item | 400 |
| a custom check's own wording | 200 |
| the note on a verification pass | 300 |
| an exception's note | 400 |
| an exception's evidence | 600 |
| a revoke reason | 300 |
| a version's change comment | 600 |

The numbers come from what was already stored. A person writes **31**
characters in a note. An agent's median is **367**, and the longest in the
library is **3,316** - about 500 words on one checklist item. Nobody reads that,
so the finding inside it is lost as surely as if it had never been written.
Version comments were worse: symbol edits ran to a median of 876 and a maximum
of 4,087.

Refused, not truncated. A cut-off sentence teaches nobody; the refusal names the
length, the limit and what to write instead - "say what is wrong and how you
know, in a few sentences". A refused item comes back on the blocked list and the
rest of the save goes through.

In the web UI the box simply stops accepting text, with a counter that appears
in the last quarter, so nobody writes three paragraphs and then loses them.

Nothing already stored was changed. The limits apply to what is written from
now on.

## 2026-09-14 — Standing decisions have a register, and a failing check has a worklist

**Reviews → Exceptions** lists every standing decision in the library: the
subject, the check, why, how long it holds, who made it, and whether it still
applies. An exception was visible only on its own component's card before this,
so nothing could answer "what have we excused". A decision that pins nothing
holds for every future version of a part, and now somebody can see which ones
those are.

A **stale** row is the point of the screen. An exception dies when a fact it
named changes, and one that has quietly stopped applying means the check it
excused is failing again somewhere nobody is looking.

**A failing check opens.** The library-health panel already grouped failures by
check rather than by part, because "fp.courtyard_grid on 76 footprints" is one
job and "218 failed parts" is a wall. The numbers were dead text. Click one and
it lists every part it fails on, with each part's own note and a link to it.

**The review state is three facts, not one word.** A card now reads
`ISSUES · FAILS · JUDGED 10/11` instead of `ISSUES` alone. "Partial" used to
mean "nobody has looked", "a question was added last week" and "one item is
still open" all at once, and a footprint could read "unreviewed" straight after
somebody decided every check on it. The queue keeps the single word, because a
list has to sort by something, and carries the facts in the tooltip.

### Fixed

A verification saved after **Mark checked** discarded every answer underneath
it. The one-click confirmation is stored with no item breakdown by design, and
the next save was seeded from it, so a part went from twelve recorded answers to
one. Found 2026-08-25, fixed today. Answers now survive the sequence.

The library-health panel counted some failures twice — once from the agent's
flag and once from the machine's finding — reporting `cmp.datasheet_text` on 47
components where 27 carry it.

## 2026-09-14 — Eight convention rules are checks now, not prose

Rules that lived as paragraphs in the skill documents, for an agent to read and
re-read on every part, are checks the platform runs itself:

| Check | From | Finds today |
|---|---|---|
| `fp.zero_annulus` | footprints section 6 | 0 |
| `fp.quad_numbering` | footprints section 2 | 0 |
| `sym.top_edge` | symbols section 3 | 24 (warning) |
| `sym.pin_length` | symbols section 4 | 2 |
| `cmp.value_placeholder` | library section 3 | 0 |
| `cmp.pins_to_pads` | - | 0 |
| `cmp.pads_to_pins` | - | 13 (warning) |
| `cmp.value_field` | library section 3 | 0 |

Across all 857 subjects the eight add **two** error-level failures, both in
`sym.pin_length`: `Crystal_GND24_Small` mixes 0.635 mm and 1.27 mm stubs,
`LSM6DS3` mixes 2.54 mm and 3.81 mm. Nothing else turned red. That is what
severity and computed conformance were built for.

**The Value rule is now seven rules under one key.** A resistor's Value is
checked against the RKM code, a capacitor's against the unit format, an IC's
against its part number verbatim, a test point's against its own name. A
category no rule covers yet falls through to the same human question as before,
so nothing was lost. The Checks page shows them as `BASE.Resistance`,
`BASE.MPN`, `BASE.Component name` and so on, each with the condition it applies
under.

`fp.quad_numbering` catches the mirrored-footprint defect the skill records as
having shipped once. It reads the direction the pads trace in number order:
every one of the 48 IC packages in the library runs counter-clockwise, and the
seven parts that run the other way are all connectors, whose numbering follows
the datasheet and which the check deliberately does not cover.

**Six parts carry a standing exception instead of a recurring finding.** The
four `15EDGKNM` connectors, `KEYS2466` and `RPi_CM5` are the deviations the
library conventions already document. Each now holds a recorded decision with
the reason on it, so the rule stands for everything else and nobody re-discovers
them.

## 2026-09-14 — A check can read the drawing

Checks could only ask about a component: its category, its base symbol, its
fields. A symbol or a footprint carried three facts - its kind, its name and a
fingerprint - so every geometry rule stayed prose in a skill document for an
agent to read and re-read.

They now carry their own. A footprint check can ask for the pad count, the lead
pitch, how many pads sit off the 0.1 mm grid, which corner pad 1 is in, and
whether a quad package numbers counter-clockwise. A symbol check can ask for the
pin count, the distinct pin numbers, the unit count and which electrical pin
types are present.

Three facts compare two things, which no single assertion can do:

- **`$pins_without_pads`** - symbol pins whose number has no pad. A signal with
  nowhere to land.
- **`$pads_without_pins`** - pads the symbol does not draw. Usually an exposed
  thermal pad or an NC lead.
- **`$value_is_mpn` / `$value_is_name` / `$value_placeholder`** - the three
  shapes the Value rule takes.

Measured over all 439 components: **13 parts** have a gap between symbol and
footprint, and **every one of them is a pad the symbol does not draw** - an
exposed pad or an NC lead. Not one part has a pin with nowhere to go. Splitting
the one "mismatch" number in two is what made that readable.

Two counting errors are fixed with it. The pad count used to include paste
apertures and thermal vias, so a QFN-16 with an exposed pad reported 26 pads
instead of 17. And a two-pad chip resistor was reported as having pad 1 in the
"bottom-left" corner; it has no corner, and now reads "left".

The Checks page reads the fact list from the platform instead of holding its
own copy, so a footprint rule is never offered a component fact.

## 2026-09-14 — "Does not apply" is one decision, and it lasts

N/A is gone as an answer. The button on a check now reads **Does not apply...**
and it records a standing decision instead of a note on one version.

The two used to say the same thing, and only the throwaway one got used: 314
live N/A answers, 312 of them written by agents, not one with a reason on it,
every one due to expire at the next version bump - against zero rows in the
table built to hold such decisions. The reason was simple. N/A was the button on
the row.

Three things change for you:

- **You can say it about a check nobody has run.** Every judgment item offers
  it, not only a failing one. A check that is not about this part does not need
  running first.
- **It asks three questions**: which way it does not apply, why in your own
  words, and how long the decision holds. The note is required, because it is
  the only place the reason will ever live.
- **Excused items leave the count.** A card reads "judged 3 of 9" with "2
  item(s) excused by a standing decision" beside it. An exception says the
  question is not about this part. It never says somebody looked.

An earlier bug is fixed with it: granting an exception on an item nobody had
answered yet did nothing at all until an unrelated save happened to run. It now
takes effect on the response.

The library health panel also reports automatic failures again - `fp.courtyard_grid`
on 76 footprints, `cmp.datasheet_text` on 47 components. Those went invisible
when automatic checks stopped being written into records.

Agents keep working. The API still accepts "na" and turns it into a pinned
exception, so an agent cannot record a blanket waiver over every future version
of a part - only a person can, in the review card. An agent's decision must now
carry a note.

Decision record
[0018](docs/decisions/0018-does-not-apply-is-an-exception-not-an-answer.md).

## 2026-09-14 — Excusing a check takes one button

A standing exception was already in the platform, but nothing said so. The only
way in was Verify... then N/A then "keep this decision?", and that chain sat
under three folds: the verification row, the checklist, and verify mode. A
failing check in front of you looked like something you could only fix or
ignore.

Now a failing row carries an **Excuse...** button. It asks three things - why,
a note, and how long the decision holds - and it needs no verify mode, because
an exception is not an answer and stages nothing.

Four smaller changes in the same place:

- A part with a failing check opens on that check. The row and its checklist
  are unfolded for you.
- Clicking the row LABEL opens it. Before, only the small triangle worked.
- Standing decisions list above the checklist, so one you grant can be found
  again. Each has its own **Revoke exception**.
- The card's own Revoke is now **Revoke verification**. Two identical red
  buttons a few pixels apart withdrew very different things.

A component can now pin an exception to its own fields - "while this
component's own data is unchanged". Its `$material_sha` is the symbol's and the
footprint's joined together, so the drawing scope said nothing about a Value or
a datasheet. The scope label reads what was actually pinned.

## 2026-09-14 — Automatic checks are worked out, not remembered

Change a check and the whole library re-reads itself. There is no "Re-run auto
checks" button and no "Apply to existing parts" button, because there is nothing
left to re-run: the automatic answers are computed when something asks for them,
and cached against a fingerprint of the checklist, the part and its exceptions.
Edit any of those and the fingerprint changes, so the next read works it out
again.

Measured: tightening the drill minimum from 0.3 mm to 0.45 mm reported 19
failing footprints across all 212 immediately — no republish, no backfill.
Publishing a check used to do the opposite: adding one moved 418 components to
"partial" in a single publish, and the only ways out were a mass republish or
answering them by hand.

Two smaller effects worth knowing. Completeness is now measured over the
judgment items only, so a machine check can never sit "unanswered". And "Mark
checked" no longer hides a failing automatic check — it vouches for the
judgment, not for what the code can still see.

Decision record
[0017](docs/decisions/0017-conformance-is-computed-not-recorded.md).

## 2026-09-14 — Warnings, and decisions that last

**A check now has a severity** — error, warning or ignore. A warning-level
failure is shown and counted but never makes a part read as failed, which is
what lets a new check ship at all: publishing one used to re-open the whole
library, and four checks were seeded *switched off* to avoid it. Those four are
now warnings, which is what "off" always meant. The severity is recorded on the
answer, so editing a checklist never rewrites what a past review meant.

`Ignore` replaces the old on/off switch: one control with three values instead
of a switch beside a severity.

**And a decision can be kept.** Answer a check N/A on the review card and it now
asks whether to keep it — for this drawing, or for this part always. A standing
exception outlives the version, so a pad move no longer takes it with it. The
part lists its exceptions with who granted each one, why, and what it is pinned
to; revoking one brings the check straight back.

This is the fix for something the numbers made plain: the library held **zero**
waivers, while agents had invented **188 different `custom:` check names**, 150
used exactly once. Nobody was refusing to record decisions — a waiver died with
the version, so nobody wrote one.

An exception scoped to the drawing dies the moment the copper moves, and one
pinned to a fact the part has not got is refused rather than being quietly
stale. Both halves are copied from KiCad's own DRC model, which has carried a
severity per rule and a list of excluded findings for years. Decision record
[0016](docs/decisions/0016-severity-and-standing-exceptions.md).

## 2026-09-14 — Checks you write instead of code

A check can now be **declarative**: pick a fact about the part, pick one
assertion, and the validator answers it. No new code per rule.

```
$symbol_reference   is one of    J
$symbol_pin_count   is at least  1        when $symbol_on_board ^true$
$footprint_pad_count is at least 2
```

Facts are the same vocabulary `when` reads — properties, `$category`,
`$base_symbol`, `$purchasable` — plus new ones derived from the drawings a
component pins: `$symbol_reference`, `$symbol_pin_count`, `$symbol_unit_count`,
`$symbol_on_board`, `$symbol_sim_link`, `$footprint_pad_count`,
`$footprint_has_model3d`. They are computed only when a check reads one, so a
checklist mentioning none costs nothing.

Assertions: is one of · matches · is exactly · is at least · is at most · is
present. Exactly one per check — the wording is written from it, so the sentence
a reviewer reads cannot disagree with the rule.

This is what makes symbol rules per component category possible: a symbol has no
category, but the component pinning it does, so the check lives on the
component. Trialled on Connectors: `$symbol_reference is one of J` found six
parts drawn as USB, CN, CN, BAT, BAT and FPC, and `$symbol_pin_count is at least
1`, narrowed to board parts, correctly passed over the seventeen off-board
terminal-block plugs instead of failing them.

## 2026-09-14 — One check, several variants

A check can now be stated more than once for one scope, as named **variants**:
`Transistors.NMOS` requires `Drain Source Voltage`, `Transistors.NPN` requires
`Collector-Emitter Voltage`, and both are `cmp.required_props`. That was the one
thing a `when` predicate alone could not do, and it is what
`conditional_required_properties` has been asking for since the original YAML
import.

The Scope column reads `Category.VARIANT`, so filtering `Scope` for
`Transistors.` gives you every sub-type rule at once.

**No ordering to remember.** A key with several variants must split on ONE field
with distinct values, plus at most one variant with no condition — the fallback.
At most one can match, so nothing depends on the order they are written in, and
a sorted table cannot contradict the effective rule. The save path refuses a
variant nothing can reach: a condition matching everything, a duplicate
condition, a second fallback, or a split across two fields.

A disabled variant falls through to the next one; disabling every variant is
what switches the check off. A category restating a key replaces its whole
group.

**And the fragility is now countable.** Open a varied check and it prints how
the live parts fall: `14 part(s) in scope · NMOS 7 · NPN 3 · other 4`. A
non-zero "no match" means the field you are splitting on is not reliable — which
is the honest signal that the category wants a subcategory instead of a
predicate.

## 2026-09-14 — Every check in one table

Reviews → Checklists is now a single `DataTable` of every check in the
platform — one row per scope and check, with a filter on every column. Filter
**Scope** to see what one category does differently, **Applies when** to find
the conditional ones, **Runs** for what is switched off; sort by **Key** and a
check lines up with every override of it, so `cmp.required_props` across
fifteen categories reads as fifteen adjacent rows.

A new check is added in the first row of the table: pick its scope, type its
key and what it asks, press Add. There is no separate form.

Rows are what a scope STATES, not the cross product — a category contributes
only what it changes, which is the same question answered from the other side.
Open a row to edit its settings, its `when` predicate, or a judgment check's
wording.

Publishing is per scope and the button says how many: a checklist version
belongs to one scope, so editing rows from three scopes publishes three
versions, and both the toolbar and the confirmation name them.

## 2026-09-14 — A check says which parts it is about

A checklist item can now carry a **`when` predicate**: "apply this check to
components where `comp_type` matches `^TVS$`", or `$category`, `$base_symbol`,
`$purchasable` — a bare name is a property, a `$` name is a structural fact the
API validates. Every condition must match. Edit it under the caret on any
check; a row that has one is badged `when`. Decision record
[0015](docs/decisions/0015-a-check-says-which-subjects-it-is-about.md).

This is what `conditional_required_properties` has been waiting for since the
original YAML import — it has sat in the Diodes and Transistors rule blocks
since the beginning with no check implementing it.

A check whose predicate a part does not satisfy is reported as **n/a here**, not
as switched off. Those are different statements — one says the check is not
about parts like this one, the other says the owner turned it off — and the
review card prints them separately.

One caution, recorded in the decision: a predicate over a PROPERTY is only as
stable as the property. A category is a row; `comp_type` is free text, and the
library already carries the `ZENNER` spelling the conventions skill flags. An
edit there silently stops the check running.

## 2026-09-14 — A check carries its own settings, and the rules table is gone

**Reviews → Checklists is one tab per kind now**, not one entry per checklist.
Components, Symbols, Footprints in the sidebar; the scope is a dropdown in the
header, with a dot against each category that already states something. A
category's list is created the first time you save one and removed when it
states nothing, so the sidebar cannot fill with empty lists.

**Every check is one row, folded.** Key, what it checks, where it comes from,
whether it runs — and the caret opens the rest: the thresholds, the property
lists, the patterns, the wording of a judgment check. Filter by Stated here /
Automatic / Judgment / Switched off, or search by key.

Every number, list and pattern the validator measures against now lives on the
checklist item of the check that uses it, under the sentence it produces.
Reviews → Checklists → any list, **Automatic checks**: the drill minimum sits
under "No drill hole below 0.3 mm", the courtyard width under its own check, and
a component's required properties under `cmp.required_props`. Decision record
[0014](docs/decisions/0014-a-check-carries-its-own-configuration.md).

**Fifteen per-category rule sets started working.** They were seeded from the
YAML libraries at the original import and **nothing had ever read them**, so
"a Capacitor carries Value and Voltage" had never been enforced on a single
part. Each one is now a category-scoped component checklist you can edit, and
the merge that was already there does the scoping. Measured over 439
components: **189 now have their property values checked where nothing checked
them before**; 13 fail the new `cmp.property_values` and 11 fail
`cmp.required_props` on rules their own category had always stated. Nothing
already recorded moved — a part picks the rules up on its next publish or its
next "Re-run auto checks".

**Two new checks, both per-category.** `cmp.property_values` applies a
category's value patterns. `cmp.base_symbol_allowed` is the first SYMBOL rule
scoped to a component category: a symbol carries no category, one base symbol
is shared across categories, and a symbol nothing uses yet has none at all — so
the check is answered on the COMPONENT, where the category is exact. List the
base symbols a category allows and a part pointing at the wrong one fails
mechanically instead of waiting for somebody to notice. Both are switched OFF
on the base list with an empty set, so no part gained an unanswered item; fill a
set in on a category to turn one on. (Dry run: allowing only `R` for Resistor
flags `NCP15XH103F03RC`, which is drawn as `Thermistor_NTC`.)

The `rules` table is dormant; a startup migration folded it into the
checklists and reports the keys nothing consumes rather than dropping them
(`conditional_required_properties` on Diodes and Transistors is the one real
rule still unimplemented).

Two fixes fell out of it. An empty manufacturer list now means the check does
not apply, which is what `Mechanical_7S` and `TestPoints` were saying — read as
"none of these is filled in" it failed all 14 of those parts. And a parameter
is refused on save unless it fits its type: a threshold above zero, a pattern
that compiles.

## 2026-09-13 — An automatic check is switched on or off, not typed out

The checklist editor no longer asks anybody to write down what an automatic
check does. `services/validator.py` now carries the catalogue — key, text and
hint for every check it answers — and the editor renders that catalogue
read-only with one switch per row. Saving rewrites a machine item's wording from
the code, so an automatic item can no longer describe a rule the validator does
not apply. Decision record
[0013](docs/decisions/0013-the-validator-owns-the-automatic-checks.md).

**A category checklist can now modify what it inherits.** It always merged on
top of the base list, but additively: it could add a check and reword one, and
it could never say "the base list asks for this and my parts have not got the
thing it asks about". The category editor now lists every inherited item with
three choices — inherit it, override its wording here, or switch it off for this
category. `Reviews → Checklists → New category checklist` creates one.

**Switching a check off turns it off, and the card says so.** The resolved
checklist is now the validator's switchboard: a switched-off key is not run into
the record, an answer it already had is dropped from the next record for that
subject, and the review card and the agent's `get_review_checklist` report it
under `switched_off` rather than leaving the question unexplained. Both kinds of
switch only reach COMPONENT checks per category — symbols and footprints have no
category, so their checks switch on their base list, for every part at once.

**Two new ways to re-run the automatic checks without publishing.** "Re-run auto
checks" on a review card does one subject; "Apply to existing parts" on a
checklist does every subject that list governs. Until now the validator ran only
inside a publish, so refreshing the machine answers meant publishing again —
which drops every agent answer the new version cannot carry. A re-run writes at
the machine tier only: it cannot overwrite a human or agent answer, and it
closes no queued review request.

Two automatic checks that were built but never seeded — `sym.sim_link` and
`cmp.sim_params` — now appear in the editor switched off, so the deferred
decision is one click away instead of invisible.

## 2026-09-13 — `LSM6DS3` redrawn to the house geometry

The symbol put VDDIO and VDD on the top edge and both GND pads on the bottom
edge, which §3 of `conventions-symbols` forbids on anything that is not one of
the §5.6 digital blocks. It was also the first symbol the new `sym.pin_length`
check failed. Published as v5; `LSM6DS3TR-C` was repointed automatically and
starts unreviewed.

No pin number, name, electrical type or count changed — only positions, stub
lengths and visibility. Five defects:

- **Supplies and grounds moved to the left edge**, supplies in the top two
  slots and GND 6 and 7 in the bottom two, so a ground symbol drops straight
  into them instead of turning back under the box.
- **Pins 10 and 11 were 3.81 mm stubs** against 2.54 mm on the other twelve.
- **Pins 10 and 11 also ended 3.81 mm INSIDE the body.** Their connection
  points sat at x = 12.7, which is the body outline itself, so the stub ran
  inward. §4 requires the tip to land on the outline.
- **GND 6 and 7 were a coincident stacked pair with neither hidden** — the
  open finding from v3. They are now two separate visible pins.
- **NC 10 and 11 were hidden.** They are not a stack, so nothing justified it,
  and a hidden `no_connect` pin cannot be given the X marker §2 requires.

Grouping follows the §3 right-side order and was checked against ST
DocID030071 Rev 3 Table 2 (p.20): host serial interface (CS, SCL, SDA,
SDO/SA0), then the sensor-hub master I²C that Table 2 gives as MSCL/MSDA
(SCX, SDX), then the interrupts. One blank slot between groups. Still one unit.

**The NC pads sit on the LEFT edge, above the grounds** (owner instruction).
They carry no net, so they cost nothing there, and moving them off the right
edge drops it from 13 slots to 10. Both edges now span the same height and the
body is 27.94 mm instead of 33.02 mm.

`CS` keeps the plain `line` pin style on purpose. The inverted-bubble rule is
scoped to §5.6 digital blocks, and Table 2 gives CS as an I²C/SPI **mode
select** (1 = I²C enabled, 0 = SPI), not a plain active-low strobe.

`Crystal_GND24_Small` (0.635 mm and 1.27 mm stubs) is the remaining
`sym.pin_length` failure and is untouched.

## 2026-09-13 — A dead pad is stacked, not drawn twice

Three hours after the section above was written, the library owner drew the part
a better way, and the rule it stated is reversed.

- **A straight-through routing pad is now STACKED hidden on the pin it faces.**
  The symbol draws one pin per channel, and the netlist carries BOTH pads on
  that channel's net, so pcbnew raises the ratsnest and DRC does not pass until
  the straight-through trace is drawn. The earlier rule drew the dead pads as
  separate visible pins and trusted the designer to remember the wire across the
  body. `conventions-symbols` v17 states the new rule in section 2.1.
- **`no_connect` on a stacked pin is worse than wrong, it is silent.** Measured
  on KiCad 10.0.5 with a netlist export: KiCad DROPS a hidden `no_connect` pin
  out of the stack, gives its pad a private `unconnected-…` net and warns
  `no_connect_connected`. A drawing that looks like it carries the signal
  across the package carries nothing. `free` carries the pad and stays quiet
  when a design leaves the pads open.
- **Small parts may hide a duplicate power pad again.** The "redundant GND/VDD
  pads are NOT stacked" rule was written for large ICs and was being enforced on
  four-pin parts. It now says what it meant: a symbol split into units never
  hides a power pin; a small part may, with a REASON written in the version
  comment and the `sym.stacked` note; and on the boundary the author asks the
  user, while a reviewer records `custom:stacked-power-pad` so the question
  reaches the Reviews queue.
- **The symbol is published and verified.** `TPD4E05U06` v6 carries the owner's
  drawing — four TVS glyphs on a common ground rail, the straight-through pads
  stacked hidden and typed `free`, GND pad 8 hidden on pad 3 — and every
  checklist item on it is answered. `TPD4E05U06DQAR` was verified against the
  section 6.6 table of SLVSBO7L Rev. L at the same time: `5.5V` stand-off,
  `6.5V` breakdown minimum and `10nA` leakage maximum all hold. Note for later
  passes, recorded on the part: the PROSE in section 7.3.5 contradicts that
  table, quoting 6 V and 5 V. The table is the authority.
- **Three corrections to the description templates**, `conventions-library`
  v33. The multi-channel ESD array row hard-coded "4-Channel" — right for the
  one part on the row, and a false channel count on the first 6-channel
  sibling; the count is now a literal written per part, the way the SMAJ row
  already treats the direction word, checked against the datasheet's pin table.
  The simple 2-pin TVS clamp row now says why it carries no direction word
  where the SMAJ row below calls that word mandatory: the row is scoped to the
  `D_TVS_Bi` symbol, so every part on it is bidirectional. And the Transistors
  alternation gained `PNP`, which it had never offered; no PNP part is in the
  library yet, so nothing was mis-described.
- **The synced KiCad library is a working copy.** A symbol drawn in the PCM
  package on disk is replaced by the next **Sync 7Sigma Library**, and nothing
  said so. [docs/reference/kicad-integration.md](docs/reference/kicad-integration.md)
  now does.
- **"A cathode bar is never a C" is a footprint rule.** It lives in a
  validator-enforced section with no domain stated, and a symbol's zener glyph
  is a C on purpose. `conventions-footprints` v36 says which layer it governs.
- **Cite an artifact, not a memory.** The skill had named `TPD4E05U06` as the
  precedent for a stacked `NC` pad; a pass that could not find the stack in any
  published version struck it out as fiction. The platform drawing had never
  carried it and the intent had. A precedent now has to name the symbol AND the
  version it was checked against.

## 2026-09-13 — Pin stub length follows the pin NUMBER, not the pin count

`USB_C_Receptacle_USB2.0_16P` kept failing its `sym.geometry` check. It is a
verbatim stock KiCad `Connector:` drawing with 5.08 mm pin stubs, and the
`conventions-symbols` rule said 2.54 mm with one exception, "very high pin
count", recorded against `STM32H573IITxQ` (176 pins). A 17-pin connector did
not qualify, so every verification pass flagged a symbol that was correct.

The rule was keyed on the wrong thing. KiCad draws the pin NUMBER along the
stub, so the stub is the space the number has. Measured with
`kicad-cli sym export svg`, which reports each string's plotted width, at the
1.27 mm house font:

| Pin number | Width | Against a 2.54 mm stub |
|---|---|---|
| `A` | 1.29 mm | fits |
| `B1` | 2.68 mm | 0.14 mm over — accepted |
| `A12` | 3.71 mm | 1.17 mm over — prints into the body |

A survey of all 198 base symbols confirmed pin count was never the driver: 58
carry a length other than 2.54 mm, including `XC6206PxxxMR` (3 pins) and
`LD1117S` (4 pins) at 5.08 mm, and every `Conn_*` symbol at 3.81 mm.

- **`conventions-symbols` v16** replaces the pin-count exception with a
  pin-number-width one: 2.54 mm by default, 5.08 mm when any pin number runs
  to three or more characters — alphanumeric connector designators (`A12`,
  `B12`), BGA coordinates, three-digit numbers. `USB_C_Receptacle_USB2.0_16P`
  is now correct as drawn and no longer needs a geometry finding.
- **New machine check `sym.pin_length`**: every pin in a symbol uses the same
  stub length. The absolute value stays a judgment call on `sym.geometry`,
  where the new three-character rule is now a hint; mixing lengths inside one
  drawing is purely mechanical, and it is what actually goes wrong. Across the
  library it finds two: `LSM6DS3` (2.54 mm on 12 pins, 3.81 mm on 2) and
  `Crystal_GND24_Small` (0.635 mm and 1.27 mm). Neither is changed here.
- **The `sym.pins_grid` check was reading past pins.** Both symbol checks now
  split the source into pin blocks instead of matching `(at …)` straight after
  the `(pin …)` header. The child tokens are not in a fixed order — `LAN8671`
  carries `(hide yes)` before `(at …)`, and that pin was skipped silently, so
  an off-grid hidden pin could have passed. The block scanner is also anchored
  to the start of a line, because `A_S-1WR3` has the text "5-pin SIP (pin 3
  absent)" in its Description and the old shape matched it.

`sym.pin_length` is seeded for new installations. Adding it to the live base
checklist is a manual step in the Skills → Checklists view, and it un-answers
the item on every existing symbol with no backfill, exactly as
`cmp.datasheet_text` did on 2026-08-25.

## 2026-09-13 — A straight-through routing pad is not a `no_connect`

`TPD4E05U06` reported an ERC error as soon as the schematic wired its right-hand
pads. TI builds the TPD family for flow-through routing: pads 6, 7, 9 and 10 of
the DQA package carry no internal connection and sit directly opposite the pin
whose trace they continue, so the board runs one straight trace onto the signal
pad and off the dead pad facing it (1-10, 2-9, 4-7, 5-6). The datasheet says so
in the description column of the pin table, not in the `NC` name alone —
"Not connected; Used for optional straight-through routing. Can be left floating
or grounded" (SLVSBO7L Rev. L p.5) — and draws it in the layout example on p.16.

- **The four pads are now electrical type `free`, not `no_connect`.**
  `no_connect` tells KiCad the pad must never be connected, so the designer's
  pass-through wire raises `no_connect_connected`. Measured on KiCad 10.0.5:
  `no_connect` errors when a wire lands on it, `passive` errors with
  `pin_not_connected` when the design leaves the pads open, and `free` is clean
  both ways. The pass-through is optional per design, so both cases happen and
  `free` is the only correct type. Pin numbers, names, positions and count are
  unchanged. The symbol now verifies `checked` on every item.
- **The rule is written up as `conventions-symbols` v15, section 2.1.** The
  same reading applies to the rest of the TPD family and to any package a
  datasheet calls flow-through. **Superseded the same day** — v15 asked for the
  dead pads to be drawn as separate visible pins, and v17 stacks them instead;
  see the section above.
- **The pin-1 circle came off the symbol.** A symbol carries no pin-1 marker
  since the house rule of 2026-09-13. Pin 1 is named by its printed number, and
  the orientation marker is a footprint job.

## 2026-09-13 — The SMAJ TVS family reads one way

Verifying `SMAJ28A` turned up four things the family had been carrying, none
of them a defect in the part in front of us.

- **Four SMAJ parts printed a part number where the rule asks for a rating.**
  `Value` plus the reference designator is the only part identity printed next
  to a symbol on a schematic sheet, and the house rule sends a TVS to its
  reverse stand-off voltage. `SMAJ28A` had been moved to `28V` on 2026-09-13;
  `SMAJ12A`, `SMAJ24A`, `SMAJ24CA` and `SMAJ28CA` still read as their MPN.
  They now read `12V`, `24V`, `24V` and `28V`. The MPN is untouched on
  `Manufacturer Part Number 1`, which is what the BOM draws from.
  **`SMAJ24CA` is fitted on CE_Aqua_V2 at D12, D13 and D19**, so those three
  refs will print `24V` after the next library sync. Same symbol, same land,
  same netlist, same part ordered.
- **Two TVS base symbols offered through-hole footprints.** `SMAJxxA` and
  `D_TVS_Bi` both carried `ki_fp_filters "TO-???* *_Diode_* *SingleDiode* D_*"`
  on twelve components that are surface-mount without exception. The filter is
  what narrows the footprint chooser, so naming a package the part is not made
  in turns the one control meant to prevent a wrong land into a source of them.
  Both now read `D_*`, which covers every land actually in use — `D_SMA`,
  `D_SOD-123FL`, `D_SOD-323`, `D_0402_1005Metric` — and every stock KiCad
  diode footprint. No pin, graphic or geometry change, so every verification
  carried.
- **`SMAJ12A` simulated a clamp 21% above the part's guaranteed maximum.** Its
  `Sim.Params` carried `RS=0.5`, where the datasheet clamping point (19.9 V at
  20.1 A, breakdown 14.0 V) gives 0.29 Ω — so the model clamped at 24.05 V
  against a guaranteed 19.9 V. `RS=0.3` now puts it at 20.03 V, 0.7% high, and
  back in line with how its siblings were derived (`SMAJ24A` derives 1.05 and
  stores 1.2; `SMAJ28A` derives 1.44 and stores 1.5 — round up, so the model
  errs pessimistic). `CJ` is deliberately untouched on all three: the SMAJ
  datasheet states no junction capacitance, so there is nothing to check the
  existing estimate against and a replacement would be a guess.
- **Both TVS symbols are now findable by what they do.** `D_TVS_Bi` still
  carried `ki_keywords "diode TVS thyrector"` — no unabbreviated
  "transient voltage suppressor", no direction, and no "ESD" or "clamp" even
  though five of its seven components are ESD protection diodes. It now reads
  `diode TVS transient voltage suppressor bidirectional bipolar ESD clamp
  thyrector`, matching the widening `SMAJxxA` got in 2026-08. Direction is the
  word that most needs indexing here: the library holds both kinds on lookalike
  SMAJ part numbers.

`conventions-library` v31 records the direction word as part of the SMAJ
`ki_description` template — all five parts had carried `Unidirectional` /
`Bidirectional` since 2026-08, but the skill's table still showed the row
without it, so the next standardization pass would have stripped it back out.
It also closes the `Value` question with the reason it went unfixed for so
long: a family-wide deviation defends itself, because when every sibling is
wrong the same way, consistency reads as evidence.

## 2026-09-13 — A flagged machine item can be answered

An `auto` checklist item that an agent flagged as wrong rendered read-only in
the verification card. There was no way to accept it, waive it or re-check it
by hand, so the finding sat on the part for ever.

- **The Checked / N/A / Flag buttons now appear on any machine item that
  carries a finding**, `failed` or `flagged`. Before, the card offered them on
  `failed` alone. A machine item that PASSED still offers none — the validator
  owns those.
- **`cmp.datasheet_text` is the item this shows up on.** An agent flags it when
  the archived PDF is only partly searchable, which is a judgement a person has
  to close, not a rule the validator can re-run.
- **Nothing changed in the API.** A human answer has always outranked an
  agent's on any key, and the answer it replaces is still kept as `superseded`,
  so accepting a flag does not erase the description of what was found.
- **A machine item nobody has answered yet is still read-only.** Backfilling
  one still needs the API.
- **The lifecycle pill is drawn the same size as the pills beside it.** It sat
  in a button row, which stretched it to the height of the select next to it
  and pushed the pair out of line. The component detail header also wraps now
  instead of letting a long part number push the pills on top of each other.

## 2026-09-13 — The nano-SIM socket is drawn the size it really is

`7Sigma:nanoSIM_ShouHan_TL6P-H1.35` published an outline of 11.18 x 12.82 mm
for a part that measures 11.00 x 12.30, sitting 0.06 mm off centre. Version 7
redraws it. No copper moved.

- **`F.Fab` and `F.SilkS` now trace the part.** Body 10.0 x 10.4 mm with the
  top-left corner chamfered, four corner legs out to y +/-6.15, two shell tabs
  out to x +/-5.5. The silk used to stand visibly outside the connector in a
  3D render; it no longer does.
- **Two sources agree on the size to a hundredth of a millimetre.** The STEP
  model's own vertices, and the vendor drawing measured at 600 dpi with the
  scale taken from the two mounting-hole centres. The old outline's own commit
  message quoted 11.0 x 12.3 and then published 11.18 x 12.82.
- **The courtyard is symmetric again**, x +/-6.1 by y +/-6.9, and never larger
  than before in any direction, so it cannot raise a new clearance violation on
  a board already laid out.
- **The `F.Fab` pin-1 circle moved inside the outline**, from (2.5, 6.0) to
  (2.5, 4.9).
- **Boards keep their own copy until they are updated from the schematic.**
  CE_Dongle_V3 carries this part; nothing breaks, and the board shows the old
  silkscreen until its owner refreshes it.
- **The land pattern was verified, not changed.** Pad sizes match the drawing
  exactly; every pad and hole position is within 0.10 mm of it, which is the
  0.1 mm grid the house convention asks for. The part's own leads sit inside
  their pads with at least 0.16 mm to spare.
- **`conventions-footprints` v35 drops this footprint from its origin-offset
  list.** The +0.060 recorded there was the centre of the wrong outline, not
  the centre of the part.

## 2026-09-13 — A footprint preview looks like the footprint editor

The pad numbers landed earlier today on a plot: every layer visible, mask and
paste washing the copper mauve, and the numbers in whatever colour was spare.
A preview is meant to be recognisable as the thing KiCad shows, so the render
now matches the footprint editor's own palette and layer visibility.

- **Mask, paste and adhesive are no longer drawn.** They are translucent
  washes over the copper and they turned KiCad's red pads into mauve ones.
  The visible set is the editor's default, passed to `kicad-cli --layers`.
- **Pad numbers are white, holes are the editor's cyan, and the canvas is the
  board background.** A footprint preview now sits on navy, not on the
  schematic grey a symbol uses.
- **Both renderers are told the same thing.** The layer list is decided by the
  api and travels in the render request, so the container obeys and decides
  nothing.
- **`footprint_theme` is `Skyline-7S` instead of empty.** With no theme named,
  kicad-cli falls back to "footprint editor settings" — whatever KiCad config
  the renderer happens to carry — and the hole colour really did differ
  between a developer's Mac and the server.
- **Editing a theme file now re-renders.** The preview cache keyed on the
  theme's NAME, so a colour change left every cached picture showing the old
  palette with no way to ask for a new one. The key carries a digest of the
  theme file.
- **Trap worth knowing: KiCad discards a pure-white layer colour.** A layer
  set to `rgb(255,255,255)` plots in a fallback grey instead. The label layer
  is `rgb(254,254,254)`.

`services/pad_labels.py` is now `services/preview_style.py`: it owns the pad
numbers, the layer list and the re-stacking together.

## 2026-09-13 — A footprint preview prints its pad numbers

Every 2D footprint preview — the footprint page, the component page, the
paste box, both panes of a geometry diff — now carries the pad number on each
pad, the way KiCad's own footprint editor draws it. Reading a pinout off a
preview no longer means counting pins from the pin-1 mark.

- **The numbers are drawn, not guessed.** `kicad-cli` plots no pad numbers, so
  the render path writes one `fp_text` per pad into a COPY of the source and
  renders that. Nothing is stored: the `.kicad_mod` in the mirror, the file
  KiCad downloads and the version history are untouched. A preview is
  therefore no longer a byte-faithful plot of the stored source — read
  `api/app/services/pad_labels.py` before comparing one against it.
- **One number per land.** An exposed pad and its thermal vias share a number
  and are labelled once. Two numbers on one land (USB-C A1/B12) are spread
  along the pad rather than written over each other.
- **Through-hole numbers sit on top of the hole.** KiCad plots drill holes
  last, over everything, so the finished SVG is re-stacked to put the labels
  above them.
- **Existing previews re-render once.** The cache key includes the labels, so
  the first view of each footprint after the update costs one kicad-cli run.

## 2026-09-13 — A footprint or a base symbol can be renamed

Until now a name chosen wrongly was permanent. There was no rename, and
delete-and-recreate was refused while any component version referenced the row
— and would have discarded the version history, the review record and the
production sign-off anyway.

- **Rename moves the name AND every reference to it, in one transaction.** One
  new geometry version carrying the new name, one republished component
  version per component that references it, the `.kicad_mod` moved in the
  mirror, and the stale entries in `categories.defaults` rewritten. On the
  footprint page, under "Rename this footprint"; as the agent tools
  `rename_footprint` and `rename_base_symbol`; over HTTP as
  `POST /api/{footprints,symbols}/{id}/rename`.
- **A rename costs no verification and no sign-off.** The land pattern, the pin
  map, the pinned geometry and the part are unchanged, so both carry. The
  `Footprint` property and `base_component` stay material for every other kind
  of edit — the exemption is a mapping on the one pair being renamed, and it
  has one caller.
- **History keeps the old name.** Superseded versions are immutable and go on
  saying what they published under.
- **A board already laid out keeps the old library id** until its owner updates
  the project from the schematic. The geometry lives in the board file, so
  nothing breaks, but KiCad reports the old id as missing until then.
- **`L_Changjiang_FTC404030S` is now `L_CJIANG_FTC404030S`.** `CJIANG` is the
  canonical manufacturer name decided on 2026-09-13. The old name was also a
  KiCad **stock** filename while our land is not the stock land — stock pads sit
  at ±1.35 mm and ours at ±1.4 mm — so it claimed a Tier 0 identity the copper
  does not support. Affects `CE_Dongle_V3` (L4, L5) and `EVSE_20_CTRL` (L8, L9)
  at their next update from the schematic.
- Reasoning, and the three rejected alternatives:
  [docs/decisions/0012](docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md).

## 2026-09-13 — A cathode bar is one straight line, and the validator decides its width

- **The 0.2 mm polarity mark is no longer an accepted FAILURE.** It was a rule
  an agent had to remember, and one had already broken it by narrowing
  `D_SOD-123FL`'s bar. `fp.silk_width` now passes exactly **one** `F.SilkS` line
  at 0.2 mm and fails the rest, so a footprint drawn wholly at 0.2 mm is still
  caught. Both 0.1 mm and 0.2 mm are legal for the mark itself.
- **A cathode bar is a single straight line** — never a C-shaped bracket — with
  both endpoints on the 0.1 mm grid, on or within the courtyard, and at least
  0.1 mm clear of pad copper. Its stroke may overhang the courtyard outline,
  which is thinner; only the line's position matters.
- **Nine footprints corrected.** `D_0402`, `LED_0402`, `LED_0603` and
  `LED_Silverlight_M3535N1` were C-shaped, and the Silverlight bar was two
  overlapping segments. `D_SOD-323` sat off-grid at x = −1.61. `D_SOD-323`,
  `D_SOD-123FL`, `LED_OSRAM_SFH4725AS` and `LED_Silverlight` had bars hanging
  outside the courtyard. `D_0402` and `LED_0402` had endpoints at y = ±0.45.
  Widths were left as drawn.

## 2026-09-13 — Verifying a land: JLC beats a dimension read off a drawing

- **`conventions-footprints` §1 now covers CHECKING a footprint, not only
  creating one.** A pass read "0.60 x 1.40" off a scanned XKB drawing and
  changed `USB_C_Receptacle_XKB`'s rear shield slot to a 1.4 mm drill. The JLC
  land for the same LCSC code uses 1.2999974 — what the footprint already had.
  Reverted. One `easyeda2kicad --lcsc_id=` call answers the whole question, and
  when a scan and JLC disagree, JLC wins.
- **The origin follows the vendor land, not the body centre**, for a connector
  or switch whose body overhangs its pads. Six footprints on this BOM anchor
  that way, from −4.495 mm on the RJ45 to +0.060 mm on the nanoSIM. The
  `fp.origin` checklist item still says "centred on the body" and is what made a
  pass flag a correct footprint.
- **The platform copy and the installed copy use different variables.**
  `${SEVENSIGMA_DIR}/3DModels/…` on the platform is rewritten at PCM package
  time to `${KICAD10_3RD_PARTY}/3dmodels/com_sevensigma_models3d/…`. Converting
  between them is expected in both directions — it is not KiCad corrupting the
  path on save.
- **`CJIANG` is the canonical manufacturer**, added to the table in
  `conventions-library`. `L_Changjiang_FTC404030S` was renamed in place to
  `L_CJIANG_FTC404030S`, carrying its verification across.
- **Accepted deviations recorded rather than "corrected":** the SOT-23 family's
  1.00 mm pitch, the `Crystal_SMD_3225` pads at y = ±0.90, the house chip lands
  under Tier 0 names, and `TS24CA`'s contact placement — all deliberate, all
  now carrying the numbers that prove a later pass does not need to re-derive
  them.

## 2026-09-13 — Every footprint on CE_Dongle_V3 is verified, and a 3D model can finally be measured

All 38 distinct footprints on the CE_Dongle_V3 BOM were checked against their
documentation. Twenty had never been verified at all. Machine-item failures on
that BOM went from nine to zero.

- **`fp.model_fit` is no longer unverifiable.** Every pass before today recorded
  it `skipped`, for want of a tool. `scripts/model-bbox.py` measures a STEP
  model from its own coordinates, and `scripts/footprint-render.py` renders a
  footprint in 3D with `kicad-cli` so a model can be judged by eye. Both are
  now required by `conventions-footprints` v31.
- **Measure vertices, not every point.** A bounding box over every
  `CARTESIAN_POINT` is invalid: a STEP `LINE` carries a reference point that can
  sit far out along its own infinite line. That error produced four false model
  defects in this sweep — a −3578 mm enclosure, an 80 % oversize switch, a 58 mm
  RJ45 and a lightpipe said to have no clearance. All four were withdrawn.
- **Thermal vias were eating their exposed pads.** `VQFN-40` (ESP32-C6) had
  0.00 mm of EP copper outside the via ring, against the 0.2 mm minimum;
  `QFN-16`, both `QFN-56` variants and `QFN-68` were 0.05 mm or less. Cause: the
  via was enlarged to the house 0.6 mm on a 0.3 mm drill while keeping the via
  centres KiCad stock drew for its smaller 0.5/0.2 vias. Rings pulled inward;
  `VQFN-40` also gained the back-side `B.Cu` land that stock carries.
- **Mechanical pads no longer carry pin numbers.** The support tabs on
  `SW_Push…TS24CA` and the steel bracket feet on `SW_Push…TC-6615` are now named
  `MP` instead of `3` and `4`. The bracket numbering is what made SW2 on
  CE_Dongle_V3 electrically dead. No net changes on any existing board.
- **`RJ45_RCH_RC01812`'s model** sat 4.1 mm inside the board. Z offset set to 0.
- **The SOT-23 1.00 mm pitch is a decided house choice**, not the defect three
  separate passes filed it as. Recorded in `conventions-footprints` v31.
- **Section 8 of the footprint conventions was wrong.** It told agents to omit
  `F.CrtYd` on non-electrical parts, relying on a
  `footprint_style.exempt_base_components` list that does not exist in the code.
  `validate_footprint` fails `fp.courtyard_present` unconditionally and never
  reads the rule block. Two agents followed the old text and published
  footprints that failed validation. Corrected in v29.
- **The validator had never run on most of these footprints.** Their versions
  predate the 2026-08-24 validation subsystem, so their twelve machine items
  read as unanswered, which is easy to mistake for passed. Backfilled by
  republishing identical drawings with `force`. Library-wide, 89 of 213
  footprints would fail a machine item today; 76 of those on
  `fp.courtyard_grid`.

## 2026-09-13 — A verification has four answers, and "skipped" is not one

- **`skipped` is retired** (decision
  [0011](docs/decisions/0011-retire-the-skipped-verification-result.md)). It
  meant "this item applies, but I could not verify it". Everybody read it as
  "does not apply" — the job `na` already does — so agents used it to mean "I
  did not re-open the datasheet on this pass", even on items a previous pass had
  verified and that had not changed since.
- **An item nobody can verify is now LEFT UNANSWERED**, which produces the same
  `partial` state `skipped` always did. The verification vocabulary is
  `checked` | `na` | `failed` | `flagged`.
- **What it was costing:** 138 stored skips, every single one carrying reason
  `unstated` because the agent tool never had a reason argument; 45 subjects
  held at `partial` by one; **38 of those with nothing else open**. Most notes
  said only that a datasheet was out of scope for that pass, and several added
  that a prior datasheet-backed check had already confirmed the item.
- **`na` now requires a reason code** — `feature_absent`, `kind_exempt`,
  `waived` or `other` — from an agent or a human. `na` is the answer that closes
  an item, so it is the one that has to justify itself. The machine tier is
  exempt: the validator answers `na` in a dozen places ("no SMD pads", "no
  vias") with a note and no code.
- **Nothing was migrated and no subject changed state.** Stored `skipped` rows
  keep the value, are read as unanswered, and are reported separately on the
  health panel as "Left over from the retired skipped answer", so the open work
  stays visible instead of disappearing.
- The review card drops its Skip button; the health panel's "why items are
  skipped" becomes "why items do not apply".

## 2026-09-13 — A symbol shows every unit, one at a time

- **A multi-unit symbol drew only its first unit, everywhere.** A dual op-amp
  looked like a single one and a 10-bank STM32 showed one bank, on the
  component page, the template page, the review workbench, the change feed and
  the paste box. `kicad-cli sym export svg` plots ONE FILE PER UNIT and has no
  switch to write one file, and every preview took the first of those files.
- **Every symbol preview now carries a ‹ A · 1/10 › pager.** The renderer takes
  `?unit=N` and answers with an `X-Unit-Count` header; one control, shared by
  the preview and the before/after diff panes, reads it. The letter is KiCad's
  own — unit 1 is A, the suffix it prints after the reference as `U7A`.
- **The paste box pages too**, by re-rendering the unsaved text. A `blob:` URL
  carries no headers, so there is nothing else it could read the count from.
- **A single-unit symbol and every footprint are untouched**, URL included:
  `?unit=` is only added past the first unit, so their renders keep their place
  in the browser cache and the server's `immutable` promise.
- **Previews were answering 401 on a dev server.** Only `request()` in `api.ts`
  asked for the session cookie, so the big preview's own `fetch` — and the
  thumbnails, and the paste-box render, and the STEP/IGES viewer — were sent
  cross-origin without it and refused by the default-deny gate. The deployed
  app is same-origin and never showed this.
- **The geometry review workbench drew nothing at all.** Its preview pane sat
  directly in a flex COLUMN, where `.preview-fill`'s `flex: 1` (basis 0) beat
  the `height: 420px` beside it, so the box collapsed to its own 10px of
  padding and border. A symbol or footprint review had no drawing to review.

## 2026-09-13 — Counts stop stacking one digit per line

- **Library health reads again.** Every three-digit count on Reviews → Library
  health wrapped vertically — `162` came out as `1`, `6`, `2` on three lines.
  The cards sit in a `.field-grid`, whose tracks are 200px wide at their
  narrowest, and `dl.kv` pinned its label column at a fixed 150px. That left
  the value column about one character wide, and `overflow-wrap: break-word`
  on `.kv dd` did the rest.
- **The label track gives way now, the value track does not.** `dl.kv` is
  `minmax(0, 150px) minmax(min-content, 1fr)`, so the label shrinks first and a
  number keeps its width. Long prose values still wrap, because `break-word`
  keeps their min-content small. `.num` is `white-space: nowrap` as well — a
  number is one token and must never break.

## 2026-09-13 — A gain gets its prefixes too

- **An op-amp's open-loop gain reads and writes `100k`, `1M`, `10M`.** It has
  no unit, so nothing is printed after the prefix and there is no space before
  it — the way a gain is written on a datasheet. Its form allows 1e2 to 1e7 and
  its own default was already the string `100k`, which nothing parsed.
- **The rule is the form's own, not a list of field names.** A unitless value
  gets prefixes when its scale is LOGARITHMIC, because a form asks for a log
  slider exactly when its value spans decades. Anything linear stays a plain
  box: a dielectric constant of 4.3, an emission coefficient of 1.9, a
  threshold at 0.5 of the rail, twenty points per decade. A future parameter
  opts in by declaring `scale="log"` with no unit, with no frontend edit.
- **Loss tangent is deliberately left alone.** `0.002` could print as `2m`, but
  every fab and every datasheet publishes `Df = 0.02`. The same reasoning keeps
  RKM notation off length fields: a box should not fight the convention the
  number is copied from.

## 2026-09-13 — The simulator's numbers carry their units

- **Capacitance, inductance, voltage, current and time are unit-aware fields
  now.** Every ngspice parameter used to be a plain box with its unit printed
  beside it in grey. A diode's saturation current defaults to `2.5n` and its
  form allows down to 1e-18; a capacitance goes to 1e-15 and a PULSE edge to
  1e-12. Typing those as decimals is the defect the length field was built to
  stop. Nine quantities exist in `si.ts` now, up from four.
- **Three places changed, and no form definition did.**
  `sch_lib.PARAM_FORMS`, `sim_scenario.ANALYSIS_FORMS` and `LiveControl`
  already declared a unit per field, so the part inspector, the run bar and the
  live knobs are driven from what the server already sends. A new parameter
  becomes unit-aware with no frontend edit.
- **ngspice spells mega `MEG`, and a field that ignored that would be wrong by
  a factor of a billion.** To ngspice, `M` is MILLI. Our boxes read `M` as
  mega, because that is what a schematic means and what the resistance box
  beside them already did (user decision). So the two directions use different
  tables: what is already stored is read with ngspice's rule, and what we write
  back always spells mega `MEG`. Verified end to end — typing `1M` into a
  resistor puts `1MEG` in the downloaded `.kicad_sch`.
- **A field with no unit stays a plain box.** An op-amp's open-loop gain is
  `V/V`, an inverter's threshold is `x rail`, a sweep is a point count. A
  prefix on a dimensionless number is nonsense, so `quantityForUnit` returns
  nothing for them and the old control renders.
- **Audited every input in the app first**: 379 controls across 73 files, 228
  of them value fields. The simulator was the whole gap. Copper weight is
  deliberately untouched — it is a preset list mapping an ounce label to
  millimetres, not a typed value — and no temperature or mass input exists.

## 2026-09-12 — The agent instructions moved next to the code they govern

- **`api/CLAUDE.md` was 2764 lines and `web/CLAUDE.md` was 1688.** A `CLAUDE.md`
  in a subdirectory is read when an agent opens a file in that directory, so
  every backend task paid for the frontend rules and every frontend task paid
  for the whole backend. Two files carried the rules for about 70 services, 17
  routers, the simulator, the field solver, the flasher and the sync plugin.
- **There are 17 `CLAUDE.md` files now, and the largest is 510 lines.** Each one
  holds what applies to its own directory: `api/app/services/`,
  `api/app/routers/`, `api/app/services/fieldsolver|flasher|pcm_plugin/`,
  `mcp/`, `web/src/components/`, `web/src/pages/`, `web/src/sim/` and its three
  sub-directories. The root file merged its layout and
  routing tables into one that sends a task to the right file.
- **Long-form topics moved to [docs/reference/](docs/reference/)** — datasheets,
  production economics, the review axis, the projects module, SPICE runs,
  simulation models, PCM packaging, KiCad integration, deployment, the Jaravis
  implementation and two past simulator audits. The nearest `CLAUDE.md` links to
  each page, so a rule is written once and read where it applies.
- **The rules that keep this working are written down and checked.**
  [docs/reference/writing-instruction-files.md](docs/reference/writing-instruction-files.md)
  states the six: a 200-line budget per file, the derivability test, link never
  summarise, put a rule in the narrowest file that covers it, never use `@path`
  imports (they load at launch and defeat the split), and state the current fact
  with no narration of what the file used to say. `scripts/check-docs.py`
  enforces the three a machine can decide — line budget, broken relative links,
  and `@path` imports — and reports 0 errors today.
- **No rule was dropped.** Every line of the three original files is either in a
  new file or is a heading level, a table row or a cross-reference that the move
  itself changed. A link check over all 29 files reports no broken relative
  link.

## 2026-09-12 — The programming log paid for an index nobody used

- **`programming_logs` carried two indexes of 52 MB and only ever read one.**
  The table holds 2,444,307 rows across 6321 runs, the largest row count in the
  database, and it only grows because every line of every run is kept on
  purpose. It had a surrogate `id` primary key beside a unique constraint on
  `(run_id, seq)`. `pg_stat_user_indexes` reported **zero scans, ever**, on the
  `id` index: nothing addresses a log line by anything but its run and its
  sequence, no foreign key pointed at it, and the writer never supplied one.
- **`(run_id, seq)` is the primary key now**, and the table went from 375 MB to
  304 MB — 53 MB of index and 18 MB of row overhead. Nothing was deleted: the
  row count and the run count are unchanged.
- **A startup migration applies it once**, guarded by the presence of the `id`
  column, and reports itself at `GET /api/health/schema` as
  `programming_logs.pk`. It ends in a `VACUUM FULL`, because `DROP COLUMN` only
  marks a column dead in Postgres and the bytes stay until the table is
  rewritten. Measured on the full 2.44 M rows: 0.54 s of DDL and 1.7 s of
  rewrite, which is why it runs at startup rather than in the background.

## 2026-09-12 — The git mirror is the source archive

- **Ingest no longer stores a `source.tar.gz` per snapshot.** It wrote one for
  every commit and nothing ever read it back. The key appeared twice in the
  whole codebase: the write, and a line in a docstring.
- **The mirrors already held the same content, four times smaller.** Measured on
  the server: 16 stored tarballs came to about 950 MB, which was 68% of the
  bucket, while the bare mirrors that hold EVERY commit of EVERY project come to
  214 MB. One project shows the shape of it — 117 MB of mirror against 533 MB of
  tarballs for 8 commits.
- **The first start after this deploy removes the stored tarballs**, in the
  background and behind the marker `maintenance/snapshot-archives-dropped.v1`,
  the same way the schematic render purge works. The bucket should fall to about
  450 MB.
- **`gitrepo.archive_tgz` rebuilds any tree on demand** from the local mirror,
  with no network call. It is now the only way back to a byte-exact tree.
- **`DATA_DIR/git` must be in the backup set.** After the purge the mirror and
  the upstream remote are the only copies of project source. See
  [decision 0009](docs/decisions/0009-the-git-mirror-is-the-source-archive.md).

## 2026-09-12 — One control, one unit rule, and a tooltip that stays on screen

- **Three input designs became one.** Only `.text` ever declared a border,
  background and focus ring; `.row-input` was used bare 83 times and fell through
  to the browser's NATIVE widget, so the Admin page, the table filters and the
  field solver rendered three different-looking forms. One rule now draws every
  text control, and the size classes carry size only — three heights, 34 / 26 /
  22 px, and nothing else varies.
- **Every unit now prints the same way**: the prefix that puts 1-999 before the
  decimal point, at most three decimals. `0.05 Ω` reads `50 mΩ`, `1 560 432 Ω`
  reads `1.56 MΩ` with a warm ⓘ carrying the exact value. Impedance and
  percentage joined length and frequency, so Target Z and tolerance are the same
  control as design frequency. On a resistance `10M` is megohms and `10m` is
  milliohms.
  - Length changed with it: prepreg 3313 now reads `99.4 um` rather than
    `0.0994 mm`. One rule everywhere was judged worth more than matching a
    single datasheet's spelling.
- **`2.4e9` never parsed**, in any unit field, despite the frequency field's own
  help text advertising it — the exponent was read as a unit suffix.
- **The ⓘ moved inside the box, and its tooltip stays on screen.** Beside the
  box the marker took 18 px of the field's width and cut `500 um` to `500 u`;
  the tip itself was anchored `right: 0` and ran off the LEFT edge of the window
  on every field in the solver, measured at x = −132.
- **`4k7` now parses.** RKM notation — the prefix standing in for the decimal
  point — is how values are printed on parts and in schematic Value fields, so
  `4k7`, `4R7`, `1M5` and `2G4` all read correctly. Enabled for impedance and
  frequency only: a length is based on mm, so `1m5` there would mean 1.5 metres
  in a box expecting a fraction of one.
- **Rounding could break its own rule.** 999 999 999 Hz sits below 1 GHz, so it
  was printed in MHz, rounded to three decimals, and came out as `1000 MHz` —
  four digits before the point, which is the one thing the prefix ladder exists
  to prevent. The prefix is now re-picked AFTER rounding: it reads `1 GHz`.
- **Field solver**: coplanar is a segmented Off/On beside Signal rather than a
  checkbox, target Z, tolerance and design frequency share one row (the property
  panel widened to fit the widest legitimate value, `999.999 kHz` at 121 px,
  three across), the structure
  box lost its redundant `mm` column, and the cross-section view is remembered
  PER PROFILE — it used to reuse the previous profile's zoom and centre, which
  "lock view" then made permanent.
- **Stock's held parts are grouped by component**: 120 project-rows became 46
  part-rows, folded to 15, with the boards and reference designators behind each
  row grouped by project.
- **Library health folds its long lists** to two rows plus a count.
- **Admin**: the display currency is a dropdown of the currencies that actually
  have an exchange rate, and its fields fill their column instead of sitting at
  the browser's default 176 px with the placeholder cut off.

## 2026-09-12 — One way to label a field, and Setup becomes Admin

- **Setup is now Admin, and it is the same width as every other page.** It
  carried a 860px cap and was the only page in the app narrower than the rest,
  so the same card rendered at two sizes depending on how you reached it. The
  name follows what the page is: administration of the DEPLOYMENT, now that
  everything belonging to the signed-in person has moved to Account. `/setup`
  redirects to `/admin`.
- **Four competing form styles became one.** `edit-grid`, `user-form`,
  `cred-form` and the field solver's `fs-field` all existed at once, and their
  labels were mono UPPERCASE 11px in one and sans sentence-case 12px in another
  — so a form looked different depending on the page it was on. The field
  solver's shape won, promoted to a shared `<Field>` / `<FieldRow>` /
  `<FieldSet>` and a `.field` CSS family. Every form in the app now labels the
  same way.
- **The two input sizes stay, and are now written down.** `.text` for a standard
  field, `.row-input` for the compact one inside table rows and toolbars. A
  duplicate `select.sel` style was folded into the shared one.

## 2026-09-12 — Git tokens belong to an account, not to each project

- **One revoked token was hiding behind three good copies.** Every project kept
  its own encrypted git token, so four projects on one GitHub account held four
  independent copies of one secret. Three were live and the fourth had been
  revoked, and nothing in the platform compared them — the only symptom was one
  project failing to fetch with `could not read Username`, which reads like a
  terminal bug rather than a refused credential. Decision 0010.
- **Credentials are now named accounts.** Add a token once on the new **Account**
  page — click your name in the top bar — and pick it by name on any project.
  Rotating it is one edit in one place, and two projects on one account can no
  longer disagree about the secret.
- **A project can still carry its own token** for a one-off repository. When both
  are set the account wins, and the project page says which is in force rather
  than only "stored (encrypted)" — that wording is how the stale copy hid.
- **Check tells you whether a credential still works**, before somebody needs it.
  It runs the same `git ls-remote` a real fetch uses, once per project on that
  account, and stores the verdict with its date. A credential nobody has checked
  reads "not checked", never "ok". The refusal message is translated where it is
  shown: "the remote refused this token (expired, revoked, or no access to this
  repository)".
- **The Account page holds everything that is yours, not the deployment's.**
  Your password, your API tokens (create, revoke, and read the value back), your
  git credentials, and the four boxes that used to sit on Setup — Effective
  URLs, the KiCad plugin install, the `.kicad_httplib` download and the Claude
  Code / MCP settings. Every one of those carries YOUR token, so two people must
  see two different strings; Setup keeps the deployment's shared configuration
  and a pointer here.
- **Existing tokens migrate themselves** on first start. Distinct token values
  become one credential each, named after the host and numbered when one host has
  several accounts; rename them to whatever you recognise.

## 2026-09-12 — The snapshot-archive purge checks before it deletes

- **The purge would have destroyed the only copy of one project's source.**
  Decision 0009 stops storing a `source.tar.gz` per snapshot because the git
  mirror holds the same commits for a quarter of the space, and a startup purge
  removes the ones already stored. That is right for three of the four projects
  on the server. Project 3 had no mirror directory, an empty checkout, and a
  remote the platform holds no credential for, so its 102.9 MiB archive was the
  only copy of that tree — and that snapshot is the project's current one and is
  pinned by a production run.
- **The purge now verifies the premise per archive.** `gitrepo.can_rebuild`
  asks whether the commit is still an object in that project's mirror — the
  directory existing is not enough, because a re-clone of a rewritten remote can
  lose a commit. What cannot be rebuilt is kept and logged by key, and the
  completion marker is withheld, so fetching the missing mirror and restarting
  finishes the job. Dry-run against production: 743.9 MiB deleted, 102.9 MiB
  kept.
- **A missing mirror is no longer invisible.** The Projects page announced it
  only for a project with no snapshot, so one that was ingested and later lost
  its mirror looked healthy. It now shows a red `no mirror` pill either way —
  without the mirror nothing can rebuild that tree, and backing up `DATA_DIR/git`
  does not cover it.
- **A failed checkout no longer leaves an empty directory behind.**
  `materialize` created the destination before extracting into it, so a missing
  mirror left a directory that answers `.exists()` and holds nothing; an audit
  counted one as a checkout on disk. It now names the missing mirror instead of
  dying on its `cwd` with a bare `FileNotFoundError`, and removes a half-made
  checkout.

## 2026-09-12 — One symbol viewer, one footprint viewer, one canvas

- **The review workbench drew symbols and footprints on a white card.** Its
  preview asked for `background: var(--paper, #fff)` and `--paper` is defined
  nowhere in the stylesheet, so the fallback always won — in dark theme and in
  light. kicad-cli renders light strokes on a transparent background, so the
  picture needs a dark ground under it, which the other previews supplied and
  this one did not.
- **Every preview now goes through one component**, `GeometryPreview`. There
  were six near-identical `<img>` shells across the component page, the template
  page, the templates list, the review workbench and the paste box, with four
  different missing/error stories and three different canvas colours. The canvas
  is now a single palette entry, `--kicad-canvas`, and a caller's class carries
  the size only.
- **The 2D/3D footprint switch was written twice** — component page and template
  page — and the copies had drifted on which state they remembered. One
  `FootprintPreview` owns it now.
- **A preview that has nothing to show says what is missing.** The templates
  list used to render an em dash, and the review workbench a broken-image icon;
  both now carry the server's own explanation where it sends one.

## 2026-09-12 — Table columns that cut their own pills

- **Every sign-off and review pill in the component browser was cut in half.**
  The columns were 4% wide each, which is 55 px — a pill is `inline-block`, so
  the column's ellipsis cannot shorten it and the word is simply clipped:
  "NOT S…", "CHECK…", "UNREV…". The widths the browser needs were written down
  once, in `styles.css`, with a comment saying 9% fits "not signed"; when the
  page moved to the shared `DataTable` the numbers were re-typed as 4 and the
  CSS was left behind as dead rules. Restored, with the reasoning now next to
  the numbers.
- **The bulk sign-off checkbox had an ellipsis stuck to it.** A checkbox is
  13 px of replaced content in a 3%-wide column with 12 px of padding either
  side, so it overflowed and `text-overflow: ellipsis` drew a "…" beside every
  one. Action columns now clip instead of ellipsising, and take 6 px of padding.
- **Centred columns now have centred headers.** `SIGN-OFF` and `REVIEW` sat
  left of the pills they name. `DataTable` copies `ctr` onto the header cell.
- **Nine more tables re-measured.** Reviews (lifecycle, used-in), Orders (net
  total, invoiced, status), Devices (MAC, project, last seen — and its widths
  summed to 103%), the project BOM (tier, qty/dev), Stock (written off, paid
  unit, market unit), the production overview (cost/dev, margin, sale) and the
  project orders tab (its widths summed to 93%). Every header now fits its
  column, and the only cells that still truncate are free text — manufacturer
  names, reference designator lists, repository URLs — where the full value is
  on hover.
- **Filtering the browser's review column for "issues" found nothing.** The
  pill prints "issues" for a failed check; the filter text said "checks fail".

## 2026-09-12 — Every IC in the library now draws its supply current

- **The amplifiers, comparators and logic gates delivered current to their
  loads and took none from their rails.** A behavioural output stage is a
  controlled source, and a controlled source referenced to node 0 manufactures
  its current out of the ground node; the supply pins were only read, by ideal
  sensors that draw nothing. Measured with an ammeter in every supply leg:
  `sigma_opamp` put 5.00 mA into a 1k load and drew 14 pA from its rail,
  `sigma_rail_buf` put out 3.22 mA and drew exactly zero, and `sigma_ldo`
  delivered 100 mA while drawing only its own 3 mA. Every rail-current,
  decoupling, regulator-loading and efficiency answer from those models was
  wrong. Signal-path answers were not, which is why it lasted: the verdict
  harnesses check signals.
- **Eighteen models corrected, plus one new shared block.** `sigma_supply`
  does the two jobs that belong to whichever block owns the rails: it draws a
  quiescent current from rail to rail, and it moves the stage's output current
  off node 0 and onto the supplies. It carries an RC lag because the
  correction closes a real loop — rail to clamp to output to current — and an
  algebraic one aborts the operating point.
- **Models built from a real switch were always right.** `sigma_ucc27538` and
  `sigma_hss` measured 117 mA and 2.38 A from their supplies, correctly; they
  only needed a quiescent current. The split between the two kinds is
  structural and now recorded in the simulation skill.
- **`IQ` is per channel, not per package.** A composed wrapper shares one
  parameter across every block it holds, so a dual part would charge a package
  figure twice. Divide by the channel count and show the arithmetic in the
  component's `Sim.Params` comment.
- **Nothing in the signal path moved.** Against the old models a corrected
  op-amp matched the closed-loop output and the saturated swing to seven
  digits. All six `EVSE_20_CTRL` harnesses still pass every check — 102 of
  102 — with no convergence trouble. The verdict numbers shift in the fourth
  decimal, in the direction of a rail that now sags under real load.
- **All 34 affected components now carry their own number**, each with the
  datasheet page in its version comment. Five regulators held values that were
  already wrong, one of them by a factor of ten. Three parts are marked
  `placeholder` and say what would confirm them: the negative 12 V regulator,
  whose datasheet publishes no typical at all; the gate driver, whose only
  tabulated bias current is measured below its own turn-on threshold; and the
  buck's efficiency, whose curve in the datasheet is drawn for a sibling
  variant's board.
- **The buck converter conflated two states.** It drew its SHUTDOWN current
  whether enabled or not, and those differ by about an order of magnitude. It
  now follows the enable pin.
- **A component edit does not reach a board that already exists.**
  `Sim.Params` is baked into the project's own schematic, which is a git
  checkout, so a board picks these numbers up only after Tools → Update
  Symbols from Library and a commit. A model edit is different: it reaches
  every snapshot at once. The two halves of this change therefore land at
  different times.

## 2026-09-12 — A run that says how far it has got, and a scope you can zoom

- **The Run button reports real progress, not just "Running…".** ngspice says
  where it is: during a transient it prints the simulated time it has reached.
  The process that owns the solver records that against the transient's own
  stop time, and the browser polls it once a second. The bar names its phase
  too, because reading the schematic through kicad-cli is several seconds
  before the solver starts and a bar frozen at zero reads as a stall.
- **A verdict harness solves its transient TWICE**, which the progress bar
  made visible. The deck's own `.tran` writes the rawfile the scope plots, and
  the `tran` inside `.control` is the run the `meas` verdicts read. Every
  `_sim` project in EVSE_20_CTRL is built that way, so a 720 ms scenario costs
  about 27 s instead of 14 s. The bar counts the sweeps and names which one is
  running, so it stays monotonic instead of reaching 98% and starting again.
- **The scope zooms and pans.** Drag selects a window, as it always did but
  nothing said so. The wheel now zooms about the pointer, shift-wheel and a
  trackpad's horizontal scroll pan, and Reset zoom appears once the view is
  not the whole run. Every pane moves together, because they share one time
  axis and a zoom that moved one of them would break the reading that stacking
  them is for. A new run resets the window.
- **Taller doubles the pane height**, and gives the scope more of the window
  so two tall panes still fit without scrolling. The setting is remembered per
  sheet.

## 2026-09-12 — A mirrored part on its side is placed the way KiCad places it

- **The schematic transform applied `(mirror x|y)` before the rotation. KiCad
  applies it after, in sheet axes.** At 0 degrees the two orders agree, so
  every sheet but one looked right. At 90 or 270 degrees the mirror flipped
  the symbol's own axis, which is the OTHER sheet axis: a mirrored resistor
  lying on its side had pin 1 drawn and connected at pin 2's end, and a
  mirrored zener the wrong way round. CP_PWM carries eight such parts and
  the Simulator reported nine "group touches more than one net" conflicts
  for it. The overlay's `_place`, the server drawing's `placement_matrix`
  and the browser's `matrixOf` all moved together; on the EVSE_20_CTRL
  snapshot every one of 1511 placed pins now sits on the net the kicad-cli
  netlist gives it, and the conflicts are gone. The netlist and the
  simulation were never affected — they come from kicad-cli, not from this
  transform.
- **The "No charge is drawn on N nets" notice counts nets, not wire groups.**
  A power net drawn in several places was listed once per place, so GND
  appeared twice in a list of 19.

## 2026-09-11 — The Board dropdown lists boards, not simulation harnesses

- **A project's Board selector no longer offers its `_sim` projects.**
  `EVSE_20_CTRL` carries six simulation harnesses beside the design, each a
  real `.kicad_pro`, so the project view listed seven "boards" and a project
  with one board and six harnesses showed a dropdown at all. The ingest now
  classifies every discovered project as a `board` or a `harness` from its
  root sheet: a sheet carrying a SPICE directive is a harness. The project
  view, the project list and the BOM/board/schematic tabs show boards only;
  the Simulator keeps listing the harnesses as before. The name suffix is not
  the rule, so a schematic-only design stays a board and a harness is one
  whatever it is called.
- **The Schematic tab gained a Simulation picker.** It lists the design and
  every harness of the snapshot, so a harness sheet is still readable in the
  project view. Simulate and Play live open the harness that is picked. With
  the design picked, they let the Simulator open its first harness instead of
  the design and a "carries no directives" notice.
- **Old snapshots are classified on first read** and the answer is stored, so
  no re-fetch is needed.

## 2026-09-11 — A part with no land pattern stays off the board

- **A cabled antenna, an RF pigtail or an enclosure with no drawn outline is no
  longer pushed onto the PCB.** The generator forced `on_board yes` on every
  part outside the `Simulation` category, so a base symbol's own
  `(on_board no)` was thrown away — `Antenna_Cabled` and `RF_Pigtail` were
  emitted as on-board although both drawings say otherwise, and the note on
  `Antenna_Cabled` claiming this flag prevents a missing-footprint report had
  not been true for any of six parts. A part is now off-board when **the base
  symbol declares `(on_board no)` AND the component has no footprint**. See
  [decision 0005](docs/decisions/0005-off-board-parts.md).
- **Both halves of that rule are load-bearing.** Without the declaration, a
  `Footprint` somebody merely forgot would drop the part off the board in
  silence. Without the footprint test, the 17 terminal-block plugs would drop
  off too: `TERMINAL_BLOCK_PLUG` declares `(on_board no)` while every component
  on it carries the deliberate `TerminalBlock_Plug_Invisible` land, so the next
  *Update PCB from Schematic* would have **deleted those footprints from boards
  that already exist**.
- **One predicate, three readers.** `generator.off_board` is called by the
  mirror, by the KiCad HTTP catalog record (which is what KiCad actually places
  from) and by the validator, so what the validator forgives and what KiCad is
  told cannot drift. `in_bom` is deliberately not derived the same way —
  `RPi_CM5` carries an `(in_bom no)` this library does not mean, and honouring
  it would drop the most expensive line on the board out of every BOM.
- **The validator gained its third footprint-less branch.** It already answered
  `na` for BOM-only and simulation-only parts; an off-board part was the case
  with no branch, so `cmp.required_props` and `cmp.footprint_ref` failed by
  construction on every cabled antenna and pigtail and had to be answered by
  hand. An ordinary part with an empty `Footprint` still fails.
- **Two RF pigtails and a shared symbol.** `BWIPX1-SMA-1.13L100` (C784403,
  I-PEX Gen 1 to SMA female) and `ACA-RFSMA-K TO IPEX1 001` (C22467635, to
  RP-SMA female), on a new 0-pin `RF_Pigtail` base symbol with reference `W`.
  Both are bulkhead types and both mate with an antenna already in the library.
  Gender was confirmed from each manufacturer's own drawing: the Chinese
  `外螺内孔` reads like RP-SMA to an English eye and is a standard SMA jack,
  because the jack carries the external thread and the plug carries the nut.
- **`Enclosure` now declares itself off-board.** This moves only the three
  Italtronic enclosures, which have no footprint; the four Hammond and the
  Takachi parts carry real lands and are untouched. Whether the Italtronic
  three should get their own mechanical footprints is still open
  ([docs/todo.md](docs/todo.md)).
- **RF uses one spelling for VSWR.** The category carried both `V.S.W.R` (four
  on-board antennas) and `VSWR` (four cabled parts) for one quantity, which
  splits any template or parametric filter. All four were renamed; none was
  reviewed or signed, so the rename cost no verification.

## 2026-09-11 — JLC06121H-3313A, and a board file checked against its stackup layer by layer

- **`JLC06121H-3313A` joins the stackup library.** JLCPCB's published 6-layer
  1.2 mm controlled-impedance build, outer 1 oz and inner 0.5 oz: prepreg 3313
  0.0994 mm under each outer layer, a 0.1 mm core under each of those, and
  **three 7628 sheets — 0.2104, 0.218 and 0.2104 mm — in the middle gap**.
  Copper and dielectric sum to 1.1684 mm. The Dk of every sheet was already in
  the material library, so nothing was assumed that the fab does not publish.
  JLCPCB renders the 1.2 mm tables only after a click, which is why the code
  appears nowhere in the page source; the figures were read from the rendered
  page on 11 September 2026.
- **The project Stackup tab now says WHERE the board file and the assigned
  stackup disagree**, not only that they do. Both sides are reduced to the same
  normal form — the ordered copper layers, and the dielectric GAP between each
  neighbouring pair — and every copper thickness, gap thickness, sheet
  thickness, Dk and loss tangent is compared, each with its own verdict.
  Inside tolerance counts as the same: copper 0.005 mm, dielectric 0.02 mm, Dk
  0.05, loss tangent 0.002.
- **Why the gap and not the layer.** KiCad allows only `copper - 1` dielectric
  layers, so a fab gap built from three prepreg sheets becomes one KiCad
  dielectric carrying three sub-layers, written with the bare `addsublayer`
  token. Counting `(layer …)` nodes could therefore never agree with the fab's
  own table, and the old reader returned the first sheet of such a layer and
  silently lost the rest. What a field sees is the gap.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same.** The board file was read inside a bare `except`, so a pruned mirror
  reported the board as declaring no stackup of its own. The page now states
  which of the two happened, and what to do about it.
- `total_mm` of a board file is now the copper-plus-dielectric build, the way a
  fab states a stackup; the solder mask is reported separately as `mask_mm`.
  The two sides describe a mask differently and are not compared on it.
- The agent tool `fieldsolver_board` returns the same table as `comparison`.

## 2026-09-11 — One stackup table everywhere, a stackup that is electrical only, and a board that has a colour

- **`JLC06121H-3313A` joins the stackup library** — JLCPCB's published 6-layer
  1.2 mm build, with **three 7628 sheets in the middle gap** (0.2104, 0.218,
  0.2104 mm). 1.1684 mm of copper and dielectric. JLCPCB renders its 1.2 mm
  tables only after a click, which is why the code appears nowhere in the page
  source; the figures were read from the rendered page.
- **EVSE_20_CTRL is built to it.** The board file carried a placeholder — FR4 at
  Er 4.5 everywhere, prepreg 0.1 mm, core 0.35 mm — that no fab states, so no
  width solved against it would have been the width the board gets.
- **One stackup table, everywhere** (`web/src/components/StackupTable.tsx`):
  the project comparison, the field solver and the stackup editor all draw the
  same colour-coded, top-to-bottom rows, aligned by one backend function so the
  picture cannot disagree with the verdict.
- **The board-file check is layer by layer.** It compared two things — copper
  count and total thickness — so a board could carry the wrong laminate in every
  gap and read as agreeing. Now every copper thickness, dielectric gap, sheet,
  Dk and loss tangent has its own verdict, plus solder mask ink thickness and Dk
  and the presence of a legend, each against a published figure.
- **KiCad sub-layers are read.** A fab gap of three prepreg sheets is one KiCad
  dielectric carrying `addsublayer` groups; the old reader took the first
  `(thickness)` and silently lost the rest. `total_mm` also counted the solder
  mask, which a fab stackup does not, so every comparison was 0.02 mm out.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same** — the board file was read inside a bare `except`.
- **A stackup is electrical only**
  ([decision 0008](docs/decisions/0008-a-stackup-is-electrical-only.md)). Board
  **colour is project data**, versioned like the assignment, chosen from
  JLCPCB's own list with the legend following the mask; picking one writes
  nothing to the library. Outer layers are **per face**, so a board can carry
  legend or a different finish on one side. Copper is named `L1`…`Ln` by
  position and dielectric labels are generated — neither is typed — and a save
  that would put **copper against copper is refused**.
- **Impedance profiles survive a refresh** (`field_workspaces`, one row per
  person) and are banked **per stackup**: switching parks the open set and picks
  up the other, because a profile's cells are keyed by copper layer name.
  Saving to a board is **all-or-nothing** and refuses a stackup mismatch,
  server-side. Removing a profile, a stackup or a rule set now asks first.
- **The solder mask is drawn as one object.** It arrives as several overlapping
  rectangles and each was filled with a translucent green, so every overlap
  doubled the alpha — three different greens, darkest where two met, and a
  coplanar ground that looked mis-drawn.
- **Numbers carry their unit** (`SiInput`): type `35um`, `0.035`, `1.4mil`,
  `2.4GHz`. Copper thickness is checked against the foils that exist and the
  weight is read off it. The mask over a trace is derived as half the figure
  over the substrate — subtracting the copper gives −4.5 µm on JLCPCB's own
  published pair.
- **Every modal locks the page behind it, closes on Escape and on a click
  outside** (`web/src/components/modal.ts`). Escape is bound on the document:
  on the backdrop it only fires once focus is inside, which is why dialogs had
  to focus themselves to be dismissable at all.

## 2026-09-10 — Datasheets stored once, versioned by text; re-signed PDFs no longer bump parts

- **One stored file per distinct content.** Datasheet bytes moved from
  `datasheet_versions` into a content-addressed `documents` table; a version
  is now a history row that points at a document, and two components that
  link the same PDF share one copy (24 files were shared between parts, the
  TPS7A20 variants among them). The page index follows the document, so a
  shared file is indexed once. The move ran at startup in SQL and rewrote the
  tables, which handed the disk back
  ([decision 0004](docs/decisions/0004-datasheet-identity-and-storage.md)).
- **A new version means the text changed.** TI re-signs every PDF about every
  two days and generates the whole tail of the document at download time, so
  one TPS61023 datasheet had 37 stored copies, each of which bumped the
  component to a new version and dropped its verification. The identity is
  now a hash of the page text with a role per page: the body in order, the
  orderable-part table reduced to its part-number and lifecycle pairs, the
  drawings as an unordered set, the live tape-and-reel tables excluded. On a
  copy of the production library that took 704 versions down to 616 and 557
  stored files down to 484, and every difference left is real. A re-signed
  file answers `restamped` and stores nothing. The revision label parsed from
  the document ("Rev. B", "SLVSF14B") shows on the datasheet card and in the
  history.
- **A real revision is a review event.** The automatic bump now runs through
  the shared publish path; the review record does not carry across a
  datasheet whose text changed (the sign-off does), and a review request is
  opened with the revision labels, the pages that are new or edited, how many
  drawings were removed, and whether the orderable-part table moved.
- **A stored web page is no longer counted as an unsearchable datasheet.**
  LCSC serves its "document not available" page as `C10425.pdf` with
  `Content-Type: text/html`; the leading bytes now decide what a file is, so
  186 such pages moved from `scan` to `none`. One of them is a current copy
  and needs a real datasheet.
- **The fetcher learns which user agent a host accepts.** Infineon and
  Nexperia refuse `curl` and serve a browser string; onsemi does the reverse.
  A refusal retries with the other string and the answer is remembered per
  host. The 11 empty Infineon downloads in the audit log were this.
- **A saved URL is fetched at once**, not at the nightly run.
- **Clean-up endpoints.** `GET /api/datasheets/restamps` lists the history
  the byte rule wrote; `POST /api/datasheets/restamps/collapse` folds it into
  the surviving version and drops the orphaned files.

## 2026-09-10 — Sync plugin 1.5.0 owns library updates; HTTP catalog every 2 minutes

- **Sync plugin 1.5.0 records what it installed in the Plugin and Content
  Manager.** The PCM decides "update available" from its own record,
  `installed_packages.json`, and only its dialog writes it — so a library the
  Sync button had already refreshed still showed a badge on every start, and
  Update All re-downloaded the 259 MB models zip the delta had delivered.
  After a successful sync the library and 3D-model packages are recorded at
  the served version and pinned, KiCad's own switch for "updated elsewhere":
  no badge, no Update All, a manual Update still in the menu. The plugin
  package is left alone and still updates through the PCM. KiCad reads the
  record at start-up and writes its in-memory copy back when the PCM dialog
  closes, so a dialog closed later in the same session can restore the old
  versions; the next sync corrects them. The closing notification now also
  says that placed parts are copies (Tools → Update Footprints / Symbols from
  Library).
- **KiCad re-fetches the part catalog every 2 minutes instead of every hour.**
  The `.kicad_httplib` now carries `timeout_categories_seconds` and
  `timeout_parts_seconds` of 120. KiCad 10 refreshes the catalog in a
  background thread every `max` of the two, and no menu action, IPC command or
  plugin can force it, so the interval is the only lever. A published
  footprint or field change reaches the symbol chooser within two minutes;
  one refresh costs 17 requests and about 44 kB on the wire. The values are
  embedded in the file: download `7Sigma.kicad_httplib` again from Setup and
  replace the installed copy.

## 2026-09-10 — Built means finished and passed; the Aqua history, again

- **The shelf no longer holds units nobody can pick up.** Stock per batch used
  to add the quantity typed on the production run to the devices recorded in
  it, which claimed 118 units that exist in no record and $1,700 at cost —
  four on Dongle Batch 1 against 521 real devices, 44 on Batch 3, 67 on Aqua
  Batch 5 — while two other batches read as 113 and 47 units "overdrawn". A
  batch that has any device record is now counted from its devices and from
  nothing else; the typed quantity rides along as `qty_recorded` so a wrong
  run quantity stays visible. Only a batch with **no** device records at all,
  which is the V3 prototype runs, is still counted from its quantity, and that
  is the one remaining source of an unserialized unit. See
  [decision 0007](docs/decisions/0007-built-means-finished-and-passed.md),
  which overrides item 8 of [decision 0003](docs/decisions/0003-orders-shipments-and-device-history.md).
- **A board that never passed is not stock.** The retro import had written a
  `produced` event for every imported device, failed ones included, so 82
  boards whose newest programming or test run failed sat on the shelf and
  could be picked for a shipment. They are unbuilt until a later run passes.
  Production after the pass: dongles 4,429 passed, 4,366 shipped, 63 on the
  shelf; Aqua 914, 867, 47.
- **Every built batch stays on the shelf card.** The card selected rows by what
  was left on them, so the moment `built` started counting passed devices, six
  of seven dongle batches vanished — everything they held had shipped. The
  filter now drops planned batches and keeps the rest, and **Recorded sits next
  to Built**: a row is marked when built is above recorded, which is impossible
  rather than merely unlucky. Dongle Batch 5 is recorded as 455 boards and has
  568 devices, Batch 6 as 945 against 992. Under-building is ordinary attrition
  and is not marked.
- **347 more Aqua units were filed under the dongle.** The July re-attribution
  used the functional test and the pushed GPIO template and called an untested
  Aqua indistinguishable. It is not: every config report carries the device's
  own `INFO1` line, `"Module":"CE_Aqua"` or `"Module":"CE_Dongle_v2"`. The
  signal agrees with the test everywhere the two overlap — none of the 4,121
  Module=Dongle devices ever ran the Aqua test, and all 584 Aqua-tested devices
  are Module=Aqua.
- **77 boards had two records each.** The 2025-11-05 firmware names a device by
  its full MAC where earlier builds used the last three bytes, so a board
  re-flashed after that date appeared as both `dongle_<6 hex>` and
  `dongle_<12 hex>`. They are merged into the older record. One pair survived
  the merge: `8BD26C` and `78:42:1C:8B:D2:6C` are a genuine three-byte
  collision between two products.
- **Two Aqua batches had been sold twice.** The run migration turned the build
  quantity of runs 12 and 13 into orders of 315 and 200 units that no invoice
  covers, on top of the real Aqua sales. Both orders are gone and the runs'
  sale columns are blank, so the idempotent migration cannot recreate them.
- Scripts: `docs/flasher/fix_aqua_attribution_2.py` and
  `docs/flasher/fix_built_is_passed.py`, both dry-run by default. The reasoning
  and the numbers are in `docs/flasher/design.md`.

## 2026-09-07 — Order page layout, device list sorting, sort hints

- **Sync plugin 1.4.1 quarantines the duplicates iCloud makes at install.**
  A PCM install into an iCloud folder can leave a `7Sigma_Base 2.kicad_sym`
  (the previous library) beside the real one. KiCad registers it as a second
  symbol library and the sync plugin, which has no baseline for it, listed
  every symbol in it as "only here — never sent" (153 rows on 2026-09-06).
  The sweep that runs at the start of every sync now handles duplicate
  files as well as folders: empty folders are deleted, anything with content
  is moved to `strays/<timestamp>/` inside the plugin folder, and the dead
  `sym-lib-table` / `fp-lib-table` rows go with it. Nothing is deleted. The
  sweep itself, from 2026-08-27, never reached installed plugins because that
  change did not bump `PLUGIN_VERSION`; this one does.
- **`list_footprints` finds a shared land by any package name it serves.**
  The agent tool matches the query against a footprint's `tags`, `descr`
  and hidden `Equivalent Packages` property as well as its name, and a hit
  made that way says which field matched and quotes it. Searching "WQFN-16"
  or "LFCSP-16" now returns the QFN-16 3x3 mm land those packages share
  (conventions-footprints v27, §1), instead of nothing.
- **Order page**: the products, invoices and shipments tables size their
  columns to the content and scroll inside the card instead of clipping;
  under 1700 px the tables take the full width with the two short cards
  beneath. Notes is a full-width row of the order form.
- **Devices list**: Project, Batch and Runs sort and filter on the server,
  and a Where column shows the device state (in stock, shipped, …). The
  batch shown is the one the orders side linked to the device.
- **Every sortable header** shows a faint sort glyph and the whole header
  cell is the click target — before, the title alone was the button and
  nothing marked it as one.

## 2026-09-06 — Orders in the project window, demand, decided JLC orders

- **Orders tab** on every project, next to Batches: one row per order line
  for that project's products, with the order's status and a link to it.
- **Demand card** on the Orders page and at the top of the Orders tab: open
  order quantity against devices on the shelf and the quantity of planned
  batches, with the shortfall or the surplus. `GET /api/demand`.
- **A JLC import decision now overrides JLC's cached panel count.** Before,
  an order decided as 4-up kept showing JLC's 1-up count in the queue and in
  the run-fill check (Batch 8: 200 devices and "short" against 800). The
  queue shows a decided order as decided, keeps JLC's own factor for
  reference, and names the parts JLC sourced from its own stock, which the
  BOM vote cannot see.

## 2026-09-03 — Sales orders, shipments and a per-device history

Decision record [0003](docs/decisions/0003-orders-shipments-and-device-history.md).
A sale is no longer a set of columns on a production run.

- **Customers and orders** are tables: an order holds one line per product,
  so an Aqua and a dongle sit on one order. Status (open / partial /
  fulfilled) follows the shipments and is never set by hand.
- **Invoices per order**: proforma, advance, final, correction. Advance +
  final + correction should equal the net total; the page warns, nothing
  blocks. Due date defaults to issue + the customer's terms. Revenue converts
  per invoice at the invoice date.
- **Every device has a history**: produced in a batch, shipped on an order,
  returned, repaired, replaced, disposed of. The flasher writes the first
  event on the first pass in a batch. Finished-device stock is a count of
  devices on the shelf per batch, valued at the batch's actual per-device
  cost; batches from before device records are counted from the batch
  quantity ("without a serial").
- **Shipping draws oldest-first** from the batches the user ticks, or takes
  pasted device IDs. A return against a device FIFO never picked swaps it in
  and puts the guessed device back. A warranty replacement is charged to the
  original order, so an order with three replacements shows the cost of
  503 devices against the revenue of 500.
- **Migration at startup**: each run with a price became an order line and
  one unserialized delivery; runs sharing an order reference share the order.
  The run's own sale columns stay for the register, whose figures do not move.
- New: Production → Orders, an order page, "Where it is" on every device page.

## 2026-08-31 — Field solver

Controlled-impedance geometry moved from the standalone prototype into the
platform, as **Simulator → Field solver**. A 2D quasi-TEM FEM solver for
microstrip, stripline, coplanar and differential lines with via fences, checked
against closed forms (microstrip Hammerstad-Jensen 0.6 %, stripline Wheeler
0.1 %, CPWG conformal 2.5 %) and against JLCPCB's own calculator.

- Stackups and production rules are library data in Postgres. Stackups are
  written by administrators only; anybody may assign one to a board.
- A board's stackup and its impedance profiles are commit-versioned like the
  cost plan: assigned at a commit, carried forward until changed. Changing the
  stackup keeps every profile and result and marks the results outdated.
- The board file and the assigned stackup may disagree; the difference is
  reported, nothing is blocked.
- The sweep is floored at 1 MHz — below that a perfect conductor stops
  describing a real board.
- `triangle`, the mesher, is licensed for personal and research use only and
  must be replaced before any commercial release.
- The solver runs on both architectures. amd64 installs the mesher's wheel;
  arm64 has no wheel published, so the image builds the same version from the
  upstream git tag. The two builds agree on Z0 to 0.0013 % and produce meshes
  that differ by about 3 % in node count.
- The server VM went from 2 cores and 8 GB to 8 cores and 16 GB, and from a
  `x86-64-v2-AES` CPU model, which has no AVX at all, to `host`. A geometry
  search that took 21.1 s takes 8.2 s. The api container's memory ceiling rose
  from 1500 MB to 6 GB to hold six solver workers.

This file starts on 2026-08-28. For earlier work, read the git history.

Each entry says what changed and why. Put a note here when a change alters how
the platform behaves in production, not for every commit.

## 2026-08-29

### Added

- **A package simulation wrapper is now built from blocks, not written.** KiCad
  netlists one element per reference designator, so the subcircuit `Sim.Name`
  points at is always package-level. Those wrappers were typed by hand, one per
  part, and nine of the sixty-five models in the library held no behaviour at
  all — two instance lines and a parameter pass-through. Two of them,
  `sigma_74hc21` and `sigma_buf2`, were written, linked to nothing, and never
  noticed. A symbol's link now stores a block design and the platform generates
  the `.subckt` from it. See
  [decision 0001](docs/decisions/0001-generate-package-sim-wrappers-from-blocks.md).

  The rule that shapes it is one wrapper port per unique symbol pin, never
  fewer. Two pins are never merged onto one port, because the schematic may put
  them on different nets and one port carries one node. The result is that the
  port list is `p1 p2 p4 …` by construction, so **`Sim.Pins` is derived and can
  no longer be mis-authored** — the swapped pair that `validate_pin_map` admits
  it cannot catch is not expressible in this mode.

### Changed

- **Eleven symbols moved to composed models and thirteen hand-written wrappers
  were deleted.** The conversion preserved every wrapper's interface, so no
  component's `Sim.Params` row moved: `cli/simrecompose.py apply --verify`
  reported 0 lost parameters and 0 moved defaults. Checked under ngspice
  against the deployed library, the composed wrapper beside the hand-written
  one on the same stimulus: `v(y1) = v(o1) = 3.283582 V`, `v(y2) = v(o2) = 0 V`.

- **Nine superseded simulation primitives were deleted**: `sigma_and4`,
  `sigma_buf`, `sigma_buf_3st`, `sigma_dff`, `sigma_dff_r`, `sigma_dff_sr`,
  `sigma_inv`, `sigma_monostable` and `sigma_iso7721`. Each has a
  `sigma_rail_*` equivalent that reads its own supply pins at run time, and
  every one of those is in use. The library holds 54 models, from 65.

### Fixed

- **The rail check no longer reports correctly wired supplies as miswired.** It
  failed sixteen links, and all sixteen were right. Its list of rail port names
  held eleven entries, so `vdd1`, `gnd2`, `vcc1`, `vinp`, `vinn` and `vs` were
  not rails as far as it knew; rail ports are matched by shape now.

  The second half of the check is deleted rather than widened. "A `power_in`
  pin on a port that is not rail-shaped" cannot tell an LDO's `in` from an
  op-amp's `in+`, because the difference lives in the model and not in the
  name. It reported ten LDOs, three DC/DC bricks, an isolator, a high-side
  switch and a flip-flop whose `pren` is tied high because it has no preset —
  and not one real fault. Nothing is lost: each port takes exactly one pin, so
  a supply pin landing on a signal port displaces another pin onto the real
  rail port, and that pin is not a power pin, which is what the surviving half
  tests. All 62 simulation links now validate clean.

- **Generated text is emitted in a fixed order.** `SimModelVersion.parsed` and
  `SymbolSimLink.composition` are JSONB, and Postgres reorders an object's
  keys, so a dict iterated in the session that wrote it gives one order and the
  same dict read back gives another. A wrapper therefore differed from itself
  across a round trip, and the mirror withheld the `Sim.*` fields of
  `74LVC1G175GW,125` over a moved word in a comment. Any list the composer
  derives from a dict is now ordered explicitly.

## 2026-08-28

### Fixed

- **The API no longer exhausts the server.** The `kicadlib-api` container held
  4.8 GB of memory (1.8 GB resident and 3.0 GB in swap) on an 8 GB host, and it
  peaked at 6.0 GB. The kernel killed it four times in August (18 August, and
  three times on 23 August), each time at 6.9 GB to 7.5 GB. The kill was a
  global out-of-memory event, so it also damaged the unrelated stacks on the
  same machine. Four defects caused this:

  1. `datasheet_pages.index_one` started one thread for each stored datasheet
     version and limited nothing. One `pymupdf4llm` extraction uses 400 MB to
     450 MB at peak, even for a document of 10 pages. The nightly re-check
     walks all 678 datasheets, so many extractions ran together. A
     `BoundedSemaphore(1)` now permits one extraction at a time. Extraction is
     CPU-bound and the host has 2 cores, so the threads never ran in parallel.
     They only held memory together.
  2. glibc kept the freed memory. The process held 67 malloc heaps of 64 MB,
     which is 4.2 GB of arena, for approximately 48 MB of live objects. The
     image now sets `MALLOC_ARENA_MAX=2`, and the new `services/memory.py`
     calls `malloc_trim(0)` after each large document. Both halves are
     necessary. A measurement on the real corpus shows 16 documents plateau at
     636 MB with 2 arenas, instead of a continuous climb.
  3. No container had a memory limit, so a fault in one container became a
     fault of the whole host. The api service now sets `mem_limit: 1500m` and
     `memswap_limit: 1500m`. A regression now restarts one container instead
     of stopping the machine.
  4. Datasheet versions 367 and 368 failed to index on every boot, for ever.
     `pymupdf4llm` returns lone UTF-16 surrogates for some malformed CID fonts.
     Postgres refuses them, and the error arrived after the guard that stamps
     `pages_indexed_at`. The two documents therefore repeated approximately
     900 MB of extraction at each start. `_drop_surrogates` now removes these
     characters. A lone surrogate carries no text, so this loses nothing.

### Changed

- `mirror.write_manifest` hashes each file in blocks of 1 MB. Before, it read
  each file complete. This is a small improvement, and it is not the cause of
  the memory fault above.
