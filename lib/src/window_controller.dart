import 'dart:ui';

import 'widgets/sub_drag_to_resize_area.dart';
import 'window_controller_impl.dart';

/// The [WindowController] instance that is used to control this window.
abstract class WindowController {
  WindowController();

  factory WindowController.fromWindowId(int id) {
    return WindowControllerMainImpl(id);
  }

  factory WindowController.main() {
    return WindowControllerMainImpl(0);
  }

  /// The id of the window.
  /// 0 means the main window.
  int get windowId;

  /// Close the window.
  Future<void> close();

  /// Show the window.
  Future<void> show();

  /// Hide the window.
  Future<void> hide();

  /// Judge if the window is hidden.
  Future<bool> isHidden();

  /// Focus the window.
  Future<void> focus();

  /// Start dragging the window.
  Future<void> startDragging();

  // https://github.com/rustdesk-org/window_manager/blob/f19acdb008645366339444a359a45c3257c8b32e/lib/src/window_manager.dart#L470
  /// Sets whether the window can be moved by user.
  ///
  /// @platforms macos
  Future<void> setMovable(bool isMovable);

  /// Maximize the window.
  Future<void> maximize();

  /// Unmaximize the window.
  Future<void> unmaximize();

  /// Judge if the window is maximized.
  Future<bool> isMaximized();

  /// Judge if the window is minimized.
  Future<bool> isMinimized();

  /// Minimize the window
  Future<void> minimize();

  /// show the window of window
  Future<void> showTitleBar(bool show);

  /// Indicate if the window is in fullscreen mode.
  Future<bool> isFullScreen();

  /// Make the window full screen or not
  Future<void> setFullscreen(bool fullscreen);

  /// Set the window frame rect.
  Future<void> setFrame(Rect frame);

  /// Get the window frame rect.
  Future<Rect> getFrame() async {
    return Future.value(Rect.zero);
  }

  /// Center the window on the screen.
  Future<void> center();

  /// Set the window's title.
  Future<void> setTitle(String title);

  /// available only on macOS.
  Future<void> setFrameAutosaveName(String name);

  /// start resizing
  Future<void> startResizing(SubWindowResizeEdge resizeEdge);

  /// Check if is intercepting the native close signal.
  Future<bool> isPreventClose();

  /// Set if intercept the native close signal. May useful when combine with the onclose event listener.
  /// This will also prevent the manually triggered close event.
  Future<void> setPreventClose(bool isPreventClose);

  /// Get x11 id for specific window
  ///
  /// This is only valid in x11/Linux.
  Future<int> getXID();

  /// Most useful for ensuring windows *cannot* be resized. Windows are
  /// resizable by default, so there is no need to explicitly define a window
  /// as resizable by calling this function.
  Future<void> resizable(bool resizable);

  /// Sets the minimum size of window to `width` and `height`.
  Future<void> setMinimumSize(Size size);

  /// Sets whether the window should show always on top of other windows.
  Future<void> setAlwaysOnTop(bool isAlwaysOnTop);
}
