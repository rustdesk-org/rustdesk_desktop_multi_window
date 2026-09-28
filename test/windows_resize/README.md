# Windows resize regression probe

Requires Windows with an unlocked desktop, Flutter 3.24.5, Visual Studio C++
tools, Windows SDK CDB (x64), and Python 3.12 with Pillow. The probe raises its own
windows briefly to sample screen pixels; do not lock the desktop during a run.
It does not connect to a remote computer.

From this repository in PowerShell:

```powershell
$env:FLUTTER_ROOT = 'D:/lib/flutter'
$probe = Join-Path $env:TEMP 'multi-window-regression'
./test/windows_resize/prepare.ps1 -FlutterRoot $env:FLUTTER_ROOT -Destination $probe
Set-Location $probe
& "$env:FLUTTER_ROOT/bin/flutter.bat" build windows --debug --no-pub
python validate.py Debug
python stress.py Debug
& "$env:FLUTTER_ROOT/bin/flutter.bat" build windows --release --no-pub
python validate.py Release
python stress.py Release
```

Set `CDB_PATH` if the debugger is not installed in its default Windows SDK path.
The three additional plugin dependencies are required by this plugin's existing
Windows CMake target. They are confined to the generated probe application.

`validate.py` runs 16 scenarios: ordinary startup, a busy UI callback, an old-size
build held across a resize, resize during recovery, hide/show, slow and very slow
startup, close during recovery, minimize/restore, absent/cleared/late application
handlers, rapid resizing, fullscreen/restore, maximize/restore, and delayed show.
Optional trailing arguments select individual scenarios, e.g.
`python validate.py Debug busy_ui busy_build`.

Every surviving window must have `kDone` resize state, matching parent/child/EGL
sizes, and green pixels in four interior locations. Debug also checks the plugin's
internal refresh flag; ordinary Release builds do not emit the plugin's PDB.
Green is painted only after the deliberate UI stall. CDB uses a non-invasive,
non-suspending attach (`-pvr`). Raw debugger output, JSON results, and screenshots
of pixel failures are saved under the generated application directory.

`stress.py` creates and closes 100 secondary windows in 50 rounds in one process,
alternating UI stalls and window operations. It applies the same native and pixel
checks every round and verifies that the plugin removes all closed window IDs.

To compare against the unfixed revision, build a separate probe against that
checkout and set `$env:RESIZE_PROBE_BASELINE = '1'`. This permits the old DLL and
absence of the new refresh fields; resize state, geometry, and pixel checks still
apply. Remove the variable when testing the fix. Always use a fresh build directory
when changing plugin checkouts: MSBuild can otherwise retain stale native objects.

This probe does not validate RustDesk's network reconnection or monitor
subscriptions; those require a separate full-client test. It also does not emulate
different GPU drivers or mixed monitor DPI settings.

On the validation machine, the Release stress run stopped at its first immediate
fullscreen/restore round: the window had matching sizes and `kDone`, but could not
be brought above other windows for the pixel check. The same failure reproduced
with the unmodified `8b774a6` plugin. The individual fullscreen scenario, which
allows time between transitions, passed. This stress failure is retained rather
than treated as a passing result.
