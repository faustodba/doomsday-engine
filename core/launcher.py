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
from core.adaptive_timing import AdaptiveTiming
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


def _gioco_process_vivo(porta: int, adb_exe: str) -> bool:
    """Il processo del gioco esiste (può essere in background/foreground)."""
    pkg = GAME_ACTIVITY.split("/")[0]
    out = _adb_cmd(porta, "shell", "ps", "-A", adb_exe=adb_exe) \
          or _adb_cmd(porta, "shell", "ps", adb_exe=adb_exe)
    return pkg in out


def _gioco_in_foreground(porta: int, adb_exe: str) -> bool:
    """
    Check best-effort: gioco presente nell'output dumpsys activity top.

    Nota: check NON STRETTO — può dare falso positivo se pkg appare come
    task background. Safety-net reale è il monkey recovery in attendi_home,
    che rilancia monkey se durante il polling schermata resta UNKNOWN per
    troppo tempo. Preferiamo falso positivo (proseguiamo nel launcher) a
    falso negativo (rinunciamo lasciando MuMu orfano).
    """
    pkg = GAME_ACTIVITY.split("/")[0]
    out = _adb_cmd(porta, "shell", "dumpsys", "activity", "top", adb_exe=adb_exe)
    return bool(out) and pkg in out


def _avvia_gioco(porta: int, adb_exe: str,
                 log_fn: Optional[Callable] = None) -> bool:
    """
    Avvia il gioco con strategia robusta anti-background.

    Per ogni tentativo (max 3):
      1. am start -n GAME_ACTIVITY
      2. sleep 3s (l'intent viaggia)
      3. monkey -p pkg -c LAUNCHER 1  (SEMPRE — idempotente, porta UI al top)
      4. sleep 5s (app UI render)
      5. check foreground via `dumpsys activity top | grep pkg`
         - se gioco in foreground → OK
         - altrimenti prossimo tentativo

    Motivazione osservata in prod:
      - `am start OK` accetta l'intent ma spesso il processo parte in
        background senza UI al top (schermo resta su HOME Android)
      - `ps | grep pkg` ritorna match ma il gioco NON è visibile
      - `monkey LAUNCHER` porta sempre l'app al top (equivalente a tap icona)
      - `dumpsys activity top` verifica foreground reale, non solo processo vivo
    """
    pkg = GAME_ACTIVITY.split("/")[0]
    for tentativo in range(1, 4):
        _log(f"am start gioco (tentativo {tentativo}/3)", log_fn)
        out = _adb_cmd(
            porta,
            "shell", "am", "start", "-n", GAME_ACTIVITY,
            adb_exe=adb_exe,
        )
        if not out or "Error" in out or "error" in out:
            _log(f"am start tentativo {tentativo} output: {out[:80]}", log_fn)
        else:
            _log(f"am start OK: {out[:80]}", log_fn)

        time.sleep(3.0)

        # SEMPRE monkey dopo am start — idempotente se gioco già in foreground,
        # forza l'UI al top se processo è in background
        _log("monkey launcher (porta UI al top)", log_fn)
        _adb_cmd(
            porta,
            "shell", "monkey", "-p", pkg,
            "-c", "android.intent.category.LAUNCHER", "1",
            adb_exe=adb_exe,
        )
        time.sleep(5.0)

        # Verifica foreground (non solo processo vivo)
        if _gioco_in_foreground(porta, adb_exe):
            _log("gioco verificato in foreground", log_fn)
            return True

        # Fallback diagnosi: se processo vivo ma non in foreground → continua
        if _gioco_process_vivo(porta, adb_exe):
            _log("processo gioco vivo ma NON in foreground — retry", log_fn)
        else:
            _log("processo gioco NON trovato — retry", log_fn)

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

    # 2. Polling is_android_started (timeout adattivo per-istanza — F-A)
    _tm = AdaptiveTiming(nome)
    _boot_timeout = _tm.get("boot_android_s", float(_cfg.timeout_adb_s))
    _log(
        f"Polling Android started (max {_boot_timeout:.0f}s, "
        f"base={_cfg.timeout_adb_s}s)",
        log_fn,
    )
    t_start = time.time()
    android_ok = False
    while time.time() - t_start < _boot_timeout:
        info = _mumu_info(indice, _manager)
        if info.get("is_android_started") or info.get("android_started"):
            boot_s = time.time() - t_start
            _log(f"Android started dopo {boot_s:.0f}s", log_fn)
            _tm.record("boot_android_s", boot_s)
            android_ok = True
            break
        elapsed = time.time() - t_start
        _log(f"  in attesa... ({elapsed:.0f}s)", log_fn)
        time.sleep(DELAY_POLL_S)

    if not android_ok:
        _log(f"TIMEOUT: Android non started dopo {_boot_timeout:.0f}s", log_fn)
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


def attendi_home(ctx, log_fn: Optional[Callable] = None) -> bool:  # noqa: C901
    """[auto-WU16] Stabilizzazione adattiva: poll più rapido + tracking."""
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
    # Path ADB + porta istanza — necessari per monkey recovery nel polling
    _adb_path  = os.environ.get("MUMU_ADB_PATH") or _cfg.adb
    porta_attesa = getattr(device, "port", None) if device is not None else None

    # auto-WU16: tracking adaptive — misura tempo totale attendi_home
    _t_attesa_home_start = time.time()
    _tm = AdaptiveTiming(nome)

    # 1. Attesa caricamento con polling attivo (F-B1).
    # auto-WU16: t_min ridotto 15→10s (splash gioco tipico è 8-12s post-load)
    t_min = 10.0
    t_max = float(_cfg.delay_carica_iniz_s)
    _log(
        f"[{nome}] attesa caricamento min={t_min:.0f}s max={t_max:.0f}s "
        f"(polling attivo)",
        log_fn,
    )
    time.sleep(t_min)

    if nav is not None:
        t_poll = time.time()
        while time.time() - t_poll < (t_max - t_min):
            time.sleep(2.0)
            try:
                schermata_early = nav.schermata_corrente()
            except Exception:
                schermata_early = Screen.UNKNOWN
            if schermata_early in (Screen.HOME, Screen.MAP):
                elapsed = t_min + (time.time() - t_poll)
                _log(
                    f"[{nome}] schermata={schermata_early} rilevata a {elapsed:.0f}s "
                    f"— skip attesa residua",
                    log_fn,
                )
                break
    else:
        # Fallback: nessun nav, pausa completa
        time.sleep(max(0.0, t_max - t_min))

    # 2. Loop BACK + polling schermata
    if nav is None:
        _log(f"[{nome}] navigator non disponibile — skip polling", log_fn)
    else:
        # auto-WU21: dismiss banners catalog PRIMA del polling cieco BACK.
        # Identifica banner/popup specifici e applica dismiss action mirata
        # (tap_X / tap_centro / tap_coords) invece di BACK indiscriminato.
        # Deploy 1: catalog ha solo banner_eventi_laterale; placeholder per
        # daily_login, news_feed, event_modal etc da popolare post-discovery.
        try:
            from shared.ui_helpers import dismiss_banners_loop
            class _MiniCtx:
                pass
            mini = _MiniCtx()
            mini.device = device
            mini.matcher = ctx.matcher if hasattr(ctx, 'matcher') else None
            if mini.matcher is not None:
                bdism = dismiss_banners_loop(mini, max_iter=8,
                                             log_fn=lambda m: _log(f"[{nome}] {m}", log_fn))
                if bdism:
                    _log(f"[{nome}] banner pre-polling dismissed: {bdism}", log_fn)
                    time.sleep(2.0)  # consenti UI di stabilizzarsi
        except Exception as exc:
            _log(f"[{nome}] banner dismiss errore (non bloccante): {exc}", log_fn)

        _log(f"[{nome}] loop BACK + polling schermata (max {_cfg.timeout_carica_s}s)", log_fn)
        t_start = time.time()
        trovata = False
        unknown_streak = 0            # cicli consecutivi Screen.UNKNOWN
        last_monkey_t = 0.0           # ts ultimo monkey di recovery
        # auto-WU16: poll più reattivo (5.5→3.5s). Mantiene back+sleep+screenshot
        # ma rileva HOME prima nei casi normali. Slow PC: ~5s totali per ciclo.
        POLL_BACK_INTERVAL_S = 3.5    # sleep tra back e schermata_corrente
        MONKEY_EVERY_N = 8            # auto-WU16: 6→8 cicli (~28s con poll 3.5s = ~42s prima)
        MONKEY_COOLDOWN_S = 30.0      # cooldown minimo tra monkey successivi
        # auto-WU21: discovery — salva screenshot quando UNKNOWN persiste,
        # per estrarre template di popup non catalogati.
        UNKNOWN_SNAPSHOT_AT = 5
        snapshot_taken = False
        # auto-WU22: ad ogni iter, prima del BACK cieco prova catalog dismiss.
        # Critico per "Exit game?" dialog (priority=0): se il polling BACK
        # apre il dialog, il dismiss_banners_loop lo intercetta e tappa CANCEL
        # invece di confermare OK (catastrofico) o accumulare BACK→dialog.
        try:
            from shared.ui_helpers import dismiss_banners_loop as _dbl
        except Exception:
            _dbl = None

        while time.time() - t_start < _cfg.timeout_carica_s:
            # auto-WU22: catalog dismiss INTRA-loop per intercettare popup
            # aperti dal BACK precedente (es. "Exit game?" dialog).
            if _dbl is not None and hasattr(ctx, 'matcher') and ctx.matcher is not None:
                try:
                    class _Mini:
                        pass
                    mini = _Mini()
                    mini.device = device
                    mini.matcher = ctx.matcher
                    bd = _dbl(mini, max_iter=2,
                             log_fn=lambda m: _log(f"[{nome}] {m}", log_fn))
                    if bd:
                        # Banner trovato e chiuso, salta il BACK di questa iter
                        time.sleep(1.0)
                        try:
                            schermata = nav.schermata_corrente()
                        except Exception:
                            schermata = Screen.UNKNOWN
                        if schermata != Screen.UNKNOWN:
                            _log(f"[{nome}] schermata rilevata post-dismiss: {schermata}", log_fn)
                            trovata = True
                            break
                        # Continua loop ma senza BACK (popup era qui, BACK probabilmente lo riapriva)
                        continue
                except Exception as exc:
                    _log(f"[{nome}] dismiss intra-loop errore: {exc}", log_fn)

            # BACK chiude eventuali popup sovrapposti (daily login, eventi, ecc.)
            if device is not None:
                device.back()
            time.sleep(POLL_BACK_INTERVAL_S)

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

            # Recovery: app uscita dal foreground durante il polling?
            # Ogni N cicli UNKNOWN consecutivi, rilancia monkey per forzare
            # il gioco in foreground (idempotente se già al top).
            unknown_streak += 1

            # auto-WU21 discovery: 1 screenshot quando UNKNOWN streak == 5,
            # per analisi visiva offline → estrazione template banner.
            if (unknown_streak == UNKNOWN_SNAPSHOT_AT
                    and not snapshot_taken
                    and device is not None):
                try:
                    import cv2
                    from datetime import datetime as _dt
                    shot = device.screenshot()
                    if shot is not None and getattr(shot, "frame", None) is not None:
                        out_dir = Path(__file__).resolve().parents[1] / "debug_task" / "boot_unknown"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                        fname = f"{nome}_streak{unknown_streak}_{ts}.png"
                        cv2.imwrite(str(out_dir / fname), shot.frame)
                        _log(f"[{nome}] discovery screenshot salvato: debug_task/boot_unknown/{fname}", log_fn)
                        snapshot_taken = True
                except Exception as exc:
                    _log(f"[{nome}] discovery screenshot errore: {exc}", log_fn)

            now = time.time()
            if (unknown_streak >= MONKEY_EVERY_N
                    and (now - last_monkey_t) > MONKEY_COOLDOWN_S
                    and porta_attesa is not None):
                try:
                    pkg = GAME_ACTIVITY.split("/")[0]
                    _adb_cmd(
                        porta_attesa,
                        "shell", "monkey", "-p", pkg,
                        "-c", "android.intent.category.LAUNCHER", "1",
                        adb_exe=_adb_path,
                    )
                    _log(f"[{nome}] monkey recovery (UNKNOWN {unknown_streak} cicli)", log_fn)
                    last_monkey_t = now
                    unknown_streak = 0
                    time.sleep(3.0)  # attesa UI al top
                except Exception as exc:
                    _log(f"[{nome}] monkey recovery errore: {exc}", log_fn)

        # 3. Timeout
        if not trovata:
            _log(f"[{nome}] TIMEOUT: schermata ancora UNKNOWN dopo "
                 f"{_cfg.timeout_carica_s}s", log_fn)
            return False

    # 4. Stabilizzazione: attende HOME stabile senza popup/overlay
    # auto-WU16: sleep 5.0→3.0s, timeout 60→40s, mantenuto stable_count >= 3
    # per evitare false positive da banner/animazioni.
    if nav is not None:
        _log(f"[{nome}] stabilizzazione HOME (max 40s)...", log_fn)
        stable_count = 0
        t_stab = time.time()
        while time.time() - t_stab < 40:
            time.sleep(3.0)
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
            # auto-WU16: traccia tempo totale attendi_home per AdaptiveTiming
            home_total_s = time.time() - _t_attesa_home_start
            try:
                _tm.record("attendi_home_total_s", home_total_s)
            except Exception:
                pass
            _log(f"[{nome}] HOME raggiunto in {home_total_s:.0f}s", log_fn)
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
