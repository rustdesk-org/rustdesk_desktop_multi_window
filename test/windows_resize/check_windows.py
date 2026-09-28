import ctypes as c
import ctypes.wintypes as w
import json, os, re, subprocess, time
from pathlib import Path
from PIL import ImageGrab
u = c.windll.user32
k = c.windll.kernel32
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongPtrW.restype = c.c_ssize_t
u.GetWindow.argtypes = [w.HWND, c.c_uint]
u.GetWindow.restype = w.HWND
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetForegroundWindow.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
u.WindowFromPoint.argtypes = [w.POINT]
u.WindowFromPoint.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.IsWindow.argtypes = [w.HWND]
u.GetDpiForWindow.argtypes = [w.HWND]
CB = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

def windows(pid):
    rows = []

    @CB
    def enum(h, _):
        owner = w.DWORD()
        u.GetWindowThreadProcessId(h, c.byref(owner))
        name = c.create_unicode_buffer(256)
        u.GetClassNameW(h, name, 256)
        if owner.value == pid and name.value == 'RustdeskMultiWindow':
            child = u.GetWindow(h, 5)
            rows.append(dict(hwnd=h, child=child, userdata=u.GetWindowLongPtrW(h, -21), childdata=u.GetWindowLongPtrW(child, -21), dpi=u.GetDpiForWindow(h)))
        return True
    u.EnumWindows(enum, 0)
    return rows

def inspect(pid, root, config, reportdir, tag, expected=2, pixels=True):
    rows = windows(pid)
    build = root / 'build/windows/x64'
    engine = 'windows-x64' + ('-release' if config == 'Release' else '')
    sdk = Path(os.environ['FLUTTER_ROOT'])
    symbols = f'{sdk}/bin/cache/artifacts/engine/{engine};{build}/plugins/desktop_multi_window/{config};{build}/runner/{config}'
    commands = [f'.sympath {symbols}', '.reload /f flutter_windows.dll']
    if config == 'Debug':
        commands.append('.reload /f desktop_multi_window_plugin.dll')
    for row in rows:
        base = f"((flutter_windows!flutter::FlutterWindowsView*)((flutter_windows!flutter::FlutterWindow*){hex(row['childdata'])})->binding_handler_delegate_)"
        commands += [f".echo WINDOW {row['hwnd']}", f'dx {base}->resize_status_', f'dx {base}->surface_']
        if config == 'Debug':
            commands.append(f"dt desktop_multi_window_plugin!FlutterWindow {hex(row['userdata'])}")
    commands += ['qd']
    cmd = reportdir / f'{tag}-cdb.txt'
    cmd.write_text('\n'.join(commands) + '\n')
    result = subprocess.run([os.environ.get('CDB_PATH', 'C:\\Program Files (x86)\\Windows Kits\\10\\Debuggers\\x64\\cdb.exe'), '-pvr', '-p', str(pid), '-cf', str(cmd)], capture_output=True, text=True, timeout=25)
    (reportdir / f'{tag}-native.txt').write_text(result.stdout)
    states = re.findall('resize_status_ : (\\w+)', result.stdout)
    widths = [int(v, 16) for v in re.findall('width_\\s+: (0x[0-9a-f]+)', result.stdout)]
    heights = [int(v, 16) for v in re.findall('height_\\s+: (0x[0-9a-f]+)', result.stdout)]
    pending = re.findall('child_refresh_pending_ : (\\d+)', result.stdout)
    old = u.GetForegroundWindow()
    try:
        for i, row in enumerate(rows):
            pr = w.RECT()
            cr = w.RECT()
            u.GetClientRect(row['hwnd'], c.byref(pr))
            u.GetClientRect(row['child'], c.byref(cr))
            row.update(parent=[pr.right, pr.bottom], client=[cr.right, cr.bottom])
            if pixels:
                try:
                    # Fullscreen restores a saved extended style. Reset our earlier
                    # topmost transition before raising the window for capture.
                    if not u.SetWindowPos(row['hwnd'], w.HWND(-2), 0, 0, 0, 0, 19):
                        raise RuntimeError('Cannot reset probe z-order for pixel verification')
                    if not u.SetWindowPos(row['hwnd'], w.HWND(-1), 0, 0, 0, 0, 19):
                        raise RuntimeError('Cannot raise probe for pixel verification')
                    time.sleep(0.18)
                    r = w.RECT()
                    u.GetWindowRect(row['child'], c.byref(r))
                    locations = [(0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]
                    for attempt in range(5):
                        u.SetWindowPos(row['hwnd'], w.HWND(-1), 0, 0, 0, 0, 0x13)
                        u.SetForegroundWindow(row['hwnd'])
                        time.sleep(.2)
                        u.GetWindowRect(row['child'], c.byref(r))
                        shot = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
                        unobscured = all(u.GetAncestor(u.WindowFromPoint(w.POINT(r.left + int(shot.width * x), r.top + int(shot.height * y))), 2) == row['hwnd'] for x, y in locations)
                        if unobscured:
                            break
                    if not unobscured:
                        cloaked = w.DWORD()
                        c.windll.dwmapi.DwmGetWindowAttribute(w.HWND(row['hwnd']), 14, c.byref(cloaked), c.sizeof(cloaked))
                        hit = [u.GetAncestor(u.WindowFromPoint(w.POINT(r.left + int(shot.width * x), r.top + int(shot.height * y))), 2) for x, y in locations]
                        raise RuntimeError(f"Probe obscured: hwnd={row['hwnd']}, style={hex(u.GetWindowLongPtrW(row['hwnd'], -16))}, exstyle={hex(u.GetWindowLongPtrW(row['hwnd'], -20))}, cloaked={cloaked.value}, hit={hit}, rect={(r.left, r.top, r.right, r.bottom)}")
                    points = [shot.getpixel((int(shot.width * x), int(shot.height * y)))[:3] for x, y in locations]
                    row['pixels'] = points
                    row['green'] = all((all((abs(a - b) <= 5 for a, b in zip(rgb, (76, 175, 80)))) for rgb in points))
                    if not row['green']:
                        shot.save(reportdir / f'{tag}-{i}-failed.png')
                finally:
                    u.SetWindowPos(row['hwnd'], w.HWND(-2), 0, 0, 0, 0, 19)
    finally:
        if old and u.IsWindow(old):
            u.SetForegroundWindow(old)
    ok = len(rows) == expected and len(states) == expected and (len(widths) == expected) and (len(heights) == expected) and (len(pending) == expected or config == 'Release' or os.environ.get('RESIZE_PROBE_BASELINE') == '1') and all((s == 'kDone' for s in states)) and all((x == '0' for x in pending))
    if ok:
        ok = all((row['parent'] == row['client'] == [widths[i], heights[i]] and (not pixels or row['green']) for i, row in enumerate(rows)))
    return dict(tag=tag, ok=ok, states=states, pending=pending, widths=widths, heights=heights, windows=rows)

def launch(binary, args, log):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.Popen([str(binary), *args], cwd=binary.parent, startupinfo=startup, stdout=log, stderr=log)
