---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# A device fetches from its own address, and on this deployment that address is plain HTTP

## Context and Problem Statement

Step 16 of `Dongle_V2 config` tells the device to fetch its berry scripts from
the platform with `UrlFetch`. Run 6340 was the first run in which that step ever
executed on production. It failed on every retry with `TLS connection error
296`.

The URL came from `public_base_url`, which production sets to
`https://disfunction.cc/lib`. The log says so:

```
base_url = https://disfunction.cc/lib (from public_base_url)
```

A day of measurement on a Dongle V2 established what the device can and cannot
do. Two passes, identical results:

| URL given to the device | Result |
|---|---|
| `http://disfunction.cc/…` | Done, Done |
| `https://disfunction.cc/…` | Failed, Failed |
| `http://188.114.96.3/…` (the edge, by IP) | Failed, Failed |
| `http://192.168.200.28/…` (the LAN nginx, by IP) | Done, Done |

Against the Cloudflare edge the device completed **0 of about 12** HTTPS
attempts. Against unrelated hosts it completed some and not others — Google 2 of
4, GitHub 1 of 3. So the failure is not "Tasmota cannot do HTTPS". It is this
device and this edge, and it is total.

Ruled out by direct test, so that nobody repeats them:

* **The certificate authority.** Cloudflare Universal SSL does not allow the CA
  to be pinned without Advanced Certificate Manager. Replacing the LAN
  certificate changed nothing, because the edge terminates TLS.
* **`SetOption132`.** It governs MQTT TLS only. It has no effect on `UrlFetch`.
* **Memory.** A clean boot reports about 205 kB free. The failure is identical
  with the heap at its largest.
* **Chain size and User-Agent.** The edge answers `200` to `TasmotaClient` over
  plain HTTP, so nothing is blocking the client by name.

One fact reframes the whole question. **Tasmota's HTTP client accepts any
certificate.** It performs no validation. So HTTPS was never giving the device
an authenticated peer — it was giving it an encrypted channel to an unverified
one, at the price of a handshake it cannot complete.

The platform's public address is also not negotiable: `PUBLIC_BASE_URL` is what
generated symbols embed in datasheet links, and browsers, KiCad and the MCP
server all use it. It must stay `https`.

## Decision Drivers

* A device must be programmable anywhere with internet, not only on the home
  LAN. Stated by the user: "we have no certainty that the devices will be
  programmed in my home network."
* The browser address and the device address are answers to different
  questions. One value cannot serve both when a device cannot reach it.
* One place to set it. A new project must not have to remember it.
* The bench agent binds `127.0.0.1` only, and that is not negotiable
  (`bench_agent/CLAUDE.md`). A laser is not a thing to expose to a LAN.

## Considered Options

1. **Keep HTTPS and make the device cope.** Rejected on the measurement: 0 of
   about 12.
2. **Serve the files from the LAN nginx with a Let's Encrypt certificate, and
   split-horizon DNS.** Rejected. It ties programming to one network, which is
   the constraint the user removed.
3. **Serve the files from the bench agent over the LAN.** Rejected. It requires
   widening the agent's bind address.
4. **Set `base_url` in each project's parameter set.** Works today and needs no
   deploy, because a parameter is the first candidate in `_resolve_base_url`.
   Rejected as the permanent answer: it is three copies of one address, a new
   project forgets it, and the Parameters page marks it `unused` because
   `base_url` is a runtime variable no version declares.
5. **Derive the device address by rewriting `https` to `http` automatically.**
   Rejected. Downgrading a transport is a decision, and a decision that happens
   silently is one nobody can audit.
6. **A `DEVICE_BASE_URL` setting, ranked above `public_base_url`.** Chosen.

## Decision Outcome

Chosen: option 6. `config.device_base_url` is a new setting, empty by default,
and `_resolve_base_url` weighs it between the parameter and `public_base_url`.
Production sets it to `http://disfunction.cc/lib`. Every other deployment leaves
it empty and behaves exactly as before.

The candidate order is now: a parameter set that says so on purpose, then the
device address, then the public address, then the two addresses the bench
reports.

Nothing else changes. No published version overrides the download URL, so all
three deployments are fixed by one value with no re-publish.

Verified against the real endpoint before the change shipped:

```
http://disfunction.cc/lib/api/flasher/files/107/mateodongle_config.be
  200, 12321 bytes, sha256 991b361d0caa5c1ed881784d978b0aa95ed1b9d89b85d763010d732a8bbe98e1
```

That hash is the one stored in `device_file_versions`. The plain-HTTP path
serves the same bytes, and the edge does not redirect, because "Always Use
HTTPS" is off on the zone.

### Consequences

* Good: a device is programmable from any network with internet. No split DNS,
  no certificate to renew, no agent bind change, no firmware change.
* Good: the two addresses are now separate settings, so the next person can see
  that a device and a browser were given different answers on purpose.
* Bad, and stated plainly: **the berry scripts cross the internet in the clear.**
  The endpoint is unauthenticated by design and the files are device
  configuration rather than secrets, so this is an exposure to TAMPERING, not to
  disclosure.
* Bad: `_download_files` verifies the byte COUNT only, not the sha256. A
  substitution of the same length would pass. The hash is already in the run
  spec (`engine.py`, the `files` block), and the device can compute one in
  Berry, so closing this is a small change to one step. It is not part of this
  decision, and until it lands the gap above is real.
* Neutral: HTTPS was already unauthenticated for this client, because Tasmota
  validates no certificate. Moving to HTTP removes encryption. It removes no
  guarantee the device was ever checking.
