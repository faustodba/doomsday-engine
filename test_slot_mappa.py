# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_slot_mappa.py
#
#  Test diagnostico OCR contatore slot su FAU_00.
#  Eseguire da C:\doomsday-engine:
#    python test_slot_mappa.py
#
#  Output:
#    - Risultato leggi_contatore_slot() (pipeline completa)
#    - Risultato _ocr_slot_thresh130() (fallback parsed)
#    - Testo grezzo Tesseract dal preprocessing thresh_130 psm=6 scale=2
#    - debug_crop_slot.png  — crop zona (890,117,946,141) salvato su disco
# ==============================================================================

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cv2
import numpy as np
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = os.environ.get(
    "TESSERACT_EXE",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

# ------------------------------------------------------------------------------
# Costanti
# ------------------------------------------------------------------------------
ADB_HOST   = "127.0.0.1"
ADB_PORT   = 16384          # FAU_00
ZONA_SLOT  = (890, 117, 946, 141)
TOTALE_NOTO = 4             # max squadre default FAU_00
DEBUG_CROP  = os.path.join(ROOT, "debug_crop_slot.png")
DEBUG_CROP_THRESH = os.path.join(ROOT, "debug_crop_slot_thresh130.png")


# ------------------------------------------------------------------------------
# Helpers di stampa
# ------------------------------------------------------------------------------
def sep(titolo: str) -> None:
    print()
    print("=" * 60)
    print(f"  {titolo}")
    print("=" * 60)


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def main() -> None:
    # ── 1. Connessione ADB ──────────────────────────────────────────────────
    sep("1. Connessione ADB")
    print(f"  host={ADB_HOST}  porta={ADB_PORT}")

    try:
        from core.device import AdbDevice
        device = AdbDevice(host=ADB_HOST, port=ADB_PORT)
        print("  AdbDevice OK")
    except Exception as exc:
        print(f"  [ERRORE] AdbDevice: {exc}")
        sys.exit(1)

    # ── 2. Screenshot ───────────────────────────────────────────────────────
    sep("2. Screenshot")
    screen = device.screenshot()
    if screen is None:
        print("  [ERRORE] screenshot() ha restituito None")
        sys.exit(1)

    frame_bgr = screen.frame
    h_frame, w_frame = frame_bgr.shape[:2]
    print(f"  Screenshot acquisito: {w_frame}x{h_frame} px")

    # ── 3. leggi_contatore_slot (pipeline completa) ─────────────────────────
    sep("3. leggi_contatore_slot()")
    try:
        from shared.ocr_helpers import leggi_contatore_slot
        attive, totale = leggi_contatore_slot(screen, totale_noto=TOTALE_NOTO)
        if attive == -1 or totale == -1:
            print(f"  risultato : ({attive}, {totale})  → lettura fallita")
        else:
            liberi = max(0, totale - attive)
            print(f"  risultato : attive={attive}  totale={totale}  → slot liberi={liberi}")
    except Exception as exc:
        print(f"  [ERRORE] leggi_contatore_slot: {exc}")
        import traceback
        traceback.print_exc()

    # ── 4. Crop zona e salvataggio ──────────────────────────────────────────
    sep("4. Crop zona ZONA_SLOT e salvataggio")
    x1, y1, x2, y2 = ZONA_SLOT
    pil_full  = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    crop_pil  = pil_full.crop((x1, y1, x2, y2))

    crop_pil.save(DEBUG_CROP)
    print(f"  Zona  : {ZONA_SLOT}")
    print(f"  Size  : {crop_pil.size} px")
    print(f"  Saved : {DEBUG_CROP}")

    # ── 5. _ocr_slot_thresh130 (fallback parsed) ────────────────────────────
    sep("5. _ocr_slot_thresh130() — risultato parsed")
    try:
        from shared.ocr_helpers import _ocr_slot_thresh130
        risultato_fb = _ocr_slot_thresh130(crop_pil)
        print(f"  risultato : {risultato_fb}")
        if risultato_fb == (-1, -1):
            print("  → fallback NON ha trovato pattern X/Y")
        else:
            print(f"  → fallback ha letto attive={risultato_fb[0]}  totale={risultato_fb[1]}")
    except Exception as exc:
        print(f"  [ERRORE] _ocr_slot_thresh130: {exc}")
        import traceback
        traceback.print_exc()

    # ── 6. Testo grezzo Tesseract — thresh_130 psm=6 scale=2 ───────────────
    sep("6. Testo grezzo Tesseract (thresh=130, psm=6, scale=2)")
    try:
        w, h    = crop_pil.size
        arr_rgb = np.array(crop_pil)
        gray    = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2GRAY)
        gray2   = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray2, 130, 255, cv2.THRESH_BINARY)

        # Salva l'immagine preprocessata per ispezione visiva
        Image.fromarray(binary).save(DEBUG_CROP_THRESH)
        print(f"  Preprocessed saved : {DEBUG_CROP_THRESH}")

        cfg   = "--psm 6 -c tessedit_char_whitelist=0123456789/"
        testo = pytesseract.image_to_string(binary, config=cfg).strip()
        print(f"  testo raw : {repr(testo)}")

        m = re.search(r"(\d+)/(\d+)", testo)
        if m:
            print(f"  match X/Y : attive={m.group(1)}  totale={m.group(2)}")
        else:
            print("  match X/Y : nessuno — pattern X/Y non trovato nel testo grezzo")

        # Prova anche psm=7 e psm=13 per confronto
        for psm_alt in (7, 13):
            cfg_alt   = f"--psm {psm_alt} -c tessedit_char_whitelist=0123456789/"
            testo_alt = pytesseract.image_to_string(binary, config=cfg_alt).strip()
            m_alt     = re.search(r"(\d+)/(\d+)", testo_alt)
            print(f"  psm={psm_alt} raw={repr(testo_alt)}  match={m_alt.groups() if m_alt else None}")

    except Exception as exc:
        print(f"  [ERRORE] OCR grezzo: {exc}")
        import traceback
        traceback.print_exc()

    # ── 7. Pixel check (pre-check maschera_bianca) ──────────────────────────
    sep("7. Pre-check pixel bianchi (soglia 140)")
    try:
        arr_check  = np.array(crop_pil).astype(int)
        px_bianchi = int(np.sum(
            (arr_check[:, :, 0] > 140) &
            (arr_check[:, :, 1] > 140) &
            (arr_check[:, :, 2] > 140)
        ))
        print(f"  pixel bianchi (R,G,B > 140) : {px_bianchi}")
        print(f"  soglia minima               : 15")
        if px_bianchi < 15:
            print("  → pre-check FALLISCE  → fallback thresh_130 verrebbe attivato")
        else:
            print("  → pre-check PASSA  → pipeline maschera_bianca usata")
    except Exception as exc:
        print(f"  [ERRORE] pixel check: {exc}")

    sep("FINE TEST")
    print(f"  debug_crop_slot.png          → {DEBUG_CROP}")
    print(f"  debug_crop_slot_thresh130.png → {DEBUG_CROP_THRESH}")
    print()


if __name__ == "__main__":
    main()
