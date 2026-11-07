---
status: accepted
date: 2026-11-07
decision-makers: Mateusz Kowalik
---

# Make each job a section, draw a batch as a board, and keep the scan group

## Context and Problem Statement

Production had 17 tabs that served four jobs: make, stock, sell and money. A
batch page had 6 tabs, and its Process tab had 9 cards, with 200 gap rows on
Batch 8. The route of a process was only text on the batch page. The process map
was only on the project page, and it showed no counts and no stock. The bench
read nothing from its URL, so no page could link to it. Lists folded in three
different ways, and a folded list said nothing about its rows. About 26 groups of
API functions had no control in the UI. The proposal and its sketches are at
<https://claude.ai/artifact/Jqx7CZ45WcXBxPp6oaQonq>.

## Decision Drivers

* The person at the table must see which step can go now, and how far stock goes.
* After programming, the board can say how many devices can go, but not which. A
  person packs a subset of the devices, for example when cartons run out, and
  chooses them with a barcode scanner that types a code and Enter.
* Every platform function must be available from the UI.
* A figure on a field must be the figure the click is judged by.

## Considered Options

Navigation:

* A: four Operations sections (Production, Stock, Sales, Finance), each with 3 to
  5 tabs.
* B: one Production section, with all 17 links in one grouped strip.
* C: one Production section, with a menu per group.

Scanned groups:

* Keep the text box and its group, and let them run several steps.
* A printed barcode for Run and Apply, so nobody touches the computer.

Bench link:

* Pre-set the bench and leave every control open.
* Pre-set the bench and lock the project and the batch.

## Decision Outcome

Chosen by the user on 2026-11-07: navigation A, the text box and its group, and a
bench link that only pre-sets.

1. **The top bar has two groups.** Engineering is Library, Projects, Simulator and
   Reviews. Operations is Production, Stock, Sales and Finance. `/` is Home. The
   user menu holds Account, History, Admin and Log out. A section link opens the
   tab last used in that section. Every old address redirects.
2. **One component draws the process in three modes**, `ProcessBoard`: live on the
   batch page, plan on the project's Process tab, mini in the Batches list and on
   Home. The fields run on a snake path, 5 to a row.
3. **The server computes the board** (`twins.board`, `process.input_stock`). The
   stock of an input is found the way `check_shortages` finds it. `can_go` is the
   units waiting, limited by the stock of the step's parts.
4. **A scan group sits directly under the board.** It keeps the plain text box and
   its rules: a code and Enter adds one device, a scan is recorded as `scanned`
   and a tick as `list`, each device is judged on its own, and the group stays
   after a step. The server checks each code (`craft/check-codes`), because the
   page's list is as old as the page. A wrong code gives a red row and a sound,
   never a dialog: a dialog took the focus, so the next scan only closed it and
   that code was lost. The group survives a reload in the browser. Several ticked
   steps run in route order as one write (`craft/steps`), and the preview stays in
   the card, so a scan can never land on a dialog button.
5. **A bench link pre-sets the project, the batch, the steps and the stack.** The
   operator can change all of them. Firmware and parameters stay pinned by the
   procedure version.
6. **One fold rule.** A secondary list with more than 8 rows starts folded, and its
   header gives the count, state counts and the main action. A fold never hides a
   problem. The main list of a page never folds, and it gets the counts above its
   filter row.
7. **Shipping is Pack, then Send.** The one-step "Ship…" leaves the order page.
8. **An order keeps its own invoice rows** for now, with no link to the sales
   invoices (user, 2026-11-07).
9. **The repair jobs are admin-only on the API too:** the JLC fee refresh, the fee
   split, the adjustment rewrite and the re-compute of programming checks. They got
   a control on an admin-only panel, and a control is never hidden without the
   route's gate.

10. **Money reads in PLN, a component's price in USD, and an invoice in its own
    currency** (user, 2026-11-07). A total, a batch, an order, a device and a shelf
    read in PLN, because these are the prices dealt with a client. The stock value
    at JLCPCB and in the office, and the value at cost of finished products, are
    PLN too. A part's unit price stays in USD. USD stays the stored base. A batch's
    figure converts at the rate of the batch's date, as the batch page already did,
    so a closed batch's PLN cost does not move: a device carries its own batch's
    rate onto a shelf and an order. A figure that belongs to no batch (a stock
    value, a planned BOM) converts at today's rate. One display currency for the
    platform replaces the per-project setting. A batch's price override now names
    its currency: Materials writes USD and a cost line writes PLN. An override with
    no currency was written while every project displayed USD, so it reads as USD.
    Batch 8's in-house assembly is a bare 1.878288, and read as PLN it would drop
    from 7 PLN per device to 1.88.

11. **Every function has a screen, or a written reason** (user, 2026-11-07). A route
    with no caller in `web/src` gets a screen or is removed. The two other answers
    are a machine client and a function the UI reaches through another route, each
    written in `scripts/routes-without-ui.txt`. `scripts/check-ui-routes.py` fails the
    build on anything else. These routes went: the retired YAML import
    (`/api/import`), the one-step `POST /api/orders/{id}/shipments`, because a shipment
    is Pack, then Send, the planned serial registry (`/api/runs/{id}/devices`, with no
    row on production), and reads that repeated another route. The rules of a screen
    and where a new function goes are in `docs/reference/ui-map.md`.
12. **Time is stored in UTC and shown in local time** (user, 2026-11-07).
13. **Dark is the default theme** (user, 2026-11-07).

### Consequences

* Good, because a person sees the state of a batch on one screen, and each job has
  few tabs.
* Good, because the batch page, the bench and a shipment's Pack card scan the same
  way.
* Bad, because changing job can take one more click than today's flat list. The
  section link opens the last used tab to reduce this.
* Bad, because every old address must keep its redirect. Links in saved bookmarks
  and in older documents depend on them.
* Bad, because several steps in one write means one Undo takes back all of them.
  The Undo question names each step.

### Confirmation

`api/tests/costs/test_twins.py` pins the board figures, the code check and the
group run, and `web/` passes `tsc --noEmit`. A browser check drives the batch page,
the bench link and the old addresses.

A rate per document, so a batch's PLN total is the sum of what each line cost on
its own day, is more exact and was not taken: it needs a PLN figure beside every
USD figure in the cost code. Today's rate for everything was not taken: a closed
batch's cost would move every day.

## Pros and Cons of the Options

### Navigation A

* Good, because the second row shows only the pages of one job.
* Bad, because the top bar has 8 links.

### Navigation B

* Good, because every page is one click away.
* Bad, because the strip keeps today's 17 links on two lines at 1,100 px.

### Navigation C

* Good, because it is the shortest.
* Bad, because most moves take two clicks and the pages stay hidden.

### A printed barcode for Run and Apply

* Good, because nobody touches the computer.
* Bad, because a person must read the skipped devices in the preview before the
  write.
