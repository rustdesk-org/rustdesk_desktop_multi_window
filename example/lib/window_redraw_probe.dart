import 'dart:ffi';
import 'dart:io';

const _heapZeroMemory = 0x00000008;
const _invalidColor = 0xffffffff;
const _rectFields = 4;
const _pointFields = 2;
const _topmostWindow = -1;
const _keepPositionAndSize = 0x0003;
const _firstChild = 5;

final _kernel32 = DynamicLibrary.open('kernel32.dll');
final _user32 = DynamicLibrary.open('user32.dll');
final _gdi32 = DynamicLibrary.open('gdi32.dll');
final _getProcessHeap = _kernel32
    .lookupFunction<IntPtr Function(), int Function()>('GetProcessHeap');
final _heapAlloc = _kernel32.lookupFunction<
    Pointer<Void> Function(IntPtr, Uint32, IntPtr),
    Pointer<Void> Function(int, int, int)>('HeapAlloc');
final _heapFree = _kernel32.lookupFunction<
    Int32 Function(IntPtr, Uint32, Pointer<Void>),
    int Function(int, int, Pointer<Void>)>('HeapFree');
final _findWindow = _user32.lookupFunction<
    IntPtr Function(Pointer<Uint8>, Pointer<Uint8>),
    int Function(Pointer<Uint8>, Pointer<Uint8>)>('FindWindowA');
final _getWindowProcess = _user32.lookupFunction<
    Uint32 Function(IntPtr, Pointer<Uint32>),
    int Function(int, Pointer<Uint32>)>('GetWindowThreadProcessId');
final _getClientRect = _user32.lookupFunction<
    Int32 Function(IntPtr, Pointer<Int32>),
    int Function(int, Pointer<Int32>)>('GetClientRect');
final _getWindow = _user32.lookupFunction<IntPtr Function(IntPtr, Uint32),
    int Function(int, int)>('GetWindow');
final _clientToScreen = _user32.lookupFunction<
    Int32 Function(IntPtr, Pointer<Int32>),
    int Function(int, Pointer<Int32>)>('ClientToScreen');
final _getDc =
    _user32.lookupFunction<IntPtr Function(IntPtr), int Function(int)>('GetDC');
final _releaseDc = _user32.lookupFunction<Int32 Function(IntPtr, IntPtr),
    int Function(int, int)>('ReleaseDC');
final _getPixel = _gdi32.lookupFunction<Uint32 Function(IntPtr, Int32, Int32),
    int Function(int, int, int)>('GetPixel');
final _setWindowPos = _user32.lookupFunction<
    Int32 Function(IntPtr, IntPtr, Int32, Int32, Int32, Int32, Uint32),
    int Function(int, int, int, int, int, int, int)>('SetWindowPos');
final _getCurrentProcess = _kernel32
    .lookupFunction<IntPtr Function(), int Function()>('GetCurrentProcess');
final _terminateProcess = _kernel32.lookupFunction<
    Int32 Function(IntPtr, Uint32), int Function(int, int)>('TerminateProcess');

void exitRegressionProcess(int code) {
  // DLL detach can block multi-engine shutdown on this SDK. The standalone
  // harness owns this process and preserves the assertion result as its status.
  if (_terminateProcess(_getCurrentProcess(), code) == 0) {
    throw StateError('Unable to exit the regression process with status $code');
  }
}

Pointer<T> _allocate<T extends NativeType>(int bytes) {
  final memory = _heapAlloc(_getProcessHeap(), _heapZeroMemory, bytes);
  if (memory == nullptr) {
    throw StateError('HeapAlloc failed');
  }
  return memory.cast<T>();
}

void _free(Pointer<NativeType> memory) {
  if (_heapFree(_getProcessHeap(), 0, memory.cast<Void>()) == 0) {
    throw StateError('HeapFree failed');
  }
}

class WindowRedrawProbe {
  WindowRedrawProbe._(this.handle);

  final int handle;

  void keepAboveOtherWindows() {
    if (_setWindowPos(
            handle, _topmostWindow, 0, 0, 0, 0, _keepPositionAndSize) ==
        0) {
      throw StateError('Unable to keep the test window unobscured');
    }
  }

  factory WindowRedrawProbe.find(String title) {
    final name = _allocate<Uint8>(title.length + 1);
    final process = _allocate<Uint32>(sizeOf<Uint32>());
    try {
      name.asTypedList(title.length).setAll(0, title.codeUnits);
      final handle = _findWindow(nullptr, name);
      if (handle == 0 || _getWindowProcess(handle, process) == 0) {
        throw StateError('Test window not found: $title');
      }
      if (process.value != pid) {
        throw StateError('Refusing to probe a window from another process');
      }
      return WindowRedrawProbe._(handle);
    } finally {
      _free(process);
      _free(name);
    }
  }

  List<int> clientSize({bool flutterView = false}) {
    final rect = _allocate<Int32>(sizeOf<Int32>() * _rectFields);
    try {
      final target = flutterView ? _getWindow(handle, _firstChild) : handle;
      if (target == 0 || _getClientRect(target, rect) == 0) {
        throw StateError('GetClientRect failed');
      }
      return List.unmodifiable([rect[2] - rect[0], rect[3] - rect[1]]);
    } finally {
      _free(rect);
    }
  }

  int screenColor() {
    final point = _allocate<Int32>(sizeOf<Int32>() * _pointFields);
    final dc = _getDc(0);
    try {
      final size = clientSize();
      point[0] = size[0] ~/ 2;
      point[1] = size[1] ~/ 2;
      if (dc == 0 || _clientToScreen(handle, point) == 0) {
        throw StateError('Unable to locate the test window on screen');
      }
      final color = _getPixel(dc, point[0], point[1]);
      if (color == _invalidColor) {
        throw StateError('GetPixel failed; an interactive desktop is required');
      }
      return color;
    } finally {
      if (dc != 0 && _releaseDc(0, dc) == 0) {
        throw StateError('ReleaseDC failed');
      }
      _free(point);
    }
  }
}
