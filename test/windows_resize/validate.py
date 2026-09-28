import json
import os
import sys
import time
from pathlib import Path

from check_windows import inspect, launch

root = Path(__file__).parent
config = sys.argv[1] if len(sys.argv) > 1 else 'Debug'
binary = root / f'build/windows/x64/runner/{config}/resize_probe.exe'
assert b'desktop_multi_window.resizeBarrier' in binary.with_name('desktop_multi_window_plugin.dll').read_bytes() or os.environ.get('RESIZE_PROBE_BASELINE') == '1', 'Wrong or stale plugin DLL'
reportdir = root / f'verification-{config}-{time.strftime('%Y%m%d-%H%M%S')}'
reportdir.mkdir()
reports = []
try:
    for mode in sys.argv[2:] or ['fast', 'busy_ui', 'busy_build', 'resize_during', 'hide_show', 'startup_slow', 'startup_very_slow', 'close_during', 'minimize_restore', 'no_handler', 'clear_handler', 'late_handler', 'rapid_resize', 'fullscreen', 'maximize_restore', 'hidden_start']:
        with (reportdir / f'{mode}.log').open('w') as log:
            process = launch(binary, [mode], log)
            try:
                time.sleep(9 if mode in ('startup_very_slow', 'minimize_restore', 'late_handler', 'hidden_start') else 4)
                report = inspect(process.pid, root, config, reportdir, mode, 1 if mode == 'close_during' else 2)
                reports.append(report)
                print(json.dumps(dict(mode=mode, ok=report['ok'], states=report['states'], pixels=[r.get('green') for r in report['windows']])), flush=True)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
finally:
    (reportdir / 'results.json').write_text(json.dumps(reports, indent=2))
    print(str(reportdir), flush=True)
if not all((r['ok'] for r in reports)):
    sys.exit(1)
