"""Returning freed memory to the OS after the big-blob sweeps.

The datasheet sweeps are careful at the Python level — one `data` blob in the
session at a time, expunged straight after (see `_classify_worker`). That is
not enough. They run in daemon *threads*, and glibc gives every thread its own
malloc arena that grows in 64 MB heaps. A freed 30 MB PDF goes back to that
arena's free list, never to the kernel, and the next blob lands on a fresh
heap because the free chunk does not fit it. On 2026-08-28 the API container
was holding 67 such heaps — 4.2 GB of arena for ~48 MB of live objects, which
filled all 3.8 GB of swap and dragged the whole host down.

Two halves, and both are needed:

- `MALLOC_ARENA_MAX=2` (set in the Dockerfile) caps how many arenas exist, so
  the sweeps stop spraying allocations across a new heap per thread.
- `trim()` below is the half that actually gives memory back. `malloc_trim(0)`
  walks every arena and releases the free pages at the top of each heap.
  Python's own `gc.collect()` does NOT do this — it frees objects into the
  allocator and stops there.

Call it after each item of a sweep over large blobs, never in a hot loop:
it walks all arenas and costs milliseconds.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging

log = logging.getLogger(__name__)

_malloc_trim = None
_probed = False


def _resolve():
    """Look up malloc_trim once. Absent on musl and on non-Linux, where the
    call is simply a no-op rather than an error."""
    global _malloc_trim, _probed
    if _probed:
        return _malloc_trim
    _probed = True
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        fn = libc.malloc_trim
        fn.argtypes = [ctypes.c_size_t]
        fn.restype = ctypes.c_int
        _malloc_trim = fn
    except (OSError, AttributeError) as e:
        log.info(f"malloc_trim unavailable, memory trimming disabled: {e}")
        _malloc_trim = None
    return _malloc_trim


def trim() -> bool:
    """Release free heap pages back to the OS. True when memory was returned."""
    fn = _resolve()
    if fn is None:
        return False
    try:
        return bool(fn(0))
    except Exception:  # noqa: BLE001 — trimming must never break a caller
        return False
