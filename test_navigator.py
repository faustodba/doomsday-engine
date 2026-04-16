# ==============================================================================
#  DOOMSDAY ENGINE V6 — test_navigator.py
#
#  Test runtime isolato RT-03:
#    Passo 1 — Screenshot + riconoscimento schermata HOME
#    Passo 2 — Tap bottone MAPPA + verifica schermata MAPPA
#    Passo 3 — Tap bottone HOME + verifica ritorno HOME
#
#  Prerequisiti:
#    - FAU_00 avviata in MuMu con Doomsday aperto sulla HOME del gioco
#    - ADB connesso (verificare con: adb devices)
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_navigator.py
#
#  Output:
#    - Stampa score template per ogni passo
#    - Salva screenshot PNG di ogni passo in C:\doomsday-engine\debug_nav\
#    - Esito finale: PASS / FAIL per ogni passo
# ==============================================================================

import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import cv2

from core.device import AdbDevice
from core.navigator import GameNavigator, NavigatorConfig, Screen
from shared.template_matcher import get_matcher

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
ADB_HOST   = "127.0.0.1"
ADB_PORT   = 16384          # porta FAU_00
NOME       = "FAU_00"
DEBUG_DIR  = os.path.join(ROOT, "debug_nav")

os.makedirs(DEBUG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_lines = []

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    log_lines.append(line)

def salva_screenshot(shot, nome_file: str) -> None:
    if shot is None:
        log(f"  [WARN] screenshot None — non salvato ({nome_file})")
        return
    path = os.path.join(DEBUG_DIR, nome_file)
    cv2.imwrite(path, shot.frame)
    log(f"  Screenshot salvato: {path}")

def separa(titolo: str) -> None:
    log("")
    log("=" * 55)
    log(f"  {titolo}")
    log("=" * 55)

# ---------------------------------------------------------------------------
# Setup device + matcher + navigator
# ---------------------------------------------------------------------------
separa("SETUP")
log(f"Connessione ADB: {ADB_HOST}:{ADB_PORT}")
device  = AdbDevice(host=ADB_HOST, port=ADB_PORT, name=NOME)
matcher = get_matcher(template_dir=os.path.join(ROOT, "templates"))
cfg     = NavigatorConfig(
    pin_threshold=0.70,
    log_scores=True,
)
nav = GameNavigator(device=device, matcher=matcher, config=cfg, log_fn=log)

risultati = {}

# ---------------------------------------------------------------------------
# PASSO 1 — Screenshot + identificazione schermata corrente
# ---------------------------------------------------------------------------
separa("PASSO 1 — Identificazione schermata")

shot = device.screenshot()
salva_screenshot(shot, "passo1_screenshot.png")

if shot is None:
    log("FAIL: screenshot None — ADB non risponde")
    risultati["passo1"] = "FAIL"
else:
    score_home = matcher.score(shot, cfg.pin_home_template)
    score_map  = matcher.score(shot, cfg.pin_map_template)
    log(f"Score {cfg.pin_home_template} : {score_home:.3f}")
    log(f"Score {cfg.pin_map_template}  : {score_map:.3f}")
    log(f"Soglia attiva  : {cfg.pin_threshold}")

    screen = nav._classifica(shot)
    log(f"Schermata rilevata: {screen.name}")

    if screen == Screen.HOME:
        log("PASS: schermata HOME riconosciuta")
        risultati["passo1"] = "PASS"
    elif screen == Screen.MAP:
        log("WARN: schermata MAPPA — torna manualmente in HOME e rilancia")
        risultati["passo1"] = "WARN"
    else:
        log(f"FAIL: schermata UNKNOWN — score home={score_home:.3f} troppo basso")
        log(f"      Template dir: {os.path.join(ROOT, 'templates', 'pin')}")
        risultati["passo1"] = "FAIL"

# ---------------------------------------------------------------------------
# PASSO 2 — Tap MAPPA + verifica
# ---------------------------------------------------------------------------
separa("PASSO 2 — Navigazione MAPPA")

if risultati.get("passo1") in ("PASS",):
    log("Tap toggle HOME/MAPPA...")
    device.tap(cfg.toggle_btn)
    time.sleep(cfg.wait_after_action)

    shot2 = device.screenshot()
    salva_screenshot(shot2, "passo2_mappa.png")

    if shot2 is None:
        log("FAIL: screenshot None dopo tap toggle")
        risultati["passo2"] = "FAIL"
    else:
        score_home2 = matcher.score(shot2, cfg.pin_home_template)
        score_map2  = matcher.score(shot2, cfg.pin_map_template)
        log(f"Score {cfg.pin_home_template} : {score_home2:.3f}")
        log(f"Score {cfg.pin_map_template}  : {score_map2:.3f}")
        screen2 = nav._classifica(shot2)
        log(f"Schermata rilevata: {screen2.name}")

        if screen2 == Screen.MAP:
            log("PASS: schermata MAPPA raggiunta")
            risultati["passo2"] = "PASS"
        else:
            log(f"FAIL: schermata attesa MAP, rilevata {screen2.name}")
            log(f"      Verificare toggle_btn={cfg.toggle_btn} o {cfg.pin_map_template}")
            risultati["passo2"] = "FAIL"
else:
    log("SKIP: passo 1 non superato")
    risultati["passo2"] = "SKIP"

# ---------------------------------------------------------------------------
# PASSO 3 — Ritorno HOME + verifica
# ---------------------------------------------------------------------------
separa("PASSO 3 — Ritorno HOME")

if risultati.get("passo2") == "PASS":
    log("Tap toggle MAPPA/HOME...")
    device.tap(cfg.toggle_btn)
    time.sleep(cfg.wait_after_action)

    shot3 = device.screenshot()
    salva_screenshot(shot3, "passo3_home.png")

    if shot3 is None:
        log("FAIL: screenshot None dopo tap toggle")
        risultati["passo3"] = "FAIL"
    else:
        score_home3 = matcher.score(shot3, cfg.pin_home_template)
        score_map3  = matcher.score(shot3, cfg.pin_map_template)
        log(f"Score {cfg.pin_home_template} : {score_home3:.3f}")
        log(f"Score {cfg.pin_map_template}  : {score_map3:.3f}")
        screen3 = nav._classifica(shot3)
        log(f"Schermata rilevata: {screen3.name}")

        if screen3 == Screen.HOME:
            log("PASS: ritorno in HOME confermato")
            risultati["passo3"] = "PASS"
        else:
            log(f"FAIL: schermata attesa HOME, rilevata {screen3.name}")
            log(f"      Verificare toggle_btn={cfg.toggle_btn} o {cfg.pin_home_template}")
            risultati["passo3"] = "FAIL"
else:
    log("SKIP: passo 2 non superato")
    risultati["passo3"] = "SKIP"

# ---------------------------------------------------------------------------
# Riepilogo finale
# ---------------------------------------------------------------------------
separa("RIEPILOGO RT-03")
for passo, esito in risultati.items():
    simbolo = "OK" if esito == "PASS" else ("--" if esito == "SKIP" else "XX")
    log(f"  [{simbolo}] {passo.upper()}: {esito}")

log("")
if all(v == "PASS" for v in risultati.values()):
    log("RT-03 SUPERATO — Navigator HOME/MAPPA funzionante")
else:
    log("RT-03 FALLITO — vedere screenshot in debug_nav/ per diagnosi")
    log(f"  dir: {DEBUG_DIR}")

# Salva log testo
log_path = os.path.join(DEBUG_DIR, "test_navigator.log")
with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
log(f"Log salvato: {log_path}")
