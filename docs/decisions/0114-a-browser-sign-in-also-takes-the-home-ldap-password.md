---
status: accepted
date: 2026-11-24
decision-makers: Mateusz Kowalik
---

# Let a browser sign-in also take the home LDAP password

## Context and Problem Statement

The server runs one home directory: lldap with Authelia
(`docker-compose.auth.yml` and `HOMELAB.md` "Single sign-on" in the deployment
repository). Jellyfin, Nextcloud, Grafana and qBittorrent sign in with it.
Mateusz asked on 2026-11-24 that he and Kuba also sign in to Henry with their
directory accounts (`mateusz`, `kuba`). Henry had local argon2 passwords only.

## Decision Drivers

* Henry is on the internet (decision 0101). The directory and Authelia are LAN
  and Tailscale only.
* Accounts, roles and company memberships are made by an admin in Henry, and
  only there (user decision 2026-07-31, decision 0063).
* A directory outage must not lock the only admin out.
* KiCad, the sync plugin and the MCP server use personal API tokens, which must
  not change.

## Considered Options

* An LDAP bind in `POST /api/auth/login`, for accounts an admin linked to a uid.
* Authelia forward auth in nginx in front of `henry.disfunction.cc`.
* Accounts made in Henry from the directory on the first sign-in, with the role
  from a directory group.

## Decision Outcome

Chosen option: "an LDAP bind in the login, for linked accounts", because it
changes one endpoint and keeps every rule about who has an account.

* `users.ldap_uid` links one Henry account to one directory uid. An admin sets
  it in Admin → Users. Empty means local password only.
* The login takes the Henry username or the linked uid. For a linked, active
  account Henry binds as a read-only service account, searches
  `(&(uid=<uid>)<LDAP_USER_FILTER>)`, and binds as the DN it finds with the
  typed password. The filter holds the group condition (lldap group `henry`).
* If the bind fails, the local password is checked. Both work.
* An empty password is refused before any network call (unauthenticated bind,
  RFC 4513 §5.1.2).
* The lockout counts failures per account, whichever of its two names was
  typed. The audit row `auth.login` records `via: ldap` or `via: password`.
* Henry never makes, changes or removes an account, a role or a membership from
  the directory. A password change in Henry changes the local password only.
* Configuration: `LDAP_URL`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` (or
  `LDAP_BIND_PASSWORD_FILE`), `LDAP_USER_BASE`, `LDAP_USER_FILTER`,
  `LDAP_TIMEOUT_S`. Empty `LDAP_URL` turns it off. On the server Henry uses
  `ldap://lldap:3890` on the shared docker network.

Rejected:

* **Authelia forward auth** puts a second login page in front of Henry, and
  Authelia is not reachable from the internet. It would also need a
  token-carrying exception for every KiCad, sync-plugin, device and MCP path,
  which is the default-deny gate written a second time in nginx.
* **Accounts made from the directory** would give the directory the power to
  make a Henry admin. That reverses the 2026-07-31 decision that an admin makes
  every account, and a directory group would then hold the deployment.

### Consequences

* Good, because Mateusz and Kuba use one password for Henry and the home
  services, and a password change in lldap reaches Henry at once.
* Good, because a directory fault falls back to the local password, and an
  unlinked account behaves exactly as before.
* Bad, because a directory password can now be tried from the internet through
  Henry's login. Only Henry's lockout (8 failures, 15 min) protects it, and the
  same password opens Nextcloud, Jellyfin and qBittorrent.
* Bad, because a linked account answers a wrong password more slowly than an
  unlinked one (two binds), so response time shows that a uid is linked.
* Neutral: a new dependency, `ldap3` (pure Python, LGPL-3.0, used as a library).

### Confirmation

`api/tests/auth/test_ldap_login.py`: uid and username both sign in with the
directory password; the local password still works; an unlinked or deactivated
account never reaches the directory; failures lock the account under either
name; an empty password is refused without a network call; a uid is cleaned
and unique. On the server: a wrong password answers 401, the right one 200 with
`via: ldap` in the audit log, and a uid outside group `henry` is refused.
