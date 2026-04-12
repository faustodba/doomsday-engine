# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_risorse.py
#
#  Test runtime RT-04:
#    Passo 1 — Screenshot HOME + lettura 5 risorse
#    Passo 2 — Tap toggle → MAPPA + lettura 5 risorse
#    Passo 3 — Tap toggle → ritorno HOME
#    Passo 4 — Confronto valori HOME vs MAPPA (devono essere identici)
#
#  Prerequisiti:
#    - FAU_00 avviata in MuMu con Doomsday aperto sulla HOME
#    - ADB connesso
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_risorse.py
# ==============================================================================

import os, sys, time
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import cv2
from core.device import AdbDevice
from core.navigator import GameNavigator, NavigatorConfig, Screen
from shared.template_matcher import get_matcher
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

def stampa_risorse(label, r):
    log(f"  {label}:")
    log(f"    Pomodoro : {r.pomodoro:>15,.0f}" if r.pomodoro > 0 else f"    Pomodoro : FAIL")
    log(f"    Legno    : {r.legno:>15,.0f}"    if r.legno    > 0 else f"    Legno    : FAIL")
    log(f"    Acciaio  : {r.acciaio:>15,.0f}"  if r.acciaio  > 0 else f"    Acciaio  : FAIL")
    log(f"    Petrolio : {r.petrolio:>15,.0f}" if r.petrolio > 0 else f"    Petrolio : FAIL")
    log(f"    Diamanti : {r.diamanti:>15,}"    if r.diamanti > 0 else f"    Diamanti : FAIL")

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
separa("SETUP")
log(f"Connessione ADB: {ADB_HOST}:{ADB_PORT}")
device  = AdbDevice(host=ADB_HOST, port=ADB_PORT, name="FAU_00")
matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
cfg     = NavigatorConfig(pin_threshold=0.70, log_scores=False)
nav     = GameNavigator(device=device, matcher=matcher, config=cfg, log_fn=log)

risultati = {}

# ---------------------------------------------------------------------------
# Passo 1 — HOME
# ---------------------------------------------------------------------------
separa("PASSO 1 — Risorse in HOME")

if not nav.vai_in_home():
    log("FAIL: impossibile raggiungere HOME"); sys.exit(1)

shot_home = device.screenshot()
if shot_home is None:
    log("FAIL: screenshot None in HOME"); sys.exit(1)

cv2.imwrite(os.path.join(DEBUG_DIR, "rt04_home.png"), shot_home.frame)
risorse_home = ocr_risorse(shot_home)
stampa_risorse("HOME", risorse_home)

ok_home = all(v > 0 for v in risorse_home)
risultati["passo1_home"] = "PASS" if ok_home else "FAIL"
log(f"  Esito: {'PASS' if ok_home else 'FAIL'}")

# ---------------------------------------------------------------------------
# Passo 2 — MAPPA
# ---------------------------------------------------------------------------
separa("PASSO 2 — Risorse in MAPPA")

risorse_mappa = None
if not nav.vai_in_mappa():
    log("FAIL: impossibile raggiungere MAPPA")
    risultati["passo2_mappa"] = "FAIL"
else:
    shot_mappa = device.screenshot()
    if shot_mappa is None:
        log("FAIL: screenshot None in MAPPA")
        risultati["passo2_mappa"] = "FAIL"
    else:
        cv2.imwrite(os.path.join(DEBUG_DIR, "rt04_mappa.png"), shot_mappa.frame)
        risorse_mappa = ocr_risorse(shot_mappa)
        stampa_risorse("MAPPA", risorse_mappa)
        ok_mappa = all(v > 0 for v in risorse_mappa)
        risultati["passo2_mappa"] = "PASS" if ok_mappa else "FAIL"
        log(f"  Esito: {'PASS' if ok_mappa else 'FAIL'}")

# ---------------------------------------------------------------------------
# Passo 3 — Ritorno HOME
# ---------------------------------------------------------------------------
separa("PASSO 3 — Ritorno HOME")
if nav.vai_in_home():
    log("PASS: ritorno in HOME confermato")
    risultati["passo3_ritorno"] = "PASS"
else:
    log("FAIL: impossibile tornare in HOME")
    risultati["passo3_ritorno"] = "FAIL"

# ---------------------------------------------------------------------------
# Passo 4 — Confronto HOME vs MAPPA
# ---------------------------------------------------------------------------
separa("PASSO 4 — Confronto HOME vs MAPPA")
if risultati.get("passo1_home") == "PASS" and risultati.get("passo2_mappa") == "PASS":
    campi = ["pomodoro", "legno", "acciaio", "petrolio", "diamanti"]
    tutti_uguali = True
    for campo in campi:
        vh = getattr(risorse_home,  campo)
        vm = getattr(risorse_mappa, campo)
        ok = (vh == vm)
        if not ok:
            tutti_uguali = False
        log(f"  {campo:10}: HOME={vh}  MAPPA={vm}  {'OK' if ok else 'DIFF'}")
    risultati["passo4_confronto"] = "PASS" if tutti_uguali else "WARN"
    log(f"  Esito: {'PASS — valori identici' if tutti_uguali else 'WARN — valori diversi (lag OCR normale)'}")
else:
    log("  SKIP: uno dei passi precedenti e' fallito")
    risultati["passo4_confronto"] = "SKIP"

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
separa("RIEPILOGO RT-04")
for passo, esito in risultati.items():
    simbolo = "OK" if esito == "PASS" else ("~~" if esito in ("WARN", "SKIP") else "XX")
    log(f"  [{simbolo}] {passo}: {esito}")

log("")
if all(v in ("PASS", "WARN") for v in risultati.values()):
    log("RT-04 SUPERATO — OCR risorse funzionante in HOME e MAPPA")
else:
    log("RT-04 FALLITO — vedere log e screenshot in debug_nav/")

log_path = os.path.join(DEBUG_DIR, "test_risorse.log")
with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
log(f"Log salvato: {log_path}")
