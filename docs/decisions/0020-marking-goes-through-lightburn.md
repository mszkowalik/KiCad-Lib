---
status: "accepted"
date: 2026-09-16
decision-makers: Mateusz Kowalik
---

# Drive the laser through LightBurn and a local agent, not a direct controller driver

## Context and Problem Statement

Device serials are engraved by a fibre galvo marker. The old tool patched a
serial into a `.lbrn2` template and drove LightBurn over UDP from a desktop
application. Moving marking onto the platform raised the question of whether the
browser could drive the laser controller itself and leave LightBurn out — which
was the preferred outcome, because LightBurn is one more thing to install,
licence and keep un-modal on a bench machine.

The hardware investigation that answers it is in
[docs/reference/laser-marking.md](../reference/laser-marking.md).

## Decision Drivers

* An operator plugs in a device and wants it marked, with no manual step between.
* Nothing may be installed on machines we do not control (user constraint,
  2026-09-16) — though the laser lives on exactly one machine, which we do.
* A mark must be recorded against the device like a flash is.
* The direct path was the stated preference, so rejecting it needs evidence, not
  an opinion.

## Considered Options

* **Direct USB driver from the page (WebUSB).** No LightBurn at all.
* **Browser only, no agent.** The page patches the template and downloads it;
  the operator drags it into LightBurn and presses Start for every part.
* **Local marking agent.** A small process on the laser machine turns one HTTP
  request into LightBurn's `FORCELOAD` / `START` / `STATUS`.

## Decision Outcome

Chosen option: **the local marking agent**, because the direct driver turned out
to cost an open-ended reverse-engineering project, and the browser-only option
does not deliver the automatic flow that was the point of the work.

The direct driver was not rejected on principle. It was probed on the hardware
and failed on a fact:

* The controller is a **BSL board** (USB `04b4:1004`, "SEATHINKING SEA-LASER"),
  a Cypress FX2LP with four bulk endpoints. WebUSB can claim it — no kernel
  driver holds interface 0, and the interface was claimed from userspace.
* Its endpoint layout matches the EZCAD2 **LMC** boards that
  [galvoplotter](https://github.com/meerk40t/galvoplotter) drives, so the open
  source protocol looked like it would apply.
* **It does not.** Every LMC opcode — `GetVersion`, `GetSerialNo`,
  `GetListStatus`, `GetPositionXY`, `ReadPort` — returns the same 20-byte idle
  frame `fe ff 00 14 … fb`, reproducible across a device reset. The board speaks
  its own protocol, and the only references are LightBurn's closed
  implementation and the vendor's `bslapp`.
* Decoding it needs a USB capture of LightBurn driving the board. **This is not
  possible on the bench machine**: Apple Silicon on macOS 26 exposes no `XHC`
  capture interface, and `dumpcap -D` lists network interfaces only. It needs a
  Windows or Linux host that nobody has to hand.

So the agent is the honest path today, and the door is left open: `mark_laser`
is one op with one implementation behind it, and swapping the agent for a
direct driver later changes that op and nothing else.

### Consequences

* Good, because the whole platform side — runs, logs, history, the publish gate,
  the version editor — is reused unchanged. A marking procedure is an ordinary
  deployment version with `kind = "mark"`.
* Good, because the agent needs NOTHING INSTALLED: it is one standard-library
  Python file, which is what makes "run this on the laser machine" an
  instruction rather than a project. That is why it speaks plain HTTP and polls
  rather than using a WebSocket — the library was the whole obstacle.
* Good, because the agent holds no token, makes no outbound connection, and
  never reads the artwork. It receives a finished `.lbrn2` and points LightBurn
  at it, so a bench running an old agent still marks whatever the platform sends.
* Good, because the agent checks the `Origin` of every connection. Chrome's
  Local Network Access prompt is asked once, and after that any page the
  operator visits could reach `127.0.0.1` — the allow-list is what stops a
  random website starting a laser.
* Bad, because the laser bench now needs LightBurn running and un-modal. The
  agent reports both hops separately, because "agent down" and "LightBurn not
  answering" are fixed in different places.
* Bad, because a mark is **operator-confirmed, not machine-proven** until
  `STATUS` is verified to report busy during a real job. LightBurn answered `OK`
  to `STATUS` and `START` with no laser attached (measured 2026-07-26), so
  neither confirms that anything was engraved.
* Bad, because Chrome blocks the loopback connection by default. The bench
  profile carries `LoopbackNetworkAccessAllowedForUrls` so a configured bench
  never prompts.

### Confirmation

The bench page reaches the agent and reports LightBurn's state — verified
headless against the real agent on 2026-09-16, which correctly reported "the
agent is running, but LightBurn is not answering". A mark run stores its log and
its `marked` value on the run like any other procedure.

Revisit this decision only with a USB capture in hand. Re-probing the board
without one repeats work that has been done and recorded.
