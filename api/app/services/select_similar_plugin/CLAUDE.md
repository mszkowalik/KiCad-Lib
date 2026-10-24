# Select Similar plugin (`api/app/services/select_similar_plugin`)

Altium's Find Similar Objects as a KiCad IPC plugin, served as the fourth
package of the platform's PCM repository. Why IPC and a floating window, not a
docked SWIG pane:
[decision 0096](../../../../docs/decisions/0096-select-similar-is-an-ipc-plugin-with-a-floating-panel.md).
Why the platform serves it:
[decision 0100](../../../../docs/decisions/0100-the-platform-serves-select-similar.md).
User-facing behaviour: [README.md](README.md). The platform never imports
these modules. `services/pcm.py` only zips the files.

- **Every top-level file in this folder ships to every user.** `pcm._similar_files`
  zips them all into `plugins/`, except `README.md`, `CLAUDE.md` and
  `icon-pcm.png` (the package icon). A scratch file left here reaches every
  KiCad that updates. Folders (`tests/`, `__pycache__/`) never ship.
- **Bump `SIMILAR_VERSION` in `services/pcm.py`** whenever a shipped file
  changes. The Plugin and Content Manager compares version strings only, so a
  new zip under the old version reaches nobody.
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

  The first KiCad to start takes `/tmp/kicad/api.sock`, and a later one gets
  `api-<pid>.sock`. So `ls /tmp/kicad` before you connect: with the user's
  KiCad closed, the sandbox holds `api.sock`. Pass the socket as
  `KiCad(socket_path="ipc://...")`, or as `KICAD_API_SOCKET` to
  `select_similar.py`. KiCad builds the plugin venv under
  `$T/cache/KiCad/10.0/python-environments/` within seconds. Test with the
  Python of that venv, because users run that one. A KILLED sandbox leaves its
  socket file behind: delete that one file, nothing else in that folder. The
  sandbox window appears on the user's screen, so tell them it is yours.
- **Screenshots of a covered window:** `screencapture -x -o -l <window id>`.
  The id comes from `CGWindowListCopyWindowInfo` (a five-line Swift script).
  A region capture grabs whatever window is on top, often the user's.
- **No test has clicked the toolbar button itself.** The tests reproduce the
  launch with KiCad's command line and environment (`api_plugin_manager.cpp`,
  `InvokeAction`). On macOS, KiCad raises the new process with `osascript`
  after 250 ms. So the window comes forward when KiCad starts it, and stays
  behind when a shell starts it.
