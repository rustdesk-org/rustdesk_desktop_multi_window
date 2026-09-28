# Validation record (2026-09-28)

Environment: Windows 11 Enterprise build 26200, Flutter 3.24.5, Dart 3.5.4,
MSVC 2022, two 1920 x 1080 monitors at 96 DPI. The machine has Intel UHD 730
and NVIDIA GTX 1650 adapters; adapters were not independently forced or tested.

| Check | Result |
| --- | --- |
| RustDesk native Debug plugin build, with its existing warning settings | Passed |
| Standalone Debug: all 16 scenarios described in README | 16 passed |
| Standalone Release: all 16 scenarios | 16 passed |
| Debug lifecycle stress: 50 rounds, 100 secondary windows | Passed |
| Release lifecycle stress, including immediate fullscreen/restore | Incomplete: first fullscreen round failed the visibility check |
| Upstream `8b774a6`, Release, ordinary startup | Passed |
| Upstream `8b774a6`, Release, busy UI and busy widget build | Both reproduced `kResizeStarted` and failed the green-pixel check |
| Upstream `8b774a6`, Release lifecycle stress | Same fullscreen visibility failure |
| Generated probe `dart analyze lib/main.dart` | No issues |
| `git diff --check` | Passed |

The fixed-plugin scenario tests checked actual screen pixels, engine resize state,
and agreement between parent client size, child size, and EGL surface size. Debug
also checked that the plugin's pending refresh flag was cleared. Release plugin
builds do not emit a PDB, so that private flag was not checked in Release.

Expanded tests found that the initial fix depended on application method-handler
registration: an absent or cleared handler left the child one pixel too wide.
The final fix uses a no-op `flutter/system` message acknowledged by ServicesBinding
as the UI-thread barrier, and needs no Dart API changes. Absent, cleared, and late
handler scenarios all passed with the final implementation.

The Release stress visibility failure also occurred with the unmodified upstream
plugin. At failure, both Flutter views were `kDone` and their sizes agreed, but the
fullscreen/restored window could not be brought above other windows for a valid
pixel check. The isolated fullscreen scenario passed. This is recorded as a
failure/incomplete stress run, not as a successful 100-window Release run.

Full-client checks used a local RustDesk development build containing existing
reconnect debugging changes. After loading the final plugin, the second remote
window opened and received an image; five close/reopen cycles and switching its
selected monitor from 1 to 0 and back to 1 passed. Both windows had matching native
sizes and `kDone`, and the reopened windows had no waiting dialogs.

Forcing reconnect while a session was already connected received new textures in
several trials but left a `Connecting...` overlay. Therefore full-client reconnect
is **not** certified by this validation. Those application paths are outside this
plugin diff. Early reconnect trials with an incorrect relay argument were excluded.
The saved connection preference was restored before repeating client checks.

Mixed DPI, other Flutter versions, independent GPU selection, long network outages,
and an overnight soak were not tested.

## Regression surface

- `windows/flutter_window.cc`: secondary-window startup/show recovery, its first
  frame callback, and parent resize while recovery is pending or exhausted. These
  paths must keep the temporary child size until the UI and raster threads catch
  up, and invalidate callbacks for obsolete sizes.
- `windows/flutter_window.h`: private state and helpers for that recovery.
- `test/windows_resize/`: new standalone test tooling, with no application runtime
  or production dependency changes.

The main-window runner, existing base-window fullscreen/DPI implementations, Dart
application methods, and RustDesk network/session code are outside the final diff.
