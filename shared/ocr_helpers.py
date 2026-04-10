# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/ocr_helpers.py
#
#  Funzioni OCR riutilizzabili tra tutti i task.
#
#  Funzioni:
#    ocr_zona()          — estrae testo grezzo da una zona screenshot
#    ocr_intero()        — OCR con psm=7 (riga singola, zona intera)
#    ocr_cifre()         — estrae solo cifre da una zona
#    ocr_risorse()       — legge le 4 risorse dal deposito (pomodoro/legno/petrolio/acciaio)
#    prepara_otsu()      — preprocessa con soglia Otsu (testo scuro su chiaro)
#    prepara_crema()     — preprocessa con threshold per testo crema/dorato (UI gioco)
#    estrai_numero()     — converte stringa OCR in int (gestisce K, M, separatori)
#
#  Design:
#    - Nessuna dipendenza da device.py, state.py, logger.py
#    - Input: sempre Screenshot (da core.device) o np.ndarray
#    - Output: str | int | float | None — mai eccezioni per dati malformati
#    - I parametri Tesseract sono costanti modificabili in cima al file
# ==============================================================================

from __future__ import annotations

import re
from typing import NamedTuple

import cv2
import numpy as np

try:
    import pytesseract
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

# Import locale — Screenshot è in core.device ma non vogliamo dipendenza ciclica,
# accettiamo sia Screenshot che np.ndarray come input
try:
    from core.device import Screenshot
    _ScreenshotType = Screenshot
except ImportError:
    _ScreenshotType = None   # type: ignore


# ==============================================================================
# Costanti Tesseract
# ==============================================================================

# psm=7  → tratta l'immagine come riga di testo singola
# psm=6  → blocco uniforme di testo
# psm=13 → riga grezza, senza analisi layout
_PSM_LINE   = "--psm 7"
_PSM_BLOCK  = "--psm 6"
_PSM_RAW    = "--psm 13"
_DIGITS_CFG = "--psm 7 -c tessedit_char_whitelist=0123456789KkMm.,"

# Charset solo numeri + separatori comuni nel gioco
_NUM_WHITELIST = "0123456789KkMm.,/ "


# ==============================================================================
# Helpers interni
# ==============================================================================

def _to_array(img: "Screenshot | np.ndarray") -> np.ndarray:
    """Converte Screenshot → np.ndarray BGR, o passa array invariato."""
    if _ScreenshotType is not None and isinstance(img, _ScreenshotType):
        return img.array
    if isinstance(img, np.ndarray):
        return img
    raise TypeError(f"ocr_helpers: tipo immagine non supportato: {type(img)}")


def _crop_zone(arr: np.ndarray, zone: tuple[int, int, int, int] | None) -> np.ndarray:
    """Ritaglia la zona (x1, y1, x2, y2) se fornita."""
    if zone is None:
        return arr
    x1, y1, x2, y2 = zone
    return arr[y1:y2, x1:x2]


def _run_tesseract(img_gray: np.ndarray, config: str) -> str:
    """Chiama Tesseract sull'immagine grayscale e ritorna testo pulito."""
    if not _TESSERACT_OK:
        return ""
    try:
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
    """
    Preprocessa con soglia Otsu — ottimale per testo scuro su sfondo chiaro.

    Passaggi: crop → grayscale → upscale → blur → Otsu binarize → invert.

    Args:
        img:   Screenshot o array BGR
        zone:  (x1, y1, x2, y2) zona da ritagliare (None = tutta l'immagine)
        scale: fattore di upscale prima dell'OCR (2.0 = raddoppia)

    Returns:
        Array grayscale binarizzato, pronto per Tesseract.
    """
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
    """
    Preprocessa per testo crema/dorato su sfondo scuro (tipico UI Doomsday).

    Isola i pixel luminosi (valore > thresh_low) e li porta a bianco
    su sfondo nero, poi inverte per Tesseract (testo nero su bianco).

    Args:
        img:        Screenshot o array BGR
        zone:       zona da ritagliare
        scale:      fattore upscale
        thresh_low: soglia luminosità minima per considerare un pixel "testo"

    Returns:
        Array grayscale binarizzato pronto per Tesseract.
    """
    arr = _to_array(img)
    roi = _crop_zone(arr, zone)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    if scale != 1.0:
        h, w = gray.shape
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_CUBIC)

    # Soglia manuale: pixel luminosi → bianco (testo), resto → nero
    _, binary = cv2.threshold(gray, thresh_low, 255, cv2.THRESH_BINARY)
    # Inverti per Tesseract (vuole testo nero su bianco)
    return cv2.bitwise_not(binary)


# ==============================================================================
# OCR principale
# ==============================================================================

def ocr_zona(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    config: str = _PSM_LINE,
    preprocessor: str = "otsu",
) -> str:
    """
    Estrae testo grezzo da una zona dell'immagine.

    Args:
        img:          Screenshot o array BGR
        zone:         (x1, y1, x2, y2) zona — None = tutta l'immagine
        config:       stringa config Tesseract
        preprocessor: "otsu" | "crema" | "none"

    Returns:
        Testo estratto (stringa vuota se fallisce).
    """
    arr = _to_array(img)

    if preprocessor == "otsu":
        processed = prepara_otsu(arr, zone)
    elif preprocessor == "crema":
        processed = prepara_crema(arr, zone)
    else:
        # None: converte solo in grayscale senza binarizzazione
        roi = _crop_zone(arr, zone)
        processed = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    return _run_tesseract(processed, config)


def ocr_intero(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    preprocessor: str = "otsu",
) -> str:
    """
    OCR ottimizzato per riga singola (psm=7), zona intera.
    Strategia preferita: prima prova psm=7 sulla zona intera,
    poi fall-back su psm=13 se il risultato è vuoto.

    Returns:
        Testo estratto, stringa vuota se entrambi i tentativi falliscono.
    """
    result = ocr_zona(img, zone, config=_PSM_LINE, preprocessor=preprocessor)
    if result:
        return result
    # Fall-back psm=13
    return ocr_zona(img, zone, config=_PSM_RAW, preprocessor=preprocessor)


def ocr_cifre(
    img: "Screenshot | np.ndarray",
    zone: tuple[int, int, int, int] | None = None,
    preprocessor: str = "otsu",
) -> str:
    """
    Estrae solo cifre e separatori numerici (0-9, K, M, punto, virgola).
    Usa la whitelist Tesseract per ridurre gli errori di riconoscimento.

    Returns:
        Stringa con solo i caratteri numerici, vuota se nulla trovato.
    """
    return ocr_zona(img, zone, config=_DIGITS_CFG, preprocessor=preprocessor)


# ==============================================================================
# Parsing numerico
# ==============================================================================

def estrai_numero(testo: str) -> int | None:
    """
    Converte una stringa OCR in intero, gestendo i formati del gioco:
      - "12.345"   → 12345   (punto come separatore migliaia)
      - "12,345"   → 12345   (virgola come separatore migliaia)
      - "12.5K"    → 12500
      - "1.2M"     → 1200000
      - "  8 "     → 8
      - ""         → None
      - "abc"      → None

    Returns:
        int se il parsing riesce, None altrimenti.
    """
    if not testo:
        return None

    testo = testo.strip().upper().replace(" ", "")

    # Rimuove caratteri non numerici prima di analizzare i separatori
    # (gestisce testo OCR sporco come "8.542 res" → "8.542")
    import re as _re
    testo = _re.sub(r"[^0-9.,KM]", "", testo)

    # Gestisce K (migliaia) e M (milioni)
    multiplier = 1
    if testo.endswith("K"):
        multiplier = 1_000
        testo = testo[:-1]
    elif testo.endswith("M"):
        multiplier = 1_000_000
        testo = testo[:-1]

    # Rimuove separatori migliaia (punto o virgola se seguiti da 3 cifre)
    # Strategia: se c'è sia punto che virgola, il punto è separatore migliaia
    if "." in testo and "," in testo:
        testo = testo.replace(".", "")  # rimuove punto-separatore
        testo = testo.replace(",", ".")  # virgola → decimale
    elif "," in testo:
        # Solo virgola: potrebbe essere separatore migliaia (12,345) o decimale
        # Se ci sono esattamente 3 cifre dopo la virgola → separatore migliaia
        parts = testo.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            testo = testo.replace(",", "")
        else:
            testo = testo.replace(",", ".")
    elif "." in testo:
        # Multipli punti (1.234.567) → tutti separatori migliaia
        parts = testo.split(".")
        if len(parts) > 2:
            testo = testo.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3:
            testo = testo.replace(".", "")

    # Estrae la prima sequenza numerica (ignora testo spazzatura dopo)
    match = re.search(r"\d[\d.]*", testo)
    if not match:
        return None

    num_str = match.group().rstrip(".")
    try:
        valore = float(num_str)
        return int(round(valore * multiplier))
    except ValueError:
        return None


# ==============================================================================
# Lettura risorse deposito
# ==============================================================================

class RisorseDeposito(NamedTuple):
    """Risorse lette dal deposito. None = lettura fallita per quella risorsa."""
    pomodoro:  int | None
    legno:     int | None
    petrolio:  int | None
    acciaio:   int | None


# Zone standard del deposito risorse (coordinate 960x540)
# Possono essere sovrascritte se lo schermo del gioco cambia
ZONE_RISORSE_DEFAULT: dict[str, tuple[int, int, int, int]] = {
    "pomodoro": (68,  11, 160, 25),
    "legno":    (175, 11, 267, 25),
    "petrolio": (282, 11, 374, 25),
    "acciaio":  (389, 11, 481, 25),
}


def ocr_risorse(
    img: "Screenshot | np.ndarray",
    zone_risorse: dict[str, tuple[int, int, int, int]] | None = None,
    preprocessor: str = "crema",
) -> RisorseDeposito:
    """
    Legge le 4 risorse dal deposito nella barra superiore dello screenshot.

    Strategia per ogni risorsa:
      1. OCR sulla zona intera con psm=7
      2. Se fallisce, OCR cifre-only sulla stessa zona
      3. Parsing con estrai_numero()

    Args:
        img:          Screenshot della schermata HOME
        zone_risorse: dict con zone custom (None = usa ZONE_RISORSE_DEFAULT)
        preprocessor: "crema" (default) o "otsu"

    Returns:
        RisorseDeposito con i valori letti (None se lettura fallita).
    """
    zone = zone_risorse or ZONE_RISORSE_DEFAULT
    risultati: dict[str, int | None] = {}

    for risorsa, zona in zone.items():
        # Tentativo 1: psm=7 zona intera
        testo = ocr_intero(img, zona, preprocessor=preprocessor)
        valore = estrai_numero(testo)

        # Tentativo 2: solo cifre
        if valore is None:
            testo = ocr_cifre(img, zona, preprocessor=preprocessor)
            valore = estrai_numero(testo)

        risultati[risorsa] = valore

    return RisorseDeposito(
        pomodoro=risultati.get("pomodoro"),
        legno=risultati.get("legno"),
        petrolio=risultati.get("petrolio"),
        acciaio=risultati.get("acciaio"),
    )
