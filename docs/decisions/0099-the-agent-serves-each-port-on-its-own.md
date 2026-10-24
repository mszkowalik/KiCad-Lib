---
status: accepted
date: 2026-10-24
decision-makers: Mateusz Kowalik
consulted: Claude (code review of the bench agent, bench runs 8957 to 8995)
informed: bench operators
---

# Serve each port on its own: a console per port, an esptool process per job, and the flash images kept on the bench machine

## Context and Problem Statement

The bench page offers four stations, but the bench agent served one. It had one
console slot and one esptool job for the whole machine
([work list](../todo.md) rows 49 and 51):

* A second station's console closed the first one's. The console routes named
  no port, so a call went to whichever console was open. Runs 8964 and 8966
  (2026-10-24) both failed with "tx failed: the monitor is not open".
* A second esptool job was refused with "the agent is already programming a
  device" (runs 8957, 8958, 8968).
* esptool ran as a library in a thread, with the process-wide `sys.stdout`
  swapped for each job. Two jobs at once would mix their logs, and Python
  cannot stop a thread from outside. Abort ended the run on the platform, and
  the agent went on erasing or writing the unit.

Each unit also fetched the same 2.46 MB factory image from the platform and
sent it to the agent again: 2.5 s and 0.9 s of run 8994.

## Decision Drivers

* The operator wants at least four stations to program at the same time.
* Abort, Abort during Erase and "Stop waiting" must stop esptool within 2 s.
* The agent stays standard library plus `vendor.zip`. It holds no platform
  token and makes no outbound connection
  ([bench_agent/CLAUDE.md](../../api/app/services/bench_agent/CLAUDE.md)).
* The agent is downloaded, not deployed. An old agent meets a new page, and a
  new agent meets an old page, for weeks.

## Considered Options

1. State per port in one agent, and one esptool PROCESS per esptool call.
2. State per port, and esptool kept in threads.
3. One agent process per station, each on its own HTTP port.
4. The agent fetches firmware from the platform itself, by URL.

## Decision Outcome

Chosen option: 1, with the image cache on both ends, because it is the only
option that gives separate logs, a cancel that works, and no change to how an
operator installs and starts the agent.

1. The agent keeps a console per port and an esptool job per port. Every
   console route names its port. A call for a port with no open console fails.
   A call without a port (a page from before this) reaches a console only when
   exactly one is open.
2. Each esptool call runs as `python -m esptool` in its own process, with the
   vendored tree on `PYTHONPATH`. Its output is read line by line into the job
   log. `POST /esp/cancel` kills the process and ends the connect ladder. The
   process costs 0.06 s to start (measured 2026-10-24, macOS Python 3.9.6).
3. A flash request names each image by SHA-256. The agent keeps the images it
   was given in `~/Library/Caches/7Sigma Agent/images/<sha256>.bin`, checks
   the hash on every write and every use, and drops the least recently used
   beyond 100 MB. A request for an image it lacks is refused before a job
   exists, with `missing`; the page then sends those bytes once.
4. The page keeps fetched firmware (by SHA-256) and marking artwork (by set and
   name) in Cache Storage. The platform serves both with
   `Cache-Control: private, max-age=31536000, immutable`.
5. `PROTOCOL_VERSION` is 5. `/hello` reports `per_port`, `esp_cancel` and
   `image_cache`, and the page asks for these capabilities, not the number.
   With an agent that lacks `per_port`, the page lets one station work at a
   time: a press takes a synchronous claim, and the other stations wait.
6. `/serial-ports` reports each node's USB serial number. An ESP32-C6 reports
   its MAC there. The page counts a NEW device by that number (or by a socket
   left empty for 6 s), so a C6 that leaves the bus on its own resets is not
   run again by Automatic.

### Consequences

* Good, because four stations can program at once, each with its own log.
* Good, because Abort stops the agent's esptool, and the port is free for the
  next job at once.
* Good, because a unit no longer waits for the same 2.5 MB twice. The bytes
  cross the network once per browser and loopback once per machine.
* Good, because a failed connect no longer leaves the port open in the agent:
  the process that held it is gone. `release_own_port` stays for the console.
* Bad, because the agent now depends on the text esptool prints when it fails
  ("A fatal error occurred: …"), where it caught the exception before. A
  different esptool in `vendor.zip` must be checked against `esptool_failure`.
* Bad, because an operator must download the agent again to run several
  stations. Until then the page says so and runs one station at a time.
* Neutral, because the cache directory grows to 100 MB on each bench machine.

### Confirmation

* `api/tests/flasher/test_agent_stations.py`: two ports at once with separate
  logs, a refusal on the same port, cancel within 2 s during a write and
  during the BOOT wait, one console per port, the idle watch per port, and the
  image cache.
* A browser check (2026-10-24) of the real bench page and the local engine
  against a stand-in agent: two stations started by Automatic within the same
  second and wrote at the same time, a 3 s reset of the same unit started
  nothing, a new unit started a run, Abort sent one cancel, and an old agent
  ran the stations one after the other.
* Still open: the bench test with four CE_Dongle_V3 units that row 49 asks for.

## Pros and Cons of the Options

### State per port, esptool in threads

* Good, because no process starts.
* Bad, because `contextlib.redirect_stdout` swaps one global, so two jobs mix
  their logs, and whether esptool 4.8.1 keeps other module state that two
  threads share was never checked.
* Bad, because a thread cannot be stopped, so Abort cannot stop esptool.

### One agent per station

* Good, because the code would not change.
* Bad, because an operator would start four programs on four HTTP ports, and
  Chrome asks for local-network access per origin and port.
* Bad, because the printer, LightBurn and the status page belong to the
  machine, not to a station, and would be served four times.

### The agent fetches the firmware itself

* Good, because the page would send nothing.
* Bad, because the agent would need a platform token and an outbound
  connection, which are the two things it is designed not to have.

## More Information

* Decision [0023](0023-the-agent-programs-the-device.md) moved esptool and the
  console into the agent. This record keeps that and changes how the agent
  runs them.
* The command echo defect found on the same bench (row 50) is fixed in the
  engine (`protocol.is_echo`), not here.
