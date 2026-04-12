# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_risorse_debug.py
#
#  Diagnostica RT-04: salva i crop delle zone risorse per verifica visiva
#  e stampa i valori raw OCR prima del parsing.
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_risorse_debug.py
#
#  Output in: C:\doomsday-engine\debug_nav\risorse\
# ==============================================================================

import os, sys, time
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import cv2
import numpy as np
from PIL import Image
import pytesseract

import pytesseract
import os
pytesseract.pytesseract.tesseract_cmd = os.environ.get(
    "TESSERACT_EXE",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

from core.device import AdbDevice
from shared.ocr_helpers import _to_pil, _maschera_bianca, _parse_valore, _parse_diamanti

ADB_HOST  = "127.0.0.1"
ADB_PORT  = 16384
DEBUG_DIR = os.path.join(ROOT, "debug_nav", "risorse")
os.makedirs(DEBUG_DIR, exist_ok=True)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

# ---------------------------------------------------------------------------
# Zone V5 calibrate
# ---------------------------------------------------------------------------
_ZONA_BARRA_COMPLETA = (425, 4, 948, 28)
_BARRA_X0 = 425
_BARRA_Y0 = 4

ZONE = {
    "pomodoro": {"zona": (455, 4, 520, 28), "taglio": 0, "tipo": "risorsa"},
    "legno":    {"zona": (555, 4, 622, 28), "taglio": 0, "tipo": "risorsa"},
    "acciaio":  {"zona": (655, 4, 720, 28), "taglio": 0, "tipo": "risorsa"},
    "petrolio": {"zona": (755, 4, 820, 28), "taglio": 0, "tipo": "risorsa"},
    "diamanti": {"zona": (855, 4, 920, 28), "taglio": 0, "tipo": "diamanti"},
}

# ---------------------------------------------------------------------------
# ADB + screenshot
# ---------------------------------------------------------------------------
log("Connessione ADB...")
device = AdbDevice(host=ADB_HOST, port=ADB_PORT, name="FAU_00")
shot = device.screenshot()
if shot is None:
    log("FAIL: screenshot None"); sys.exit(1)

pil_img = _to_pil(shot)
log(f"Screenshot: {shot.width}x{shot.height}")

# Salva barra completa per verifica visiva
barra_full = pil_img.crop(_ZONA_BARRA_COMPLETA)
barra_full.save(os.path.join(DEBUG_DIR, "00_barra_completa.png"))
# Versione ingrandita 4x
w, h = barra_full.size
barra_full.resize((w*4, h*4), Image.NEAREST).save(
    os.path.join(DEBUG_DIR, "00_barra_completa_4x.png"))
log(f"Barra completa salvata ({w}x{h}px)")

# ---------------------------------------------------------------------------
# Per ogni zona: crop raw + 4x + maschera + OCR raw
# ---------------------------------------------------------------------------
log("")
log("=" * 55)
log("  CROP + OCR per zona")
log("=" * 55)

barra = pil_img.crop(_ZONA_BARRA_COMPLETA)

for nome, info in ZONE.items():
    x1, y1, x2, y2 = info["zona"]
    crop = barra.crop((
        x1 - _BARRA_X0, y1 - _BARRA_Y0,
        x2 - _BARRA_X0, y2 - _BARRA_Y0,
    ))
    w, h = crop.size
    crop4x = crop.resize((w*4, h*4), Image.LANCZOS)

    # Salva crop raw e 4x
    crop.save(os.path.join(DEBUG_DIR, f"{nome}_raw.png"))
    crop4x.save(os.path.join(DEBUG_DIR, f"{nome}_4x.png"))

    # Maschera bianca
    mask = _maschera_bianca(crop4x, info["taglio"])
    mask.save(os.path.join(DEBUG_DIR, f"{nome}_mask.png"))

    # OCR raw
    if info["tipo"] == "diamanti":
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,."
    else:
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789.MKB"

    testo = pytesseract.image_to_string(mask, config=cfg).strip()

    # Parsing
    if info["tipo"] == "diamanti":
        valore = _parse_diamanti(testo)
    else:
        valore = _parse_valore(testo)

    # Conta pixel bianchi nella maschera
    arr_mask = np.array(mask)
    px_bianchi = int(np.sum(arr_mask > 0))

    log(f"{nome:10} | raw='{testo}' | valore={valore} | px_bianchi={px_bianchi}")

log("")
log(f"Crop salvati in: {DEBUG_DIR}")
log("Aprire le immagini *_mask.png per verificare il preprocessing.")
log("Se px_bianchi=0 le zone sono sbagliate o il testo non e' bianco.")
