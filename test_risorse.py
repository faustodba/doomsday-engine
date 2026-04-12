# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_risorse.py
#
#  Test runtime RT-04:
#    Passo 1 — Screenshot HOME
#    Passo 2 — Lettura 5 risorse (pomodoro, legno, acciaio, petrolio, diamanti)
#    Passo 3 — Verifica valori plausibili (> 0)
#
#  Prerequisiti:
#    - FAU_00 avviata in MuMu con Doomsday aperto sulla HOME
#    - ADB connesso
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_risorse.py
#
#  Output: stampa valori letti + salva screenshot in debug_nav/
# ==============================================================================

import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import cv2

from core.device import AdbDevice
from shared.ocr_helpers import ocr_risorse

ADB_HOST  = "127.0.0.1"
ADB_PORT  = 16384
DEBUG_DIR = os.path.join(ROOT, "debug_nav")
os.makedirs(DEBUG_DIR, exist_ok=True)

log_lines = []

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_lines.append(line)

def separa(titolo):
    log("")
    log("=" * 55)
    log(f"  {titolo}")
    log("=" * 55)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
separa("SETUP")
log(f"Connessione ADB: {ADB_HOST}:{ADB_PORT}")
device = AdbDevice(host=ADB_HOST, port=ADB_PORT, name="FAU_00")

# ---------------------------------------------------------------------------
# Passo 1 — Screenshot
# ---------------------------------------------------------------------------
separa("PASSO 1 — Screenshot HOME")
shot = device.screenshot()
if shot is None:
    log("FAIL: screenshot None — ADB non risponde")
    sys.exit(1)

path = os.path.join(DEBUG_DIR, "rt04_screenshot.png")
cv2.imwrite(path, shot.frame)
log(f"Screenshot salvato: {path}")
log(f"Dimensioni: {shot.width}x{shot.height}")

# ---------------------------------------------------------------------------
# Passo 2 — Lettura risorse
# ---------------------------------------------------------------------------
separa("PASSO 2 — Lettura risorse")
risorse = ocr_risorse(shot)
log(f"Pomodoro : {risorse.pomodoro:>15,.0f}" if risorse.pomodoro > 0 else "Pomodoro : FAIL")
log(f"Legno    : {risorse.legno:>15,.0f}"    if risorse.legno    > 0 else "Legno    : FAIL")
log(f"Acciaio  : {risorse.acciaio:>15,.0f}"  if risorse.acciaio  > 0 else "Acciaio  : FAIL")
log(f"Petrolio : {risorse.petrolio:>15,.0f}" if risorse.petrolio > 0 else "Petrolio : FAIL")
log(f"Diamanti : {risorse.diamanti:>15,}"    if risorse.diamanti > 0 else "Diamanti : FAIL")

# ---------------------------------------------------------------------------
# Passo 3 — Verifica
# ---------------------------------------------------------------------------
separa("PASSO 3 — Verifica")
risultati = {
    "pomodoro": risorse.pomodoro > 0,
    "legno":    risorse.legno    > 0,
    "acciaio":  risorse.acciaio  > 0,
    "petrolio": risorse.petrolio > 0,
    "diamanti": risorse.diamanti > 0,
}
for nome, ok in risultati.items():
    log(f"  [{'OK' if ok else 'XX'}] {nome}: {'PASS' if ok else 'FAIL'}")

separa("RIEPILOGO RT-04")
if all(risultati.values()):
    log("RT-04 SUPERATO — tutte le risorse lette correttamente")
else:
    falliti = [n for n, ok in risultati.items() if not ok]
    log(f"RT-04 PARZIALE — falliti: {falliti}")
    log("  Controllare zone in ocr_helpers.py ZONE_RISORSE_V5")

log_path = os.path.join(DEBUG_DIR, "test_risorse.log")
with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
log(f"Log salvato: {log_path}")
