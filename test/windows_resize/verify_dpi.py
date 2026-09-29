import argparse
import ctypes as c
import ctypes.wintypes as w
import hashlib
import json
import time
import traceback
from pathlib import Path

from native_probe import NativeProbe, ProbePaths, user32
from verify import Application, DEFAULT_CDB, INITIAL_PIXEL, UPDATED_PIXEL, complete, record

BASE_DPI = 96
DPI_CONTEXT = -4
MONITOR_NEAREST = 2
EFFECTIVE_DPI = 0
PRIMARY_MONITOR = 1
DEVICE_NAME_LENGTH = 32
MOVE_FLAGS = 0x0001 | 0x0004 | 0x0010  # No size, z-order or activation change.
MONITOR_MARGIN = 80
SW_HIDE = 0
SW_SHOW = 5
SETTLE_SECONDS = 1.2
RAPID_INTERVAL = 0.05
RAPID_SWITCHES = 5
REFRESH_WIDTH_DELTA = 1
MONITOR_CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC,
                               c.POINTER(w.RECT), w.LPARAM)


class MonitorInfo(c.Structure):
    _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT),
                ('flags', w.DWORD), ('device', w.WCHAR * DEVICE_NAME_LENGTH)]


class Desktop:
    def __init__(self):
        self.api = user32()
        self.api.GetDpiForWindow.argtypes = [w.HWND]
        self.api.GetDpiForWindow.restype = w.UINT
        self.api.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
        self.api.MonitorFromWindow.restype = w.HMONITOR
        self.api.GetMonitorInfoW.argtypes = [w.HMONITOR, c.POINTER(MonitorInfo)]
        self.api.EnumDisplayMonitors.argtypes = [w.HDC, c.POINTER(w.RECT),
                                                MONITOR_CALLBACK, w.LPARAM]
        self.scaling = c.WinDLL('shcore', use_last_error=True)
        self.scaling.GetDpiForMonitor.argtypes = [w.HMONITOR, c.c_int,
                                                c.POINTER(w.UINT), c.POINTER(w.UINT)]
        self.scaling.GetDpiForMonitor.restype = c.c_long

    def read_monitor(self, handle):
        info = MonitorInfo()
        info.size = c.sizeof(info)
        if not self.api.GetMonitorInfoW(handle, c.byref(info)):
            raise c.WinError(c.get_last_error())
        x, y = w.UINT(), w.UINT()
        status = self.scaling.GetDpiForMonitor(handle, EFFECTIVE_DPI,
                                               c.byref(x), c.byref(y))
        if status != 0:
            raise RuntimeError(f'GetDpiForMonitor failed: {status:#x}')
        rectangle = lambda value: [value.left, value.top, value.right, value.bottom]
        return dict(handle=handle, device=info.device, dpi=[x.value, y.value],
                    primary=bool(info.flags & PRIMARY_MONITOR),
                    monitor=rectangle(info.monitor), work=rectangle(info.work))

    def monitors(self):
        rows, errors = [], []

        @MONITOR_CALLBACK
        def visit(handle, device, rectangle, context):
            try:
                rows.append(self.read_monitor(handle))
                return True
            except Exception as error:
                errors.append(error)
                return False

        succeeded = self.api.EnumDisplayMonitors(None, None, visit, 0)
        if errors:
            raise errors[0]
        if not succeeded:
            raise c.WinError(c.get_last_error())
        return rows

    def window(self, probe):
        return dict(monitor=self.api.MonitorFromWindow(probe.parent, MONITOR_NEAREST),
                    parent_dpi=self.api.GetDpiForWindow(probe.parent),
                    child_dpi=self.api.GetDpiForWindow(probe.child),
                    outer=probe.rect(probe.parent, client=False))


class DpiExercise:
    def __init__(self, application, probe):
        self.application = application
        self.probe = probe
        self.desktop = Desktop()
        self.monitors = self.desktop.monitors()
        current = self.desktop.window(probe)['monitor']
        self.source = next(item for item in self.monitors if item['handle'] == current)
        candidates = [item for item in self.monitors if item['dpi'] != self.source['dpi']]
        if not candidates:
            raise RuntimeError('Cross-DPI verification requires two monitors with different DPI')
        self.destination = candidates[0]
        self.movements = []
        self.stages = []

    def check(self, target, *, tag, green, command):
        self.application.send(command)
        metrics = self.application.wait(f'{command}-completed')['data']
        native = self.probe.inspect(tag)
        window = self.desktop.window(self.probe)
        state = dict(native=native, window=window, dart=metrics, expected_monitor=target)
        self.stages.append(record(self.probe.paths.report, tag, state))
        expected_pixel = UPDATED_PIXEL if green else INITIAL_PIXEL
        if not complete(native, expected_pixel):
            raise RuntimeError(f'Native surface or visible pixels failed at {tag}')
        if window['monitor'] != target['handle']:
            raise RuntimeError(f'The window did not reach the expected monitor at {tag}')
        expected_dpi = target['dpi'][0]
        if window['parent_dpi'] != expected_dpi or window['child_dpi'] != expected_dpi:
            raise RuntimeError(f'Native window DPI mismatch at {tag}')
        if metrics['pixelRatio'] * BASE_DPI != expected_dpi:
            raise RuntimeError(f'Flutter devicePixelRatio mismatch at {tag}')
        if metrics['physicalSize'] != native['parent'] or metrics['green'] != green:
            raise RuntimeError(f'Flutter size or fresh-color update mismatch at {tag}')

    def move(self, target):
        before = self.desktop.window(self.probe)
        left, top, _right, _bottom = target['work']
        started = time.monotonic()
        if not self.desktop.api.SetWindowPos(
                self.probe.parent, None, left + MONITOR_MARGIN, top + MONITOR_MARGIN,
                0, 0, MOVE_FLAGS):
            raise c.WinError(c.get_last_error())
        after = self.desktop.window(self.probe)
        movement = dict(before=before, after=after, seconds=time.monotonic() - started)
        self.movements.append(movement)
        record(self.probe.paths.report, f'move-{len(self.movements)}', movement)
        if after['monitor'] != target['handle'] or after['parent_dpi'] != target['dpi'][0]:
            raise RuntimeError('A real cross-monitor DPI transition did not occur')
        if before['parent_dpi'] == after['parent_dpi']:
            raise RuntimeError('The test movement did not change DPI')

    def require_pending_refresh(self):
        self.probe.refresh()
        parent, child = self.probe.size(self.probe.parent), self.probe.size(self.probe.child)
        record(self.probe.paths.report, f'pending-{len(self.movements)}',
               dict(parent=parent, child=child))
        if child != [parent[0] + REFRESH_WIDTH_DELTA, parent[1]]:
            raise RuntimeError('Temporary recovery width was not active before the DPI switch')

    def show(self, visible):
        self.desktop.api.ShowWindow(self.probe.parent, SW_SHOW if visible else SW_HIDE)
        if bool(self.desktop.api.IsWindowVisible(self.probe.parent)) != visible:
            raise RuntimeError('The test window did not reach the requested visibility')

    def run(self, scenario):
        self.check(self.source, tag='initial', green=False, command='metrics')
        for index, target in enumerate((self.destination, self.source)):
            if scenario == 'pending':
                self.require_pending_refresh()
            if scenario == 'hidden':
                self.show(False)
            if scenario == 'rapid' and index == 0:
                for move in range(RAPID_SWITCHES):
                    self.move(self.destination if move % 2 == 0 else self.source)
                    time.sleep(RAPID_INTERVAL)
            else:
                self.move(target)
            if scenario == 'hidden':
                self.show(True)
            time.sleep(SETTLE_SECONDS)
            self.check(target, tag=f'after-{index + 1}', green=index == 0, command='toggle')


def enable_process_dpi_awareness():
    api = c.WinDLL('user32', use_last_error=True)
    api.SetProcessDpiAwarenessContext.argtypes = [c.c_void_p]
    api.SetProcessDpiAwarenessContext.restype = w.BOOL
    if not api.SetProcessDpiAwarenessContext(c.c_void_p(DPI_CONTEXT)):
        raise c.WinError(c.get_last_error())


def run(options):
    enable_process_dpi_awareness()
    report = options.report.resolve()
    report.mkdir(parents=True, exist_ok=False)
    bundle = options.project.resolve() / 'build/windows/x64/runner' / options.configuration
    application = Application(bundle / 'resize_probe.exe', report)
    result = dict(scenario=options.scenario, configuration=options.configuration,
                  sdk=str(options.flutter_root), project=str(options.project),
                  plugin_sha256=hashlib.sha256((bundle / 'desktop_multi_window_plugin.dll')
                                              .read_bytes()).hexdigest(), passed=False)
    exercise = None
    try:
        application.wait('ready')
        paths = ProbePaths(project=options.project.resolve(), report=report,
                           configuration=options.configuration, sdk=options.flutter_root,
                           debugger=options.cdb)
        exercise = DpiExercise(application, NativeProbe(application.process.pid, paths))
        exercise.run(options.scenario)
        result['passed'] = True
    except Exception as error:
        result.update(error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        application.close()
        if exercise is not None:
            result.update(monitors=exercise.monitors, movements=exercise.movements,
                          stages=exercise.stages)
        (report / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, scenario=options.scenario, report=str(report))))


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--flutter-root', type=Path, required=True)
    parser.add_argument('--configuration', choices=('Debug', 'Release'), required=True)
    parser.add_argument('--scenario', choices=('roundtrip', 'rapid', 'pending', 'hidden'),
                        required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--cdb', type=Path, default=DEFAULT_CDB)
    return parser.parse_args()


if __name__ == '__main__':
    run(arguments())
