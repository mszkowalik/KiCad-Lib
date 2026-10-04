---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Read both companies' invoices from KSeF into an inbox, and let agents file them

## Context and Problem Statement

KSeF, the national e-invoice system, holds every Polish invoice both companies
issue and receive. 7Sigma's script already read it (API 2.0, a read-only
token kept in the macOS keychain). The user's answers of 2026-10-04:

* Start read-only (answer 8). Only download from KSeF for 9SIGMA (answer 10).
* The user adds a token for each company, and Polish invoices then come in
  without anybody typing them. Foreign invoices are added by agents.
* The MCP server must let agents add the invoices and assign them properly.
* 7Sigma's sales invoices are drafted on the platform and uploaded to KSeF by
  hand ([0066](0066-the-platform-issues-7sigmas-sales-invoices.md)).

## Decision Drivers

* Reading KSeF never moves money: a fetched purchase changes no figure until
  somebody decides what it is.
* A token that reads every invoice of a company is guarded like the fleet
  broker's credential.
* KSeF's limits (20 metadata queries an hour) are spent on purpose, and a long
  limit is reported, never slept through.
* An agent goes through the same checks as a person.

## Considered Options

* Import each fetched invoice straight into the register.
* Fetch into an inbox; link sales, import purchases on request.
* A timer that syncs on its own, or a sync an admin starts.

## Decision Outcome

Chosen options: "fetch into an inbox" and "a sync an admin starts". A purchase
imported straight into the register would put unassigned money in it for every
invoice nobody has looked at, and an invoice the platform already holds by hand
would be doubled. A timer would spend the hourly limit whether or not anybody
needs the data; it can be added once the use is known.

1. **One KSeF token per company**, Fernet-encrypted (`ksef_credentials`),
   admin-only, write-only: the API says whether one is set, never what it is.
   Never an environment variable or a configuration knob.
2. **The client is the script's**: the token and the challenge timestamp
   encrypted with the Ministry's `KsefTokenEncryption` key (RSA-OAEP,
   SHA-256), the metadata query in windows of 90 days, the XML per invoice. A
   short 429 is waited out; a long one stops the sync and records until when.
3. **A sync fills the inbox** (`ksef_invoices`) and downloads the XML to
   MinIO. It resumes a week before the newest issue date it read; the first
   one starts when KSeF 2.0 did (2026-02-01).
4. **A sales invoice is linked by the sync.** For 7Sigma it is matched to the
   document of the same series and number: a draft becomes issued, with KSeF's
   number and the hash from the metadata, which prints the QR code, and the
   record takes KSeF's figures. A draft whose number KSeF holds for another
   buyer is not linked and the sync says so. An invoice written directly in
   KSeF becomes a record of its own. For 9SIGMA every sales invoice is recorded,
   for reading only. The numbering counts the numbers KSeF holds before their
   XML arrives.
5. **A purchase waits** until a person or an agent imports it as a supplier
   document billed to that company (its positions without destinations, the
   XML filed with it) or skips it with a reason. A document already holding
   its KSeF number, or the same seller NIP and number, is linked, not doubled.
6. **Agents get invoice tools** over MCP: list and read supplier invoices,
   create one KSeF does not hold, assign a position, list the KSeF inbox,
   import from it, list sales invoices and draft one for 7Sigma. Each runs the
   website's route functions, so the same guards apply, and each sees only the
   token user's companies. A local MCP tool files an invoice's original from
   the user's disk.

### Consequences

* Good, because every Polish invoice of both companies reaches the platform
  from one place, with its legally binding XML.
* Good, because the monthly invoice is closed by the sync: the draft becomes
  issued with its QR code without retyping the KSeF number.
* Bad, because a sync is a button press; nothing reads KSeF on its own yet.
* Bad, because the client has not met the real KSeF from the platform yet: it
  is the script's, tested against a fake. The first sync with a real token is
  its first real run.
* Neutral, because sending invoices to KSeF stays outside the platform.

### Confirmation

Tests show that the token is encrypted for the Ministry's key and the access
token is used for the query, that a long limit raises instead of sleeping, that
a sync links a draft and issues it with KSeF's hash, records an invoice KSeF
alone holds and takes its number out of the series, leaves a purchase in the
inbox until it is imported, refuses a second import, does not link a draft whose
number KSeF gave another buyer, and that an FA(3) invoice reads back to the same
document.

## Pros and Cons of the Options

### Import straight into the register

* Good, because nothing waits.
* Bad, because unreviewed money lands in the register, and hand-entered
  invoices double.

### An inbox

* Good, because fetching is harmless and importing is a decision.
* Bad, because somebody has to work the inbox.

### A timer, or an admin's sync

* Good (timer), because the data is always fresh.
* Bad (timer), because it spends the hourly limit for nobody.

## More Information

The rules are in [docs/reference/ksef.md](../reference/ksef.md).
