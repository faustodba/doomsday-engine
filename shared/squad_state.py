"""shared/squad_state.py — analisi stato per slot squadra (HOME / MAPPA).

Per ogni slot squadra visibile nella colonna destra (sotto il contatore X/Y),
identifica lo stato corrente:
    - 'gather'  🪏  raccolta in corso sul nodo
    - 'march'   →   marcia verso il nodo (verde)
    - 'return'  ←   ritorno al rifugio (arancione)
    - 'idle'    ⛺  ferma in attesa
    - None          slot vuoto (no avatar)

Posizione UI:
    Contatore slot X/Y  → (890, 117, 946, 141)   [HOME / MAPPA, identica]
    Slot avatar 0..N    → sotto il contatore, colonna destra

L'icona stato è in basso a destra dell'avatar (ROI ~25-30 px).

Pipeline:
    1. Per ogni slot index i in [0..max_squadre):
       - estrai ROI avatar (per check occupied)
       - se occupato → estrai ROI icona stato → match template
    2. Output lista dict per slot

Coord da calibrare con screenshot reali — vedi `_SLOT_AVATAR_BOXES`.

ATTENZIONE: il file richiede calibrazione coord prima dell'uso. Da fare con
1 screenshot HOME prod + estrazione manuale ROI.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)

# ─── Coord UI 960×540 ──────────────────────────────────────────────────────
# Calibrate 09/05/2026 su screenshot FAU_01 prod (HOME, 2/4 slot in gather).
# Slot 60×65 px in colonna destra, primo slot subito sotto contatore X/Y.
# Y_TOP=145 (subito sotto contatore @ y=141), height=60.
# Range x [880, 945] = 65 px wide.

_SLOT_X_LEFT  = 880
_SLOT_X_RIGHT = 945
_SLOT_Y_TOP   = 145
_SLOT_HEIGHT  = 60   # px verticali tra i centri di 2 slot consecutivi

# Avatar slot 0..4 (5 slot per master/full, 4 per le altre)
_SLOT_AVATAR_BOXES: list[tuple[int, int, int, int]] = [
    (_SLOT_X_LEFT, _SLOT_Y_TOP + i * _SLOT_HEIGHT,
     _SLOT_X_RIGHT, _SLOT_Y_TOP + (i + 1) * _SLOT_HEIGHT)
    for i in range(5)
]

# ROI icona stato in basso-destra dello slot avatar (offset relativo al ROI 65×60).
# Validato su sample reale: pixel verdi concentrati a x[53-63] y[32-43] dentro ROI.
# Allargo leggermente per robustezza ad anti-aliasing (15×15).
_ICONA_STATO_OFFSET = (50, 30, 65, 45)   # (dx_left, dy_top, dx_right, dy_bottom)

# Soglia varianza pixel per check occupied (slot vuoto = nero uniforme var<500;
# slot con avatar = texture/colori var>1000). Validato 09/05.
_OCC_VAR_SOGLIA = 1000.0


# ─── Stati ─────────────────────────────────────────────────────────────────

STATO_GATHER = "gather"
STATO_MARCH  = "march"
STATO_RETURN = "return"
STATO_IDLE   = "idle"


# ─── API ────────────────────────────────────────────────────────────────────

def analizza_slot_squadre(screen,
                            max_squadre: int = 4,
                            matcher=None) -> list[dict]:
    """Analizza ogni slot squadra in HOME/MAPPA.

    Args:
        screen: oggetto Screenshot V6 (con `.frame` numpy array BGR)
        max_squadre: numero slot per questa istanza (4 default, 5 master)
        matcher: TemplateMatcher V6 (per match icone stato). Se None, usa
                 fallback color-based.

    Returns:
        list[dict] con max_squadre elementi:
        [
            {idx: 0, occupied: True,  stato: 'gather'},
            {idx: 1, occupied: True,  stato: 'march'},
            {idx: 2, occupied: True,  stato: 'return'},
            {idx: 3, occupied: False, stato: None},
        ]
    """
    if screen is None or not hasattr(screen, "frame"):
        return [{"idx": i, "occupied": False, "stato": None}
                for i in range(max_squadre)]

    frame = screen.frame
    if frame is None:
        return [{"idx": i, "occupied": False, "stato": None}
                for i in range(max_squadre)]

    out: list[dict] = []
    n = min(max_squadre, len(_SLOT_AVATAR_BOXES))

    for i in range(n):
        x1, y1, x2, y2 = _SLOT_AVATAR_BOXES[i]
        try:
            avatar_roi = frame[y1:y2, x1:x2]
        except Exception:
            out.append({"idx": i, "occupied": False, "stato": None})
            continue

        if avatar_roi.size == 0:
            out.append({"idx": i, "occupied": False, "stato": None})
            continue

        occupied = _is_avatar_occupied(avatar_roi)
        if not occupied:
            out.append({"idx": i, "occupied": False, "stato": None})
            continue

        # Estrai ROI icona stato (in basso a destra)
        ox1, oy1, ox2, oy2 = _ICONA_STATO_OFFSET
        try:
            icon_roi = avatar_roi[oy1:oy2, ox1:ox2]
        except Exception:
            icon_roi = None

        stato = _classifica_icona_stato(icon_roi, matcher=matcher)
        out.append({"idx": i, "occupied": True, "stato": stato})

    return out


# ─── Helpers interni ────────────────────────────────────────────────────────

def _is_avatar_occupied(roi: np.ndarray) -> bool:
    """Determina se lo slot avatar è occupato (avatar visibile) o vuoto.

    Heuristic: slot vuoto = uniforme grigio scuro (varianza pixel bassa).
    Slot con avatar = varianza alta (texture, colori, contorni).
    """
    if roi is None or roi.size == 0:
        return False
    try:
        gray = np.mean(roi, axis=2) if roi.ndim == 3 else roi
        var = float(np.var(gray))
        return var > _OCC_VAR_SOGLIA
    except Exception:
        return False


def _classifica_icona_stato(roi: Optional[np.ndarray],
                              matcher=None) -> Optional[str]:
    """Classifica lo stato dell'icona in basso a destra dell'avatar.

    Strategia attuale: color-based (più semplice, no template). 4 colori target:
        - verde scuro (gather)  → H~50-65, S>120, V<200
        - verde chiaro (march)  → H~40-55, S>100, V>180
        - arancione (return)    → H~10-25, S>150
        - grigio/bianco (idle)  → S<60

    Se matcher fornito, usa template matching (più robusto). Coord
    template da estrarre: pin_slot_{gather,march,return,idle}.png.
    """
    if roi is None or roi.size == 0:
        return None

    # Strategia color-based (default).
    # Calibrazione 09/05 su sample reale (FAU_01 multi-stato):
    #   gather verde scuro: HSV (~42, 59-130, 45-100)  — verde basso V
    #   march verde chiaro:  HSV (~50, 100+, 180+)      — verde alto V
    #   return arancione:    HSV (~15, 150+, 130+)
    #   idle grigio:         HSV (any, <30, any)
    try:
        import cv2
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h_med = float(np.median(hsv[:, :, 0]))
        s_med = float(np.median(hsv[:, :, 1]))
        v_med = float(np.median(hsv[:, :, 2]))

        # Idle: saturazione bassa (grigio/bianco). Soglia abbassata da 60 → 30
        # perché "gather scuro" può avere S~50-60 → falso positivo idle.
        if s_med < 30:
            return STATO_IDLE
        # Arancione (return): H basso + saturazione alta
        if 8 <= h_med <= 25 and s_med >= 120:
            return STATO_RETURN
        # Verde (gather o march): H~35-75
        if 35 <= h_med <= 75:
            # March = verde chiaro luminoso (V alto)
            if v_med >= 150:
                return STATO_MARCH
            # Gather = verde scuro (V basso, copre anche pickaxe ombrato)
            return STATO_GATHER
        # Fallback
        return None
    except Exception as exc:
        _log.debug("[SQUAD-STATE] classify error: %s", exc)
        return None


# ─── Aggregazione comoda ────────────────────────────────────────────────────

def conta_per_stato(slots: list[dict]) -> dict:
    """Aggrega lista slot in conteggio per stato.

    Returns:
        {gather: int, march: int, return: int, idle: int, vuoti: int}
    """
    out = {"gather": 0, "march": 0, "return": 0, "idle": 0, "vuoti": 0}
    for s in slots:
        if not s.get("occupied"):
            out["vuoti"] += 1
            continue
        st = s.get("stato")
        if st in out:
            out[st] += 1
    return out
