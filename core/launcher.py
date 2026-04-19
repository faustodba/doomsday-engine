# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/launcher.py
#
#  Gestisce avvio e chiusura istanze MuMuPlayer per V6.
#
#  Funzioni pubbliche:
#    avvia_player(log_fn)              → bool
#    reset_istanza(ist, log_fn)        → None   (pre-ciclo, stato pulito)
#    avvia_istanza(ist, log_fn)        → bool
#    attendi_home(ctx, log_fn)         → bool
#    chiudi_istanza(ist, porta, log_fn)→ None
#
#  Configurazione letta da global_config.json sezione "mumu" ad ogni chiamata:
#    mumu.manager             — path MuMuManager.exe
#    mumu.adb                 — path adb.exe (override: env MUMU_ADB_PATH)
#    mumu.timeout_adb_s       — timeout polling is_android_started
#    mumu.timeout_carica_s    — timeout polling HOME dopo avvio gioco
#    mumu.delay_carica_iniz_s — attesa fissa iniziale dopo avvio gioco
#    mumu.n_back_pulizia      — deprecato (BACK ora nel loop polling)
#    mumu.player_exe          — path MuMuNxMain.exe ("" = auto-deriva da manager)
#    mumu.timeout_player_s    — timeout polling avvio player
#
#  Standard V6: nessun asyncio, solo time.sleep(), subprocess.run() con
#  timeout, log tramite log_fn(msg) passata dall'esterno.
# ==============================================================================

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from core.navigator import Screen
from config.config_loader import load_global


# ==============================================================================
# Costanti fisse — non configurabili da global_config.json
# ==============================================================================

# Candidati fallback per auto-rilevamento MuMuManager.exe
# Usati se il path configurato in global_config.json non esiste sul disco.
_MUMU_MANAGER_CANDIDATI = [
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"C:\Program Files\Netease\MuMuPlayer\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer\MuMuManager.exe",
    r"D:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"D:\Program Files\Netease\MuMuPlayer\MuMuManager.exe",
    r"D:\Program Files (x86)\Netease\MuMuPlayer\nx_main\MuMuManager.exe",
    r"D:\Program Files (x86)\Netease\MuMuPlayer\MuMuManager.exe",
]

GAME_ACTIVITY: str = (
    "com.igg.android.doomsdaylastsurvivors"
    "/com.gpc.sdk.unity.GPCSDKMainActivity"
)

# Intervalli di polling non esposti in global_config (costanti operative interne)
DELAY_POLL_S: float = 5.0   # intervallo polling android_started


# ==============================================================================
# Helpers interni
# ==============================================================================

def _log(msg: str, log_fn: Optional[Callable] = None) -> None:
    line = f"[LAUNCHER] {msg}"
    if log_fn is not None:
        log_fn(line)
    else:
        print(line)


def _resolve_manager(configured_path: str) -> str:
    """
    Ritorna configured_path se il file esiste.
    Altrimenti cerca il primo candidato esistente in _MUMU_MANAGER_CANDIDATI.
    Fallback finale: configured_path anche se assente.
    """
    if os.path.exists(configured_path):
        return configured_path
    for p in _MUMU_MANAGER_CANDIDATI:
        if os.path.exists(p):
            return p
    return configured_path


def _mumu_info(indice: int, manager_exe: str) -> dict:
    """
    Chiama MuMuManager info -v <indice> e ritorna il JSON parsato.
    Ritorna {} se errore o output non parsabile.
    """
    try:
        result = subprocess.run(
            [manager_exe, "info", "-v", str(indice)],
            capture_output=True, timeout=10,
        )
        out = result.stdout.decode(errors="replace").strip()
        return json.loads(out)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return {}


def _adb_cmd(porta: int, *args: str, adb_exe: str) -> str:
    """
    Esegue: adb -s 127.0.0.1:<porta> <args>
    Ritorna stdout come stringa. Timeout 15s.
    Ritorna "" in caso di errore.
    """
    try:
        result = subprocess.run(
            [adb_exe, "-s", f"127.0.0.1:{porta}"] + list(args),
            capture_output=True, timeout=15,
        )
        return result.stdout.decode(errors="replace").strip()
    except (subprocess.TimeoutExpired, Exception):
        return ""


def _avvia_gioco(porta: int, adb_exe: str,
                 log_fn: Optional[Callable] = None) -> bool:
    """
    Avvia il gioco tramite am start con retry 3 volte.
    Ritorna True se il comando è andato a buon fine almeno una volta.
    """
    for tentativo in range(1, 4):
        _log(f"am start gioco (tentativo {tentativo}/3)", log_fn)
        out = _adb_cmd(
            porta,
            "shell", "am", "start", "-n", GAME_ACTIVITY,
            adb_exe=adb_exe,
        )
        if out and "Error" not in out and "error" not in out:
            _log(f"am start OK: {out[:80]}", log_fn)
            return True
        _log(f"am start tentativo {tentativo} fallito: {out[:80]}", log_fn)
        if tentativo < 3:
            time.sleep(3.0)
    return False


# ==============================================================================
# Player — avvio MuMuPlayer (necessario su Windows 11)
# ==============================================================================

_PLAYER_PROCESS_NAME = "MuMuNxMain.exe"
_PLAYER_POLL_S: float = 3.0


def _is_player_running() -> bool:
    """True se MuMuNxMain.exe è in esecuzione (tasklist Windows)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {_PLAYER_PROCESS_NAME}"],
            capture_output=True, timeout=10,
        )
        out = result.stdout.decode(errors="replace")
        return _PLAYER_PROCESS_NAME in out
    except (subprocess.TimeoutExpired, Exception):
        return False


def avvia_player(log_fn: Optional[Callable] = None) -> bool:
    """
    Avvia MuMuPlayer (MuMuNxMain.exe) se non già in esecuzione.

    Su Windows 11 il player deve essere avviato prima di poter lanciare
    le singole istanze con MuMuManager. Su Windows 10 non è necessario
    ma non causa problemi.

    Il path dell'eseguibile è derivato da:
      1. mumu.player_exe in global_config.json (se non vuoto)
      2. Altrimenti: stessa directory di mumu.manager / MuMuNxMain.exe

    Ritorna:
        True  — player già in esecuzione o avviato con successo
        False — timeout avvio
    """
    _cfg    = load_global().mumu
    timeout = _cfg.timeout_player_s

    # Già in esecuzione?
    if _is_player_running():
        _log("MuMuPlayer già in esecuzione", log_fn)
        return True

    # Determina path player
    if _cfg.player_exe:
        player_path = _cfg.player_exe
    else:
        manager_resolved = _resolve_manager(_cfg.manager)
        player_path = str(Path(manager_resolved).parent / _PLAYER_PROCESS_NAME)

    _log(f"Avvio MuMuPlayer: {player_path}", log_fn)

    if not os.path.exists(player_path):
        _log(f"ERRORE: {player_path} non trovato", log_fn)
        return False

    # Avvio non bloccante
    try:
        subprocess.Popen([player_path])
    except Exception as exc:
        _log(f"ERRORE avvio MuMuPlayer: {exc}", log_fn)
        return False

    # Polling fino a timeout
    _log(f"Polling MuMuPlayer (max {timeout}s)", log_fn)
    t_start = time.time()
    while time.time() - t_start < timeout:
        time.sleep(_PLAYER_POLL_S)
        if _is_player_running():
            _log(f"MuMuPlayer avviato OK ({time.time()-t_start:.0f}s)", log_fn)
            return True
        elapsed = time.time() - t_start
        _log(f"  in attesa MuMuPlayer... ({elapsed:.0f}s)", log_fn)

    _log(f"TIMEOUT: MuMuPlayer non avviato dopo {timeout}s", log_fn)
    return False


# ==============================================================================
# API pubblica
# ==============================================================================

def avvia_istanza(ist: dict, log_fn: Optional[Callable] = None) -> bool:
    """
    Avvia un'istanza MuMuPlayer e il gioco Doomsday.

    Flusso:
      0. avvia_player() — verifica/avvio MuMuPlayer (W11)
      1. MuMuManager control -v <indice> launch
      2. Polling is_android_started ogni DELAY_POLL_S, max timeout_adb_s
      3. adb connect 127.0.0.1:<porta>
      4. avvia_gioco() con retry 3

    Args:
        ist: dict istanza da instances.json
             Campi usati: "indice" (int), "porta" (int), "nome" (str)

    Ritorna:
        True  — gioco avviato
        False — timeout o errore
    """
    _cfg     = load_global().mumu
    _manager = _resolve_manager(_cfg.manager)
    _adb     = os.environ.get("MUMU_ADB_PATH") or _cfg.adb

    nome   = ist.get("nome",   "?")
    indice = ist.get("indice", 0)
    porta  = ist.get("porta",  16384 + indice * 32)

    _log(f"avvio istanza {nome} (indice={indice} porta={porta})", log_fn)
    _log(f"manager={_manager}", log_fn)
    _log(f"adb={_adb}", log_fn)

    # 0. Verifica/avvio MuMuPlayer (necessario su Windows 11)
    if not avvia_player(log_fn):
        _log("ERRORE: MuMuPlayer non avviato — impossibile procedere", log_fn)
        return False

    # 0.5. Reset socket ADB tra istanze sequenziali (fix #F1b).
    # Su macchina lenta (HDD + 11 istanze seriali) il frame grabber ADB
    # accumula socket rotti -> device.screenshot() ritorna None persistente.
    # kill-server+start-server resetta stato senza toccare MuMu.
    _log(f"[{nome}] adb kill-server/start-server (reset socket)", log_fn)
    try:
        subprocess.run([_adb, "kill-server"],  timeout=10, capture_output=True)
        subprocess.run([_adb, "start-server"], timeout=10, capture_output=True)
    except Exception as exc:
        _log(f"[{nome}] adb reset warn: {exc}", log_fn)

    # Attesa spegnimento completo istanza precedente (max 30s)
    _log(f"[{nome}] verifica istanza spenta...", log_fn)
    t_off = time.time()
    while time.time() - t_off < 30:
        info = _mumu_info(indice, _manager)
        started = info.get("is_android_started") or info.get("android_started")
        if not started:
            _log(f"[{nome}] istanza spenta — procedo", log_fn)
            break
        _log(f"[{nome}] istanza ancora attiva — attendo 3s...", log_fn)
        time.sleep(3.0)

    # 1. Launch MuMu
    _log(f"MuMuManager control -v {indice} launch", log_fn)
    try:
        subprocess.run(
            [_manager, "control", "-v", str(indice), "launch"],
            capture_output=True, timeout=30,
        )
    except Exception as exc:
        _log(f"MuMuManager launch errore: {exc}", log_fn)
        return False

    # 2. Polling is_android_started
    _log(f"Polling Android started (max {_cfg.timeout_adb_s}s)", log_fn)
    t_start = time.time()
    android_ok = False
    while time.time() - t_start < _cfg.timeout_adb_s:
        info = _mumu_info(indice, _manager)
        if info.get("is_android_started") or info.get("android_started"):
            _log(f"Android started dopo {time.time()-t_start:.0f}s", log_fn)
            android_ok = True
            break
        elapsed = time.time() - t_start
        _log(f"  in attesa... ({elapsed:.0f}s)", log_fn)
        time.sleep(DELAY_POLL_S)

    if not android_ok:
        _log(f"TIMEOUT: Android non started dopo {_cfg.timeout_adb_s}s", log_fn)
        return False

    # 3. adb connect
    _log(f"adb connect 127.0.0.1:{porta}", log_fn)
    try:
        result = subprocess.run(
            [_adb, "connect", f"127.0.0.1:{porta}"],
            capture_output=True, timeout=15,
        )
        out = result.stdout.decode(errors="replace").strip()
        if "connected" not in out and "already connected" not in out:
            _log(f"adb connect anomalia: {out}", log_fn)
        else:
            _log(f"adb connect: {out}", log_fn)
    except Exception as exc:
        _log(f"adb connect errore: {exc}", log_fn)
        return False

    # 4. Avvia gioco
    if not _avvia_gioco(porta, _adb, log_fn):
        _log("ERRORE: impossibile avviare il gioco dopo 3 tentativi", log_fn)
        return False

    _log(f"istanza {nome} avviata OK", log_fn)
    return True


def attendi_home(ctx, log_fn: Optional[Callable] = None) -> bool:
    """
    Attende che l'istanza raggiunga la schermata HOME dopo l'avvio del gioco.

    Flusso:
      1. Attesa fissa delay_carica_iniz_s (caricamento iniziale)
      2. Loop fino a timeout_carica_s:
         - device.back() (chiude popup di avvio)
         - time.sleep(1.5)
         - schermata = nav.schermata_corrente()
         - log "[nome] schermata=X (Ns)"
         - se schermata != Screen.UNKNOWN: break
      3. Se timeout: return False
      4. Stabilizzazione: attende HOME stabile per 3 poll consecutivi (max 60s)
         con BACK ad ogni iterazione per chiudere popup/banner
      5. vai_in_home() verifica finale

    Args:
        ctx: TaskContext con navigator disponibile

    Ritorna:
        True  — HOME raggiunto
        False — timeout
    """
    _cfg = load_global().mumu
    nome = getattr(ctx, "instance_name", "?")
    nav    = getattr(ctx, "navigator", None)
    device = getattr(ctx, "device", None)

    # 1. Attesa fissa caricamento
    _log(f"[{nome}] attesa caricamento iniziale {_cfg.delay_carica_iniz_s}s", log_fn)
    time.sleep(_cfg.delay_carica_iniz_s)

    # 2. Loop BACK + polling schermata
    if nav is None:
        _log(f"[{nome}] navigator non disponibile — skip polling", log_fn)
    else:
        _log(f"[{nome}] loop BACK + polling schermata (max {_cfg.timeout_carica_s}s)", log_fn)
        t_start = time.time()
        trovata = False
        while time.time() - t_start < _cfg.timeout_carica_s:
            # BACK chiude eventuali popup sovrapposti (daily login, eventi, ecc.)
            if device is not None:
                device.back()
            time.sleep(1.5)

            try:
                schermata = nav.schermata_corrente()
            except Exception:
                schermata = Screen.UNKNOWN

            elapsed = time.time() - t_start
            _log(f"[{nome}] schermata={schermata} ({elapsed:.0f}s)", log_fn)

            if schermata != Screen.UNKNOWN:
                _log(f"[{nome}] schermata rilevata: {schermata}", log_fn)
                trovata = True
                break

        # 3. Timeout
        if not trovata:
            _log(f"[{nome}] TIMEOUT: schermata ancora UNKNOWN dopo "
                 f"{_cfg.timeout_carica_s}s", log_fn)
            return False

    # 4. Stabilizzazione: attende HOME stabile senza popup/overlay
    # Un singolo rilevamento HOME non basta — il gioco mostra banner e
    # popup per 10-30s dopo il caricamento. Aspettiamo che la HOME sia
    # stabile per 3 poll consecutivi con score mappa nel range normale.
    if nav is not None:
        _log(f"[{nome}] stabilizzazione HOME (max 30s)...", log_fn)
        stable_count = 0
        t_stab = time.time()
        while time.time() - t_stab < 30:
            time.sleep(5.0)
            try:
                schermata = nav.schermata_corrente()
            except Exception:
                schermata = Screen.UNKNOWN
            if schermata == Screen.HOME:
                stable_count += 1
                _log(f"[{nome}] HOME stabile {stable_count}/3", log_fn)
                if stable_count >= 3:
                    _log(f"[{nome}] HOME stabilizzata — pronti", log_fn)
                    break
            else:
                if stable_count > 0:
                    _log(f"[{nome}] HOME instabile ({schermata}) — reset contatore", log_fn)
                stable_count = 0
        else:
            _log(f"[{nome}] stabilizzazione timeout — procedo comunque", log_fn)

    # 5. vai_in_home() verifica finale
    if nav is not None:
        _log(f"[{nome}] vai_in_home() verifica finale", log_fn)
        ok = nav.vai_in_home()
        if ok:
            _log(f"[{nome}] HOME raggiunto", log_fn)
        else:
            _log(f"[{nome}] vai_in_home() FALLITO", log_fn)
        return ok

    _log(f"[{nome}] navigator assente — HOME assunto (ottimistico)", log_fn)
    return True


def reset_istanza(ist: dict, log_fn: Optional[Callable] = None) -> None:
    """
    Forza la chiusura completa di un'istanza prima di un nuovo ciclo.
    Garantisce uno stato pulito indipendentemente da cosa è successo prima.

    Flusso:
      1. am force-stop gioco via adb (ignora errori)
      2. MuMuManager control -v <indice> shutdown
      3. Polling is_android_started == False (max 30s)
      4. adb disconnect
    """
    _cfg     = load_global().mumu
    _manager = _resolve_manager(_cfg.manager)
    _adb     = os.environ.get("MUMU_ADB_PATH") or _cfg.adb

    nome   = ist.get("nome",   "?")
    indice = ist.get("indice", 0)
    porta  = ist.get("porta",  16384 + indice * 32)

    _log(f"[{nome}] reset pre-ciclo (indice={indice} porta={porta})", log_fn)

    # 1. Force-stop gioco
    _adb_cmd(porta, "shell", "am", "force-stop",
             GAME_ACTIVITY.split("/")[0], adb_exe=_adb)

    # 2. Shutdown MuMu
    _log(f"[{nome}] MuMuManager shutdown...", log_fn)
    try:
        subprocess.run(
            [_manager, "control", "-v", str(indice), "shutdown"],
            capture_output=True, timeout=30,
        )
    except Exception as exc:
        _log(f"[{nome}] shutdown errore (ignorato): {exc}", log_fn)

    # 3. Polling spegnimento (max 30s)
    t_off = time.time()
    while time.time() - t_off < 30:
        time.sleep(3.0)
        info = _mumu_info(indice, _manager)
        started = info.get("is_android_started") or info.get("android_started")
        if not started:
            _log(f"[{nome}] istanza spenta ({time.time()-t_off:.0f}s)", log_fn)
            break
        _log(f"[{nome}] ancora attiva — attendo...", log_fn)
    else:
        _log(f"[{nome}] timeout spegnimento — procedo comunque", log_fn)

    # 4. adb disconnect
    try:
        subprocess.run(
            [_adb, "disconnect", f"127.0.0.1:{porta}"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

    _log(f"[{nome}] reset completato", log_fn)


def chiudi_istanza(ist: dict, porta: int,
                   log_fn: Optional[Callable] = None) -> None:
    """
    Chiude il gioco e l'istanza MuMuPlayer.

    Flusso:
      1. am force-stop GAME_ACTIVITY via adb shell
      2. MuMuManager control -v <indice> shutdown
      3. adb disconnect 127.0.0.1:<porta>

    Args:
        ist:  dict istanza (campi: "indice", "nome")
        porta: porta ADB dell'istanza
    """
    _cfg     = load_global().mumu
    _manager = _resolve_manager(_cfg.manager)
    _adb     = os.environ.get("MUMU_ADB_PATH") or _cfg.adb

    nome   = ist.get("nome",   "?")
    indice = ist.get("indice", 0)

    _log(f"chiusura istanza {nome} (indice={indice} porta={porta})", log_fn)

    # 1. Force-stop gioco
    _log(f"[{nome}] am force-stop {GAME_ACTIVITY.split('/')[0]}", log_fn)
    _adb_cmd(porta, "shell", "am", "force-stop",
             GAME_ACTIVITY.split("/")[0], adb_exe=_adb)

    # 2. Shutdown MuMu
    _log(f"[{nome}] MuMuManager control -v {indice} shutdown", log_fn)
    try:
        subprocess.run(
            [_manager, "control", "-v", str(indice), "shutdown"],
            capture_output=True, timeout=30,
        )
    except Exception as exc:
        _log(f"[{nome}] MuMuManager shutdown errore: {exc}", log_fn)

    # 3. adb disconnect
    _log(f"[{nome}] adb disconnect 127.0.0.1:{porta}", log_fn)
    try:
        subprocess.run(
            [_adb, "disconnect", f"127.0.0.1:{porta}"],
            capture_output=True, timeout=10,
        )
    except Exception as exc:
        _log(f"[{nome}] adb disconnect errore: {exc}", log_fn)

    _log(f"istanza {nome} chiusa", log_fn)
