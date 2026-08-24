#ifndef DESKTOP_MULTI_WINDOW_WINDOWS_SHOW_RECOVERY_H_
#define DESKTOP_MULTI_WINDOW_WINDOWS_SHOW_RECOVERY_H_

constexpr bool ShouldArmShowRecovery(bool has_controller,
                                     bool /* first_frame_rendered */) {
  return has_controller;
}

static_assert(ShouldArmShowRecovery(true, false),
              "recovery must start before the first frame");
static_assert(ShouldArmShowRecovery(true, true),
              "a hidden generated frame may not have been presented");
static_assert(!ShouldArmShowRecovery(false, false),
              "recovery requires a controller");
static_assert(!ShouldArmShowRecovery(false, true),
              "recovery requires a controller after the first frame");

#endif  // DESKTOP_MULTI_WINDOW_WINDOWS_SHOW_RECOVERY_H_
