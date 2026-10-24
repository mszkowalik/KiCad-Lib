# Select Similar plugin (`clients/kicad-select-similar`)

Altium's Find Similar Objects as a KiCad IPC plugin. Why IPC and a floating
window, not a docked SWIG pane:
[decision 0096](../../docs/decisions/0096-select-similar-is-an-ipc-plugin-with-a-floating-panel.md).
User-facing behaviour: [README.md](README.md).

- **Test against a SANDBOX KiCad, never the user's open session.** Apply
  changes the selection of whatever board the API reaches, and the user is
  often working in theirs. KiCad honours three path overrides, so a second,
  isolated PCB editor costs one command:

  ```
  T=<scratch dir>; mkdir -p $T/config $T/docs/KiCad/10.0/plugins $T/cache
  cp -R ~/Library/Preferences/kicad/10.0 $T/config/10.0   # api.enable_server must be true
  ln -s "$PWD" $T/docs/KiCad/10.0/plugins/com.sevensigma.select-similar
  KICAD_CONFIG_HOME=$T/config KICAD_DOCUMENTS_HOME=$T/docs KICAD_CACHE_HOME=$T/cache \
    /Applications/KiCad/KiCad.app/Contents/Applications/pcbnew.app/Contents/MacOS/pcbnew <copy of a board> &
  ```

  Its socket is `ipc:///tmp/kicad/api-<pid>.sock` (the user's KiCad holds
  `api.sock`). Pass it as `KiCad(socket_path=...)`, or as `KICAD_API_SOCKET`
  to `select_similar.py`. KiCad builds the plugin venv under
  `$T/cache/KiCad/10.0/python-environments/` within seconds. Test with the
  Python of that venv, because users run that one. Killing the sandbox leaves its socket
  file behind: delete `/tmp/kicad/api-<pid>.sock`, nothing else in that folder.
- **Screenshots of a covered window:** `screencapture -x -o -l <window id>`.
  The id comes from `CGWindowListCopyWindowInfo` (a five-line Swift script).
  A region capture grabs whatever window is on top, often the user's.
- **No test has clicked the toolbar button itself.** The tests reproduce the
  launch with KiCad's command line and environment (`api_plugin_manager.cpp`,
  `InvokeAction`). On macOS, KiCad raises the new process with `osascript`
  after 250 ms. So the window comes forward when KiCad starts it, and stays
  behind when a shell starts it.
- **Bump `VERSION` in `build_package.py`** whenever a packaged file changes,
  or the Plugin and Content Manager keeps the old copy.
