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


# ==============================================================================
#  Tipi di dato condivisi — usati da template_matcher.py e dai task
# ==============================================================================

from dataclasses import dataclass
import numpy as np
import cv2


@dataclass
class MatchResult:
    """
    Risultato di un'operazione di template matching.

    Attributi:
        found : True se lo score supera la soglia
        score : valore grezzo del match (0.0 – 1.0)
        cx    : coordinata X del centro del match
        cy    : coordinata Y del centro del match
    """
    found: bool
    score: float
    cx:    int
    cy:    int


class Screenshot:
    """
    Wrapper attorno a un frame BGR (numpy array) con metodi di template matching.

    Usato da TemplateMatcher e dai task per eseguire ricerche visive
    senza dipendere dall'implementazione ADB concreta.
    """

    def __init__(self, frame: np.ndarray):
        """
        Args:
            frame: immagine BGR come numpy array (h, w, 3)
        """
        self._frame = frame

    @property
    def frame(self) -> np.ndarray:
        return self._frame

    @property
    def width(self) -> int:
        return self._frame.shape[1]

    @property
    def height(self) -> int:
        return self._frame.shape[0]

    def crop(self, roi: tuple[int, int, int, int]) -> "Screenshot":
        """Ritorna una nuova Screenshot ritagliata sulla ROI (x1,y1,x2,y2)."""
        x1, y1, x2, y2 = roi
        return Screenshot(self._frame[y1:y2, x1:x2].copy())

    def match_template(
        self,
        template: "Screenshot",
        threshold: float = 0.80,
        zone: tuple[int, int, int, int] | None = None,
    ) -> MatchResult:
        """
        Cerca `template` nello screenshot con cv2.TM_CCOEFF_NORMED.

        Args:
            template:  Screenshot del template da cercare
            threshold: soglia minima per considerare il match trovato
            zone:      (x1,y1,x2,y2) — limita la ricerca a questa area

        Returns:
            MatchResult(found, score, cx, cy)
        """
        haystack = self._frame
        offset_x = offset_y = 0

        if zone is not None:
            x1, y1, x2, y2 = zone
            haystack  = self._frame[y1:y2, x1:x2]
            offset_x  = x1
            offset_y  = y1

        needle = template.frame
        if haystack.shape[0] < needle.shape[0] or haystack.shape[1] < needle.shape[1]:
            return MatchResult(False, 0.0, 0, 0)

        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        _, score, _, max_loc = cv2.minMaxLoc(result)
        score = float(score)

        th, tw = needle.shape[:2]
        cx = offset_x + max_loc[0] + tw // 2
        cy = offset_y + max_loc[1] + th // 2

        return MatchResult(found=score >= threshold, score=score, cx=cx, cy=cy)

    def match_template_all(
        self,
        template: "Screenshot",
        threshold: float = 0.80,
        zone: tuple[int, int, int, int] | None = None,
        cluster_px: int = 20,
    ) -> list[MatchResult]:
        """
        Trova tutte le occorrenze del template (NMS con cluster_px).

        Returns:
            Lista di MatchResult ordinata per score decrescente.
        """
        haystack = self._frame
        offset_x = offset_y = 0

        if zone is not None:
            x1, y1, x2, y2 = zone
            haystack  = self._frame[y1:y2, x1:x2]
            offset_x  = x1
            offset_y  = y1

        needle = template.frame
        if haystack.shape[0] < needle.shape[0] or haystack.shape[1] < needle.shape[1]:
            return []

        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        th, tw = needle.shape[:2]

        locations = np.where(result >= threshold)
        matches: list[MatchResult] = []
        for pt in zip(*locations[::-1]):
            score = float(result[pt[1], pt[0]])
            cx = offset_x + pt[0] + tw // 2
            cy = offset_y + pt[1] + th // 2
            matches.append(MatchResult(True, score, cx, cy))

        # NMS semplice: rimuovi match troppo vicini tenendo il migliore
        matches.sort(key=lambda m: m.score, reverse=True)
        kept: list[MatchResult] = []
        for m in matches:
            if all(abs(m.cx - k.cx) > cluster_px or abs(m.cy - k.cy) > cluster_px
                   for k in kept):
                kept.append(m)
        return kept

    def __repr__(self) -> str:
        return f"Screenshot(w={self.width}, h={self.height})"
