# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_bag_ocr.py
#
#  Test standalone OCR pannello BAG RESOURCE.
#  Coordinate calibrate da misurazioni reali 14/04/2026.
#
#  Uso:
#    1. Apri BAG → RESOURCE nel gioco
#    2. python test_bag_ocr.py --porta 16384
#    3. Con scroll: python test_bag_ocr.py --porta 16384 --scroll 2
# ==============================================================================

import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = os.environ.get(
        "TESSERACT_EXE",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    _TESS_OK = True
except ImportError:
    _TESS_OK = False
    print("[WARN] pytesseract non disponibile")

# ---------------------------------------------------------------------------
# Coordinate calibrate (960x540)
# ---------------------------------------------------------------------------

# Griglia: spigolo (150,135), box 82x82, gap 22px
GRIGLIA_COL_X  = [191, 295, 399, 503, 607]   # centri colonne
GRIGLIA_RIGA_Y = [176, 280, 384, 488]         # centri righe

# Pannello destra
PANNELLO_TITOLO  = (665,  80, 824, 124)   # "150,000 Wood"
PANNELLO_OWNED   = (664, 175, 796, 206)   # "Owned: 33"
PANNELLO_GRANTS  = (663, 206, 839, 246)   # "Grants 150,000 Wood."
CAMPO_QTY_ZONA   = (678, 428, 933, 462)   # - 1 + MAX (zona completa)
USE_BTN_ZONA     = (707, 476, 905, 508)   # USE button

# Centro USE e campo input
USE_BTN_XY  = (806, 492)
CAMPO_QTY_XY = (738, 445)
OK_XY        = (879, 509)

DELAY_TAP_ICONA = 1.0

# Mapping grants → risorsa
_GRANTS_MAP = [
    ("food",  "pomodoro"),
    ("wood",  "legno"),
    ("steel", "acciaio"),
    ("oil",   "petrolio"),
]


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def ocr_zona(frame, zona: tuple) -> str:
    x1, y1, x2, y2 = zona
    if not _TESS_OK:
        return "[pytesseract N/D]"
    try:
        from PIL import Image
        roi = frame[y1:y2, x1:x2]
        pil = Image.fromarray(roi[:, :, ::-1])
        w, h = pil.size
        if w == 0 or h == 0:
            return "[zona vuota]"
        pil4x = pil.resize((w * 4, h * 4), Image.LANCZOS)
        return pytesseract.image_to_string(pil4x, config="--psm 6").strip()
    except Exception as e:
        return f"[ERR: {e}]"


def get_frame(screen):
    frame = getattr(screen, "frame", None)
    if frame is None:
        import numpy as np
        if isinstance(screen, np.ndarray):
            frame = screen
    return frame


def sep(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_owned(testo: str) -> int:
    t = testo.replace(",", "")
    m = re.search(r"owned[:\s]+(\d+)", t, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else -1


def parse_grants(testo: str) -> tuple:
    tl = testo.lower()
    if " or " in tl:
        return ("MISTO", 0)
    risorsa = ""
    for kw, nome in _GRANTS_MAP:
        if kw in tl:
            risorsa = nome
            break
    if not risorsa:
        return ("", 0)
    nums = re.findall(r"\d+", testo.replace(",", "").replace(".", ""))
    return (risorsa, int(nums[0]) if nums else 0)


def parse_titolo(testo: str) -> tuple:
    """Estrae pezzatura e risorsa dal titolo (es. '150,000 Wood')."""
    tl = testo.lower()
    risorsa = ""
    for kw, nome in _GRANTS_MAP:
        if kw in tl:
            risorsa = nome
            break
    nums = re.findall(r"\d+", testo.replace(",", "").replace(".", ""))
    pezzatura = int(nums[0]) if nums else 0
    return (risorsa, pezzatura)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test OCR BAG RESOURCE")
    parser.add_argument("--porta",  type=int, default=16384)
    parser.add_argument("--righe",  type=int, default=4)
    parser.add_argument("--scroll", type=int, default=0,
                        help="Swipe giù prima di iniziare")
    args = parser.parse_args()

    sep(f"TEST OCR BAG — porta {args.porta}")
    print("PREREQUISITO: BAG → RESOURCE già aperto")

    try:
        from core.device import AdbDevice
        device = AdbDevice(host="127.0.0.1", port=args.porta)
        print(f"OK: connesso 127.0.0.1:{args.porta}")
    except Exception as e:
        print(f"[ERRORE] {e}"); sys.exit(1)

    if args.scroll > 0:
        print(f"Scroll giù {args.scroll}×...")
        for _ in range(args.scroll):
            device.swipe(480, 420, 480, 180, duration_ms=400)
            time.sleep(0.8)

    n_righe  = min(args.righe, len(GRIGLIA_RIGA_Y))
    risultati = []

    for i_riga in range(n_righe):
        y = GRIGLIA_RIGA_Y[i_riga]
        sep(f"RIGA {i_riga+1} (Y={y})")

        for i_col, x in enumerate(GRIGLIA_COL_X):
            print(f"\n  --- col={i_col+1} ({x},{y}) ---")

            device.tap(x, y)
            time.sleep(DELAY_TAP_ICONA)

            screen = device.screenshot()
            if screen is None:
                print("  [ERR] screenshot fallito"); continue
            frame = get_frame(screen)
            if frame is None:
                print("  [ERR] frame N/D"); continue

            t_titolo = ocr_zona(frame, PANNELLO_TITOLO)
            t_owned  = ocr_zona(frame, PANNELLO_OWNED)
            t_grants = ocr_zona(frame, PANNELLO_GRANTS)

            print(f"  Titolo raw : {repr(t_titolo)}")
            print(f"  Owned  raw : {repr(t_owned)}")
            print(f"  Grants raw : {repr(t_grants)}")

            # Parsing — usa titolo come fonte primaria, grants come fallback
            risorsa_t, pezzat_t = parse_titolo(t_titolo)
            risorsa_g, pezzat_g = parse_grants(t_grants)
            owned = parse_owned(t_owned)

            # Preferisce titolo se leggibile
            risorsa   = risorsa_t or risorsa_g
            pezzatura = pezzat_t  or pezzat_g

            if t_grants and " or " in t_grants.lower():
                risorsa = "MISTO"

            print(f"  → risorsa={risorsa or 'N/D':10s} "
                  f"pezzatura={pezzatura:>12,}  owned={owned}")

            risultati.append({
                "col": i_col+1, "riga": i_riga+1,
                "x": x, "y": y,
                "titolo_raw": t_titolo,
                "owned_raw":  t_owned,
                "grants_raw": t_grants,
                "risorsa": risorsa,
                "pezzatura": pezzatura,
                "owned": owned,
            })

    # Riepilogo
    sep("RIEPILOGO")
    ok    = [r for r in risultati
             if r["risorsa"] and r["risorsa"] != "MISTO" and r["owned"] >= 0]
    misto = [r for r in risultati if r["risorsa"] == "MISTO"]
    nd    = [r for r in risultati if not r["risorsa"]]

    print(f"Totale icone : {len(risultati)}")
    print(f"  OK         : {len(ok)}")
    print(f"  Misto/skip : {len(misto)}")
    print(f"  N/D        : {len(nd)}")

    if ok:
        print("\nLetture OK:")
        for r in ok:
            print(f"  ({r['x']},{r['y']}) {r['risorsa']:10s} "
                  f"{r['pezzatura']:>12,}  owned={r['owned']}")

    if nd:
        print("\nNon leggibili:")
        for r in nd:
            print(f"  ({r['x']},{r['y']}) "
                  f"titolo={repr(r['titolo_raw'])[:40]}  "
                  f"grants={repr(r['grants_raw'])[:40]}")

    pct = 100*len(ok)//len(risultati) if risultati else 0
    print(f"\nAffidabilità risorse: {len(ok)}/{len(risultati)} ({pct}%)")
    risorsa_ok = [r for r in ok if r['risorsa'] in
                  ['pomodoro','legno','acciaio','petrolio']]
    print(f"Di cui risorse target: {len(risorsa_ok)}")


if __name__ == "__main__":
    main()
