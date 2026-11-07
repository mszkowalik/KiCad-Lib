# The UI map: where a function goes

Read this page before you add a screen, a tab, a button or an API route. It holds
the structure of the UI and the logic of its screens. The look of a screen is in
[web/CLAUDE.md](../../web/CLAUDE.md). The reasoning is in decision
[0103](../decisions/0103-a-job-is-a-section-and-a-batch-is-a-board.md).

## The map

The top bar names jobs, not database tables. A person looks for what they want to
do, so a function goes under the job it serves.

| Group | Section | The job | Its tabs |
|---|---|---|---|
| Engineering | Library | Define parts | Components, Templates, Datasheets, Skills |
| Engineering | Projects | Design a product | One project: Design, Make, Sell and Project tabs |
| Engineering | Simulator | Test a circuit | Circuit, Field solver |
| Engineering | Reviews | Check the library | Queue, Checklists |
| Operations | Production | Make devices | Batches, Bench, Devices, Procedures |
| Operations | Stock | Know what we hold | Parts, Organizers, Finished devices, Transfers, Suppliers, JLCPCB |
| Operations | Sales | Sell and ship | Orders, Shipments, Sales invoices, Customers |
| Operations | Finance | Know what it cost | Cost overview, Purchase invoices, KSeF, Company books, Exchange rates |
| User menu | Account | One person's settings | Tokens, git accounts, KiCad setup, theme |
| User menu | History | What changed, and undo | My changes, Write batches, Everyone |
| User menu | Admin | The deployment | Configuration, Users, Companies, Fleet broker, Data jobs, System |

`/` is Home: what waits for a person, across all sections.

## Where a new function goes

Answer these questions in order, and stop at the first answer.

1. **Does it act on one record?** It goes on that record's page: one batch, one
   device, one order. Do not add a new page and do not add it to a list page.
2. **Does it act on one step of a batch?** It goes on that field of the batch board,
   in the work panel under the board.
3. **Is it a rare correction of one batch?** It goes in the Corrections card on the
   batch's Settings tab.
4. **Does it apply to the whole data set once?** It goes on Admin → Data jobs.
5. **Does it change the deployment or data that every project reads?** It goes on
   Admin, or on the section's page with an admin gate. Rules are in decision
   [0045](../decisions/0045-configuration-is-an-administrators-surface.md).
6. **Is it one person's preference?** It goes on Account.
7. **Does it show a new kind of record?** Only then add a tab, under the section of
   the job. The tab has its own main list.

A new top-bar section needs a decision record. A section is a job, and the platform
has few jobs.

## The rules of a screen

1. **Every function has a screen.** A route with no caller in the UI is a function
   nobody can find. Give it a screen or remove it. The only other answer is a machine
   client, written with its reason in
   [routes-without-ui.txt](../../scripts/routes-without-ui.txt).
   `scripts/check-ui-routes.py` fails the build on anything else.
2. **One figure has one home.** Other pages link to it. Two copies of a figure become
   two different figures.
3. **A page answers one question first.** The main list of a page never folds. Every
   other list folds above 8 rows and shows its highlights in the folded line.
4. **A check that passes draws nothing.** Show a card when something is wrong or when
   the check could not run. "22 of 22 reconcile" is a line nobody acts on.
5. **A problem leads somewhere.** A warning has a link or a button to the place that
   fixes it. A red pill with no way to act on it reads as a missing feature.
6. **A write that moves money or stock shows a preview first.** The dry run uses the
   real write path. Apply is enabled only for the body the preview saw.
7. **A write tells how to undo it.** It names the write batch on History → Write
   batches.
8. **Every delete asks first**, and it names what goes. Rules are in
   [components/CLAUDE.md](../../web/src/components/CLAUDE.md).
9. **A scanner never meets a dialog.** It types a code and Enter, and a dialog would
   lose the next code. A wrong code is a row and a sound. The box keeps the focus.
10. **A batch is a board.** A step is a field, and the order of the fields is the order
    of the work. A new step kind is a new kind of field, not a new tab.
11. **The bench link only presets.** It opens the bench with the settings chosen. The
    person starts the work there.
12. **A money figure has one currency by kind.** A total is PLN, a component's unit
    price is USD, and an invoice is in its own currency. Rules are in
    [web/CLAUDE.md](../../web/CLAUDE.md).
13. **Time is stored in UTC and shown in local time.** Use `localWhen`, `localDate` and
    `localTime` from `format.ts`. Never slice an ISO string for display: that prints UTC.
14. **The screen uses the job's word.** A batch, a procedure, a device. Not run,
    deployment or unit record. The words are in the [glossary](glossary.md).
15. **An old address keeps working.** A moved page gets a `Moved` redirect in `App.tsx`,
    with its parameters. Saved links and schematics depend on it. A tab is in the URL.
16. **Check a screen on the dark theme.** Dark is the default.

## Before you report a new function as done

1. You can name the section and the page from the questions above.
2. `python3 scripts/check-ui-routes.py` passes.
3. It uses `DataTable`, `FoldSection`, `Field` and `TabStrip`, and no new CSS class
   if an existing one fits.
4. You opened it in a browser on dark, with real data, and you measured that no figure
   is cut.
5. `CHANGELOG.md` says what a user can now do, and where.
