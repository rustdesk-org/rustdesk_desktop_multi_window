import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:desktop_multi_window/desktop_multi_window.dart';

void busy(int milliseconds) {
  final timer = Stopwatch()..start();
  while (timer.elapsedMilliseconds < milliseconds) {}
}

void main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  final child = args.isNotEmpty && args[0] == 'multi_window';
  final mode = child
      ? jsonDecode(args[2])['mode'] as String
      : (args.isEmpty ? 'busy_ui' : args[0]);
  final id = child ? int.parse(args[1]) : 0;
  Future<dynamic> handler(call, int from) async {
    if (!child && call.method == 'shown' && from == 2) {
      final wc = WindowController.fromWindowId(from);
      if (mode == 'resize_during') {
        Timer(const Duration(milliseconds: 350),
            () => wc.setFrame(const Rect.fromLTWH(130, 100, 550, 330)));
      } else if (mode == 'close_during') {
        Timer(const Duration(milliseconds: 350), wc.close);
      } else if (mode == 'minimize_restore') {
        Timer(const Duration(milliseconds: 350), wc.minimize);
        Timer(const Duration(milliseconds: 6500), wc.focus);
      } else if (mode == 'hide_show') {
        Timer(const Duration(milliseconds: 350), wc.hide);
        Timer(const Duration(milliseconds: 1300), wc.show);
      } else if (mode == 'rapid_resize') {
        for (var n = 0; n < 20; n++) {
          Timer(
              Duration(milliseconds: 100 + n * 40),
              () => wc
                  .setFrame(Rect.fromLTWH(160, 100, 500 + n * 3, 300 + n * 2)));
        }
      } else if (mode == 'fullscreen') {
        Timer(const Duration(milliseconds: 350), () => wc.setFullscreen(true));
        Timer(
            const Duration(milliseconds: 1800), () => wc.setFullscreen(false));
      } else if (mode == 'maximize_restore') {
        Timer(const Duration(milliseconds: 350), wc.maximize);
        Timer(const Duration(milliseconds: 1800), wc.unmaximize);
      }
    }
    return null;
  }

  if (!child || mode != 'no_handler')
    DesktopMultiWindow.setMethodHandler(handler);
  if (child && mode == 'clear_handler')
    DesktopMultiWindow.setMethodHandler(null);
  if (child && mode == 'late_handler') {
    DesktopMultiWindow.setMethodHandler(null);
    Timer(const Duration(seconds: 6),
        () => DesktopMultiWindow.setMethodHandler(handler));
  }
  if (child && mode == 'startup_slow') busy(1800);
  if (child && mode == 'startup_very_slow') busy(6000);
  runApp(Probe(id: id, mode: mode));
  if (!child && mode == 'stress') {
    final dir = Directory(args[1]);
    for (var round = 0; round < 50; round++) {
      final modes = ['busy_ui', 'busy_build', 'fast'];
      final windows = <WindowController>[];
      for (final testMode in ['fast', modes[round % modes.length]]) {
        final wc = await DesktopMultiWindow.createWindow(
            jsonEncode({'mode': testMode}));
        windows.add(wc);
        await wc.setTitle('resize_probe_$testMode');
        await wc
            .setFrame(Rect.fromLTWH(100 + windows.length * 30, 100, 500, 300));
      }
      await Future<void>.delayed(const Duration(milliseconds: 1200));
      final wc = windows.last;
      if (round % 5 == 0) {
        await wc.hide();
        await wc.show();
      } else if (round % 5 == 1) {
        await wc.minimize();
        await wc.focus();
      } else if (round % 5 == 2) {
        await wc.maximize();
        await wc.unmaximize();
      } else if (round % 5 == 3) {
        await wc.setFullscreen(true);
        await wc.setFullscreen(false);
      } else {
        for (var i = 0; i < 10; i++) {
          await wc.setFrame(Rect.fromLTWH(160, 100, 500 + i * 2, 300.0 + i));
        }
      }
      await Future<void>.delayed(const Duration(milliseconds: 800));
      File('${dir.path}/ready.json').writeAsStringSync(jsonEncode(
          {'round': round, 'ids': windows.map((w) => w.windowId).toList()}));
      final ack = File('${dir.path}/ack-$round');
      while (!ack.existsSync()) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      for (final window in windows) {
        await window.close();
      }
      await Future<void>.delayed(const Duration(milliseconds: 200));
      final remaining = await DesktopMultiWindow.getAllSubWindowIds();
      if (remaining.isNotEmpty)
        throw StateError('Windows not closed: $remaining');
    }
    File('${dir.path}/done').writeAsStringSync('50');
    exit(0);
  }
  if (!child) {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    for (final testMode in ['fast', mode]) {
      final wc =
          await DesktopMultiWindow.createWindow(jsonEncode({'mode': testMode}));
      await wc.setTitle('resize_probe_$testMode');
      await wc.setFrame(Rect.fromLTWH(100 + wc.windowId * 30, 100, 500, 300));
    }
  }
}

class Probe extends StatefulWidget {
  const Probe({super.key, required this.id, required this.mode});
  final int id;
  final String mode;
  @override
  State<Probe> createState() => ProbeState();
}

class ProbeState extends State<Probe> {
  bool ready = false;
  bool blockBuild = false;
  @override
  void initState() {
    super.initState();
    if (widget.id > 0) {
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        if (widget.mode == 'hidden_start')
          await Future<void>.delayed(const Duration(seconds: 6));
        await WindowController.fromWindowId(widget.id).show();
        await DesktopMultiWindow.invokeMethod(0, 'shown');
        Timer(const Duration(milliseconds: 80), () {
          if (widget.mode == 'busy_build') {
            setState(() {
              blockBuild = true;
              ready = true;
            });
          } else {
            if (widget.mode != 'fast') busy(800);
            setState(() {
              ready = true;
            });
          }
        });
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (blockBuild) {
      blockBuild = false;
      busy(800);
    }
    return MaterialApp(
        home: ColoredBox(
            color: ready ? Colors.green : Colors.red,
            child: Center(
                child: Text(
                    '${widget.id}: ${widget.mode} ${ready ? "ready" : "starting"}'))));
  }
}
