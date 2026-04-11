# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/device.py
#
#  STANDARD ARCHITETTURALE (Step 25 — vincolante):
#    Tutti i metodi sono SINCRONI. Non esistono più metodi async.
#    I task usano: device.tap(x,y), device.screenshot(), device.back(),
#                  device.swipe(x1,y1,x2,y2), device.tap_sync((x,y))
# ==============================================================================

from __future__ import annotations
from typing import Optional


class FakeDevice:
    """
    Device fittizio per test — SINCRONO (Step 25).
    Tutti i metodi sono sincroni. Usato da tutti i task e test V6.
    """

    def __init__(self, screenshots=None, name: str = "FAKE_00", index: int = 0):
        self.name  = name
        self.index = index
        self.port  = 16384 + index * 32

        self.taps:        list = []
        self.calls:       list = []
        self.key_calls:   list = []
        self.text_inputs: list = []
        self.swipe_calls: list = []
        self.tap_calls:   list = []
        self.scrolls:     list = []
        self.text_inputs_list: list = []

        self._screenshots_list = list(screenshots) if screenshots else []
        self._screen_idx  = 0
        self._default_shot = None
        self.launched:      bool = False
        self.game_running:  bool = True

    # ── Screenshot ────────────────────────────────────────────────────────────

    def add_screenshot(self, s) -> None:
        self._screenshots_list.append(s)

    def set_default_shot(self, s) -> None:
        self._default_shot = s

    def _pop_screenshot(self):
        self.calls.append(("screenshot",))
        if self._screen_idx < len(self._screenshots_list):
            s = self._screenshots_list[self._screen_idx]
            self._screen_idx += 1
            return s
        return self._default_shot

    def screenshot(self):
        """Sincrono."""
        return self._pop_screenshot()

    def screenshot_sync(self):
        """Alias di screenshot() — compatibilità navigator."""
        return self._pop_screenshot()

    # ── Tap ───────────────────────────────────────────────────────────────────

    def _record_tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        self.calls.append(("tap", x, y))
        self.tap_calls.append((x, y))

    def tap(self, x_or_coord, y=None) -> None:
        """Sincrono. Accetta (x,y) o ((x,y),)."""
        if y is None:
            coord = x_or_coord
            self._record_tap(int(coord[0]), int(coord[1]))
        else:
            self._record_tap(int(x_or_coord), int(y))

    def tap_sync(self, coord_or_x, y=None) -> None:
        """Alias di tap() — compatibilità navigator."""
        self.tap(coord_or_x, y)

    def tap_tuple(self, coord: tuple) -> None:
        self._record_tap(coord[0], coord[1])

    # ── Back ──────────────────────────────────────────────────────────────────

    def back(self) -> None:
        self.calls.append(("back",))
        self.key_calls.append("KEYCODE_BACK")

    # ── Key ───────────────────────────────────────────────────────────────────

    def key(self, keycode: str) -> None:
        self.taps.append(("KEY", keycode))
        self.calls.append(("key", keycode))
        self.key_calls.append(keycode)

    def keyevent(self, key: str) -> None:
        self.calls.append(("keyevent", key))
        self.key_calls.append(key)
        self.taps.append(("KEY", key))

    # ── Input text ────────────────────────────────────────────────────────────

    def input_text(self, text: str) -> None:
        self.taps.append(("TEXT", text))
        self.calls.append(("input_text", text))
        self.text_inputs.append(text)
        self.text_inputs_list.append(text)

    # ── Swipe / scroll ────────────────────────────────────────────────────────

    def swipe(self, x1, y1, x2, y2, duration_ms=300, **kw) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))
        self.calls.append(("swipe", x1, y1, x2, y2))

    def scroll(self, x: int, y: int, direction: int, durata_ms: int = 300) -> None:
        self.scrolls.append((x, y, direction, durata_ms))
        self.calls.append(("scroll", x, y, direction))

    # ── Utility ───────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.taps.clear()
        self.scrolls.clear()
        self.calls.clear()
        self.key_calls.clear()
        self.text_inputs.clear()
        self.swipe_calls.clear()
        self.tap_calls.clear()
        self._screen_idx = 0

    def swipe_count(self) -> int:
        return len(self.swipe_calls)

    def back_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "back")

    def taps_at(self, x: int, y: int) -> int:
        return sum(1 for c in self.calls if c[0] == "tap" and c[1] == x and c[2] == y)

    def __repr__(self) -> str:
        return f"FakeDevice(name={self.name!r}, taps={len(self.taps)})"
