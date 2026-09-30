import ctypes as c
import ctypes.wintypes as w
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageGrab

GW_CHILD = 5
GWLP_USERDATA = -21
GA_ROOT = 2
HWND_TOPMOST = -1
DPI_AWARE_CONTEXT = -4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200
WM_TIMER = 0x0113
REFRESH_TIMER = 0xFB15
SW_HIDE = 0
SW_SHOW = 5
SMTO_ABORTIFHUNG = 0x0002
MESSAGE_TIMEOUT_MS = 3000
DEBUGGER_TIMEOUT = 15
PIXEL_SETTLE = 0.15
INVALID_PIXEL = 0xFFFFFFFF
CLASS_CAPACITY = 256
SAMPLE_FRACTIONS = ((0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8))
ENUM_CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


@dataclass(frozen=True)
class ProbePaths:
    project: Path
    report: Path
    configuration: str
    sdk: Path
    debugger: Path


def user32():
    library = c.WinDLL('user32', use_last_error=True)
    signatures = {
        'GetWindowThreadProcessId': ([w.HWND, c.POINTER(w.DWORD)], w.DWORD),
        'GetClassNameW': ([w.HWND, w.LPWSTR, c.c_int], c.c_int),
        'GetWindow': ([w.HWND, w.UINT], w.HWND),
        'GetWindowLongPtrW': ([w.HWND, c.c_int], c.c_ssize_t),
        'GetClientRect': ([w.HWND, c.POINTER(w.RECT)], w.BOOL),
        'GetWindowRect': ([w.HWND, c.POINTER(w.RECT)], w.BOOL),
        'GetAncestor': ([w.HWND, w.UINT], w.HWND),
        'ShowWindow': ([w.HWND, c.c_int], w.BOOL),
        'IsWindowVisible': ([w.HWND], w.BOOL),
        'WindowFromPoint': ([w.POINT], w.HWND),
        'SetThreadDpiAwarenessContext': ([c.c_void_p], c.c_void_p),
        'SetWindowPos': ([w.HWND, w.HWND, c.c_int, c.c_int,
                          c.c_int, c.c_int, w.UINT], w.BOOL),
        'SendMessageTimeoutW': ([w.HWND, w.UINT, w.WPARAM, w.LPARAM,
                                 w.UINT, w.UINT, c.POINTER(c.c_size_t)], w.LPARAM),
        'GetDC': ([w.HWND], w.HDC),
        'ReleaseDC': ([w.HWND, w.HDC], c.c_int),
        'EnumWindows': ([ENUM_CALLBACK, w.LPARAM], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    if not library.SetThreadDpiAwarenessContext(c.c_void_p(DPI_AWARE_CONTEXT)):
        raise c.WinError(c.get_last_error())
    return library


def unique_match(pattern, text):
    matches = re.findall(pattern, text, re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError(f'Expected one debugger field {pattern}, got {matches}')
    return matches[0]


def parse_native(text, *, plugin_symbols=True):
    number = r'(0x[0-9a-fA-F]+|[0-9]+)'
    state = unique_match(r'resize_status_\s+: (\w+)', text)
    target = [int(unique_match(rf'resize_target_{axis}_\s+: {number}', text), 0)
              for axis in ('width', 'height')]
    surface = [int(unique_match(rf'\b{axis}_\s+: {number}', text), 0)
               for axis in ('width', 'height')]
    result = dict(state=state, target=target, surface=surface)
    if plugin_symbols:
        first_frame = unique_match(r'first_frame_rendered_\s+: (\S+)', text)
        result['first_frame'] = first_frame in ('0x1', '1', 'true')
    return result


class NativeProbe:
    def __init__(self, process_id, paths):
        self.process_id = process_id
        self.paths = paths
        self.api = user32()
        self.parent = self.find_window()
        self.child = self.api.GetWindow(self.parent, GW_CHILD)
        if not self.child:
            raise RuntimeError('Flutter child HWND was not found')
        self.original_outer = self.rect(self.parent, client=False)
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        if not self.api.SetWindowPos(self.parent, HWND_TOPMOST, 0, 0, 0, 0, flags):
            raise c.WinError(c.get_last_error())

    def find_window(self):
        found = []

        @ENUM_CALLBACK
        def visit(handle, unused):
            owner = w.DWORD()
            self.api.GetWindowThreadProcessId(handle, c.byref(owner))
            if owner.value != self.process_id:
                return True
            name = c.create_unicode_buffer(CLASS_CAPACITY)
            self.api.GetClassNameW(handle, name, CLASS_CAPACITY)
            if name.value == 'RustdeskMultiWindow':
                found.append(handle)
            return True

        if not self.api.EnumWindows(visit, 0):
            raise c.WinError(c.get_last_error())
        if len(found) != 1:
            raise RuntimeError(f'Expected one owned secondary window, got {found}')
        return found[0]

    def rect(self, handle, *, client):
        result = w.RECT()
        function = self.api.GetClientRect if client else self.api.GetWindowRect
        if not function(handle, c.byref(result)):
            raise c.WinError(c.get_last_error())
        return (result.left, result.top, result.right, result.bottom)

    def size(self, handle):
        left, top, right, bottom = self.rect(handle, client=True)
        return [right - left, bottom - top]

    def resize(self, width_delta):
        left, top, right, bottom = self.original_outer
        flags = SWP_NOMOVE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED
        started = time.monotonic()
        result = self.api.SetWindowPos(self.parent, None, 0, 0,
                                      right - left + width_delta, bottom - top, flags)
        if not result:
            raise c.WinError(c.get_last_error())
        return time.monotonic() - started

    def refresh(self):
        result = c.c_size_t()
        success = self.api.SendMessageTimeoutW(
            self.parent, WM_TIMER, REFRESH_TIMER, 0, SMTO_ABORTIFHUNG,
            MESSAGE_TIMEOUT_MS, c.byref(result))
        if not success:
            raise c.WinError(c.get_last_error())

    def reshow(self):
        self.api.ShowWindow(self.parent, SW_HIDE)
        if self.api.IsWindowVisible(self.parent):
            raise RuntimeError('The test window did not hide')
        self.api.ShowWindow(self.parent, SW_SHOW)
        if not self.api.IsWindowVisible(self.parent):
            raise RuntimeError('The test window did not show')

    def debugger(self, tag):
        child_data = self.api.GetWindowLongPtrW(self.child, GWLP_USERDATA)
        parent_data = self.api.GetWindowLongPtrW(self.parent, GWLP_USERDATA)
        if not child_data or not parent_data:
            raise RuntimeError('Window instance pointer was not found')
        view = ('((flutter_windows!flutter::FlutterWindowsView*)'
                f'((flutter_windows!flutter::FlutterWindow*){child_data:#x})'
                '->binding_handler_delegate_)')
        plugin_symbols = self.paths.configuration == 'Debug'
        commands = ['.reload /f flutter_windows.dll']
        if plugin_symbols:
            commands += ['.reload /f desktop_multi_window_plugin.dll']
        commands += [f'dx {view}->{field}' for field in
                     ('resize_status_', 'resize_target_width_',
                      'resize_target_height_', 'surface_')]
        if plugin_symbols:
            commands += [f'dt desktop_multi_window_plugin!FlutterWindow {parent_data:#x} '
                         'first_frame_rendered_']
        if tag == 'initial':
            if plugin_symbols:
                commands += ['x desktop_multi_window_plugin!*ChildRefresh*']
            commands += ['lmv m desktop_multi_window_plugin', 'lmv m flutter_windows']
        commands += ['qd']
        engine_dir = 'windows-x64' if plugin_symbols else 'windows-x64-release'
        plugin_dir = self.paths.project / 'build/windows/x64/plugins/desktop_multi_window'
        symbols = ';'.join([str(self.paths.sdk / 'bin/cache/artifacts/engine' / engine_dir),
                            str(plugin_dir / self.paths.configuration)])
        command_file = self.paths.report / f'{tag}-cdb.txt'
        command_file.write_text('\n'.join(commands) + '\n', encoding='utf-8')
        result = subprocess.run([str(self.paths.debugger), '-y', symbols, '-pvr', '-p',
                                 str(self.process_id), '-cf', str(command_file)],
                                capture_output=True, text=True, timeout=DEBUGGER_TIMEOUT)
        text = result.stdout + result.stderr
        (self.paths.report / f'{tag}-native.txt').write_text(text, encoding='utf-8')
        result.check_returncode()
        return parse_native(text, plugin_symbols=plugin_symbols)

    def pixels(self, tag):
        time.sleep(PIXEL_SETTLE)
        left, top, right, bottom = self.rect(self.child, client=False)
        positions = [(left + int((right - left) * x), top + int((bottom - top) * y))
                     for x, y in SAMPLE_FRACTIONS]
        hits = [self.api.GetAncestor(self.api.WindowFromPoint(w.POINT(x, y)), GA_ROOT)
                for x, y in positions]
        if any(handle != self.parent for handle in hits):
            raise RuntimeError(f'Test window is obscured; HWND hits are {hits}')
        graphics = c.WinDLL('gdi32', use_last_error=True)
        graphics.GetPixel.argtypes = [w.HDC, c.c_int, c.c_int]
        graphics.GetPixel.restype = w.DWORD
        device = self.api.GetDC(None)
        if not device:
            raise c.WinError(c.get_last_error())
        try:
            values = [graphics.GetPixel(device, x, y) for x, y in positions]
        finally:
            if not self.api.ReleaseDC(None, device):
                raise c.WinError(c.get_last_error())
        if INVALID_PIXEL in values:
            raise RuntimeError('GetPixel failed on the test window')
        ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(
            self.paths.report / f'{tag}.png')
        return values

    def inspect(self, tag):
        state = self.debugger(tag)
        return dict(**state, parent=self.size(self.parent), child=self.size(self.child),
                    pixels=self.pixels(tag))
