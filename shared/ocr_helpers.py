# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/ocr_helpers.py
#
#  FIX 12/04/2026 sessione 1:
#    - _to_array: img.array → img.frame
#  FIX 12/04/2026 sessione 3 — da lettura ocr.py V5:
#    - Zone risorse calibrate, _maschera_bianca, _parse_valore, _parse_diamanti
#    - RisorseDeposito aggiunto diamanti, upscale 4x, path Tesseract
#  FIX 12/04/2026 sessione 4 — RT-05:
#    - leggi_contatore_slot: portato da ocr.py V5 leggi_contatore_da_zona
#      Zone: testo (890,117,946,141) psm=7 + fallback cifre separate
#      Pre-check pixel bianchi: se assenti → (0, totale_noto)
#  FIX 16/04/2026:
#    - leggi_contatore_slot: pre-check < 15px bianchi prova fallback
#      thresh_130 psm=6 scale=2 prima di restituire (0, totale_noto)
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
    import os as _os
    pytesseract.pytesseract.tesseract_cmd = _os.environ.get(
        "TESSERACT_EXE",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

try:
    from core.device import Screenshot
    _ScreenshotType = Screenshot
except ImportError:
    _ScreenshotType = None  # type: ignore

_tesseract_lock = threading.Lock()

# ==============================================================================
# Costanti Tesseract
# ==============================================================================
_PSM_LINE   = "--psm 7"
_PSM_BLOCK  = "--psm 6"
_PSM_RAW    = "--psm 13"
_DIGITS_CFG = "--psm 7 -c tessedit_char_whitelist=0123456789KkMm.,"

# ==============================================================================
# Zone contatore slot — calibrate da ocr.py V5
# FIX 15/04/2026: zone cifre ricalibrate da analisi pixel colonna su screen reale.
#   Analisi pixel 5/5: cifra SX a x=908-913, slash a x=915-918, cifra DX a x=921-926.
#   Le zone precedenti (890-919 e 922-946) includevano troppo contesto → OCR confuso.
# ==============================================================================
_ZONA_TESTO_SLOT  = (890, 117, 946, 141)  # testo X/Y intero — psm=7 priorità
_ZONA_CIFRA_SX    = (906, 117, 916, 141)  # cifra attive — ricalibrata (era 890-919)
_ZONA_CIFRA_DX    = (919, 117, 929, 141)  # cifra totale — ricalibrata (era 922-946)
_SOGLIA_PX_BIANCHI = 15                   # pixel bianchi minimi per considerare slot attivi
_SOGLIA_LUMIN_PX  = 100                   # soglia luminosità RGB per pre-check (era 140 hardcoded).
                                          # WU55 28/04: abbassata 140→100 per coprire MAP sotto-illuminata
                                          # (caso FAU_07 popup overlay: max RGB=88 borderline; ora cattura).
                                          # Solo pre-check leggi_contatore_slot — no impatto su _maschera_bianca.


# ==============================================================================
# Helper conversione immagine
# ==============================================================================

def _to_array(img: "Screenshot | np.ndarray") -> np.ndarray:
    if _ScreenshotType is not None and isinstance(img, _ScreenshotType):
        return img.frame
    if isinstance(img, np.ndarray):
        return img
    raise TypeError(f"ocr_helpers: tipo non supportato: {type(img)}")


def _to_pil(img: "Screenshot | np.ndarray") -> Image.Image:
    arr = _to_array(img)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _crop_zone(arr: np.ndarray, zone: tuple) -> np.ndarray:
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

def prepara_otsu(img, zone=None, scale: float = 2.0) -> np.ndarray:
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


def prepara_crema(img, zone=None, scale: float = 2.0, thresh_low: int = 160) -> np.ndarray:
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
    """Pixel bianchi RGB>140 con padding 20px — portata da V5."""
    arr = np.array(img_pil).astype(int)
    h, w = arr.shape[:2]
    pad  = 20
    mask = np.zeros((h + pad * 2, w + pad * 2), dtype=np.uint8)
    for y in range(h):
        for x in range(taglio_sx, w):
            if arr[y, x, 0] > 140 and arr[y, x, 1] > 140 and arr[y, x, 2] > 140:
                mask[y + pad, x - taglio_sx + pad] = 255
    return Image.fromarray(mask)


# ==============================================================================
# OCR principale
# ==============================================================================

def ocr_zona(img, zone=None, config: str = _PSM_LINE, preprocessor: str = "otsu") -> str:
    arr = _to_array(img)
    if preprocessor == "otsu":
        processed = prepara_otsu(arr, zone)
    elif preprocessor == "crema":
        processed = prepara_crema(arr, zone)
    else:
        roi = _crop_zone(arr, zone)
        processed = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return _run_tesseract(processed, config)


def ocr_intero(img, zone=None, preprocessor: str = "otsu") -> str:
    result = ocr_zona(img, zone, config=_PSM_LINE, preprocessor=preprocessor)
    if result:
        return result
    return ocr_zona(img, zone, config=_PSM_RAW, preprocessor=preprocessor)


def ocr_cifre(img, zone=None, preprocessor: str = "otsu") -> str:
    return ocr_zona(img, zone, config=_DIGITS_CFG, preprocessor=preprocessor)


# ==============================================================================
# Parsing numerico — da ocr.py V5
# ==============================================================================

def _parse_valore(testo: str) -> float:
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
            if len(cifre) == 3:   val = float(cifre[:-1] + '.' + cifre[-1])
            elif len(cifre) == 2: val = float(cifre[0] + '.' + cifre[1])
            else:                  val = float(cifre)
        else:
            val = float(cifre)
    if mult == 'M':   val *= 1_000_000
    elif mult == 'K': val *= 1_000
    elif mult == 'B': val *= 1_000_000_000
    return val


def _parse_diamanti(testo: str) -> int:
    testo = testo.strip().replace(',', '').replace('.', '').replace(' ', '')
    nums = re.findall(r'\d+', testo)
    if nums:
        val = int(''.join(nums))
        return val if val < 10_000_000 else -1
    return -1


def estrai_numero(testo: str) -> int | None:
    if not testo:
        return None
    testo = testo.strip().upper().replace(" ", "")
    testo = re.sub(r"[^0-9.,KM]", "", testo)
    multiplier = 1
    if testo.endswith("K"):   multiplier = 1_000;       testo = testo[:-1]
    elif testo.endswith("M"): multiplier = 1_000_000;   testo = testo[:-1]
    if "." in testo and "," in testo:
        testo = testo.replace(".", "").replace(",", ".")
    elif "," in testo:
        parts = testo.split(",")
        testo = testo.replace(",", "") if all(len(p)==3 for p in parts[1:]) and len(parts)>=2 else testo.replace(",",".")
    elif "." in testo:
        parts = testo.split(".")
        if len(parts) > 2: testo = testo.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3: testo = testo.replace(".", "")
    match = re.search(r"\d[\d.]*", testo)
    if not match:
        return None
    try:
        return int(round(float(match.group().rstrip(".")) * multiplier))
    except ValueError:
        return None


# ==============================================================================
# Lettura risorsa singola — da ocr.py V5
# ==============================================================================

def leggi_risorsa(crop_pil: Image.Image, taglio_sx: int = 0) -> float:
    try:
        mask = _maschera_bianca(crop_pil, taglio_sx)
        cfg  = "--psm 7 -c tessedit_char_whitelist=0123456789.MKB"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(mask, config=cfg).strip()
        return _parse_valore(testo)
    except Exception:
        return -1


# ==============================================================================
# Zone risorse — calibrate su screenshot reali 960x540 (ocr.py V5, 04/04/2026)
# ==============================================================================

_ZONA_BARRA_COMPLETA = (425, 4, 948, 28)
_BARRA_X0 = 425
_BARRA_Y0 = 4

ZONE_RISORSE_V5 = {
    "pomodoro": {"zona": (455, 4, 520, 28), "taglio": 0},
    "legno":    {"zona": (555, 4, 622, 28), "taglio": 0},
    "acciaio":  {"zona": (655, 4, 720, 28), "taglio": 0},
    "petrolio": {"zona": (755, 4, 820, 28), "taglio": 0},
    "diamanti": {"zona": (855, 4, 920, 28), "taglio": 0},
}


class RisorseDeposito(NamedTuple):
    """Risorse lette dalla barra superiore. -1 = lettura fallita."""
    pomodoro: float
    legno:    float
    acciaio:  float
    petrolio: float
    diamanti: int


def ocr_risorse(img: "Screenshot | np.ndarray") -> RisorseDeposito:
    """
    Legge le 5 risorse dalla barra superiore (HOME o MAPPA).
    Pipeline identica a V5 leggi_risorse().
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
            crop   = barra.crop((x1-_BARRA_X0, y1-_BARRA_Y0, x2-_BARRA_X0, y2-_BARRA_Y0))
            w, h   = crop.size
            crop4x = crop.resize((w*4, h*4), Image.LANCZOS)
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


def ocr_risorse_robust(device, max_attempts: int = 3,
                       sleep_s: float = 0.5, log_fn=None) -> "RisorseDeposito":
    """
    auto-WU25 (27/04): wrapper di ocr_risorse con retry per zone fallite.

    Ogni tentativo prende uno screenshot fresco. I valori validi (!=-1) sono
    mantenuti tra i tentativi: solo le zone fallite vengono ri-tentate.
    Se dopo max_attempts qualche zona resta -1, ritorna comunque (caller
    deciderà fallback con valori precedenti).

    Tipici: 1 tentativo se tutto OK al primo round; 2-3 tentativi se 1-2
    zone sono fallite per overlay transient.
    """
    import time as _t
    log = log_fn or (lambda _m: None)
    rd_acc = RisorseDeposito(-1, -1, -1, -1, -1)
    fields = ("pomodoro", "legno", "acciaio", "petrolio", "diamanti")

    for attempt in range(max_attempts):
        try:
            shot = device.screenshot() if device is not None else None
        except Exception:
            shot = None
        if shot is None:
            log(f"[OCR-RETRY] tent {attempt+1}: screenshot None")
            _t.sleep(sleep_s)
            continue

        rd_new = ocr_risorse(shot)
        # Merge: per ogni campo, usa nuovo valore se non -1, altrimenti tieni acc
        merged = {}
        for f in fields:
            v_new = getattr(rd_new, f)
            v_old = getattr(rd_acc, f)
            merged[f] = v_new if v_new != -1 else v_old
        rd_acc = RisorseDeposito(**merged)

        # All OK? exit early
        ko_fields = [f for f in fields if getattr(rd_acc, f) == -1]
        if not ko_fields:
            if attempt > 0:
                log(f"[OCR-RETRY] tutto OK al tent {attempt+1}")
            return rd_acc

        if attempt < max_attempts - 1:
            log(f"[OCR-RETRY] tent {attempt+1}: KO {ko_fields} — retry")
            _t.sleep(sleep_s)

    ko_fields = [f for f in fields if getattr(rd_acc, f) == -1]
    if ko_fields:
        log(f"[OCR-RETRY] dopo {max_attempts} tent: KO finali {ko_fields}")
    return rd_acc


# ==============================================================================
# Contatore slot raccoglitori — portato da ocr.py V5 leggi_contatore_da_zona
#
# Zone calibrate (960x540):
#   _ZONA_TESTO_SLOT = (890, 117, 946, 141)  testo X/Y intero  psm=7
#   _ZONA_CIFRA_SX   = (890, 117, 919, 141)  cifra attive       fallback psm=10
#   _ZONA_CIFRA_DX   = (922, 117, 946, 141)  cifra totale       fallback psm=8
#
# Logica:
#   1. Pre-check pixel bianchi nella zona testo — se < soglia → (0, totale_noto)
#   2. OCR zona intera psm=7 → pattern X/Y
#   3. Fallback cifre separate psm=10/8
# ==============================================================================

def _ocr_zona_intera_slot(crop_pil: Image.Image) -> tuple[int, int]:
    """
    OCR X/Y sulla zona testo intera. Ritorna (attive, totale) o (-1,-1).

    FIX 15/04/2026 — calibrazione automatica con calibra_slot_ocr.py:
    6183/29400 combinazioni leggono correttamente 5/5.
    Configurazione vincente: psm=6, scale=2, maschera_bianca, taglio=0.
    Retry automatico con psm=7 e psm=13 se psm=6 fallisce.
    Salva debug/slot_ocr_debug.png per analisi in caso di fallimento.
    """
    try:
        w, h   = crop_pil.size
        crop2x = crop_pil.resize((w*2, h*2), Image.LANCZOS)
        mask   = _maschera_bianca(crop2x, taglio_sx=0)

        for psm in (6, 7, 13):
            cfg = f"--psm {psm} -c tessedit_char_whitelist=0123456789/"
            with _tesseract_lock:
                testo = pytesseract.image_to_string(mask, config=cfg).strip()
            m = re.search(r"(\d+)/(\d+)", testo)
            if m:
                return (int(m.group(1)), int(m.group(2)))

        # Tutti i psm falliti — salva debug su disco
        try:
            import os as _os_dbg
            dbg_dir = r"C:\doomsday-engine\debug_task"
            _os_dbg.makedirs(dbg_dir, exist_ok=True)
            mask.save(_os_dbg.path.join(dbg_dir, "slot_ocr_debug.png"))
            crop_pil.save(_os_dbg.path.join(dbg_dir, "slot_ocr_crop.png"))
        except Exception:
            pass

        return (-1, -1)
    except Exception:
        return (-1, -1)


def _ocr_slot_thresh130(crop_pil: Image.Image) -> tuple[int, int]:
    """
    Fallback OCR slot con thresh=130, scale=2, psm=6.
    Usato quando maschera_bianca restituisce < _SOGLIA_PX_BIANCHI pixel bianchi.
    Ritorna (attive, totale) o (-1, -1).
    """
    try:
        w, h  = crop_pil.size
        arr   = np.array(crop_pil)
        gray  = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray2, 130, 255, cv2.THRESH_BINARY)
        cfg = "--psm 6 -c tessedit_char_whitelist=0123456789/"
        with _tesseract_lock:
            testo = pytesseract.image_to_string(binary, config=cfg).strip()
        m = re.search(r"(\d+)/(\d+)", testo)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (-1, -1)
    except Exception:
        return (-1, -1)


def _ocr_cifra_singola_slot(crop_pil: Image.Image, psm: int = 10) -> int:
    """OCR singola cifra con upscale 8x + Otsu. Ritorna int o -1."""
    try:
        w, h = crop_pil.size
        pad  = Image.new('RGB', (w+10, h+10), (0, 0, 0))
        pad.paste(crop_pil, (5, 5))
        c8   = pad.resize(((w+10)*8, (h+10)*8), Image.LANCZOS)
        arr  = np.array(c8)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cfg  = f'--psm {psm} -c tessedit_char_whitelist=0123456789'
        with _tesseract_lock:
            testo = pytesseract.image_to_string(Image.fromarray(th), config=cfg).strip()
        m = re.search(r'(\d+)', testo)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1


# ==============================================================================
# Contatore slot via Squad Summary popup — pin_return TM (bypass OCR font bug)
#
# Il popup Squad Summary mostra una riga per ogni slot attivo con un pulsante
# ↩ (pin_return.png) in posizione fissa. find_all() conta le occorrenze.
# Mostra max 3 righe per schermata — swipe up per vedere le altre.
#
# Coordinate popup (960x540):
#   TAP_SLOT_BTN    = (877, 126)   apre popup (visibile solo se slot > 0)
#   SUMMARY_CLOSE   = (795, 68)    X chiusura popup
#   SUMMARY_SWIPE   = swipe (480,450,480,200) per scroll
#   SUMMARY_ROI     = (700,100,820,530) zona pin_return
#   PIN_RETURN      = "pin/pin_return.png"
#   SOGLIA_RETURN   = 0.75
#   RIGHE_PER_SCH   = 3   max righe visibili per schermata
# ==============================================================================

_TAP_SLOT_BTN   = (877, 126)
_SUMMARY_CLOSE  = (795, 68)
_SUMMARY_SWIPE_START = (480, 420)
_SUMMARY_SWIPE_END   = (480, 180)
_SUMMARY_ROI    = (700, 100, 820, 530)
_PIN_RETURN     = "pin/pin_return.png"
_SOGLIA_RETURN  = 0.75
_RIGHE_PER_SCH  = 3


def leggi_slot_da_summary(
    device,
    matcher,
    log_fn=None,
    totale_noto: int = -1,
) -> int:
    """
    Conta gli slot attivi aprendo il popup Squad Summary e contando
    le occorrenze di pin_return.png (pulsante ↩ per ogni riga attiva).

    Procedura:
      1. Verifica pixel zona pulsante (877,126) — se buio → 0 slot
      2. Tap → apre popup Squad Summary
      3. find_all(pin_return) su prima schermata → conta righe
      4. Se righe == RIGHE_PER_SCH (3) → swipe + seconda schermata
      5. Chiude popup (tap X)

    Args:
        device:      AdbDevice
        matcher:     TemplateMatcher
        log_fn:      callable(msg) per logging
        totale_noto: max slot istanza (da instances.json)

    Returns:
        int >= 0  slot attivi
        -1        popup non aperto o errore
    """
    import time

    def log(msg):
        if log_fn:
            log_fn(msg)

    # 1. Screenshot iniziale — verifica pulsante visibile
    screen = device.screenshot()
    if screen is None:
        return -1

    frame = getattr(screen, "frame", None)
    if frame is not None:
        zona_btn = frame[110:145, 860:900]
        media = int(zona_btn.mean())
        if media < 20:
            log("[SUMMARY] pulsante slot non visibile — 0 slot attivi")
            return 0

    # 2. Tap pulsante → apre popup
    device.tap(*_TAP_SLOT_BTN)
    time.sleep(1.5)

    screen2 = device.screenshot()
    if screen2 is None:
        return -1

    # 3. Conta pin_return nella prima schermata
    try:
        matches1 = matcher.find_all(
            screen2, _PIN_RETURN,
            threshold=_SOGLIA_RETURN,
            zone=_SUMMARY_ROI,
            cluster_px=50,
        )
        n1 = len(matches1)
        log(f"[SUMMARY] prima schermata: {n1} righe")
    except Exception as exc:
        log(f"[SUMMARY] errore find_all: {exc}")
        device.tap(*_SUMMARY_CLOSE)
        time.sleep(0.5)
        return -1

    totale = n1

    # 4. Se schermata piena (3 righe) → potrebbe esserci una seconda schermata
    if n1 >= _RIGHE_PER_SCH:
        device.swipe(
            _SUMMARY_SWIPE_START[0], _SUMMARY_SWIPE_START[1],
            _SUMMARY_SWIPE_END[0],   _SUMMARY_SWIPE_END[1],
            duration_ms=400,
        )
        time.sleep(1.0)

        screen3 = device.screenshot()
        if screen3 is not None:
            try:
                matches2 = matcher.find_all(
                    screen3, _PIN_RETURN,
                    threshold=_SOGLIA_RETURN,
                    zone=_SUMMARY_ROI,
                    cluster_px=50,
                )
                n2 = len(matches2)
                log(f"[SUMMARY] seconda schermata: {n2} righe")
                # Somma solo le righe nuove (non già conteggiate)
                # Le ultime righe della prima schermata si sovrappongono
                # con le prime della seconda — contiamo solo il delta
                totale = n1 + max(0, n2 - 1)
            except Exception:
                pass  # usa solo n1

        # Sanity check con totale_noto
        if totale_noto > 0:
            totale = min(totale, totale_noto)

    log(f"[SUMMARY] slot attivi: {totale}/{totale_noto if totale_noto > 0 else '?'}")

    # 5. Chiude popup
    device.tap(*_SUMMARY_CLOSE)
    time.sleep(0.8)

    return totale


def leggi_contatore_slot(
    img: "Screenshot | np.ndarray",
    totale_noto: int = -1,
) -> tuple[int, int]:
    """
    Legge il contatore slot raccoglitori X/Y dallo screenshot.
    Zone calibrate da ocr.py V5 (890,117,946,141).

    Pipeline:
      0. WU70 (29/04 sera) — SX-only ensemble [PRIMARIA quando totale_noto>0]:
         - crop _ZONA_CIFRA_SX (10×24 isolato, no "/" no DX a confondere)
         - 3 PSM diversi (10/8/7) con upscale 8x + Otsu
         - filtra a priori valori >totale_noto (impossibili) → escluso "5→7"
         - majority vote sui plausibili → (attive, totale_noto)
         - tutto fallisce → fallthrough al flow legacy
      1. Pre-check pixel bianchi — se < 15px → fallback thresh_130 psm=6 scale=2
         Se fallback trova X/Y → ritorna. Altrimenti → (0, totale_noto).
      2. OCR zona intera psm=6/7/13 → pattern X/Y  [priorità legacy]
      3. Fallback cifre separate psm=10/8

    Args:
        img:         Screenshot della HOME o MAPPA
        totale_noto: valore totale noto (da instances.json). Se >0 abilita WU70.

    Returns:
        (attive, totale) — es. (2, 4)
        (0, totale_noto) — se nessuna squadra attiva
        (-1, -1)         — se lettura fallita
    """
    try:
        pil_img = _to_pil(img)

        # WU70 — SX-only ensemble: lettura primaria quando totale_noto>0
        if totale_noto > 0:
            crop_sx = pil_img.crop(_ZONA_CIFRA_SX)
            attive_psm10 = _ocr_cifra_singola_slot(crop_sx, psm=10)
            attive_psm8  = _ocr_cifra_singola_slot(crop_sx, psm=8)
            attive_psm7  = _ocr_cifra_singola_slot(crop_sx, psm=7)
            # Filtra a priori valori non plausibili (impossibili: <0 o >totale).
            # Cattura il pattern "5→7" perché 7 viene escluso quando max=5.
            plausibili = [
                v for v in (attive_psm10, attive_psm8, attive_psm7)
                if 0 <= v <= totale_noto
            ]
            if plausibili:
                from collections import Counter
                attive = Counter(plausibili).most_common(1)[0][0]
                return (attive, totale_noto)
            # Tutti e 3 i PSM hanno letto valori non plausibili o -1.
            # Fallthrough al flow legacy come ultima spiaggia.

        # 1. Pre-check pixel bianchi nella zona testo
        x1, y1, x2, y2 = _ZONA_TESTO_SLOT
        crop_testo = pil_img.crop((x1, y1, x2, y2))
        arr_check  = np.array(crop_testo).astype(int)
        px_bianchi = int(np.sum(
            (arr_check[:, :, 0] > _SOGLIA_LUMIN_PX) &
            (arr_check[:, :, 1] > _SOGLIA_LUMIN_PX) &
            (arr_check[:, :, 2] > _SOGLIA_LUMIN_PX)
        ))

        if px_bianchi < _SOGLIA_PX_BIANCHI:
            # Pre-check fallito: pochi pixel bianchi con maschera_bianca.
            # Fallback: thresh_130, psm=6, scale=2 prima di arrendersi.
            attive_fb, totale_fb = _ocr_slot_thresh130(crop_testo)
            if attive_fb != -1 and totale_fb != -1:
                return (attive_fb, totale_fb)
            # Fallback anch'esso fallito → nessuna squadra attiva
            return (0, totale_noto)

        # 2. OCR zona intera psm=7
        attive, totale = _ocr_zona_intera_slot(crop_testo)

        # 3. Fallback cifre separate
        if attive == -1:
            crop_sx = pil_img.crop(_ZONA_CIFRA_SX)
            attive  = _ocr_cifra_singola_slot(crop_sx, psm=10)
        if totale == -1:
            crop_dx = pil_img.crop(_ZONA_CIFRA_DX)
            totale  = _ocr_cifra_singola_slot(crop_dx, psm=8)

        # Fallback totale_noto
        if totale == -1 and totale_noto > 0:
            totale = totale_noto

        if attive == -1 or totale == -1:
            return (-1, -1)

        # WU55 28/04 — cross-validation per stabilità (pattern 4↔7 confusion)
        # Se attive>totale, semanticamente impossibile: retry con preprocessing
        # alternativo (thresh_130 invece di maschera_bianca) + cifre separate.
        # Se 2/3 metodi concordano su un valore <=totale → uso quello.
        # Altrimenti (-1,-1) e il caller fa fallback HOME (più stabile).
        if attive > totale:
            attive_thresh, totale_thresh = _ocr_slot_thresh130(crop_testo)
            crop_sx = pil_img.crop(_ZONA_CIFRA_SX)
            crop_dx = pil_img.crop(_ZONA_CIFRA_DX)
            attive_cifra = _ocr_cifra_singola_slot(crop_sx, psm=10)
            totale_cifra = _ocr_cifra_singola_slot(crop_dx, psm=8)

            # Vote per attive: solo valori plausibili (0..totale_noto)
            cap = totale_noto if totale_noto > 0 else max(totale, 5)
            candidates = [v for v in (attive, attive_thresh, attive_cifra)
                          if 0 <= v <= cap]
            if candidates:
                # Majority vote, tie-break su valore minimo (conservativo)
                from collections import Counter
                count = Counter(candidates).most_common(1)[0][0]
                attive = count
                # Conferma totale se coerente
                if 0 < totale_thresh <= cap:
                    totale = totale_thresh
                elif 0 < totale_cifra <= cap:
                    totale = totale_cifra
            else:
                # Nessun valore plausibile da nessun preprocessing → reject
                return (-1, -1)

        return (attive, totale)

    except Exception:
        return (-1, -1)


# ==============================================================================
# OCR capacità nodo — popup gather (validato 30/04/2026 su FAU_07)
# ROI fissa: il popup si apre sempre al centro mappa dopo SEARCH+tap nodo.
# Censimento capacità (cfr memory/reference_capacita_nodi.md):
#   Pomodoro/Legno L7 = 1,320,000  L6 = 1,200,000
#   Acciaio       L7 =   660,000  L6 =   600,000
#   Petrolio      L7 =   264,000  L6 =   240,000
#   Pattern: L7 = L6 × 1.10
# ==============================================================================
_ZONA_CAPACITA_NODO = (270, 280, 420, 320)  # 150×40 px — popup gather


def _parse_int_with_commas(testo: str) -> int:
    """Parse '1,320,000' → 1320000. Ritorna -1 se non valido."""
    if not testo:
        return -1
    cleaned = testo.replace(",", "").strip()
    if cleaned.isdigit():
        return int(cleaned)
    return -1


def leggi_capacita_nodo(img) -> int:
    """Legge il valore Quantity dal popup gather (capacità residua nodo).

    Cascade: PSM 6 raw RGB → fallback PSM 6 binv (threshold 150).
    Validato 9/9 su FAU_07 30/04: pomodoro/legno/acciaio/petrolio L6+L7.

    Ritorna il valore intero (es. 1320000) o -1 se OCR fallisce.
    """
    if not _TESSERACT_OK:
        return -1
    try:
        arr = _to_array(img)
        x1, y1, x2, y2 = _ZONA_CAPACITA_NODO
        roi = arr[y1:y2, x1:x2]
        cfg = "--psm 6 -c tessedit_char_whitelist=0123456789,"

        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        val = _parse_int_with_commas(_run_tesseract(rgb, cfg))
        if val > 0:
            return val

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binv = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        val = _parse_int_with_commas(_run_tesseract(binv, cfg))
        if val > 0:
            return val

        return -1
    except Exception:
        return -1


# ==============================================================================
# OCR carico squadra ("Load") — maschera invio raccolta
# ROI fissa: maschera centrata, valore Load sopra il bottone MARCH.
# Validato 6/6 su FAU_01 04/05: campo L6/L7, acciaio L6, petrolio (5-cifre),
# truppe ridotte (caso underprovisioning).
# Cascade: raw RGB → binv 150 (binv 200 distorce le cifre piccole "5"→"9").
# Estrae il primo gruppo digit-virgola (binv 150 a volte ha rumore extra
# sotto, dal timer ETA).
# ==============================================================================
_ZONA_LOAD_SQUADRA = (610, 420, 780, 455)  # 170×35 px — sopra MARCH btn

_LOAD_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,7}")


def _parse_first_int_with_commas(testo: str) -> int:
    """Estrae il primo numero (con o senza virgole) dal testo, ritorna int.

    Pattern: '\\d{1,3}(?:,\\d{3})+' (con virgole) oppure '\\d{1,7}' (senza).
    Usato da leggi_load_squadra: binv 150 a volte include caratteri spuri
    dopo il numero (es. timer ETA sotto la riga Load) — questa funzione
    estrae solo la prima sequenza di cifre validate.

    Ritorna -1 se nessun match.
    """
    if not testo:
        return -1
    m = _LOAD_RE.search(testo)
    if not m:
        return -1
    return int(m.group(0).replace(",", ""))


def leggi_load_squadra(img) -> int:
    """Legge il valore "Load" dalla maschera invio raccolta.

    Il valore è il carico effettivo che la squadra raccoglierà:
        load = min(squadra_max_truppe, cap_nodo_residuo)

    Confrontato con `leggi_capacita_nodo` permette di calcolare la
    saturazione: se load < cap_nodo → squadra underprovisioned (poche
    truppe), il nodo non verrà chiuso al 100% e non rigenererà al max.

    Cascade: raw RGB → binv 150 (binv 200 distorce cifre piccole).
    Estrae il primo gruppo digit-comma per ignorare rumore ETA timer.

    Validato 6/6 su FAU_01 04/05.

    Ritorna il valore intero (es. 1320012) o -1 se OCR fallisce.
    """
    if not _TESSERACT_OK:
        return -1
    try:
        arr = _to_array(img)
        x1, y1, x2, y2 = _ZONA_LOAD_SQUADRA
        roi = arr[y1:y2, x1:x2]
        cfg = "--psm 6 -c tessedit_char_whitelist=0123456789,"

        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        val = _parse_first_int_with_commas(_run_tesseract(rgb, cfg))
        if val > 0:
            return val

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binv = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        val = _parse_first_int_with_commas(_run_tesseract(binv, cfg))
        if val > 0:
            return val

        return -1
    except Exception:
        return -1
