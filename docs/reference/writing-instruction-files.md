# Writing an agent instruction file

A `CLAUDE.md` is not a place to be thorough. It is loaded into a context window
that every later decision is made from, and a file that grows past its
usefulness makes an agent follow LESS of it, not more. Anthropic's own guidance
puts the target at under 200 lines per file and warns that a bloated file causes
an agent to ignore the rules that matter.

`scripts/check-docs.py` enforces rules 1, 3 and 5. Run it before you report
documentation work as done.

An instruction file is not a place to be thorough. It is loaded into a context
window that every later decision is made from, and a file that grows past its
usefulness makes an agent follow LESS of it, not more. Six rules, and
`scripts/check-docs.py` enforces the first, third and fifth:

1. **Target 200 lines per `CLAUDE.md`.** Past that, split by directory or move
   the long form to `docs/reference/`. The root file is the expensive one: it
   loads in every session, on every task, whatever you are working on.
2. **Apply the derivability test to every line.** Could a session working in
   this repo reconstruct it by reading the code? Then do not write it. Directory
   listings, dependency lists, standard build commands, and signatures copied
   out of source all fail this test. What passes: a gotcha, the reason a thing
   is the way it is, a convention that DIFFERS from the tool's default, a
   prohibition, and a command nobody would guess.
3. **Link, never summarise.** A summary written beside a link becomes a second
   copy that drifts, and then two files state the rule differently. Write the
   rule once, in the most specific file that covers it, and link to it from
   anywhere else that needs it.
4. **Put a rule in the narrowest file that covers it.** A `CLAUDE.md` in a
   subdirectory loads only when an agent opens a file in that directory, so a
   backend rule costs nothing on a frontend task. The exception is a
   safety-critical prohibition — "never commit without being asked", "never edit
   generated files" — which stays in the root file, where it cannot fail to
   load.
5. **Never use `@path` imports in a `CLAUDE.md`.** They are expanded at launch
   and enter context whatever the task is, which defeats the whole split. Use an
   ordinary markdown link.
6. **A file states the current fact and nothing about its own past.** No "this
   used to say X", no struck-through row kept beside its replacement. Edit the
   sentence and let git hold the history. A reader cannot tell a live rule from
   a dead one when both sit on the page.

Run `python3 scripts/check-docs.py` before you report the work as done.

## How the files are arranged here

A `CLAUDE.md` in a subdirectory is read when an agent opens a file in that
directory, not at launch. That is what makes the split pay: the backend rules
cost nothing on a frontend task. The root `CLAUDE.md` is the only one loaded in
every session, so it holds what applies everywhere and nothing else.

Long-form topics live in this directory, linked from the nearest `CLAUDE.md`.
A page here costs nothing until something reads it, which is why a rule too long
for a `CLAUDE.md` belongs here rather than compressed into one.

## Adding a page to docs/reference/

1. One topic per page. Name the file after the topic, not after the module.
2. Add a row to [index.md](index.md) in the same commit: the page, what it
   holds, and what an agent should read it before changing.
3. Link it from the `CLAUDE.md` next to the code it governs. A page nothing
   links to is a page nobody reads.
4. State the current fact. A decision that is expensive to reverse belongs in
   [../decisions/](../decisions/) instead, and an accepted decision record is
   never edited — it is superseded.
