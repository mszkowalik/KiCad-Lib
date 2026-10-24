"""Select Similar: the script KiCad runs for the toolbar button.

The first click opens the panel. Every later click finds the running panel,
brings it forward and makes KiCad's current selection the template, so the
button acts like Altium's Shift+F: select an object, press the button.
"""
from __future__ import annotations

import getpass
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

IDENTIFIER = "com.sevensigma.select-similar"
PORT_FILE = Path(tempfile.gettempdir()) / f"kicad-select-similar-{getpass.getuser()}.port"


def notify_running() -> bool:
    """Ask a running panel to come forward. True when one answered."""
    try:
        port = int(PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as conn:
            conn.sendall(b"show\n")
            return conn.recv(8).startswith(b"ok")
    except OSError:
        return False  # a stale file from a panel that crashed


def listen(wanted: threading.Event) -> socket.socket:
    """Accept "show" from later clicks. Only sets a flag: Tk is not thread-safe,
    so the Tk loop reads the flag."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    PORT_FILE.write_text(str(server.getsockname()[1]))

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # closed on exit
            with conn:
                try:
                    if conn.recv(8).startswith(b"show"):
                        conn.sendall(b"ok\n")
                        wanted.set()
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return server


def point_tk_at_its_scripts() -> None:
    """Make Tk start inside the venv KiCad builds for this plugin.

    KiCad's bundled Python (macOS) looks for init.tcl under the python.org
    install path, /Library/Frameworks/Python.framework, which does not exist,
    and under the venv prefix, which has no Tcl scripts. Tk then dies with
    "Can't find a usable init.tcl". The scripts ship in the base prefix."""
    lib = Path(sys.base_prefix) / "lib"
    for var, pattern, probe in (("TCL_LIBRARY", "tcl8.*", "init.tcl"),
                                ("TK_LIBRARY", "tk8.*", "tk.tcl")):
        if var in os.environ:
            continue
        for candidate in sorted(lib.glob(pattern), reverse=True):
            if (candidate / probe).is_file():
                os.environ[var] = str(candidate)
                break


def main() -> int:
    if notify_running():
        return 0

    point_tk_at_its_scripts()
    import tkinter as tk
    from kipy import KiCad
    from similar_board import KiCadGone, Session
    from similar_panel import Panel, Settings, report_error

    try:
        kicad = KiCad()
        session = Session(kicad)
    except KiCadGone as e:
        report_error("Select Similar",
                     "Select Similar cannot reach the PCB editor.\n\n"
                     f"{e}\n\n"
                     "Open the board in the PCB editor. If it is open, check that "
                     "Preferences > Plugins > Enable KiCad API is on.")
        return 1

    try:
        settings_path = Path(kicad.get_plugin_settings_path(IDENTIFIER)) / "settings.json"
    except Exception:
        settings_path = None

    root = tk.Tk()
    panel = Panel(root, session, Settings(settings_path))

    wanted = threading.Event()
    server = listen(wanted)

    def check_wanted() -> None:
        if wanted.is_set():
            wanted.clear()
            panel.show()
            panel.load_selection()
        root.after(250, check_wanted)

    root.after(250, check_wanted)
    root.after(50, panel.show)
    root.after(100, panel.load_selection)
    port = server.getsockname()[1]
    try:
        root.mainloop()
    finally:
        server.close()
        try:
            if PORT_FILE.read_text().strip() == str(port):
                PORT_FILE.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
