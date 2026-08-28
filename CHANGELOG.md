# Changelog

This file starts on 2026-08-28. For earlier work, read the git history.

Each entry says what changed and why. Put a note here when a change alters how
the platform behaves in production, not for every commit.

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
