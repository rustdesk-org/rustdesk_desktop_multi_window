import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:desktop_multi_window/desktop_multi_window.dart';
import 'package:flutter/material.dart';

const initialColor = Color(0xffff0000);
const updatedColor = Color(0xff00ff00);
const uiStall = Duration(milliseconds: 800);
const startupSettle = Duration(milliseconds: 700);
const messageTimeout = Duration(seconds: 5);
const initialFrame = Rect.fromLTWH(80, 80, 1016, 660);

void emit(String event, [Object? data]) {
  stdout.writeln('PROBE ${jsonEncode({
        'event': event,
        if (data != null) 'data': data,
      })}');
}

Map<String, Object> metrics(Color color) {
  final view = WidgetsBinding.instance.platformDispatcher.views.single;
  return {
    'pixelRatio': view.devicePixelRatio,
    'physicalSize': [view.physicalSize.width, view.physicalSize.height],
    'green': color == updatedColor,
  };
}

Future<void> runChild(int id) async {
  final color = ValueNotifier(initialColor);
  DesktopMultiWindow.setMethodHandler((call, from) async {
    switch (call.method) {
      case 'paint':
        color.value = updatedColor;
        return null;
      case 'toggle':
        color.value = color.value == initialColor ? updatedColor : initialColor;
        await WidgetsBinding.instance.endOfFrame;
        return metrics(color.value);
      case 'metrics':
        await WidgetsBinding.instance.endOfFrame;
        return metrics(color.value);
      case 'stall':
        color.value = updatedColor;
        unawaited(DesktopMultiWindow.invokeMethod(0, 'stall-started'));
        sleep(uiStall);
        return null;
      case 'onDestroy':
        return null;
      default:
        throw StateError('Unexpected child command: ${call.method}');
    }
  });
  runApp(ValueListenableBuilder<Color>(
    valueListenable: color,
    builder: (context, value, child) => ColoredBox(color: value),
  ));
  await WidgetsBinding.instance.endOfFrame;
  await DesktopMultiWindow.invokeMethod(0, 'ready', id);
}

Future<void> runParent() async {
  final ready = Completer<void>();
  DesktopMultiWindow.setMethodHandler((call, from) async {
    if (call.method == 'ready') {
      ready.complete();
    } else if (call.method == 'stall-started') {
      emit('stall-started');
    } else if (call.method != 'onDestroy') {
      throw StateError('Unexpected parent command: ${call.method}');
    }
    return null;
  });
  runApp(const ColoredBox(color: Colors.black));
  final window = await DesktopMultiWindow.createWindow('{}');
  await window.setTitle('PR38 native regression $pid');
  await window.setFrame(initialFrame);
  await ready.future.timeout(messageTimeout);
  await window.show();
  await Future<void>.delayed(startupSettle);
  emit('ready');
  final commands =
      stdin.transform(utf8.decoder).transform(const LineSplitter());
  await for (final command in commands) {
    if (!const ['paint', 'stall', 'toggle', 'metrics'].contains(command)) {
      throw StateError('Unexpected host command: $command');
    }
    final result =
        await DesktopMultiWindow.invokeMethod(window.windowId, command)
            .timeout(messageTimeout);
    emit('$command-completed', result);
  }
}

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  if (args.isNotEmpty && args.first == 'multi_window') {
    await runChild(int.parse(args[1]));
    return;
  }
  await runParent();
}
