"""
==============================================================================
 DOOMSDAY ENGINE V6 — tool/calibra_slot_ocr.py
 
 Tool standalone per calibrazione OCR contatore slot raccoglitori.
 
 Uso:
   python calibra_slot_ocr.py <screenshot.png>
   python calibra_slot_ocr.py  (usa screenshot ADB live da FAU_00)
 
 Il tool:
   1. Mostra la zona del contatore ritagliata e upscalata
   2. Testa tutte le combinazioni di parametri Tesseract
   3. Mostra i risultati ordinati per affidabilità
   4. Permette di modificare la zona OCR interattivamente
 
 Output: stampa i parametri migliori da copiare in ocr_helpers.py
==============================================================================
"""

import sys
import os
import re
import itertools
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = os.environ.get(
        "TESSERACT_EXE",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    TESS_OK = True
except ImportError:
    print("ERRORE: pytesseract non installato")
    sys.exit(1)

# ==============================================================================
# Parametri di calibrazione da esplorare
# ==============================================================================

# Parametro 1: zona OCR (x1,y1,x2,y2) — varianti attorno alla zona base
ZONE_CANDIDATE = [
    (890, 117, 946, 141),   # base V5
    (888, 115, 948, 143),   # +2px margine
    (892, 119, 944, 139),   # -2px margine
    (885, 112, 950, 145),   # +5px margine
    (890, 117, 930, 141),   # solo metà sx (tronca DX)
    (900, 117, 946, 141),   # taglia 10px sx
    (890, 117, 946, 135),   # taglia 6px basso
]

# Parametro 2: PSM Tesseract
PSM_CANDIDATI = [6, 7, 8, 10, 11, 13]

# Parametro 3: upscale factor
SCALE_CANDIDATI = [2, 3, 4, 6, 8]

# Parametro 4: preprocessing
PREPROC_CANDIDATI = [
    "maschera_bianca",   # pixel bianchi su nero (V5)
    "otsu",              # binarizzazione Otsu
    "thresh_130",        # soglia fissa 130
    "thresh_150",        # soglia fissa 150
    "thresh_170",        # soglia fissa 170
    "invert_otsu",       # Otsu + invert
    "contrasto",         # contrasto 2x + Otsu
]

# Parametro 5: whitelist caratteri
WHITELIST_CANDIDATI = [
    "0123456789/",
    "0123456789",
    "0123456789/ ",
    "0123456789/|",
]

# Parametro 6: taglio sx (esclude icona frecce ▲▼)
TAGLIO_SX_CANDIDATI = [0, 5, 10, 15, 20]


# ==============================================================================
# Preprocessing
# ==============================================================================

def _maschera_bianca(img_pil: Image.Image, taglio_sx: int = 0) -> Image.Image:
    arr = np.array(img_pil).astype(int)
    h, w = arr.shape[:2]
    pad = 20
    mask = np.zeros((h + pad*2, w + pad*2), dtype=np.uint8)
    for y in range(h):
        for x in range(taglio_sx, w):
            if arr[y,x,0] > 140 and arr[y,x,1] > 140 and arr[y,x,2] > 140:
                mask[y+pad, x-taglio_sx+pad] = 255
    return Image.fromarray(mask)


def applica_preprocessing(crop_pil: Image.Image, metodo: str,
                           scale: int, taglio_sx: int) -> Image.Image:
    w, h = crop_pil.size

    if metodo == "maschera_bianca":
        crop_big = crop_pil.resize((w*scale, h*scale), Image.LANCZOS)
        return _maschera_bianca(crop_big, taglio_sx * scale)

    # Per gli altri metodi: converti in grayscale e scala
    crop_big = crop_pil.resize((w*scale, h*scale), Image.LANCZOS)
    arr = np.array(crop_big)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    if taglio_sx > 0:
        gray = gray[:, taglio_sx*scale:]

    if metodo == "otsu":
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif metodo == "invert_otsu":
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = cv2.bitwise_not(th)
    elif metodo.startswith("thresh_"):
        val = int(metodo.split("_")[1])
        _, th = cv2.threshold(gray, val, 255, cv2.THRESH_BINARY)
    elif metodo == "contrasto":
        pil_g = Image.fromarray(gray)
        pil_g = ImageEnhance.Contrast(pil_g).enhance(2.0)
        arr2 = np.array(pil_g)
        _, th = cv2.threshold(arr2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        th = gray

    return Image.fromarray(th)


# ==============================================================================
# OCR singolo test
# ==============================================================================

def testa_combinazione(img_pil_full: Image.Image, zona: tuple,
                        psm: int, scale: int, preproc: str,
                        whitelist: str, taglio_sx: int) -> tuple:
    """
    Ritorna (testo_letto, attive, totale, ok) dove ok=True se pattern X/Y trovato.
    """
    try:
        x1, y1, x2, y2 = zona
        crop = img_pil_full.crop((x1, y1, x2, y2))
        processed = applica_preprocessing(crop, preproc, scale, taglio_sx)
        cfg = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
        testo = pytesseract.image_to_string(processed, config=cfg).strip()
        m = re.search(r'(\d+)/(\d+)', testo)
        if m:
            return (testo, int(m.group(1)), int(m.group(2)), True)
        return (testo, -1, -1, False)
    except Exception as e:
        return (str(e), -1, -1, False)


# ==============================================================================
# Main
# ==============================================================================

def carica_screenshot(path: str | None) -> Image.Image:
    if path and os.path.exists(path):
        img = cv2.imread(path)
        print(f"Screenshot: {path} ({img.shape[1]}x{img.shape[0]})")
    else:
        print("Screenshot non trovata — tentativo ADB live...")
        import subprocess
        import tempfile
        adb = os.environ.get("MUMU_ADB_PATH",
              r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe")
        tmp = os.path.join(tempfile.gettempdir(), "calibra_slot.png")
        remote = "/sdcard/calibra_slot.png"
        subprocess.run([adb, "-s", "127.0.0.1:16384", "shell",
                        f"screencap -p {remote}"], capture_output=True, timeout=15)
        subprocess.run([adb, "-s", "127.0.0.1:16384", "pull", remote, tmp],
                       capture_output=True, timeout=15)
        if not os.path.exists(tmp):
            print("ERRORE: impossibile acquisire screenshot ADB")
            sys.exit(1)
        img = cv2.imread(tmp)
        print(f"Screenshot ADB: {img.shape[1]}x{img.shape[0]}")

    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def salva_debug(img_pil: Image.Image, zona: tuple,
                preproc: str, scale: int, taglio_sx: int,
                label: str, out_dir: str = ".") -> str:
    x1, y1, x2, y2 = zona
    crop = img_pil.crop((x1, y1, x2, y2))
    processed = applica_preprocessing(crop, preproc, scale, taglio_sx)
    fname = os.path.join(out_dir, f"debug_{label}.png")
    processed.save(fname)
    return fname


def analisi_pixel_colonne(img_pil: Image.Image, zona: tuple):
    """Stampa mappa pixel bianchi per colonna — utile per individuare cifre."""
    x1, y1, x2, y2 = zona
    crop = img_pil.crop((x1, y1, x2, y2))
    arr = np.array(crop).astype(int)
    print(f"\nAnalisi pixel bianchi per colonna (zona {zona}):")
    for col in range(arr.shape[1]):
        n = int(np.sum((arr[:,col,0]>140)&(arr[:,col,1]>140)&(arr[:,col,2]>140)))
        bar = "#" * n
        print(f"  col {col:2d} (x={x1+col}): {n:2d} {bar}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    img_pil = carica_screenshot(path)

    print("\n" + "="*70)
    print("  CALIBRAZIONE OCR CONTATORE SLOT")
    print("="*70)

    # Analisi pixel colonne sulla zona base
    analisi_pixel_colonne(img_pil, (890, 117, 946, 141))

    print("\nAvvio test combinazioni...")
    print(f"  Zone:        {len(ZONE_CANDIDATE)}")
    print(f"  PSM:         {len(PSM_CANDIDATI)}")
    print(f"  Scale:       {len(SCALE_CANDIDATI)}")
    print(f"  Preproc:     {len(PREPROC_CANDIDATI)}")
    print(f"  Whitelist:   {len(WHITELIST_CANDIDATI)}")
    print(f"  Taglio sx:   {len(TAGLIO_SX_CANDIDATI)}")
    totale_combinazioni = (len(ZONE_CANDIDATE) * len(PSM_CANDIDATI) *
                           len(SCALE_CANDIDATI) * len(PREPROC_CANDIDATI) *
                           len(WHITELIST_CANDIDATI) * len(TAGLIO_SX_CANDIDATI))
    print(f"  TOTALE:      {totale_combinazioni} combinazioni")
    print()

    risultati_ok = []
    risultati_fail = []
    n_testati = 0

    for zona, psm, scale, preproc, wl, taglio in itertools.product(
        ZONE_CANDIDATE, PSM_CANDIDATI, SCALE_CANDIDATI,
        PREPROC_CANDIDATI, WHITELIST_CANDIDATI, TAGLIO_SX_CANDIDATI
    ):
        testo, attive, totale, ok = testa_combinazione(
            img_pil, zona, psm, scale, preproc, wl, taglio)
        n_testati += 1

        entry = {
            "zona": zona, "psm": psm, "scale": scale,
            "preproc": preproc, "whitelist": wl, "taglio_sx": taglio,
            "testo": testo, "attive": attive, "totale": totale,
        }

        if ok:
            risultati_ok.append(entry)
        else:
            risultati_fail.append(entry)

        if n_testati % 500 == 0:
            print(f"  {n_testati}/{totale_combinazioni} testati "
                  f"({len(risultati_ok)} con pattern X/Y)...", end="\r")

    print(f"\n  Completato: {n_testati} testati, "
          f"{len(risultati_ok)} con pattern X/Y trovato")

    # ==============================================================================
    # Report risultati
    # ==============================================================================
    print("\n" + "="*70)
    print("  RISULTATI — combinazioni che leggono pattern X/Y")
    print("="*70)

    if not risultati_ok:
        print("\nNESSUNA combinazione ha letto un pattern X/Y.")
        print("Possibili cause:")
        print("  - Screenshot non contiene il contatore (0 slot attivi?)")
        print("  - Tesseract non installato correttamente")
        print("  - Zone fuori dalla schermata 960x540")
    else:
        # Raggruppa per (attive, totale) letti
        from collections import defaultdict
        per_valore: dict = defaultdict(list)
        for r in risultati_ok:
            per_valore[(r["attive"], r["totale"])].append(r)

        print(f"\nValori letti distinti: {list(per_valore.keys())}")
        print()

        for (attive, totale), gruppo in sorted(per_valore.items(),
                                                key=lambda x: -len(x[1])):
            print(f"--- {attive}/{totale} — {len(gruppo)} combinazioni ---")
            # Mostra le prime 5 per questo valore
            for r in gruppo[:5]:
                print(f"  zona={r['zona']} psm={r['psm']} scale={r['scale']} "
                      f"preproc={r['preproc']!r} taglio={r['taglio_sx']} "
                      f"wl={r['whitelist']!r}")
                print(f"    → raw='{r['testo']}'")
            if len(gruppo) > 5:
                print(f"  ... e altri {len(gruppo)-5}")
            print()

        # Best config: quella con più occorrenze dello stesso valore
        best_valore = max(per_valore.keys(), key=lambda k: len(per_valore[k]))
        best = per_valore[best_valore][0]

        print("="*70)
        print("  CONFIGURAZIONE CONSIGLIATA")
        print("="*70)
        print(f"""
  Valore letto:  {best['attive']}/{best['totale']}
  Zona:          {best['zona']}
  PSM:           {best['psm']}
  Scale:         {best['scale']}
  Preprocessing: {best['preproc']}
  Whitelist:     {best['whitelist']!r}
  Taglio sx:     {best['taglio_sx']}

  Da copiare in ocr_helpers.py:
  _ZONA_TESTO_SLOT = {best['zona']}
  # psm={best['psm']} scale={best['scale']} preproc={best['preproc']}
""")

        # Salva debug della best config
        fname = salva_debug(img_pil, best["zona"], best["preproc"],
                            best["scale"], best["taglio_sx"], "best")
        print(f"  Immagine debug salvata: {fname}")

    # Salva anche fail interessanti (testo non vuoto ma senza pattern)
    fail_con_testo = [r for r in risultati_fail if r["testo"]]
    if fail_con_testo:
        print(f"\n  ({len(fail_con_testo)} combinazioni hanno letto testo "
              f"ma senza pattern X/Y — prime 10:)")
        for r in fail_con_testo[:10]:
            print(f"  psm={r['psm']} scale={r['scale']} "
                  f"preproc={r['preproc']!r} → '{r['testo']}'")


if __name__ == "__main__":
    main()
