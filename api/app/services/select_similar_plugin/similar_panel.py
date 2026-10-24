"""The Select Similar window: Altium's Find Similar Objects grid as a panel.

Tk, because KiCad's bundled Python ships Tcl/Tk 8.6 and the plugin then needs
no GUI package from PyPI. The window floats; an IPC plugin runs in its own
process and cannot dock into KiCad (decision 0096).
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

from similar_board import KiCadBusy, KiCadGone, Session, kiid_of
from similar_engine import (ANY, DIFFERENT, MODES, SAME, Criterion, Obj,
                            criteria_from_templates, find_matches, fmt, summarize)

POLL_MS = 700           # selection poll while following KiCad
POLL_SLOW_MS = 2500     # ... while a large selection is up: each poll serializes it
BIG_SELECTION = 300
GONE_LIMIT = 5          # consecutive failed polls before the panel gives up

OPTIONS = {             # Altium's defaults, plus the two this panel adds
    "zoom_matching": True,
    "select_matching": True,
    "clear_existing": True,
    "follow_selection": True,
    "keep_on_top": True,
}


class Settings:
    """Options and window geometry, kept between runs. Never fatal."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.data: Dict[str, object] = {}
        if path:
            try:
                self.data = json.loads(path.read_text())
            except (OSError, ValueError):
                self.data = {}

    def get(self, key: str, default):
        value = self.data.get(key, default)
        return value if isinstance(value, type(default)) else default

    def save(self, **values) -> None:
        self.data.update(values)
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1))
        except OSError:
            pass


class Panel:
    def __init__(self, root: tk.Tk, session: Session, settings: Settings):
        self.root = root
        self.session = session
        self.settings = settings
        self.objects: List[Obj] = []          # the last board read, for the live count
        self.templates: List[Obj] = []
        self.template_kinds: set = set()
        self.criteria: List[Criterion] = []
        self.rows: Dict[str, Criterion] = {}  # tree item id -> row
        self.seen_selection: frozenset = frozenset()
        self.applied_selection: frozenset = frozenset()
        self.failed_polls = 0
        self.editor: Optional[Tuple[ttk.Entry, Callable[[str], None]]] = None

        self.vars = {k: tk.BooleanVar(value=settings.get(k, v)) for k, v in OPTIONS.items()}
        self._build()
        self.vars["keep_on_top"].trace_add("write", lambda *_: self._apply_topmost())
        self._apply_topmost()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(POLL_MS, self.poll)

    # --- layout -----------------------------------------------------------------

    def _build(self) -> None:
        root = self.root
        root.title("Select Similar")
        root.minsize(360, 420)
        root.geometry(self.settings.get("geometry", "470x660"))

        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        self.italic = tkfont.nametofont("TkDefaultFont").copy()
        self.italic.configure(slant="italic")

        outer = ttk.Frame(root, padding=8)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        self.template_label = ttk.Label(head, text="Select an object in KiCad", anchor="w")
        self.template_label.pack(side="left", fill="x", expand=True)
        ttk.Button(head, text="Use Selection", command=self.load_selection).pack(side="right")

        grid = ttk.Frame(outer)
        grid.pack(fill="both", expand=True, pady=(6, 6))
        self.tree = ttk.Treeview(grid, columns=("value", "match"), show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="Attribute")
        self.tree.heading("value", text="Value")
        self.tree.heading("match", text="Match")
        self.tree.column("#0", width=200, stretch=False)
        self.tree.column("value", width=170, stretch=True)
        self.tree.column("match", width=80, stretch=False, anchor="center")
        scroll = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("group", font=self.bold)
        self.tree.tag_configure(SAME, foreground="#1a6fd6")
        self.tree.tag_configure(DIFFERENT, foreground="#d1452b")
        self.tree.tag_configure("edited", font=self.italic)

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-Button-1>", self._on_double)
        # Button-2 is the right button on macOS Tk, Button-3 everywhere else
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.tree.bind(seq, self._on_menu)
        for key, mode in (("s", SAME), ("a", ANY), ("d", DIFFERENT)):
            self.tree.bind(f"<KeyPress-{key}>",
                           lambda e, m=mode: self._set_mode(self._selected_rows(), m))
        self.tree.bind("<Return>", lambda e: self._edit_selected())

        opts = ttk.Frame(outer)
        opts.pack(fill="x")
        labels = (("zoom_matching", "Zoom Matching"), ("select_matching", "Select Matching"),
                  ("clear_existing", "Clear Existing"),
                  ("follow_selection", "Follow KiCad Selection"), ("keep_on_top", "Keep on Top"))
        for i, (key, text) in enumerate(labels):
            ttk.Checkbutton(opts, text=text, variable=self.vars[key]).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12))

        self.status = ttk.Label(outer, text="", anchor="w", foreground="#808080")
        self.status.pack(fill="x", pady=(6, 4))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(buttons, text="OK", command=lambda: self.apply(close=True)).pack(
            side="right", padx=4)
        ttk.Button(buttons, text="Apply", command=self.apply).pack(side="right")

        root.bind("<Escape>", lambda e: self.close())

        self.menu = tk.Menu(root, tearoff=False)
        for mode in MODES:
            self.menu.add_command(label=mode,
                                  command=lambda m=mode: self._set_mode(self._selected_rows(), m))
        self.menu.add_separator()
        self.menu.add_command(label="Reset Value", command=self._reset_values)
        self.menu.add_command(label="Set All to Any", command=self._all_any)

    def _apply_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.vars["keep_on_top"].get()))

    # --- template -------------------------------------------------------------

    def show(self) -> None:
        """Bring the window forward (a second click on the toolbar button)."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def load_selection(self, quiet: bool = False) -> None:
        """Take KiCad's current selection as the template."""
        try:
            messages = self.session.selection()
            if not self.objects:
                self.objects = self.session.read()
            templates = self.session.templates(messages)
        except KiCadBusy:
            if not quiet:
                self._status("KiCad is busy. Finish the current tool, then try again.")
            return
        except KiCadGone as e:
            self._status(f"Lost KiCad: {e}")
            return
        self.seen_selection = frozenset(filter(None, map(kiid_of, messages)))
        if not templates:
            if not quiet:
                self._status("Nothing selected. Select an object in KiCad.")
            return
        self.set_templates(templates)

    def set_templates(self, templates: List[Obj]) -> None:
        self._finish_edit(save=False)
        old = {c.key: c.mode for c in self.criteria}
        kinds = {o.kind for o in templates}
        self.templates = templates
        self.criteria = criteria_from_templates(templates)
        # Altium's dialog remembers the match options between invocations;
        # keep them while the template stays the same kind of object.
        if kinds == self.template_kinds:
            for c in self.criteria:
                c.mode = old.get(c.key, c.mode)
        self.template_kinds = kinds
        if len(templates) == 1:
            self.template_label.configure(text=f"Template: {templates[0].describe()}")
        else:
            self.template_label.configure(text=f"Template: {summarize(templates)}")
        self._fill_tree()
        self.update_preview()

    def _fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        groups: Dict[str, str] = {}
        for c in self.criteria:
            group = c.attr.group
            if group not in groups:
                groups[group] = self.tree.insert("", "end", text=group, open=True,
                                                 tags=("group",))
            iid = self.tree.insert(groups[group], "end", text=c.attr.label)
            self.rows[iid] = c
            self._paint(iid)

    def _paint(self, iid: str) -> None:
        c = self.rows[iid]
        tags = [c.mode] if c.mode != ANY else []
        if c.pattern is not None:
            tags.append("edited")
        self.tree.item(iid, values=(c.display_value(), c.mode), tags=tags)

    # --- editing --------------------------------------------------------------

    def _selected_rows(self) -> List[str]:
        return [i for i in self.tree.selection() if i in self.rows]

    def _set_mode(self, iids: List[str], mode: str) -> None:
        for iid in iids:
            self.rows[iid].mode = mode
            self._paint(iid)
        self.update_preview()

    def _reset_values(self) -> None:
        for iid in self._selected_rows():
            self.rows[iid].pattern = None
            self._paint(iid)
        self.update_preview()

    def _all_any(self) -> None:
        self._set_mode(list(self.rows), ANY)

    def _cell(self, event) -> Tuple[Optional[str], str]:
        iid = self.tree.identify_row(event.y)
        return (iid if iid in self.rows else None), self.tree.identify_column(event.x)

    def _on_click(self, event):
        self._finish_edit()
        iid, column = self._cell(event)
        if iid is None or column != "#2":
            return None
        # A click on Match opens Altium's Any / Same / Different choice, for
        # every selected row when the click lands inside the selection.
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        x, y, _, h = self.tree.bbox(iid, "match")
        menu = tk.Menu(self.root, tearoff=False)
        current = tk.StringVar(value=self.rows[iid].mode)
        rows = self._selected_rows()
        for mode in MODES:
            menu.add_radiobutton(label=mode, value=mode, variable=current,
                                 command=lambda m=mode: self._set_mode(rows, m))
        menu.tk_popup(self.tree.winfo_rootx() + x, self.tree.winfo_rooty() + y + h)
        return "break"

    def _on_double(self, event):
        iid, column = self._cell(event)
        if iid and column in ("#0", "#1"):
            self._edit_value(iid)
            return "break"
        return None

    def _on_menu(self, event):
        iid, _ = self._cell(event)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        if self._selected_rows():
            self.menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _edit_selected(self) -> None:
        rows = self._selected_rows()
        if rows:
            self._edit_value(rows[0])

    def _edit_value(self, iid: str) -> None:
        """Type a value or a pattern into the Value cell; * and ? are wildcards."""
        self._finish_edit()
        c = self.rows[iid]
        self.tree.see(iid)
        box = self.tree.bbox(iid, "value")
        if not box:
            return

        def commit(text: str) -> None:
            distinct = list(dict.fromkeys(c.template_values))
            unchanged = len(distinct) == 1 and text == fmt(c.attr.vtype, distinct[0])
            c.pattern = None if unchanged or text == "" else text
            # Typing a value means "find this"; a row left at Any would ignore it.
            if c.pattern is not None and c.mode == ANY:
                c.mode = SAME
            self._paint(iid)
            self.update_preview()

        entry = ttk.Entry(self.tree)
        entry.insert(0, c.display_value())
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda e: self._finish_edit())
        entry.bind("<KP_Enter>", lambda e: self._finish_edit())
        entry.bind("<FocusOut>", lambda e: self._finish_edit())
        entry.bind("<Escape>", lambda e: (self._finish_edit(save=False), "break")[1])
        x, y, w, h = box
        entry.place(in_=self.tree, x=x, y=y, width=w, height=h)
        entry.focus_set()
        self.editor = (entry, commit)

    def _finish_edit(self, save: bool = True) -> None:
        """Close the value editor, keeping what was typed unless `save` is False.
        Re-entrant: destroying the entry fires its FocusOut, which lands here."""
        if self.editor is None:
            return
        entry, commit = self.editor
        self.editor = None
        try:
            text = entry.get()
        except tk.TclError:
            text = None
        entry.destroy()
        if save and text is not None:
            commit(text)

    # --- matching ---------------------------------------------------------------

    def update_preview(self) -> None:
        if self.criteria:
            self._status("Preview: " + summarize(find_matches(self.objects, self.criteria)))

    def apply(self, close: bool = False) -> None:
        self._finish_edit()
        if not self.criteria:
            self._status("No template. Select an object in KiCad first.")
            return
        select_matching = self.vars["select_matching"].get()
        try:
            self.objects = self.session.read()  # fresh: the board may have changed
            matches = find_matches(self.objects, self.criteria)
            self.session.apply([o.kiid for o in matches],
                               select_matching=select_matching,
                               zoom_matching=self.vars["zoom_matching"].get(),
                               clear_existing=self.vars["clear_existing"].get())
            self.applied_selection = frozenset(
                filter(None, map(kiid_of, self.session.selection())))
        except KiCadBusy:
            self._status("KiCad is busy. Finish the current tool, then click Apply again.")
            return
        except KiCadGone as e:
            self._status(f"Lost KiCad: {e}")
            return
        self._status(("Selected: " if select_matching else "Found: ") + summarize(matches))
        if close:
            self.close()

    # --- following KiCad's selection -------------------------------------------

    def poll(self) -> None:
        delay = POLL_MS
        if (self.vars["follow_selection"].get() and self.editor is None
                and self.root.state() != "iconic"):
            messages = None
            try:
                messages = self.session.selection()
                self.failed_polls = 0
            except KiCadBusy:
                pass
            except KiCadGone as e:
                self.failed_polls += 1
                if self.failed_polls >= GONE_LIMIT:
                    self._status(f"Lost KiCad: {e}")
                    self.root.after(1500, self.close)
                    return
            if messages is not None:
                ids = frozenset(filter(None, map(kiid_of, messages)))
                if len(ids) > BIG_SELECTION:
                    delay = POLL_SLOW_MS
                # A new selection the panel did not make itself becomes the
                # template. An empty one keeps the template, as Altium's does.
                if ids and ids != self.seen_selection and ids != self.applied_selection:
                    self._follow(messages)
                self.seen_selection = ids
        self.root.after(delay, self.poll)

    def _follow(self, messages) -> None:
        try:
            if not self.objects:
                self.objects = self.session.read()
            templates = self.session.templates(messages)
        except (KiCadBusy, KiCadGone):
            return
        if templates:
            self.set_templates(templates)

    # --- misc -----------------------------------------------------------------

    def _status(self, text: str) -> None:
        self.status.configure(text=text)

    def close(self) -> None:
        self.settings.save(geometry=self.root.geometry(),
                           **{k: bool(v.get()) for k, v in self.vars.items()})
        self.root.destroy()


def report_error(title: str, message: str) -> None:
    """A message box for errors before the panel exists."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        from tkinter import messagebox
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except tk.TclError:
        print(f"{title}: {message}", file=sys.stderr)
