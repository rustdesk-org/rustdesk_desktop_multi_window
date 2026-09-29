# Windows resize recovery

Historical record: the resize-synchronization approach below was subsequently
removed after real RustDesk testing. The current patch shows the Flutter child
on `WM_SHOWWINDOW` to fix FancyZones startup visibility. Its real-user validation
uses Flutter 3.24.5 Debug/Release; the historical results below do not establish
coverage of the current patch.

Fix PR #38 without reintroducing resize timeouts while Dart is busy.

## Scope and decisions

- The original PR fails the stale-target regression; its parent fails the busy-UI regression. Both failures were reproduced before the fix.
- Hold a nonzero temporary child width until the UI barrier and next frame complete. Restore current parent geometry on a later timer tick.
- Keep callback generation/lifetime protection, the existing retry budget and visible error logging.
- The user requested smaller diffs and explicitly chose to retain repository regression tests while trimming production code and detailed reports.
- Reuse existing source files and the existing child resize helper; do not split unrelated legacy window code just to satisfy a file-size metric. Keep new functions below 50 nonblank lines.
- Existing unrelated workspace modifications remain outside this repair.

## Trim plan (at most three code files per phase)

1. [x] Review code and archive the verified implementation and full history.
2. [x] Reuse the base-window resize helper for one resize step (two files).
3. [x] Consolidate recovery into the existing window implementation; remove the extra source/CMake entry (three active code/build files, archive the superseded file).
4. [x] Rebuild and run core, lifecycle and cross-monitor regressions on Flutter 3.24.5 and 3.44.9 Debug/Release.
5. [x] Review final diff counts and record validation limits.

## Evidence

- Full prior history and pre-trim sources: `D:/Projects/flutter/pr38-before-trim-20260929/`.
- Post-trim verification: `D:/Projects/flutter/pr38-before-trim-20260929/trim-verification-summary.json`; all eight builds, four core regressions (3.24.5), 16 DPI cases (48 transitions at 150%/100%) and 32 lifecycle cases passed.
- Production diff: six files (+203/-110) reduced to four (+164/-100). Regression fixtures retained; source hashes and binary hashes recorded with results.
- Regression commands and version-specific preconditions: `test/windows_resize/README.md`.
- ARM64, display hot-unplug and live scaling-setting changes remain untested.
