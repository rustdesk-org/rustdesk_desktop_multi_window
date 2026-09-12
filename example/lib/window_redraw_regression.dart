import 'dart:async';
import 'dart:io';

import 'package:desktop_multi_window/desktop_multi_window.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'window_redraw_probe.dart';

const _initialColor = Color(0xffff0000);
const _updatedColor = Color(0xff00ff00);
const _initialPixel = 0x000000ff;
const _updatedPixel = 0x0000ff00;
const _warmup = Duration(milliseconds: 500);
const _uiStall = Duration(milliseconds: 600);
const _pollInterval = Duration(milliseconds: 25);
const _paintTimeout = Duration(seconds: 3);
const _messageTimeout = Duration(seconds: 5);
const _processTimeout = Duration(seconds: 55);
const _testFrame = Rect.fromLTWH(80, 80, 640, 480);
const _manualResizeDelta = 16.0;

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!Platform.isWindows) {
    throw UnsupportedError('This regression requires Windows and a desktop');
  }
  if (args.isNotEmpty && args.first == 'multi_window') {
    await _runChild(int.parse(args[1]));
    return;
  }
  final timeout = Timer(_processTimeout, () {
    stderr.writeln('FAIL: regression process timed out');
    exitRegressionProcess(1);
  });
  runApp(const ColoredBox(color: Colors.black));
  try {
    final regression =
        RedrawRegression(firstShow: args.contains('--first-show'));
    await regression.run();
    stdout.writeln('PASS: all native presentation checks');
    timeout.cancel();
    exitRegressionProcess(0);
  } catch (error, stack) {
    stderr.writeln('FAIL: $error\n$stack');
    timeout.cancel();
    exitRegressionProcess(1);
  }
}

Future<void> _runChild(int windowId) async {
  final color = ValueNotifier(_initialColor);
  DesktopMultiWindow.setMethodHandler((call, fromWindowId) async {
    if (call.method == 'stall') {
      color.value = _updatedColor;
      // Notify the other engine before blocking this engine's UI thread.
      DesktopMultiWindow.invokeMethod(0, 'stall-started', windowId);
      sleep(_uiStall);
      return null;
    }
    if (call.method == 'reset') {
      color.value = _initialColor;
      return null;
    }
    throw StateError('Unexpected test method: ${call.method}');
  });
  runApp(ValueListenableBuilder<Color>(
    valueListenable: color,
    builder: (context, value, child) => ColoredBox(color: value),
  ));
  await WidgetsBinding.instance.endOfFrame;
  await DesktopMultiWindow.invokeMethod(0, 'ready', windowId);
}

class RedrawRegression {
  RedrawRegression({required this.firstShow});

  final bool firstShow;
  final _ready = Completer<void>();
  Completer<void>? _stallStarted;

  Future<void> run() async {
    DesktopMultiWindow.setMethodHandler((call, fromWindowId) async {
      if (call.method == 'ready') {
        _ready.complete();
      } else if (call.method == 'stall-started') {
        _stallStarted!.complete();
      } else if (call.method == 'onDestroy') {
        return null;
      } else {
        throw StateError('Unexpected parent method: ${call.method}');
      }
      return null;
    });
    final window = await DesktopMultiWindow.createWindow('{}');
    window.setInitBackgroundColor(Colors.black);
    final title = 'RustDesk redraw regression $pid-${window.windowId}';
    try {
      await window.setTitle(title);
      await window.setFrame(_testFrame);
      await _ready.future.timeout(_messageTimeout);
      final probe = WindowRedrawProbe.find(title);
      probe.keepAboveOtherWindows();
      if (!firstShow) {
        await window.show();
        await window.focus();
        await _requireColor(
            probe, _initialPixel, 'initial window presentation');
      }
      await Future<void>.delayed(_warmup);
      final originalSize = probe.clientSize(flutterView: true);
      await _checkStalledShow(window, probe);
      if (!listEquals(originalSize, probe.clientSize(flutterView: true))) {
        throw StateError('Refresh changed the final client size');
      }
      await _checkOrdinaryReshow(window, probe);
      await _checkMinimizeRestore(window, probe);
      await _checkMaximizeRestore(window, probe);
      await _checkFullscreenRestore(window, probe);
    } finally {
      await window.close();
    }
  }

  Future<void> _checkStalledShow(
      WindowController window, WindowRedrawProbe probe) async {
    await window.hide();
    _stallStarted = Completer<void>();
    final stalled = DesktopMultiWindow.invokeMethod(window.windowId, 'stall');
    await _stallStarted!.future.timeout(_messageTimeout);
    await window.show();
    await window.focus();
    await stalled.timeout(_messageTimeout);
    if (await _waitForColor(probe, _updatedPixel)) {
      stdout.writeln('PASS: show while the UI thread exceeds resize timeout');
      return;
    }
    final stuckColor = probe.screenColor();
    final frame = await window.getFrame();
    await window.setFrame(Rect.fromLTWH(
        frame.left, frame.top, frame.width + _manualResizeDelta, frame.height));
    final manualResizeRecovered = await _waitForColor(probe, _updatedPixel);
    throw StateError(
        'Presentation stalled: pixel=0x${stuckColor.toRadixString(16)}, '
        'manual resize recovered=$manualResizeRecovered');
  }

  Future<void> _checkOrdinaryReshow(
      WindowController window, WindowRedrawProbe probe) async {
    await window.hide();
    await DesktopMultiWindow.invokeMethod(window.windowId, 'reset');
    await window.show();
    await window.focus();
    await _requireColor(probe, _initialPixel, 'ordinary hide/show');
    await Future<void>.delayed(_warmup);
    await _requireColor(probe, _initialPixel, 'post-refresh presentation');
  }

  Future<void> _checkMinimizeRestore(
      WindowController window, WindowRedrawProbe probe) async {
    await window.minimize();
    await Future<void>.delayed(_warmup);
    await window.focus();
    await _waitForWindowState(window.isMinimized, false);
    await _requireColor(probe, _initialPixel, 'minimize/restore');
  }

  Future<void> _checkMaximizeRestore(
      WindowController window, WindowRedrawProbe probe) async {
    await window.maximize();
    await _waitForWindowState(window.isMaximized, true);
    await _requireColor(probe, _initialPixel, 'maximize');
    await window.unmaximize();
    await _waitForWindowState(window.isMaximized, false);
    await _requireColor(probe, _initialPixel, 'unmaximize');
  }

  Future<void> _checkFullscreenRestore(
      WindowController window, WindowRedrawProbe probe) async {
    final originalFrame = await window.getFrame();
    await window.setFullscreen(true);
    if (await window.getFrame() == originalFrame) {
      throw StateError('Fullscreen did not change the window frame');
    }
    await _requireColor(probe, _initialPixel, 'fullscreen');
    await window.setFullscreen(false);
    if (await window.getFrame() != originalFrame) {
      throw StateError('Leaving fullscreen did not restore the window frame');
    }
    await _requireColor(probe, _initialPixel, 'leave fullscreen');
  }
}

Future<void> _waitForWindowState(
    Future<bool> Function() readState, bool expected) async {
  final elapsed = Stopwatch()..start();
  while (await readState() != expected) {
    if (elapsed.elapsed >= _paintTimeout) {
      throw StateError('Native window did not reach the expected state');
    }
    await Future<void>.delayed(_pollInterval);
  }
}

Future<bool> _waitForColor(WindowRedrawProbe probe, int expected) async {
  final elapsed = Stopwatch()..start();
  while (elapsed.elapsed < _paintTimeout) {
    if (probe.screenColor() == expected) {
      return true;
    }
    await Future<void>.delayed(_pollInterval);
  }
  return false;
}

Future<void> _requireColor(
    WindowRedrawProbe probe, int expected, String scenario) async {
  if (!await _waitForColor(probe, expected)) {
    throw StateError('$scenario: expected 0x${expected.toRadixString(16)}, '
        'got 0x${probe.screenColor().toRadixString(16)}; keep the window unobscured');
  }
  stdout.writeln('PASS: $scenario');
}
