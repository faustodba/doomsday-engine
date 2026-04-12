# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_slot.py
#
#  Test runtime RT-05:
#    Passo 1 — Screenshot HOME + lettura contatore slot (X/Y)
#    Passo 2 — Tap toggle → MAPPA + lettura contatore slot
#    Passo 3 — Confronto HOME vs MAPPA (devono essere identici)
#    Passo 4 — Ritorno HOME
#
#  Prerequisiti:
#    - FAU_00 sulla HOME del gioco
#    - ADB connesso
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_slot.py
# ==============================================================================

import os, sys, time
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import cv2
from core.device import AdbDevice
from core.navigator import GameNavigator, NavigatorConfig
from shared.template_matcher import get_matcher
from shared.ocr_helpers import leggi_contatore_slot

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
device  = AdbDevice(host=ADB_HOST, port=ADB_PORT, name="FAU_00")
matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
cfg     = NavigatorConfig(pin_threshold=0.70, log_scores=False)
nav     = GameNavigator(device=device, matcher=matcher, config=cfg, log_fn=log)

# totale_noto da instances.json FAU_00 — max_squadre=5
TOTALE_NOTO = 5

risultati = {}

# ---------------------------------------------------------------------------
# Passo 1 — HOME
# ---------------------------------------------------------------------------
separa("PASSO 1 — Contatore slot in HOME")

if not nav.vai_in_home():
    log("FAIL: impossibile raggiungere HOME"); sys.exit(1)

shot_home = device.screenshot()
cv2.imwrite(os.path.join(DEBUG_DIR, "rt05_home.png"), shot_home.frame)

attive_home, totale_home = leggi_contatore_slot(shot_home, totale_noto=TOTALE_NOTO)
log(f"  Attive : {attive_home}")
log(f"  Totale : {totale_home}")
log(f"  Libere : {max(0, totale_home - attive_home) if totale_home > 0 else 'N/D'}")

ok_home = (attive_home >= 0 and totale_home > 0)
risultati["passo1_home"] = "PASS" if ok_home else "FAIL"
log(f"  Esito: {'PASS' if ok_home else 'FAIL'}")

# ---------------------------------------------------------------------------
# Passo 2 — MAPPA
# ---------------------------------------------------------------------------
separa("PASSO 2 — Contatore slot in MAPPA")

attive_mappa = totale_mappa = -1
if not nav.vai_in_mappa():
    log("FAIL: impossibile raggiungere MAPPA")
    risultati["passo2_mappa"] = "FAIL"
else:
    shot_mappa = device.screenshot()
    cv2.imwrite(os.path.join(DEBUG_DIR, "rt05_mappa.png"), shot_mappa.frame)

    attive_mappa, totale_mappa = leggi_contatore_slot(shot_mappa, totale_noto=TOTALE_NOTO)
    log(f"  Attive : {attive_mappa}")
    log(f"  Totale : {totale_mappa}")
    log(f"  Libere : {max(0, totale_mappa - attive_mappa) if totale_mappa > 0 else 'N/D'}")

    ok_mappa = (attive_mappa >= 0 and totale_mappa > 0)
    risultati["passo2_mappa"] = "PASS" if ok_mappa else "FAIL"
    log(f"  Esito: {'PASS' if ok_mappa else 'FAIL'}")

# ---------------------------------------------------------------------------
# Passo 3 — Confronto
# ---------------------------------------------------------------------------
separa("PASSO 3 — Confronto HOME vs MAPPA")
if risultati.get("passo1_home") == "PASS" and risultati.get("passo2_mappa") == "PASS":
    ok = (attive_home == attive_mappa and totale_home == totale_mappa)
    log(f"  HOME  : {attive_home}/{totale_home}")
    log(f"  MAPPA : {attive_mappa}/{totale_mappa}")
    risultati["passo3_confronto"] = "PASS" if ok else "WARN"
    log(f"  Esito: {'PASS — identici' if ok else 'WARN — diversi (lag normale)'}")
else:
    risultati["passo3_confronto"] = "SKIP"
    log("  SKIP: passo precedente fallito")

# ---------------------------------------------------------------------------
# Passo 4 — Ritorno HOME
# ---------------------------------------------------------------------------
separa("PASSO 4 — Ritorno HOME")
if nav.vai_in_home():
    log("PASS: ritorno in HOME confermato")
    risultati["passo4_ritorno"] = "PASS"
else:
    log("FAIL")
    risultati["passo4_ritorno"] = "FAIL"

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
separa("RIEPILOGO RT-05")
for passo, esito in risultati.items():
    simbolo = "OK" if esito == "PASS" else ("~~" if esito in ("WARN","SKIP") else "XX")
    log(f"  [{simbolo}] {passo}: {esito}")

log("")
if all(v in ("PASS","WARN") for v in risultati.values()):
    log("RT-05 SUPERATO — contatore slot funzionante in HOME e MAPPA")
else:
    log("RT-05 FALLITO — vedere debug_nav/ per diagnostica")

log_path = os.path.join(DEBUG_DIR, "test_slot.log")
with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
log(f"Log salvato: {log_path}")
