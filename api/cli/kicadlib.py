#!/usr/bin/env python3
"""kicadlib — sync the 7Sigma KiCad library from the platform to this machine.

Stdlib only; works with any Python 3.9+.

Usage:
    python3 kicadlib.py sync --url http://localhost:8020 --dest ~/7SigmaLib
    python3 kicadlib.py sync --url https://disfunction.cc/lib --dest ~/7SigmaLib --prune

What it does:
  * downloads the platform's published file mirror (Symbols/*.kicad_sym,
    Footprints/7Sigma.pretty/, 3DModels/) into --dest, incrementally —
    only files whose sha256 differs are transferred
  * with --prune, removes local files that no longer exist upstream
  * prints the KiCad setup instructions when done

KiCad setup (one-time, printed again after every sync):
  1. Preferences > Configure Paths: SEVENSIGMA_DIR = <dest>
  2. Preferences > Manage Symbol Libraries: add each <dest>/Symbols/*.kicad_sym
     (nickname = file name, e.g. "Resistor")
  3. Preferences > Manage Footprint Libraries: add
     <dest>/Footprints/7Sigma.pretty with nickname "7Sigma"
  4. For the live part catalog, add the .kicad_httplib file (download it from
     the platform's KiCad page) as a symbol library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MANAGED_DIRS = ("Symbols", "Footprints", "3DModels")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kicadlib-sync/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sync(base_url: str, dest: Path, prune: bool) -> int:
    base_url = base_url.rstrip("/")
    manifest = json.loads(_get(f"{base_url}/files/manifest.json"))
    files = manifest["files"]
    print(f"manifest: {len(files)} files, generated {manifest.get('generated_at', '?')}")

    dest.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = 0
    wanted: set[str] = set()
    for entry in files:
        rel = entry["path"]
        wanted.add(rel)
        target = dest / rel
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _get(f"{base_url}/files/{urllib.parse.quote(rel)}")
        got = hashlib.sha256(data).hexdigest()
        if got != entry["sha256"]:
            print(f"  WARNING: checksum mismatch for {rel} — server-side update mid-sync? re-run sync")
        target.write_bytes(data)
        downloaded += 1
        if downloaded % 100 == 0:
            print(f"  ... {downloaded} downloaded")

    pruned = 0
    if prune:
        for managed in MANAGED_DIRS:
            root = dest / managed
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.relative_to(dest).as_posix() not in wanted:
                    f.unlink()
                    pruned += 1

    print(f"done: {downloaded} downloaded, {skipped} up-to-date"
          + (f", {pruned} pruned" if prune else ""))
    print(f"""
KiCad setup (once):
  1. Preferences > Configure Paths:  SEVENSIGMA_DIR = {dest}
  2. Manage Symbol Libraries: add the libraries in {dest / 'Symbols'}
  3. Manage Footprint Libraries: add {dest / 'Footprints' / '7Sigma.pretty'} as nickname "7Sigma"
  4. Live catalog: download the .kicad_httplib from {base_url.replace('/files', '')}
     (KiCad page in the web UI) and add it as a symbol library.""")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kicadlib", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="download/update the library files from the platform")
    s.add_argument("--url", required=True, help="platform base URL, e.g. http://localhost:8020")
    s.add_argument("--dest", required=True, help="local library directory, e.g. ~/7SigmaLib")
    s.add_argument("--prune", action="store_true",
                   help="delete local files that no longer exist upstream")
    args = ap.parse_args()
    if args.cmd == "sync":
        return sync(args.url, Path(args.dest).expanduser().resolve(), args.prune)
    return 1


if __name__ == "__main__":
    sys.exit(main())
