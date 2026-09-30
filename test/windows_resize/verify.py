import argparse
import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from native_probe import NativeProbe, ProbePaths

EVENT_TIMEOUT = 10
PROCESS_EXIT_TIMEOUT = 5
RESIZE_DELTA = 200
AFTER_REFRESH_DELAY = 1.0
INITIAL_PIXEL = 0x000000FF
UPDATED_PIXEL = 0x0000FF00
EVENT_PREFIX = 'PROBE '
DEFAULT_CDB = Path('C:/Program Files (x86)/Windows Kits/10/Debuggers/x64/cdb.exe')


class Application:
    def __init__(self, binary, report_directory):
        self.events = queue.Queue()
        self.log = (report_directory / 'application.log').open('w', encoding='utf-8')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        self.process = subprocess.Popen(
            [str(binary)], cwd=binary.parent, startupinfo=startup,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        self.reader = threading.Thread(target=self.read_events, daemon=True)
        self.reader.start()

    def read_events(self):
        for line in self.process.stdout:
            self.log.write(line)
            self.log.flush()
            if line.startswith(EVENT_PREFIX):
                self.events.put(json.loads(line[len(EVENT_PREFIX):]))

    def wait(self, expected):
        deadline = time.monotonic() + EVENT_TIMEOUT
        while time.monotonic() < deadline:
            event = self.events.get(timeout=max(0, deadline - time.monotonic()))
            if event['event'] != expected:
                raise RuntimeError(f'Expected {expected}, got {event}')
            return event
        raise TimeoutError(f'Did not receive {expected}')

    def send(self, command):
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=PROCESS_EXIT_TIMEOUT)
        self.reader.join(timeout=PROCESS_EXIT_TIMEOUT)
        self.log.close()


def complete(state, expected_pixel):
    return (state['state'] == 'kDone'
            and state['parent'] == state['child'] == state['surface']
            and all(pixel == expected_pixel for pixel in state['pixels']))


def require_stale(state, original):
    expected_target = [original['child'][0] + RESIZE_DELTA, original['child'][1]]
    if not (state['state'] == 'kResizeStarted'
            and state['surface'] == state['child'] == state['parent'] == original['child']
            and state['target'] == expected_target and state['first_frame']):
        raise RuntimeError(f'Stale-target precondition not reached: {state}')
    if all(pixel == UPDATED_PIXEL for pixel in state['pixels']):
        raise RuntimeError('Green frame was already displayed before recovery')


def record(report_directory, tag, state):
    (report_directory / f'{tag}.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
    print(json.dumps(dict(stage=tag, **state)), flush=True)
    return state


def capture(probe, tag):
    return record(probe.paths.report, tag, probe.inspect(tag))


def exercise(application, probe, scenario):
    initial = capture(probe, 'initial')
    if not complete(initial, INITIAL_PIXEL) or not initial['first_frame']:
        raise RuntimeError(f'Initial rendering was not healthy: {initial}')
    if scenario == 'healthy':
        application.send('paint')
        application.wait('paint-completed')
        probe.refresh()
        time.sleep(AFTER_REFRESH_DELAY)
        after = capture(probe, 'after-refresh')
        return dict(initial=initial, after=after, recovered=complete(after, UPDATED_PIXEL))
    application.send('stall')
    application.wait('stall-started')
    if scenario == 'busy_refresh':
        probe.refresh()
        application.wait('stall-completed')
        before = None
    else:
        durations = [probe.resize(RESIZE_DELTA), probe.resize(0)]
        application.wait('stall-completed')
        before = capture(probe, 'before-refresh')
        require_stale(before, initial)
        record(probe.paths.report, 'resize-durations', dict(seconds=durations))
        if scenario == 'stale_show':
            probe.reshow()
        else:
            probe.refresh()
    time.sleep(AFTER_REFRESH_DELAY)
    after = capture(probe, 'after-refresh')
    recovered = complete(after, UPDATED_PIXEL)
    probe.resize(RESIZE_DELTA)
    probe.resize(0)
    control = capture(probe, 'manual-resize-control')
    if not complete(control, UPDATED_PIXEL):
        raise RuntimeError(f'Manual resize control did not recover: {control}')
    return dict(initial=initial, before=before, after=after, control=control, recovered=recovered)


def run(options):
    project = options.project.resolve()
    bundle = project / 'build/windows/x64/runner' / options.configuration
    report_directory = options.report.resolve()
    report_directory.mkdir(parents=True, exist_ok=False)
    application = Application(bundle / 'resize_probe.exe', report_directory)
    metadata = dict(project=str(project), scenario=options.scenario,
                    configuration=options.configuration, process_id=application.process.pid,
                    plugin_sha256=hashlib.sha256((bundle / 'desktop_multi_window_plugin.dll')
                                                .read_bytes()).hexdigest())
    try:
        application.wait('ready')
        paths = ProbePaths(project=project, report=report_directory,
                           configuration=options.configuration, sdk=options.flutter_root,
                           debugger=options.cdb)
        outcome = exercise(application, NativeProbe(application.process.pid, paths), options.scenario)
        result = dict(**metadata, completed=True, **outcome)
    except Exception as error:
        result = dict(**metadata, completed=False, error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        application.close()
        (report_directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(**metadata, recovered=result['recovered'], report=str(report_directory))),
          flush=True)
    return 0 if result['recovered'] else 1


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--flutter-root', type=Path, required=True)
    parser.add_argument('--cdb', type=Path, default=DEFAULT_CDB)
    parser.add_argument('--scenario', choices=('healthy', 'stale', 'stale_show', 'busy_refresh'),
                        required=True)
    parser.add_argument('--configuration', default='Debug', choices=('Debug',))
    parser.add_argument('--report', type=Path, required=True)
    return parser.parse_args()


if __name__ == '__main__':
    sys.exit(run(arguments()))
