# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/ocr_helpers.py
#
#  Funzioni OCR riutilizzabili tra tutti i task.
#
#  FIX 12/04/2026 sessione 1:
#    - _to_array: img.array → img.frame
#  FIX 12/04/2026 sessione 3 — da lettura ocr.py V5:
#    - ZONE_RISORSE: zone calibrate su screenshot reali 04/04/2026 da ocr.py V5
#      (le precedenti (68,11,160,25) erano vecchie e non calibrate)
#    - _maschera_bianca: preprocessing pixel bianchi >140 RGB + padding, come V5
#    - _parse_valore: parsing M/K/B portato da V5 (gestisce "25.6M", "649M", ecc.)
#    - _parse_diamanti: parsing diamanti portato da V5 (gestisce "26,548")
#    - leggi_risorsa: upscale 4x + _maschera_bianca + psm=7, come V5
#    - RisorseDeposito: aggiunto campo diamanti
#    - ocr_risorse: usa zone e logica V5
# ==============================================================================

from __future__ import annotations

import re
import threading
from typing import NamedTuple

import cv2
import numpy as np
from PIL import Image

try:
    import pytesseract
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

try:
    from core.device import Screenshot
    _ScreenshotType = Screenshot
except ImportError:
    _ScreenshotType = None  # type: ignore

# Lock globale Tesseract — thread-safe come in V5
_tesseract_lock = threading.Lock()


# ==============================================================================
# Costanti Tesseract
# ==============================================================================
_PSM_LINE   = "--psm 7"
_PSM_BLOCK  = "--psm 6"
_PSM_RAW    = "--psm 13"
_DIGITS_CFG = "--psm 7 -c tessedit_char_whitelist=0123456789KkMm.,"


# ==============================================================================
# Helper conversione immagine
# ==============================================================================

def _to_array(img: "Screenshot | np.ndarray") -> np.ndarray:
    """Converte Screenshot → np.ndarray BGR. FIX: usa .frame non .array."""
    if _ScreenshotType is not None and isinstance(img, _ScreenshotType):
        return img.frame
    if isinstance(img, np.ndarray):
        return img
    raise TypeError(f"ocr_helpers: tipo immagine non supportato: {type(img)}")


def _to_pil(img: "Screenshot | np.ndarray") -> Image.Image:
    """Converte Screenshot/ndarray BGR → PIL RGB."""
    arr = _to_array(img)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _crop_zone(arr: np.ndarray, zone: tuple[int, int, int, int] | None) -> np.ndarray:
    if zone is None:
        return arr
    x1, y1, x2, y2 = zone
    return arr[y1:y2, x1:x2]


def _run_tesseract(img_gray: np.ndarray, config: str) -> str:
    if not _TESSERACT_OK:
        return ""
    try:
        with _tesseract_lock:
            text = pytesseract.image_to_string(img_gray, config=config)
        return text.strip()
    except Exception:
        return ""


# ==============================================================================
# Preprocessing
# ==============================================================================

def prepara_otsu(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    scale: float = 2.0,
) -> np.ndarray:
    """Preprocessing Otsu — testo scuro su sfondo chiaro."""
    arr = _to_array(img)
    roi = _crop_zone(arr, zone)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    if scale != 1.0:
        h, w = gray.shape
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def prepara_crema(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    scale: float = 2.0,
    thresh_low: int = 160,
) -> np.ndarray:
    """Preprocessing testo crema/dorato su sfondo scuro."""
    arr = _to_array(img)
    roi = _crop_zone(arr, zone)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    if scale != 1.0:
        h, w = gray.shape
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, thresh_low, 255, cv2.THRESH_BINARY)
    return cv2.bitwise_not(binary)


def _maschera_bianca(img_pil: Image.Image, taglio_sx: int = 0) -> Image.Image:
    """
    Estrae pixel bianchi (R>140, G>140, B>140) come maschera con padding 20px.
    Portata da ocr.py V5 — ottimale per testo bianco/crema barra risorse.
    """
    arr = np.array(img_pil).astype(int)
    h, w = arr.shape[:2]
    pad = 20
    mask = np.zeros((h + pad * 2, w + pad * 2), dtype=np.uint8)
    for y in range(h):
        for x in range(taglio_sx, w):
            if arr[y, x, 0] > 140 and arr[y, x, 1] > 140 and arr[y, x, 2] > 140:
                mask[y + pad, x - taglio_sx + pad] = 255
    return Image.fromarray(mask)


# ==============================================================================
# OCR principale
# ==============================================================================

def ocr_zona(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    config: str = _PSM_LINE,
    preprocessor: str = "otsu",
) -> str:
    arr = _to_array(img)
    if preprocessor == "otsu":
        processed = prepara_otsu(arr, zone)
    elif preprocessor == "crema":
        processed = prepara_crema(arr, zone)
    else:
        roi = _crop_zone(arr, zone)
        processed = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return _run_tesseract(processed, config)


def ocr_intero(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    preprocessor: str = "otsu",
) -> str:
    result = ocr_zona(img, zone, config=_PSM_LINE, preprocessor=preprocessor)
    if result:
        return result
    return ocr_zona(img, zone, config=_PSM_RAW, preprocessor=preprocessor)


def ocr_cifre(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    preprocessor: str = "otsu",
) -> str:
    return ocr_zona(img, zone, config=_DIGITS_CFG, preprocessor=preprocessor)


# ==============================================================================
# Parsing numerico — portato da ocr.py V5
# ==============================================================================

def _parse_valore(testo: str) -> float:
    """
    Converte testo OCR risorsa in float.
    Gestisce: 25.6M, 64.9M4, 45M, 649M, 1.2K, 1B
    Portato da ocr.py V5 _parse_valore.
    """
    testo = testo.strip()
    m = re.search(r'(\d+\.\d+)\s*([MKB])', testo, re.IGNORECASE)
    if m:
        val  = float(m.group(1))
        mult = m.group(2).upper()
    else:
        m = re.search(r'(\d+)\s*([MKB])', testo, re.IGNORECASE)
        if not m:
            return -1
        cifre = m.group(1)
        mult  = m.group(2).upper()
        if mult == 'M':
            if len(cifre) == 3:
                val = float(cifre[:-1] + '.' + cifre[-1])
            elif len(cifre) == 2:
                val = float(cifre[0] + '.' + cifre[1])
            else:
                val = float(cifre)
        else:
            val = float(cifre)

    if mult == 'M':   val *= 1_000_000
    elif mult == 'K': val *= 1_000
    elif mult == 'B': val *= 1_000_000_000
    return val


def _parse_diamanti(testo: str) -> int:
    """
    Converte testo OCR diamanti in intero.
    Gestisce: "26,548"  "26548"  "26.548"
    Portato da ocr.py V5 _parse_diamanti.
    """
    testo = testo.strip().replace(',', '').replace('.', '').replace(' ', '')
    nums = re.findall(r'\d+', testo)
    if nums:
        val = int(''.join(nums))
        return val if val < 10_000_000 else -1
    return -1


def estrai_numero(testo: str) -> int | None:
    """
    Converte stringa OCR in intero. Gestisce K, M, separatori.
    Usato per zone generiche non-risorsa.
    """
    if not testo:
        return None
    testo = testo.strip().upper().replace(" ", "")
    testo = re.sub(r"[^0-9.,KM]", "", testo)
    multiplier = 1
    if testo.endswith("K"):
        multiplier = 1_000;  testo = testo[:-1]
    elif testo.endswith("M"):
        multiplier = 1_000_000;  testo = testo[:-1]
    if "." in testo and "," in testo:
        testo = testo.replace(".", "").replace(",", ".")
    elif "," in testo:
        parts = testo.split(",")
        if all(len(p) == 3 for p in parts[1:]) and len(parts) >= 2:
            testo = testo.replace(",", "")
        else:
            testo = testo.replace(",", ".")
    elif "." in testo:
        parts = testo.split(".")
        if len(parts) > 2:
            testo = testo.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3:
            testo = testo.replace(".", "")
    match = re.search(r"\d[\d.]*", testo)
    if not match:
        return None
    try:
        return int(round(float(match.group().rstrip(".")) * multiplier))
    except ValueError:
        return None


# ==============================================================================
# Lettura risorsa singola — portato da ocr.py V5
# ==============================================================================

def leggi_risorsa(crop_pil: Image.Image, taglio_sx: int = 0) -> float:
    """
    Legge il valore di una risorsa da un crop PIL già upscalato 4x.
    Usa _maschera_bianca + psm=7 whitelist MKB — identico a V5.
    Ritorna float (es. 46900000.0) o -1 se fallisce.
    """
    try:
        mask = _maschera_bianca(crop_pil, taglio_sx)
        cfg  = "--psm 7 -c tessedit_char_whitelist=0123456789.MKB"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(mask, config=cfg).strip()
        return _parse_valore(testo)
    except Exception:
        return -1


# ==============================================================================
# Zone risorse — calibrate su screenshot reali 960x540 (04/04/2026, ocr.py V5)
# ==============================================================================

# Barra completa: (425,4,948,28)
_ZONA_BARRA_COMPLETA = (425, 4, 948, 28)
_BARRA_X0 = 425
_BARRA_Y0 = 4

# Zone assolute 960x540 — calibrate su screen reali
ZONE_RISORSE_V5 = {
    "pomodoro": {"zona": (455, 4, 520, 28), "taglio": 0},
    "legno":    {"zona": (555, 4, 622, 28), "taglio": 0},
    "acciaio":  {"zona": (655, 4, 720, 28), "taglio": 0},
    "petrolio": {"zona": (755, 4, 820, 28), "taglio": 0},
    "diamanti": {"zona": (855, 4, 920, 28), "taglio": 0},
}


# ==============================================================================
# RisorseDeposito
# ==============================================================================

class RisorseDeposito(NamedTuple):
    """Risorse lette dalla barra superiore. -1 = lettura fallita."""
    pomodoro: float
    legno:    float
    acciaio:  float
    petrolio: float
    diamanti: int


# ==============================================================================
# ocr_risorse — logica portata da ocr.py V5 leggi_risorse()
# ==============================================================================

def ocr_risorse(img: "Screenshot | np.ndarray") -> RisorseDeposito:
    """
    Legge le 5 risorse (pomodoro, legno, acciaio, petrolio, diamanti)
    dalla barra superiore dello screenshot HOME.

    Pipeline identica a V5 leggi_risorse():
      1. Crop barra completa (425,4,948,28) — un solo accesso immagine
      2. Per ogni risorsa: sub-crop → upscale 4x → _maschera_bianca → psm=7
      3. Diamanti: _parse_diamanti; risorse: _parse_valore

    Ritorna RisorseDeposito con valori float/int o -1 se lettura fallita.
    """
    _fallback = RisorseDeposito(-1, -1, -1, -1, -1)

    try:
        pil_img = _to_pil(img)
        barra   = pil_img.crop(_ZONA_BARRA_COMPLETA)
    except Exception:
        return _fallback

    risultati: dict = {}
    for nome, info in ZONE_RISORSE_V5.items():
        try:
            x1, y1, x2, y2 = info["zona"]
            # Coordinate relative alla barra
            crop = barra.crop((
                x1 - _BARRA_X0, y1 - _BARRA_Y0,
                x2 - _BARRA_X0, y2 - _BARRA_Y0,
            ))
            w, h = crop.size
            # Upscale 4x come V5
            crop4x = crop.resize((w * 4, h * 4), Image.LANCZOS)

            if nome == "diamanti":
                mask = _maschera_bianca(crop4x, info["taglio"])
                cfg  = "--psm 7 -c tessedit_char_whitelist=0123456789,."
                with _tesseract_lock:
                    testo = pytesseract.image_to_string(mask, config=cfg).strip()
                risultati[nome] = _parse_diamanti(testo)
            else:
                risultati[nome] = leggi_risorsa(crop4x, info["taglio"])
        except Exception:
            risultati[nome] = -1

    return RisorseDeposito(
        pomodoro=risultati.get("pomodoro", -1),
        legno=risultati.get("legno",    -1),
        acciaio=risultati.get("acciaio",  -1),
        petrolio=risultati.get("petrolio", -1),
        diamanti=risultati.get("diamanti", -1),
    )
