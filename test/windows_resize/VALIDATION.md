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
| Release lifecycle stress, including immediate fullscreen/restore | Two complete 50-round / 100-window runs passed; one earlier run crashed, see below |
| Upstream `8b774a6`, Release, ordinary startup | Passed |
| Upstream `8b774a6`, Release, busy UI and busy widget build | Both reproduced `kResizeStarted` and failed the green-pixel check |
| Upstream `8b774a6`, Release lifecycle stress | All 10 fullscreen rounds passed after correcting capture setup; busy-build rounds still reproduced the original resize failure |
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

The earlier fullscreen visibility failure was a capture-setup problem: fullscreen
restores a saved extended window style, and the verifier's temporary topmost state
needed resetting before the next capture. Clearing topmost before raising the
window fixed the check without changing plugin runtime code, sizes, or assertions.
Both upstream and fixed plugins then passed all fullscreen rounds. The fixed
plugin completed two 100-window Release runs, one under a debugger and one normally.

One preceding Release run exited while starting round 45, after 44 passing rounds.
Windows recorded an access violation in `flutter_windows.dll` at offset `0xa3becd`,
resolved using the matching engine PDB to `rx::Framebuffer11::markAttachmentsDirty`.
No crash dump was retained. The failure did not recur in the two subsequent fixed
runs or the 50-round upstream comparison. Its relationship to this change remains
undetermined; the later successful runs do not erase this failure.

Full-client retesting also required separate changes in the local RustDesk checkout:
preserve the initial connection's thread handle for reconnect, initialize image
waiting before asynchronous peer-info work without resetting it for cached data,
and allow an empty remote-tab frame to complete before hiding a Windows view.
The last condition prevents reuse of the old page during close/reopen. These
application changes are not included in this plugin PR.

With those changes rebuilt and loaded, 30 actual window close/reopen cycles passed.
Each cycle checked old-session disposal, a different new session ID, incoming
textures, and cleared wait flags/dialogs in both displayed sessions. An earlier
shortcut-driven batch that sometimes merely activated an existing window was
excluded. On the final application build, another 10 alternating reconnects,
two immediately repeated reconnect requests, and cached peer data arriving after
the first texture all passed. Both monitors retained their selection and received
new textures, with no waiting flags or dialog entries left behind. The final build
had the existing artificial reconnect delays disabled; an earlier build with an
eight-second login delay also recovered. Loaded Dart source and the Rust DLL hash
were checked against the build. These are Debug full-client checks, not a Release
full-client or long network-outage qualification.

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
