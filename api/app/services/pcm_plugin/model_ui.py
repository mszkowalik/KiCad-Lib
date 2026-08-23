"""Push's 3D-model upload window — confirm where each off-library model goes.

Push finds the `(model …)` files a locally drawn footprint points at (a STEP in
~/Downloads, one out of KiCad's own 3dmodels tree, one beside the project) and
has to store them in the library before the footprint can reference them. The
target path is a decision — `Package_SO.3dshapes/…` or `7Sigma.3dshapes/…` —
so it is shown, and editable, before anything is uploaded.

Same three-backend shape as conflict_ui.py (wxPython, AppleScript, neither) for
the same reason: KiCad ships wx, but a plugin must not die when it is missing.

**The failure direction is the opposite of conflict_ui's.** There, refusing to
answer keeps the local file — the safe outcome. Here, refusing to answer means
NOT uploading, which means the push fails validation. So cancelling cancels the
whole push (the caller sends nothing), and a missing dialog backend falls
through to the suggested paths with a notification rather than a silent stop.
"""
from __future__ import annotations

import os
import subprocess
import sys

from model_paths import check_rel_path

# Beyond this the window stops being reviewable. A footprint referencing 20
# solids is not a thing; this only fires on a bulk push of many footprints.
_SANE_ROWS = 40


def _label(item: dict) -> str:
    return f"{item['footprint']}: {item['src'].name}"


def _front() -> None:
    """Pull this process in front of KiCad — a plugin subprocess does not come
    forward on its own and the window can open behind the editor."""
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
# backend 1 — wxPython
# --------------------------------------------------------------------------

def _confirm_wx(items: list[dict]):
    try:
        import wx
    except Exception:
        return "unavailable"
    try:
        app = wx.App.Get() or wx.App(False)
    except Exception:
        return "unavailable"
    try:
        return _run_wx_dialog(wx, items)
    except Exception:
        return "unavailable"
    finally:
        del app  # never Destroy(): KiCad may own this app


def _run_wx_dialog(wx, items: list[dict]):
    n = len(items)
    dlg = wx.Dialog(None, title=f"7Sigma Push — {n} 3D model" + ("" if n == 1 else "s"),
                    style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP)
    outer = wx.BoxSizer(wx.VERTICAL)
    outer.Add(wx.StaticText(dlg, label=(
        f"{n} model file{'' if n == 1 else 's'} referenced from outside the library.\n"
        "They are uploaded to the platform and the footprint is rewritten to point at\n"
        "the stored copy. Edit the target path if the suggested folder is wrong.")),
        0, wx.ALL, 12)

    scroll = wx.ScrolledWindow(dlg, style=wx.VSCROLL)
    scroll.SetScrollRate(0, 12)
    grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=12)
    grid.AddGrowableCol(1, 1)

    fields = []
    for item in items:
        left = wx.StaticText(scroll, label=item["footprint"])
        left.SetFont(left.GetFont().Bold())
        grid.Add(left, 0, wx.ALIGN_CENTER_VERTICAL)
        src = wx.StaticText(scroll, label=str(item["src"]))
        src.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        grid.Add(src, 0, wx.EXPAND)

        grid.Add(wx.StaticText(scroll, label="3DModels/"), 0,
                 wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        field = wx.TextCtrl(scroll, value=item["rel"], size=(420, -1))
        grid.Add(field, 0, wx.EXPAND)
        fields.append((item, field))

    scroll.SetSizer(grid)
    scroll.SetMinSize((640, min(380, 60 + 62 * n)))
    outer.Add(scroll, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

    std = dlg.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
    ok = dlg.FindWindowById(wx.ID_OK, dlg)
    if ok:
        ok.SetLabel("Upload and push")
    outer.Add(std, 0, wx.EXPAND | wx.ALL, 12)

    dlg.SetSizerAndFit(outer)
    dlg.CentreOnScreen()
    _front()
    dlg.Raise()

    try:
        while True:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            bad = [(item, field.GetValue().strip(), check_rel_path(field.GetValue()))
                   for item, field in fields]
            bad = [(i, v, why) for i, v, why in bad if why]
            if not bad:
                for item, field in fields:
                    item["rel"] = field.GetValue().strip().lstrip("/")
                return items
            wx.MessageBox("\n".join(f"{i['footprint']}: {v!r} — {why}" for i, v, why in bad),
                          "Fix the target path", wx.OK | wx.ICON_WARNING, dlg)
    finally:
        dlg.Destroy()


# --------------------------------------------------------------------------
# backend 2 — AppleScript
# --------------------------------------------------------------------------

def _confirm_osascript(items: list[dict]):
    """One prompt per model. `display dialog` holds one line of text, which is
    exactly one target path, so the loop is the dialog."""
    if sys.platform != "darwin":
        return "unavailable"
    for idx, item in enumerate(items, 1):
        prompt = (f"{item['footprint']} ({idx} of {len(items)})\n\n"
                  f"Upload {item['src']}\nto 3DModels/ at:")
        while True:
            script = (
                'display dialog {} with title "7Sigma Push — 3D model" '
                'default answer {} buttons {{"Cancel", "Upload"}} '
                'default button "Upload"\n'
                "return text returned of result"
            ).format(_as_str(prompt), _as_str(item["rel"]))
            try:
                p = subprocess.run(["osascript", "-e", script],
                                   capture_output=True, text=True, timeout=600)
            except Exception:
                return "unavailable"
            if p.returncode != 0:
                return None  # cancelled — cancel the whole push
            value = p.stdout.strip().lstrip("/")
            why = check_rel_path(value)
            if why is None:
                item["rel"] = value
                break
            item["rel"] = value or item["rel"]
            prompt = f"{item['footprint']}\n\nThat path {why}.\nUpload {item['src']} to:"
    return items


def _as_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def confirm(items: list[dict]) -> tuple[list[dict] | None, str]:
    """Ask where each model goes. Returns (items, backend).

    `items` carry `footprint`, `src` (Path) and `rel` (the suggested path under
    3DModels/); `rel` is updated in place with what the user chose. A None list
    means the user cancelled and NOTHING may be pushed. Backend "none" means no
    dialog was available and the suggested paths stand — the caller says so.
    """
    if not items:
        return [], "none"
    if len(items) > _SANE_ROWS:
        return items, "too-many"
    for backend, fn in (("wx", _confirm_wx), ("osascript", _confirm_osascript)):
        out = fn(items)
        if out != "unavailable":
            return out, backend
    return items, "none"
