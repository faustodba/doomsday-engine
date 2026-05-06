# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/ocr_truppe.py
# ==============================================================================
#
#  Helper OCR per la maschera Squad Training (TruppeTask).
#
#  Tre funzioni standalone:
#    leggi_tipo_caserma(screen)        -> "infantry"|"rider"|"ranged"|"engine"|None
#    identifica_livello_attivo(screen) -> 1..6 | None
#    leggi_count_truppe(screen, liv)   -> int | None
#
#  Coord misurate da screenshot reali (06/05) — vedi commits 9538158 + analisi
#  step 1 in chat. ROI fisse a 960x540 standard del gioco.
#
#  Uso:
#      from shared.ocr_truppe import (
#          leggi_tipo_caserma, identifica_livello_attivo, leggi_count_truppe,
#      )
#      tipo = leggi_tipo_caserma(screen_post_pannello_caserme)
#      liv  = identifica_livello_attivo(screen_squad_training_panel)
#      cnt  = leggi_count_truppe(screen_squad_training_panel, liv)
# ==============================================================================

from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np

from shared.ocr_helpers import _to_array, _run_tesseract, prepara_otsu


# ──────────────────────────────────────────────────────────────────────────────
# Constants — coord ROI (960x540)
# ──────────────────────────────────────────────────────────────────────────────

# Centri delle 6 icone livelli nel selettore (post tap Train, maschera Squad
# Training). Y fissa 110, spacing 62px tra centri.
LIV_CENTRI: list[tuple[int, int]] = [
    (556, 110),   # I
    (618, 110),   # II
    (680, 110),   # III
    (744, 110),   # IV
    (810, 110),   # V
    (872, 110),   # VI
]

# ROI titolo caserma "X Barracks" (post tap pannello caserme + menu radial)
ROI_TITOLO_CASERMA = (320, 150, 640, 195)

# ROI count truppe: y fissa 150-185, x dinamica = centro_livello ± 60
ROI_COUNT_Y = (150, 185)

# Pattern testo titolo
_RE_BARRACKS = re.compile(r"\b(infantry|rider|ranged|engine)\b\s*barracks", re.IGNORECASE)

# HSV cornice icona livello selezionato (range esteso step 3 06/05).
# Pre-fix: solo arancio H 10-25 → falliva su livelli alti (Heart Piercer IV)
# che hanno cornice dorata/oro su sfondo viola.
# Post-fix: H 8-38 cattura sia arancio (livelli I-III) che oro/dorato (IV-VI).
_HSV_BORDO_LO = np.array([8,  100, 100], dtype=np.uint8)
_HSV_BORDO_HI = np.array([38, 255, 255], dtype=np.uint8)

# Soglia minima pixel "bordo selezionato" per identificare selezione
_SOGLIA_BORDO_SEL = 30

# HSV giallo brillante del numero count (testo "53,254" sotto icona).
# Solo giallo brillante e saturo (no marrone, no fondo).
_HSV_GIALLO_LO = np.array([18, 130, 150], dtype=np.uint8)
_HSV_GIALLO_HI = np.array([35, 255, 255], dtype=np.uint8)


# ──────────────────────────────────────────────────────────────────────────────
# 1. leggi_tipo_caserma
# ──────────────────────────────────────────────────────────────────────────────

def leggi_tipo_caserma(img) -> Optional[str]:
    """
    OCR del titolo "X Barracks" nella schermata post tap pannello caserme.
    Ritorna stringa lowercase o None se OCR fallisce.

    Validato su FAU_02 / FAU_03 (Infantry/Rider/Ranged/Engine).
    """
    arr = _to_array(img)
    if arr is None:
        return None
    x0, y0, x1, y1 = ROI_TITOLO_CASERMA
    crop = arr[y0:y1, x0:x1]
    # Cascade preprocessing
    for prep in ("otsu", "crema"):
        try:
            processed = prepara_otsu(crop, scale=2.0) if prep == "otsu" else \
                        _crema_local(crop, 2.0, 160)
            txt = _run_tesseract(processed, config="--psm 6 --oem 3")
        except Exception:
            continue
        m = _RE_BARRACKS.search(txt)
        if m:
            return m.group(1).lower()
    return None


def _crema_local(crop: np.ndarray, scale: float, thresh: int) -> np.ndarray:
    """Helper: prepara_crema in-place per evitare circular import."""
    if scale != 1.0:
        h, w = crop.shape[:2]
        crop = cv2.resize(crop, (int(w*scale), int(h*scale)),
                          interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    _, bin_img = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    return bin_img


# ──────────────────────────────────────────────────────────────────────────────
# 2. identifica_livello_attivo
# ──────────────────────────────────────────────────────────────────────────────

def identifica_livello_attivo(img) -> Optional[int]:
    """
    Identifica il livello attualmente selezionato nel selettore della maschera
    Squad Training. Cerca la cornice arancio/dorata del livello selezionato.

    Step 3 (06/05): range HSV esteso a H 8-38 per coprire sia cornice arancio
    (livelli I-III su sfondo neutro) sia cornice dorata (livelli IV-VI su
    sfondo viola/blu di rarità). Pre-fix solo H 10-25 → fallimento su livelli
    alti.

    Strategia: cerca il bordo (anello esterno della cornice) invece del centro
    (dove c'e' l'immagine soldato). ROI 28x28 attorno al centro icona.

    Ritorna 1..6 o None se nessun livello supera la soglia.
    """
    arr = _to_array(img)
    if arr is None:
        return None
    hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)
    counts: list[int] = []
    for cx, cy in LIV_CENTRI:
        # ROI 28x28 (±14) — copre l'intera icona livello senza sovrapposizione
        # con icone adiacenti (spacing 62px tra centri).
        roi = hsv[cy-14:cy+14, cx-14:cx+14]
        if roi.size == 0:
            counts.append(0)
            continue
        mask = cv2.inRange(roi, _HSV_BORDO_LO, _HSV_BORDO_HI)
        counts.append(int((mask > 0).sum()))

    idx_max = int(np.argmax(counts))
    if counts[idx_max] >= _SOGLIA_BORDO_SEL:
        return idx_max + 1   # 1-indexed
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 3. leggi_count_truppe
# ──────────────────────────────────────────────────────────────────────────────

def leggi_count_truppe(img, livello: int) -> Optional[int]:
    """
    OCR del numero truppe disponibili sotto l'icona del livello specificato
    (giallo brillante, es. "53,254").

    Step 3 (06/05): pre-filtro HSV giallo per isolare il testo + ROI piu'
    stretta (±35 invece di ±60). Pre-fix: ROI larga catturava numeri
    adiacenti (es. su FAU_00 dove ci sono 624,827 + 6,060 vicini → OCR
    leggeva 4807432938).

    Pipeline:
      1. Crop ROI x ±35 attorno al centro icona livello selezionato
      2. HSV mask giallo brillante → isola SOLO il testo del count
      3. Inversione (testo nero su bianco) per Tesseract
      4. PSM 7 con whitelist cifre + virgola

    Args:
        img: screenshot della maschera Squad Training
        livello: 1..6, indice della icona sopra cui leggere il count

    Ritorna int o None se OCR fallisce.
    """
    if not (1 <= livello <= 6):
        return None
    arr = _to_array(img)
    if arr is None:
        return None
    cx, _ = LIV_CENTRI[livello - 1]
    # ROI iniziale ±60 (ampia per non perdere cifre); poi auto-bbox del testo
    # giallo per stringere precisamente sul numero (evita altri count adiacenti).
    x0 = max(0, cx - 60)
    x1 = min(arr.shape[1], cx + 60)
    y0, y1 = ROI_COUNT_Y
    crop = arr[y0:y1, x0:x1]

    # Pre-filtro HSV giallo per isolare il testo
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _HSV_GIALLO_LO, _HSV_GIALLO_HI)
    if (mask > 0).sum() < 20:   # nessun testo giallo nella ROI
        return None

    # Auto-bbox: trova bounding box dei pixel gialli + filtra blob piccoli
    # (eventuali count adiacenti sono separati spazialmente, prendiamo solo
    # il blob piu' vicino al centro icona).
    ys, xs = np.where(mask > 0)
    # Scarta pixel sparsi: tieni solo cluster con almeno 5 px di altezza
    # raggruppando per colonne adiacenti.
    cx_local = (cx - x0)   # centro icona nelle coord crop
    # Cerca colonne con >= 1 pixel giallo
    col_has_yellow = mask.sum(axis=0) > 0
    # Trova cluster di colonne contigue (gap <= 5 = stesso numero)
    clusters_x = []
    current = []
    for i, has in enumerate(col_has_yellow):
        if has:
            current.append(i)
        else:
            if current:
                if not clusters_x or current[0] - clusters_x[-1][-1] > 5:
                    clusters_x.append(current[:])
                else:
                    clusters_x[-1].extend(current)
                current = []
    if current:
        clusters_x.append(current[:])
    if not clusters_x:
        return None
    # Scegli cluster con centro piu' vicino al centro icona
    def _dist_to_icon(cluster):
        mid = (cluster[0] + cluster[-1]) / 2
        return abs(mid - cx_local)
    best = min(clusters_x, key=_dist_to_icon)
    bx0 = max(0, best[0] - 3)
    bx1 = min(mask.shape[1], best[-1] + 3)
    # Crop verticale: usa solo righe con pixel gialli nel cluster scelto
    sub_mask = mask[:, bx0:bx1]
    sub_ys = np.where(sub_mask.sum(axis=1) > 0)[0]
    if len(sub_ys) < 3:
        return None
    by0 = max(0, sub_ys.min() - 2)
    by1 = min(mask.shape[0], sub_ys.max() + 3)

    # Crop finale stretto sul numero
    text_mask = mask[by0:by1, bx0:bx1]

    # Scale + invert per Tesseract
    h, w = text_mask.shape
    scale = 4.0
    mask_up = cv2.resize(text_mask, (int(w*scale), int(h*scale)),
                         interpolation=cv2.INTER_CUBIC)
    # Aggiungi padding bianco intorno
    pad = 10
    binary = 255 - mask_up
    binary = cv2.copyMakeBorder(binary, pad, pad, pad, pad,
                                 cv2.BORDER_CONSTANT, value=255)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    try:
        txt = _run_tesseract(binary,
                             config="--psm 7 -c tessedit_char_whitelist=0123456789,")
    except Exception:
        return None

    # Estrai numero (rimuove virgole separatori migliaia)
    digits = re.sub(r"[^\d]", "", txt)
    if not digits:
        return None
    try:
        n = int(digits)
        # Sanity: count truppe tipico tra 100 e 100M
        if n < 1 or n > 100_000_000:
            return None
        return n
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 4. leggi_consumo_addestramento — risorse consumate per training
# ──────────────────────────────────────────────────────────────────────────────

# Coord zona consumo (4 icone disposte orizzontalmente, y fissa, x dinamica)
CONSUMO_Y_RANGE = (305, 350)   # y delle icone risorse
CONSUMO_SPACING = 105           # spacing px tra centri icone consecutive

# HSV per identificare tipo risorsa via colore centro icona
# (validato su screenshot reali 06/05)
_HSV_RISORSE = {
    # pomodoro: rosso saturo brillante
    "pomodoro": (np.array([0, 130, 100]), np.array([15, 255, 255])),
    # legno: marrone (toni caldi medio-alti, V medio)
    "legno":    (np.array([8, 80, 80]),    np.array([25, 200, 200])),
    # acciaio: grigio metallico (saturazione bassa, V medio-alto)
    # gestito via heuristic colore: low S
    # petrolio: rosso scuro (H simile pomodoro ma V basso)
}


def _trova_pomodoro_anchor(img) -> Optional[tuple[int, int]]:
    """
    Trova il pomodoro nella zona consumo via maschera HSV rosso saturo.
    Ritorna (cx, cy) o None.
    """
    arr = _to_array(img)
    if arr is None:
        return None
    hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)
    # Rosso saturo (pomodoro): H 0-15 OR 170-180
    m1 = cv2.inRange(hsv, (0,   130, 100), (15,  255, 255))
    m2 = cv2.inRange(hsv, (170, 130, 100), (180, 255, 255))
    mask = cv2.bitwise_or(m1, m2)
    # Limito y zona consumo
    y0, y1 = CONSUMO_Y_RANGE
    mask[:y0, :] = 0
    mask[y1:, :] = 0

    # Trova cluster + scegli il PRIMO da sinistra con size >= 200 (=icona pomodoro)
    from scipy import ndimage
    labeled, n = ndimage.label(mask)
    candidati = []
    for i in range(1, n+1):
        ys, xs = np.where(labeled == i)
        if len(xs) >= 200:
            candidati.append((int(xs.mean()), int(ys.mean()), len(xs)))
    if not candidati:
        return None
    candidati.sort(key=lambda c: c[0])   # sort per x (sinistra prima)
    cx, cy, _ = candidati[0]
    return (cx, cy)


def _identifica_risorsa_a_x(img, cx: int, cy: int) -> Optional[str]:
    """
    Identifica quale risorsa e' presente in un'icona alla coordinata (cx, cy)
    via colore HSV dominante. Ritorna "pomodoro"|"legno"|"acciaio"|"petrolio"
    o None se nessuna icona riconoscibile (es. zona vuota).
    """
    arr = _to_array(img)
    if arr is None:
        return None
    # ROI 30x30 attorno al centro icona
    roi = arr[max(0, cy-15):cy+15, max(0, cx-15):cx+15]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Rosso brillante → pomodoro
    m_pom = cv2.inRange(hsv, (0, 130, 130), (15, 255, 255))
    # Rosso scuro V<100 → petrolio
    m_pet1 = cv2.inRange(hsv, (0, 100, 50),  (15, 255, 130))
    m_pet2 = cv2.inRange(hsv, (170, 100, 50), (180, 255, 130))
    m_pet = cv2.bitwise_or(m_pet1, m_pet2)
    # Marrone → legno
    m_leg = cv2.inRange(hsv, (8, 60, 60),  (25, 200, 200))
    # Grigio metallico → acciaio (S basso, V medio-alto)
    m_acc = cv2.inRange(hsv, (0, 0, 100),  (180, 50, 220))

    counts = {
        "pomodoro": int((m_pom > 0).sum()),
        "petrolio": int((m_pet > 0).sum()),
        "legno":    int((m_leg > 0).sum()),
        "acciaio":  int((m_acc > 0).sum()),
    }
    # Soglia minima per considerare "icona presente"
    if max(counts.values()) < 30:
        return None
    return max(counts, key=counts.get)


def _ocr_valore_a_destra(img, x_icona: int, y_icona: int) -> Optional[int]:
    """
    OCR del valore numerico a destra dell'icona consumo (testo bianco grande,
    es. "524.3K", "262.1K", "21").
    Ritorna intero (con K → ×1000, M → ×1e6) o None.
    """
    arr = _to_array(img)
    if arr is None:
        return None
    # ROI testo a destra dell'icona: ~70px wide, 30px tall, partendo +18 da x_icona
    x0 = x_icona + 18
    x1 = min(arr.shape[1], x0 + 75)
    y0 = max(0, y_icona - 14)
    y1 = min(arr.shape[0], y_icona + 14)
    crop = arr[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    # Maschera bianco brillante (testo)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 200), (180, 80, 255))
    if (mask > 0).sum() < 20:
        return None

    # Scale 3x + invert + Tesseract
    h, w = mask.shape
    mask_up = cv2.resize(mask, (w*3, h*3), interpolation=cv2.INTER_CUBIC)
    binary = 255 - mask_up
    binary = cv2.copyMakeBorder(binary, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    try:
        txt = _run_tesseract(
            binary,
            config="--psm 7 -c tessedit_char_whitelist=0123456789.KkMm,",
        )
    except Exception:
        return None

    # Parse "524.3K" / "262.1K" / "21" → int
    txt = txt.strip().replace(",", ".").replace("k", "K").replace("m", "M")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([KM])?", txt)
    if not m:
        return None
    try:
        val = float(m.group(1))
        suffix = m.group(2) or ""
        if suffix == "K":
            val *= 1_000
        elif suffix == "M":
            val *= 1_000_000
        return int(val)
    except (ValueError, TypeError):
        return None


def leggi_consumo_addestramento(img) -> dict:
    """
    OCR del consumo risorse per addestramento dalla maschera Squad Training.

    Strategia:
      1. Trova pomodoro (anchor) via HSV rosso saturo y[305-350]
      2. Da pomodoro_x, scansiona a step di 105px verso destra
      3. Per ogni posizione: identifica risorsa via HSV + leggi valore
      4. Stop quando nessuna icona riconoscibile o fuori schermo

    Ritorna dict {risorsa: int_consumo}, vuoto se OCR fallisce.
    Es. {"pomodoro": 524300, "legno": 262100, "petrolio": 21800}
    (per livello I solo {"pomodoro": 45000, "legno": 45000})
    """
    out: dict = {}
    anchor = _trova_pomodoro_anchor(img)
    if not anchor:
        return out
    pom_x, pom_y = anchor

    # Scansione a step verso destra (max 4 icone: pomodoro + 3)
    for step in range(0, 4):
        cx = pom_x + step * CONSUMO_SPACING
        if cx >= 940:
            break
        risorsa = _identifica_risorsa_a_x(img, cx, pom_y)
        if not risorsa:
            break   # zona vuota, fine icone
        if risorsa in out:
            # Già letto questa risorsa (improbabile) → skip duplicato
            continue
        valore = _ocr_valore_a_destra(img, cx, pom_y)
        if valore is None:
            continue
        out[risorsa] = valore
    return out


# Optional: funzione "all-in-one" per uso da TruppeTask
# ──────────────────────────────────────────────────────────────────────────────

def analizza_squad_training(img) -> dict:
    """
    Analisi completa della maschera Squad Training:
    {
      "livello_attivo": int 1..6 | None,
      "count_disponibili": int | None,
      "consumo": dict {risorsa: int} (06/05)
    }
    """
    liv = identifica_livello_attivo(img)
    count = leggi_count_truppe(img, liv) if liv else None
    consumo = leggi_consumo_addestramento(img)
    return {
        "livello_attivo":    liv,
        "count_disponibili": count,
        "consumo":           consumo,
    }
