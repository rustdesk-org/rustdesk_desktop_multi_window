# Windows resize regression tests

## Real RustDesk startup visibility

Requires Windows, Python with Pillow, and an actual RustDesk build.

`verify_visibility.py` launches an actual RustDesk build and verifies that a
visible host contains a visible `FLUTTERVIEW` after FancyZones places it. Enable
"Move newly created windows to their last known zone", remove RustDesk from
exclusions, and establish a saved zone by Shift-dragging that executable's window.
Close it before each run. Use saved authentication for connection tests.

```powershell
python test/windows_resize/verify_visibility.py --exe D:/path/to/rustdesk.exe --startup connect --peer 192.168.5.4 --report D:/path/to/new-report
# Repeat with --startup main, omitting --peer.
```

The test does not change configuration, pause Dart, or inject resize messages.
It leaves the reported process open for visual inspection. Missing placement is
an invalid precondition, not a passing test. Also inspect local window chrome;
native visibility alone does not establish that frames are being rendered.

## Controlled resize diagnostics

The following historical fault-injection tests diagnose resize synchronization.
They do not demonstrate that an ordinary user can trigger the injected stall and
are not acceptance criteria for the FancyZones visibility fix.

Requires Windows x64, Flutter 3.24.5, Visual Studio C++ tools, the Windows SDK
Debugging Tools (CDB), and Python with Pillow. Keep the desktop unlocked: tests
raise their own window and reject screen samples obscured by another window.

Create a fresh probe application and build the plugin from this working tree:

```powershell
$flutterRoot = 'D:/DevEnv/flutter/flutter' # Your Flutter 3.24.5 SDK
$probe = Join-Path $env:TEMP ('window-resize-' + (Get-Date -Format yyyyMMdd-HHmmss))
./test/windows_resize/prepare.ps1 -FlutterRoot $flutterRoot -Destination $probe
Push-Location $probe
try {
    & "$flutterRoot/bin/flutter.bat" build windows --debug --no-pub
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally {
    Pop-Location
}
```

The extra plugin dependencies are required by the existing Windows CMake target.
Use `-Offline` for preparation when those dependencies are already cached.
Run each case with a hard 60-second timeout:

```powershell
$script = (Resolve-Path ./test/windows_resize/verify.py).Path
foreach ($scenario in @('healthy', 'stale', 'stale_show', 'busy_refresh')) {
    $report = Join-Path $probe "results-$scenario"
    $arguments = @("`"$script`"", '--project', "`"$probe`"",
        '--flutter-root', "`"$flutterRoot`"", '--scenario', $scenario,
        '--report', "`"$report`"")
    $process = Start-Process python -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        $process.Kill($true)
        throw "$scenario exceeded 60 seconds"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "$scenario failed; inspect $report" }
}
```

Pass `--cdb` to `verify.py` if CDB is installed outside its default SDK location.
Each report directory must be new. The native parser requires matching Debug
plugin and engine PDBs; it intentionally fails when a field cannot be read.

- `healthy`: refresh a healthy surface after changing its color.
- `stale`: resize away and back while Dart is stalled; assert that the native
  target is stale before invoking the actual plugin recovery timer.
- `stale_show`: create the same stale target, then let hide/show arm the timer.
- `busy_refresh`: trigger recovery while Dart is still stalled.

Tests assert `kDone`, equal parent/child/EGL sizes, and green pixels in four
locations. Stale cases also assert that green was not presented before recovery.
A manual resize after the test provides an independent recovery control. CDB
uses non-invasive, non-suspending attachment; no private engine state is written.
Logs, native snapshots, screenshots, DLL hashes and results are retained.

The unfixed PR fails `stale` and `stale_show`; its parent fails `busy_refresh`.
To compare revisions, prepare independent applications against the corresponding
source trees. Reusing a native build directory can leave stale MSBuild objects.

These fault-reproduction results apply to Flutter 3.24.5. Flutter 3.44.9 uses a
merged UI/platform thread by default: the same `stale` steps left the engine
healthy before recovery, so its precondition assertion correctly failed. This
is not a passing stale-target regression test. Likewise, `busy_refresh` passing
in that configuration does not establish overlap with the blocked Dart UI.
Keep those results separate from ordinary rendering and lifecycle compatibility
checks; do not remove the native precondition assertion to obtain a pass.

## Cross-monitor DPI

`verify_dpi.py` requires two connected monitors with different scaling. Prepare
a fresh probe using the commands above, then build both Debug and Release with
the selected SDK. It supports Flutter 3.24.5 and 3.44.9 and uses matching engine
symbols in both configurations; Release does not require private plugin symbols.

Run each configuration with the same hard timeout:

```powershell
$script = (Resolve-Path ./test/windows_resize/verify_dpi.py).Path
$configuration = 'Debug' # Repeat with Release after building --release.
foreach ($scenario in @('roundtrip', 'rapid', 'pending', 'hidden')) {
    $report = Join-Path $probe "dpi-$configuration-$scenario"
    $arguments = @("`"$script`"", '--project', "`"$probe`"",
        '--flutter-root', "`"$flutterRoot`"", '--configuration', $configuration,
        '--scenario', $scenario, '--report', "`"$report`"")
    $process = Start-Process python -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        $process.Kill($true)
        throw "$scenario exceeded 60 seconds"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "$scenario failed; inspect $report" }
}
```

- `roundtrip`: move to the other DPI and back.
- `rapid`: perform five quick DPI transitions, verify rendering, then move back.
- `pending`: require the temporary one-pixel recovery width before moving,
  in both directions.
- `hidden`: hide, move across DPI, show and verify, in both directions.

The driver uses real window movement, not synthetic `WM_DPICHANGED` messages.
Each settled checkpoint verifies native window DPI, Flutter `devicePixelRatio`
and physical size, equal parent/child/EGL sizes, `kDone`, and four visible screen
pixels. The Dart fixture toggles red/green after movement to prove a new frame
was presented. Every rapid movement must also change the native monitor and DPI.
Display settings are never changed. Reports retain monitor geometry, timings,
native snapshots, screenshots, Dart metrics and plugin hashes.
