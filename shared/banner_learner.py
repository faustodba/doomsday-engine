#  ============================================================================
#  DOOMSDAY ENGINE V6 — shared/banner_learner.py
#  ============================================================================
#  [DEPRECATO WU110 — 03/05/2026]
#  La pipeline di apprendimento automatico non scattava in pratica perché il
#  fallback X cerchio dorato (`pin_btn_x_close.png` in ROI top-right) dismisses
#  i banner unmatched PRIMA che il learner abbia chance di registrarli.
#  In 4h di osservazione (03/05): 6 fallback X dorato, 0 eventi [LEARNER].
#  Opzione cleanup B scelta: default `auto_learn_banner=False` ovunque.
#  Modulo lasciato in repo per git history; può essere riattivato in futuro
#  con refactor `learn-after-fallback` (~50 righe).
#
#  Riconoscimento automatico (no-AI) di X di chiusura in alto a destra di
#  popup/banner non catalogati. Heuristic OpenCV: contour + color saturation +
#  shape compactness + posizione angolo top-right.
#
#  Output: lista candidate (cx, cy, score, bbox) ordinate per score desc.
#  Il caller valida tappando la candidata e verificando lo sblocco schermo.
#  ============================================================================

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass


# ROI di ricerca X — zona top-right canonica. Copre tutte le forme note:
#   pin_btn_x_close (cerchio dorato @ 870,97)
#   pin_btn_x_tag_diamond (cartellino bordeaux @ 825,54)
#   X cerchio rosso (futuro)
# Restringiamo y < 130: le X di chiusura sono sempre nella top-band del popup,
# mai in zona icone HOME (y > 130).
ROI_X_TOPRIGHT = (700, 0, 960, 130)  # (x1, y1, x2, y2)

# Filtri shape per candidate X (in pixel)
MIN_SIDE = 30
MAX_SIDE = 70
MIN_AREA = MIN_SIDE * MIN_SIDE
MAX_AREA = MAX_SIDE * MAX_SIDE
ASPECT_MIN = 0.65   # quasi quadrato (cerchi/cartellini diamante)
ASPECT_MAX = 1.55

# Densità minima edge interno (proxy "X bianca interna")
EDGE_DENSITY_MIN = 0.10

# Maschere colore HSV per classi tipiche di X di chiusura
# (H 0-180 in cv2). Trovate empiricamente su pin_btn_x_close (oro)
# e pin_btn_x_tag_diamond (bordeaux).
COLOR_MASKS = [
    # Rosso/bordeaux (X tag diamond — Equipment Report)
    ("red_lo", (0, 110, 50), (12, 255, 220)),
    ("red_hi", (168, 110, 50), (180, 255, 220)),
    # Giallo/oro (cerchio dorato — Pompeii, AFK reward)
    ("gold", (12, 90, 100), (35, 255, 255)),
    # Rosa/magenta (popup eventi)
    ("magenta", (140, 100, 100), (170, 255, 255)),
]


@dataclass(frozen=True)
class XCandidate:
    cx: int
    cy: int
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    score: float
    saturation: float
    area: int


def _build_color_mask(crop_bgr: np.ndarray) -> np.ndarray:
    """Maschera unione delle classi colore tipiche delle X di chiusura.
    Esclude beige/cream/grigio neutri del background HOME → pochi falsi positivi."""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    h_img, w_img = crop_bgr.shape[:2]
    mask = np.zeros((h_img, w_img), dtype=np.uint8)
    for _name, lo, hi in COLOR_MASKS:
        m = cv2.inRange(hsv, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
        mask = cv2.bitwise_or(mask, m)
    return mask


def detect_x_candidates(
    img_bgr: np.ndarray,
    roi: tuple[int, int, int, int] = ROI_X_TOPRIGHT,
) -> list[XCandidate]:
    """
    Heuristic detection di candidati X di chiusura nella ROI top-right.

    Pipeline:
      1. Crop ROI
      2. Maschere colore separate (rosso/oro/magenta) — esclude beige HOME
      3. Morphology open (kernel 3) per separare blob adiacenti
      4. findContours
      5. Filtra per area + aspect ratio quasi-quadrato
      6. Verifica edge density interna (X bianca su sfondo colorato)
      7. Score = posizione + saturazione + dimensione + edge density

    Ritorna lista XCandidate ordinata per score desc.
    """
    if img_bgr is None or img_bgr.size == 0:
        return []

    x1, y1, x2, y2 = roi
    h_img, w_img = img_bgr.shape[:2]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(w_img, x2); y2 = min(h_img, y2)
    if x2 <= x1 or y2 <= y1:
        return []

    crop = img_bgr[y1:y2, x1:x2]
    mask = _build_color_mask(crop)

    # Open (erode+dilate) per separare blob colorati adiacenti
    # (es. X tag bordeaux + bordo popup non si fondono in un mega-bbox)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[XCandidate] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Filtri shape
        if w < MIN_SIDE or h < MIN_SIDE:
            continue
        if w > MAX_SIDE or h > MAX_SIDE:
            continue
        aspect = w / max(h, 1)
        if aspect < ASPECT_MIN or aspect > ASPECT_MAX:
            continue
        area = int(cv2.contourArea(c))
        if area < MIN_AREA * 0.5:  # filtra contorni "vuoti" (solo bordo)
            continue

        # Coords absolute (compensa offset ROI)
        abs_x = x + x1
        abs_y = y + y1
        cx = abs_x + w // 2
        cy = abs_y + h // 2

        # Saturazione media nel bbox (proxy "bottone colorato")
        cell = crop[y:y + h, x:x + w]
        cell_hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
        sat_mean = float(cell_hsv[:, :, 1].mean())

        # Edge density interna (proxy "X bianca/contrasto su bottone colorato"):
        # la X di chiusura ha 2 linee diagonali ad alto contrasto col background.
        cell_gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cell_gray, 60, 180)
        edge_density = float((edges > 0).sum()) / max(cell_gray.size, 1)
        if edge_density < EDGE_DENSITY_MIN:
            continue  # bottone "vuoto" senza X interna → skip

        # Score:
        #   - posizione: più verso top-right = score maggiore
        #   - saturazione: più colore distintivo = score maggiore
        #   - dimensione: ottimo intorno a 50px (penalty per estremi)
        #   - edge density: signal X interna
        roi_w = x2 - x1; roi_h = y2 - y1
        pos_score = (x / max(roi_w, 1)) * 0.5 + (1.0 - y / max(roi_h, 1)) * 0.5
        sat_score = min(sat_mean / 200.0, 1.0)
        size_score = 1.0 - abs(((w + h) / 2.0) - 50.0) / 50.0
        size_score = max(0.0, size_score)
        edge_score = min(edge_density / 0.30, 1.0)  # 0.30 = densità tipica X
        score = 0.30 * pos_score + 0.25 * sat_score + 0.15 * size_score + 0.30 * edge_score

        candidates.append(XCandidate(
            cx=cx, cy=cy,
            bbox=(abs_x, abs_y, w, h),
            score=score,
            saturation=sat_mean,
            area=area,
        ))

    # Dedup grossolano: candidate con bbox sovrapposti >50% → tieni quello con score più alto
    candidates.sort(key=lambda c: -c.score)
    deduped: list[XCandidate] = []
    for cand in candidates:
        is_dup = False
        for kept in deduped:
            if _bbox_iou(cand.bbox, kept.bbox) > 0.5:
                is_dup = True
                break
        if not is_dup:
            deduped.append(cand)

    return deduped


def _bbox_iou(b1: tuple[int, int, int, int], b2: tuple[int, int, int, int]) -> float:
    x1a, y1a, wa, ha = b1
    x1b, y1b, wb, hb = b2
    x2a = x1a + wa; y2a = y1a + ha
    x2b = x1b + wb; y2b = y1b + hb
    ix1 = max(x1a, x1b); iy1 = max(y1a, y1b)
    ix2 = min(x2a, x2b); iy2 = min(y2a, y2b)
    iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = wa * ha + wb * hb - inter
    return inter / max(union, 1)


def crop_template_x(img_bgr: np.ndarray, cand: XCandidate,
                    pad: int = 3) -> np.ndarray:
    """Ritaglia il template della X intorno al bbox della candidata, con piccolo
    padding per tolleranza match futuri."""
    x, y, w, h = cand.bbox
    h_img, w_img = img_bgr.shape[:2]
    x1 = max(0, x - pad); y1 = max(0, y - pad)
    x2 = min(w_img, x + w + pad); y2 = min(h_img, y + h + pad)
    return img_bgr[y1:y2, x1:x2].copy()


def crop_title_zone(img_bgr: np.ndarray,
                    title_roi: tuple[int, int, int, int] = (40, 20, 410, 70)) -> np.ndarray:
    """Ritaglio della zona "titolo" del popup come template di DETECTION del banner.
    ROI default coerente con popup tipo Equipment Report.
    Caller può passare ROI dedotta dalla posizione della X candidata se serve."""
    x1, y1, x2, y2 = title_roi
    h_img, w_img = img_bgr.shape[:2]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(w_img, x2); y2 = min(h_img, y2)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((10, 10, 3), dtype=np.uint8)
    return img_bgr[y1:y2, x1:x2].copy()


def visual_diff_score(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Calcola differenza visiva tra 2 screenshot. Range [0.0, 1.0]:
      0.0 = identici
      1.0 = completamente diversi

    Hash perceptual (mean diff su versione 32×32 grayscale).
    """
    if img1 is None or img2 is None:
        return 1.0
    if img1.shape != img2.shape:
        return 1.0
    g1 = cv2.cvtColor(cv2.resize(img1, (32, 32)), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(cv2.resize(img2, (32, 32)), cv2.COLOR_BGR2GRAY)
    diff = np.abs(g1.astype(np.int16) - g2.astype(np.int16))
    return float(diff.mean()) / 255.0


def template_similarity(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Score similarità tra 2 template (per dedup learned banners).
    Resize entrambi a dim comune e fa cross-correlation normalizzata.
    Range [0.0, 1.0] (1.0 = identici).
    """
    if img1 is None or img2 is None or img1.size == 0 or img2.size == 0:
        return 0.0
    target_size = (100, 100)
    a = cv2.resize(img1, target_size)
    b = cv2.resize(img2, target_size)
    if len(a.shape) == 3:
        a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    if len(b.shape) == 3:
        b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    return float(res.max())
