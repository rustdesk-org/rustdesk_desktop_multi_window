"""Verify real RustDesk startup with an existing FancyZones placement."""

import argparse
import ctypes as c
import ctypes.wintypes as w
import json
import os
import subprocess
import time
from pathlib import Path

from native_probe import ENUM_CALLBACK, user32

GW_CHILD = 5
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
CLASS_CAPACITY = 256
STARTUP_SECONDS = 8
POLL_SECONDS = 0.1
WINDOW_CLASSES = {'connect': 'RustdeskMultiWindow', 'main': 'FLUTTER_RUNNER_WIN32_WINDOW'}


def require_zone_history(executable):
    directory = Path(os.environ['LOCALAPPDATA']) / 'Microsoft/PowerToys/FancyZones'
    settings = json.loads((directory / 'settings.json').read_text(encoding='utf-8-sig'))
    properties = settings['properties']
    if not properties['fancyzones_appLastZone_moveWindows']['value']:
        raise RuntimeError('Enable FancyZones last-zone placement before this test')
    exclusions = properties['fancyzones_excluded_apps']['value'].splitlines()
    if any(item.strip().casefold() in str(executable).casefold()
           for item in exclusions if item.strip()):
        raise RuntimeError('Remove this executable from FancyZones exclusions before this test')
    history = json.loads((directory / 'app-zone-history.json').read_text(encoding='utf-8-sig'))
    paths = [Path(entry['app-path']) for entry in history['app-zone-history']]
    if executable not in paths:
        raise RuntimeError('First place this executable in a zone with a real Shift-drag')


def visible_windows(api, process_id):
    windows = []

    @ENUM_CALLBACK
    def visit(handle, unused):
        owner = w.DWORD()
        api.GetWindowThreadProcessId(handle, c.byref(owner))
        if owner.value == process_id and api.IsWindowVisible(handle):
            name = c.create_unicode_buffer(CLASS_CAPACITY)
            api.GetClassNameW(handle, name, CLASS_CAPACITY)
            windows.append((handle, name.value))
        return True

    if not api.EnumWindows(visit, 0):
        raise c.WinError(c.get_last_error())
    return windows


def inspect(api, parent):
    child = api.GetWindow(parent, GW_CHILD)
    if not child:
        raise RuntimeError('The visible RustDesk window has no Flutter child')
    name = c.create_unicode_buffer(CLASS_CAPACITY)
    api.GetClassNameW(child, name, CLASS_CAPACITY)
    if name.value != 'FLUTTERVIEW':
        raise RuntimeError(f'Unexpected child class: {name.value}')
    api.GetPropW.argtypes = [w.HWND, w.LPCWSTR]
    api.GetPropW.restype = w.HANDLE
    style = api.GetWindowLongPtrW(child, GWL_STYLE)
    return dict(parent=parent, child=child, child_style=hex(style),
                child_visible=bool(api.IsWindowVisible(child)),
                child_has_visible_style=bool(style & WS_VISIBLE),
                zone_mask=api.GetPropW(parent, 'FancyZones_zones') or 0,
                child_zone_mask=api.GetPropW(child, 'FancyZones_zones') or 0)


def run(options):
    require_zone_history(options.exe)
    options.report.mkdir(parents=True, exist_ok=False)
    command = [str(options.exe)]
    if options.startup == 'connect':
        command += ['--connect', options.peer]
    with (options.report / 'stdout.log').open('w') as out, (options.report / 'stderr.log').open('w') as err:
        process = subprocess.Popen(command, cwd=options.exe.parent, stdout=out, stderr=err)
    print(json.dumps(dict(pid=process.pid, executable=str(options.exe))), flush=True)
    api = user32()
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'RustDesk exited during startup: {process.returncode}')
        time.sleep(POLL_SECONDS)
    windows = [handle for handle, name in visible_windows(api, process.pid)
               if name == WINDOW_CLASSES[options.startup]]
    if len(windows) != 1:
        raise RuntimeError(f'Expected one visible {options.startup} window, got {windows}')
    result = dict(pid=process.pid, startup=options.startup, **inspect(api, windows[0]))
    placed = bool(result['zone_mask'] or result['child_zone_mask'])
    result['passed'] = (placed and result['child_visible']
                        and result['child_has_visible_style'])
    (options.report / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
    if not placed:
        raise RuntimeError('FancyZones did not place the new window; invalid test precondition')
    if not result['passed']:
        raise AssertionError('The visible RustDesk host contains a hidden Flutter view')


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--startup', choices=WINDOW_CLASSES, required=True)
    parser.add_argument('--peer')
    parser.add_argument('--report', type=Path, required=True)
    options = parser.parse_args()
    options.exe = options.exe.resolve(strict=True)
    if options.startup == 'connect' and not options.peer:
        parser.error('--peer is required for a connection window')
    return options


if __name__ == '__main__':
    run(arguments())
