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
reportdir = root / f'stress-{config}-{time.strftime('%Y%m%d-%H%M%S')}'
reportdir.mkdir()
reports = []
with (reportdir / 'app.log').open('w') as log:
    process = launch(binary, ['stress', str(reportdir)], log)
    try:
        for round in range(50):
            start = time.monotonic()
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f'Exited during round {round}: {process.returncode}')
                try:
                    ready = json.loads((reportdir / 'ready.json').read_text())
                    if ready['round'] == round:
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() - start > 30:
                    raise RuntimeError(f'Timeout round {round}')
                time.sleep(0.1)
            report = inspect(process.pid, root, config, reportdir, str(round))
            reports.append(report)
            print(json.dumps(dict(round=round + 1, ok=report['ok'], states=report['states'], pixels=[r.get('green') for r in report['windows']])), flush=True)
            if not report['ok']:
                raise RuntimeError(f'Failed round {round}')
            (reportdir / f'ack-{round}').write_text('ok')
        process.wait(timeout=10)
        assert process.returncode == 0 and (reportdir / 'done').read_text() == '50'
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        (reportdir / 'results.json').write_text(json.dumps(reports, indent=2))
        print(str(reportdir), flush=True)
