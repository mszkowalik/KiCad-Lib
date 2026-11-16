---
status: accepted
date: 2026-11-16
decision-makers: Mateusz Kowalik
consulted: the RaveAggregator agent session (it runs the server's observability platform)
---

# Expose henry-api's metrics for Prometheus on a port of their own, for the server's Grafana

## Context and Problem Statement

The server runs one observability platform for all services (Grafana at
`obs.disfunction.cc`, VictoriaMetrics, Loki and Alloy, documented in the
server's `HOMELAB.md` §16). It already collects every container's logs, CPU
and memory, the nginx access log of `henry.disfunction.cc`, and Henry's
Postgres and MinIO. It cannot see inside henry-api: which routes are called
and how fast, how long SQL takes, how many people use the platform, and what
agents call. The user asked for these figures for every service.

## Decision Drivers

* `/metrics` must not be public, and must not need a token the scraper would
  have to hold.
* The label sets must stay small: the server has about 4 GB of memory free.
* No new process or container if one library in henry-api does it.

## Considered Options

* A: `prometheus_client` in henry-api, served on its own port (9100) in a
  thread, scraped over the docker network only.
* B: `/metrics` as an API route behind the gate, with a token for the scraper.
* C: derive everything from the nginx access log and the database exporter.

## Decision Outcome

Chosen option: A, because a port that only the docker network reaches needs no
credential and no exemption in the gate, and the library adds no process.

1. `services/metrics.py` serves on port 9100: a request histogram by method,
   ROUTE TEMPLATE, status, signed-in or not, and client (`mcp` or `other`); an
   SQL histogram by statement kind; a count of statements of 1 s or more, each
   logged as `slow query` with its request path; a counter per agent tool; and
   gauges read from Postgres on each scrape (accounts, active users and
   sessions in 15 min / 24 h / 7 d, sign-ins today, live OAuth tokens,
   feedback reports).
2. **No label carries a raw path, an id or a user name.** A request refused by
   the gate before routing is named by the template it would have matched.
3. henry-api is one uvicorn process. A second worker would need
   `prometheus_client`'s multiprocess mode, or each scrape sees one worker.
4. The server's compose file asks to be scraped (`obs.scrape`, `obs.port`,
   `expose: 9100`). nginx does not proxy the port.
5. The dashboards are files in the server's
   `observability/grafana/dashboards/Henry/`, made by a script there.

### Consequences

* Good, because routes, SQL time, users and agent use are visible beside the
  other services, for 90 days.
* Good, because `/metrics` adds no route, no token and no gate exemption.
* Bad, because every request and every SQL statement now costs a histogram
  observation (microseconds).
* Bad, because the gauges run a few COUNT queries every 15 seconds.

### Confirmation

On dev, `http://127.0.0.1:9100/metrics` in the api container lists the
request, SQL, tool and gauge series. A refused request is labelled with its
template (`/api/runs/{run_id}`), not `unmatched`. In production, Grafana's
Henry folder shows the series.

## Pros and Cons of the Options

### B: a route behind the gate

* Bad, because the scraper would hold a Henry token, and a route would be one
  more thing the gate and the UI-route check must account for.

### C: logs and exporters only

* Good, because henry-api would not change.
* Bad, because the access log has no route template, no SQL time and no user
  counts, and it does not see in-process agent calls.

## More Information

* The server side: `~/aws-deployment/HOMELAB.md` §16 and `CHANGELOG.md`.
