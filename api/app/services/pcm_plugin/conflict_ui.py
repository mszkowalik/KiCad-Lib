"""Sync's local-changes window — one window for every drawing sync would touch.

A row is ONE item — a symbol entry inside the generated symbol library, a
footprint file, or a single 3D model — that no longer matches what sync last
wrote here. Never a whole library: releasing 196 symbols on one click was the
old behaviour for a library file upstream had stopped carrying. Its `note` says why
it is being asked about — the platform changed it too, only this machine
changed it, or it exists only here — and the answer is the same either way:
keep mine, or take the platform's copy. Before this module the local copy always
won, in silence and for ever: there was no way to take the platform's version
short of deleting the file by hand, so an approved fix could never come back
down, and an experiment made locally could never be abandoned.

The unit is the DRAWING, not the file — see kicad_canon.py. A conflict is only
raised when the canonical forms genuinely differ, so a KiCad re-save in its own
spelling never asks a question. 3D models carry no canonical form, so they are
compared by sha behind a size/mtime pre-filter — see `_model_edits` in sync.py.

Three backends, tried in order, so a missing dependency degrades instead of
failing:

1. wxPython — real per-row Mine/Server radio buttons. KiCad ships wx, and the
   plugin venv normally sees it.
2. AppleScript `choose from list` — one tick column, ticked = take the
   platform's version. macOS only. Same mechanism Push already uses.
3. Neither available — keep every local copy, exactly as sync behaved before.

**Cancelling, closing the window and every failure path all resolve to "mine"**
for every conflict. Losing an unsent drawing because a dialog would not open is
not an acceptable outcome; refusing an update is.
"""
from __future__ import annotations

import os
import subprocess
import sys

MINE = "mine"
SERVER = "server"

# The wx list scrolls, so it stays usable far longer than AppleScript's
# `choose from list`, which cannot be scrolled sensibly at all. Two ceilings,
# because collapsing 300 per-item rows into "kept everything" is a worse answer
# than a long window the user can scroll.
_SANE_ROWS = 200        # AppleScript backend only
_WX_MAX_ROWS = 600      # above this the grid costs more widgets than it is worth


def _label(c: dict) -> str:
    """What the user sees for one row. Symbols are tagged because a symbol name
    and a footprint name can otherwise look identical."""
    name = c["name"]
    if c["kind"] == "symbol":
        name += " (symbol)"
    elif c["kind"] == "model":
        name += " (3D model)"
    note = _note(c)
    return f"{name} — {note}" if note else name


def _note(c: dict) -> str:
    """Why this row is here, plus the warning that answering "server" on a
    drawing the platform does not have means deleting it."""
    note = c.get("note") or ""
    if c.get("delete"):
        note = (note + " — " if note else "") + "server = DELETE it"
    return note


def _all_mine(conflicts: list[dict]) -> dict[str, str]:
    return {c["key"]: MINE for c in conflicts}


# --------------------------------------------------------------------------
# backend 1 — wxPython
# --------------------------------------------------------------------------

def _resolve_wx(conflicts: list[dict]) -> dict[str, str] | None:
    """Real dialog. Returns None when wx is unusable, so the caller falls back."""
    try:
        import wx
    except Exception:
        return None

    try:
        app = wx.App.Get() or wx.App(False)  # a plugin process owns no app yet
    except Exception:
        return None

    try:
        return _run_wx_dialog(wx, conflicts)
    except Exception:
        return None
    finally:
        # Never call app.Destroy() — if KiCad itself owned the app we would
        # take its UI down with us.
        del app


def _run_wx_dialog(wx, conflicts: list[dict]) -> dict[str, str]:
    n = len(conflicts)
    title = f"7Sigma Sync — {n} conflict" + ("" if n == 1 else "s")
    dlg = wx.Dialog(None, title=title,
                    style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP)

    outer = wx.BoxSizer(wx.VERTICAL)
    intro = wx.StaticText(dlg, label=(
        f"{n} drawing{'' if n == 1 else 's'} on this machine no longer match the "
        "platform.\nPick which version to keep. \"Mine\" leaves your file "
        "untouched — use Push to send it.\n\"Server\" throws your version away "
        "and takes the platform's."))
    outer.Add(intro, 0, wx.ALL, 12)

    scroll = wx.ScrolledWindow(dlg, style=wx.VSCROLL)
    scroll.SetScrollRate(0, 12)
    grid = wx.FlexGridSizer(cols=4, vgap=4, hgap=16)
    grid.AddGrowableCol(1, 1)

    buttons: dict[str, tuple] = {}
    for kind, heading in (("footprint", "Footprints"), ("symbol", "Symbols"),
                          ("model", "3D models")):
        rows = [c for c in conflicts if c["kind"] == kind]
        if not rows:
            continue
        header = wx.StaticText(scroll, label=heading)
        header.SetFont(header.GetFont().Bold())
        grid.Add(header, 0, wx.TOP, 8)
        grid.Add(wx.StaticText(scroll, label=""), 0, wx.TOP, 8)
        grid.Add(wx.StaticText(scroll, label="Mine"), 0, wx.TOP, 8)
        grid.Add(wx.StaticText(scroll, label="Server"), 0, wx.TOP, 8)
        for c in rows:
            grid.Add(wx.StaticText(scroll, label=c["name"]), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            why = wx.StaticText(scroll, label=_note(c))
            why.SetForegroundColour(
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
            grid.Add(why, 0, wx.ALIGN_CENTER_VERTICAL)
            # RB_GROUP opens a new radio group, so each row is independent
            mine = wx.RadioButton(scroll, label="", style=wx.RB_GROUP)
            server = wx.RadioButton(scroll, label="")
            mine.SetValue(True)  # safe default: never silently drop unsent work
            grid.Add(mine, 0, wx.ALIGN_CENTER)
            grid.Add(server, 0, wx.ALIGN_CENTER)
            buttons[c["key"]] = (mine, server)

    scroll.SetSizer(grid)
    scroll.SetMinSize((720, min(380, 90 + 26 * n)))
    outer.Add(scroll, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

    bulk = wx.BoxSizer(wx.HORIZONTAL)
    keep_all = wx.Button(dlg, label="Keep all mine")
    take_all = wx.Button(dlg, label="Take all server")
    bulk.Add(keep_all, 0, wx.RIGHT, 8)
    bulk.Add(take_all, 0)
    outer.Add(bulk, 0, wx.ALL, 12)

    def _set_all(which):
        def handler(_evt):
            for m, s in buttons.values():
                (s if which == SERVER else m).SetValue(True)
        return handler

    keep_all.Bind(wx.EVT_BUTTON, _set_all(MINE))
    take_all.Bind(wx.EVT_BUTTON, _set_all(SERVER))

    std = dlg.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
    ok = dlg.FindWindowById(wx.ID_OK, dlg)
    if ok:
        ok.SetLabel("Apply")
    outer.Add(std, 0, wx.EXPAND | wx.ALL, 12)

    dlg.SetSizerAndFit(outer)
    dlg.CentreOnScreen()
    _front()
    dlg.Raise()
    result = dlg.ShowModal()
    decisions = ({k: (SERVER if s.GetValue() else MINE) for k, (m, s) in buttons.items()}
                 if result == wx.ID_OK else _all_mine(conflicts))
    dlg.Destroy()
    return decisions


def _front() -> None:
    """Best effort: pull this process's window in front of KiCad. A plugin runs
    as a plain subprocess, so macOS does not foreground it automatically and the
    dialog can open behind the editor. Failure here is cosmetic."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             "tell application \"System Events\" to set frontmost of "
             f"(first process whose unix id is {os.getpid()}) to true"],
            check=False, timeout=5, capture_output=True,
        )
    except Exception:
        pass


# --------------------------------------------------------------------------
# backend 2 — AppleScript
# --------------------------------------------------------------------------

def _resolve_osascript(conflicts: list[dict]) -> dict[str, str] | None:
    """One tick column: ticked means take the platform's version.

    `choose from list` cannot draw two columns, so the question is inverted
    into a single binary. Nothing is ticked to start with, which makes Return
    the safe answer.
    """
    if sys.platform != "darwin":
        return None

    labels = [_label(c) for c in conflicts]
    by_label = {_label(c): c["key"] for c in conflicts}
    lst = "{" + ", ".join('"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
                          for s in labels) + "}"
    n = len(conflicts)
    prompt = (f"{n} drawing{'' if n == 1 else 's'} here no longer match the "
              "platform. Tick the ones to REPLACE with the platform version, "
              "discarding your copy. Unticked keeps yours — use Push to send it.")
    script = (
        f"set L to {lst}\n"
        f'set picked to choose from list L with title "7Sigma Sync conflicts" '
        f'with prompt "{prompt}" with multiple selections allowed '
        f'with empty selection allowed '
        f'OK button name "Apply" cancel button name "Keep all mine"\n'
        "if picked is false then return \"\"\n"
        "set AppleScript's text item delimiters to linefeed\n"
        "return picked as text"
    )
    try:
        p = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=600)
    except Exception:
        return None
    if p.returncode != 0:
        return _all_mine(conflicts)  # cancelled — keep everything local

    decisions = _all_mine(conflicts)
    for line in p.stdout.strip().splitlines():
        key = by_label.get(line.strip())
        if key:
            decisions[key] = SERVER
    return decisions


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def resolve(conflicts: list[dict]) -> tuple[dict[str, str], str]:
    """Ask once for every row. Returns (key -> MINE|SERVER, backend name).

    `conflicts` items carry:
      key     unique id — the absolute path, or "<path>::<entry>" for a symbol
      kind    "footprint" | "symbol" | "model"
      name    what to show
      note    why it is being asked about (optional)
      delete  True when "server" means deleting a file the platform has never
              seen (optional)

    The returned map ALWAYS covers every key, whatever happened, so the caller
    never has to handle a missing decision.
    """
    if not conflicts:
        return {}, "none"
    if len(conflicts) > _WX_MAX_ROWS:
        # Something is structurally wrong (a wiped state file, a re-import).
        # Asking 900 questions helps nobody; keep everything and say so.
        return _all_mine(conflicts), "too-many"

    for backend, fn in (("wx", _resolve_wx), ("osascript", _resolve_osascript)):
        if backend == "osascript" and len(conflicts) > _SANE_ROWS:
            continue  # a `choose from list` this long cannot be reviewed
        out = fn(conflicts)
        if out is not None:
            # a backend may only answer for what it was given
            full = _all_mine(conflicts)
            full.update({k: v for k, v in out.items() if k in full})
            return full, backend
    return _all_mine(conflicts), "none"
