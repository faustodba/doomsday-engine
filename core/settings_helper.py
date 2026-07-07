"""
core/settings_helper.py — Imposta i settings grafici + pulizia cache nel client gioco.

WU60 (29/04/2026) — Fix instabilità arena via aggiornamento MuMu + settings
gioco lightweight (storicamente LOW, vedi WU78-rev sotto).

WU78-rev (30/04/2026) — Il driver Vulkan→DirectX (Issue #88) ha eliminato
la necessità di ULTRA-LOW: i settings applicati sono Graphics HIGH + Frame
Rate MID + Optimize Mode HIGH (matching setup manuale utente FAU_10).

WU64 (29/04/2026) — Pulizia cache giornaliera integrata: Avatar → Settings
→ Help → Clear cache → polling CLOSE → CLOSE. Stato persistito in
`data/cache_state.json` (granularità giornaliera UTC).

WU195 (07/07/2026) — le due fasi (grafica HIGH, pulizia cache) sono state
separate in due funzioni pubbliche indipendenti, ciascuna con la propria
navigazione HOME→...→HOME, per diventare due task orchestrator distinti
(`tasks/grafica_hq.py::GraficaHqTask`, `tasks/pulizia_cache.py::
PuliziaCacheTask`) abilitabili/disabilitabili separatamente da dashboard
(`globali.task.grafica_hq`, `globali.task.pulizia_cache`). Prima erano
un'unica funzione `imposta_settings_lightweight()` chiamata
incondizionatamente da `core/launcher.py` ad ogni avvio istanza — rimossa.

GESTIONE TOGGLE STATEFUL (grafica):
- Graphics Quality (slider): IDEMPOTENTE — tap su HIGH resta su HIGH
- Frame Rate (3 radio button): IDEMPOTENTE — tap su MID resta MID
- Optimize Mode: pulsante HIGH distinto da Low, IDEMPOTENTE (nessun
  check visuale pre-tap necessario, a differenza del vecchio toggle LOW)

Uso:
    from core.settings_helper import esegui_grafica_hq, esegui_pulizia_cache
    esegui_grafica_hq(ctx, log_fn=lambda m: ctx.log_msg(m))
    esegui_pulizia_cache(ctx, log_fn=lambda m: ctx.log_msg(m))

Sequenza grafica HIGH (~22s):
    1. HOME → tap Avatar (48, 37)
    2. → tap icona Settings (135, 478)
    3. → tap voce System Settings (399, 141)
    4. → tap Graphics Quality HIGH (855, 130) [idempotente]
    5. → tap Frame Rate MID (740, 215) [idempotente]
    6. → tap Optimize Mode HIGH (228, 337) [idempotente]
    7. BACK × 3 (System Settings → Settings → Commander → HOME)

Sequenza pulizia cache (skip immediato, nessun tap, se già fatta oggi):
    1. HOME → tap Avatar (48, 37)
    2. → tap icona Settings (135, 478)
    3. tap Help (570, 235) → tap Clear cache (666, 375) → tap Clear icon
       (480, 200) → polling CLOSE ogni 5s max 20s → tap CLOSE (480, 445)
    4. BACK extra (Help → Settings, interno a `_pulisci_cache`)
    5. marca cache_state per oggi
    6. BACK × 2 (Settings → Commander → HOME)

Coordinate calibrate su MuMu Player 960×540, validate su FAU_10 il 29/04.

WU166 (18/06/2026) — Storico persistente pulizia cache. `data/cache_state.json`
dice solo "pulito oggi sì/no" e le righe [CACHE] nei log istanza si perdono
alla rotazione (ogni tick sovrascrive `logs/<NOME>.jsonl`) — un fallimento
notturno era invisibile entro poche ore. Ogni tentativo (ok o fallito) viene
ora appeso a `data/cache_history.jsonl` (append-only, sopravvive a riavvii e
rotazione log). Alert automatico se manca la marca giornaliera dopo un
cutoff: vedi `core/alerts.py::check_cache_pulizia_giornaliera`.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Coordinate (display 960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_AVATAR          = (48,  37)   # Avatar profilo, alto-sx HOME
_TAP_SETTINGS_ICON   = (135, 478)  # Icona Settings, basso-sx menu profilo
_TAP_SYSTEM_SETTINGS = (399, 141)  # Voce "System Settings" nel menu

_TAP_GRAPHICS_LOW    = (695, 129)  # Graphics Quality slider LOW (deprecato WU78-rev)
_TAP_FRAME_LOW       = (623, 215)  # Frame Rate selettore LOW (deprecato WU78-rev)
_TAP_OPTIMIZE_MODE   = (153, 337)  # Optimize Mode toggle LOW (deprecato WU78-rev)

# WU78-rev (30/04 10:35) — settings HIGH/MID/HIGH (matching FAU_10 manuale).
# Driver Vulkan→DirectX (Issue #88) elimina necessità ULTRA-LOW.
# Coord calibrate live FAU_00 30/04 (utente provided).
_TAP_GRAPHICS_HIGH   = (809, 123)  # Graphics Quality slider posizione HIGH
_TAP_FRAME_MID       = (717, 209)  # Frame Rate selettore MID (2° radio)
_TAP_OPTIMIZE_HIGH   = (229, 330)  # Optimize Mode pulsante HIGH (a destra di Low)

# ROI (x1,y1,x2,y2) per match template optimize low active
_ROI_OPTIMIZE_LOW   = (108, 317, 198, 357)
_TPL_OPTIMIZE_LOW   = "pin/pin_settings_optimize_low_active.png"
_SOGLIA_OPTIMIZE    = 0.90  # 0.70 → 0.90 (29/04: 0.811 era falso positivo
                            # quando Optimize NON era attivo — soglia troppo
                            # permissiva. Score reale ON deve essere ≥ 0.90)

# Pulizia cache giornaliera (WU64) — coord calibrate su FAU_10 29/04
_TAP_HELP_BTN       = (570, 235)   # Voce "Help" nel pannello SETTINGS
_TAP_CLEAR_CACHE    = (666, 375)   # Pulsante "Clear cache" nel pannello HELP
_TAP_CLEAR_ICON     = (480, 200)   # Icona scopa centrale per avviare pulizia
_TAP_CLOSE_BTN      = (480, 445)   # Pulsante CLOSE post-pulizia

_TPL_CLOSE          = "pin/pin_clear_cache_close.png"
_ROI_CLOSE          = (400, 425, 560, 465)  # box stretto sul pulsante CLOSE
_SOGLIA_CLOSE       = 0.85  # margine ampio: 0.028 (no popup) vs 1.000 (visibile)

# 07/06: Clear cache via MATCH DINAMICO. Diagnosi screenshot (data/cache_debug):
# la coord fissa (666,375) mancava il bottone su 8/11 istanze — il menu HELP ha
# 5 o 6 voci a seconda dell'account → "Clear cache" sta a y≈258 (5 voci) o y≈375
# (6 voci). Match del template + tap sul centro → robusto a entrambi i layout.
_TPL_CLEAR_CACHE_BTN = "pin/pin_help_clear_cache.png"
_ROI_CLEAR_CACHE     = (480, 170, 850, 440)  # colonna dx HELP (copre riga 2 e 3)
_SOGLIA_CLEAR_CACHE  = 0.80

_TIMEOUT_PULIZIA_S  = 20.0   # 07/06: 120→20s. Il CLOSE, quando appare, matcha
                             # SEMPRE a iter 1 (~6s, score 1.000); i fallimenti
                             # restano score≈-0.013 dal primo iter (popup mai
                             # aperto). Oltre ~15-20s insistere è inutile →
                             # tagliato lo spreco di ~100s/fallimento.
_POLL_CLOSE_S       = 5.0    # intervallo polling

# 07/06: cattura diagnostica del flow cache per ricalibrare le coord (il flow
# fallisce su 8/11 istanze: una tap cieca Help/Clear-cache/Clear-icon manca il
# bersaglio). Salva PNG in data/cache_debug/. DISATTIVARE dopo aver ricalibrato.
_DEBUG_CACHE = True

# Delay tra step (calibrati su PC lento — priorità stabilità su velocità)
# 29/04 (post-test prod FAU_00): tutti +50% perché 22.5s totali ancora insufficienti
_DELAY_NAV       = 4.5  # navigazione tra schermate (3.0 → 4.5)
_DELAY_TOGGLE    = 3.0  # tap toggle dentro stessa schermata (2.0 → 3.0)
_DELAY_BACK      = 3.0  # tra BACK e BACK (2.0 → 3.0)
_DELAY_PRE_CHECK = 2.5  # prima dello screenshot per check Optimize (1.5 → 2.5)


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def esegui_grafica_hq(
    ctx,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Imposta i 3 setting grafici HIGH:
      - Graphics Quality HIGH (idempotente)
      - Frame Rate MID (idempotente)
      - Optimize Mode HIGH (idempotente, pulsante distinto da Low)

    WU195 (07/07/2026) — estratta da `imposta_settings_lightweight()`
    (che faceva grafica+cache insieme) per diventare un task orchestrator
    indipendente (`tasks/grafica_hq.py::GraficaHqTask`), abilitabile/
    disabilitabile da dashboard separatamente dalla pulizia cache.

    Premessa: l'istanza deve essere in HOME stabile.
    Postcondizione: l'istanza torna in HOME via 3 BACK.

    Returns True se la sequenza è completata. False se device mancante
    o eccezione non gestita.
    """
    log = log_fn or (lambda m: None)

    if ctx.device is None:
        log("[SETTINGS] device non disponibile — skip")
        return False

    log("[SETTINGS] inizio sequenza grafica HIGH")

    try:
        # ── Step 1-3: navigazione HOME → System Settings ────────────────────
        log("[SETTINGS] tap Avatar (48, 37)")
        ctx.device.tap(*_TAP_AVATAR);          time.sleep(_DELAY_NAV)

        log("[SETTINGS] tap icona Settings (135, 478)")
        ctx.device.tap(*_TAP_SETTINGS_ICON);   time.sleep(_DELAY_NAV)

        log("[SETTINGS] tap System Settings (399, 141)")
        ctx.device.tap(*_TAP_SYSTEM_SETTINGS); time.sleep(_DELAY_NAV)

        # WU78-rev (30/04 10:30) — TAP Graphics HIGH + Frame MID + Optimize HIGH
        # (matching FAU_10 setup manuale utente). Driver Vulkan→DirectX (Issue
        # #88) ha eliminato necessità ULTRA-LOW per evitare cascade ADB,
        # quindi useremo settings di qualità migliore. Idempotenza:
        #   - Graphics slider: tap HIGH è idempotente (slider → posiz HIGH)
        #   - Frame radio MID: idempotente
        #   - Optimize HIGH: pulsante distinto da Low, idempotente
        log("[SETTINGS] tap Graphics Quality HIGH (855, 130)")
        ctx.device.tap(*_TAP_GRAPHICS_HIGH);   time.sleep(_DELAY_TOGGLE)

        log("[SETTINGS] tap Frame Rate MID (740, 215)")
        ctx.device.tap(*_TAP_FRAME_MID);       time.sleep(_DELAY_TOGGLE)

        log("[SETTINGS] tap Optimize Mode HIGH (228, 337)")
        ctx.device.tap(*_TAP_OPTIMIZE_HIGH);   time.sleep(_DELAY_TOGGLE)

        # ── BACK ×3: System Settings → Settings → Commander → HOME ──────────
        for i in (1, 2, 3):
            log(f"[SETTINGS] BACK {i}/3")
            ctx.device.back()
            time.sleep(_DELAY_BACK)

        log("[SETTINGS] sequenza grafica HIGH completata — istanza in HOME")
        return True

    except Exception as exc:
        log(f"[SETTINGS] ERRORE: {exc}")
        return False


def esegui_pulizia_cache(
    ctx,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Esegue la pulizia cache giornaliera (1×/die per istanza, via
    `data/cache_state.json`). Flow: Avatar → Settings → Help → Clear cache
    → polling CLOSE → CLOSE.

    WU195 (07/07/2026) — estratta da `imposta_settings_lightweight()` per
    diventare un task orchestrator indipendente
    (`tasks/pulizia_cache.py::PuliziaCacheTask`). Uscita anticipata se la
    cache è già stata pulita oggi: NESSUNA navigazione (prima, girando
    sempre insieme alla grafica, la navigazione era comunque necessaria per
    quella; ora da sola andrebbe evitata ad ogni ciclo se già fatta).

    Premessa: l'istanza deve essere in HOME stabile.
    Postcondizione: l'istanza torna in HOME (via 2 BACK se la pulizia è
    stata eseguita, nessun movimento se già fatta oggi).

    Returns True se già pulita oggi oppure se la sequenza è completata
    (indipendentemente dall'esito della singola pulizia, che è loggato e
    tracciato a parte in `data/cache_history.jsonl`). False se device
    mancante o eccezione non gestita.
    """
    log = log_fn or (lambda m: None)

    if ctx.device is None:
        log("[SETTINGS] device non disponibile — skip")
        return False

    nome = getattr(ctx, "instance_name", None) or "_unknown"
    if _cache_pulita_oggi(nome):
        log(f"[SETTINGS] cache già pulita oggi per {nome} — skip (nessuna navigazione)")
        return True

    log("[SETTINGS] inizio sequenza pulizia cache")

    try:
        log("[SETTINGS] tap Avatar (48, 37)")
        ctx.device.tap(*_TAP_AVATAR);          time.sleep(_DELAY_NAV)

        log("[SETTINGS] tap icona Settings (135, 478)")
        ctx.device.tap(*_TAP_SETTINGS_ICON);   time.sleep(_DELAY_NAV)

        log(f"[SETTINGS] avvio pulizia cache giornaliera per {nome}")
        _t_cache = time.time()
        _ok_cache = _pulisci_cache(ctx, log)
        _dt_cache = time.time() - _t_cache
        if _ok_cache:
            _marca_cache_pulita(nome)
            log(f"[SETTINGS] pulizia cache OK — marcata per {nome}")
            _log_cache_history(nome, "ok", _dt_cache, "pulizia completata")
        else:
            log("[SETTINGS] pulizia cache FALLITA — nessun mark")
            _log_cache_history(nome, "fail", _dt_cache,
                                "timeout polling CLOSE o tap fallito")

        # ── BACK ×2: Settings → Commander → HOME ────────────────────────────
        for i in (1, 2):
            log(f"[SETTINGS] BACK {i}/2")
            ctx.device.back()
            time.sleep(_DELAY_BACK)

        log("[SETTINGS] sequenza pulizia cache completata — istanza in HOME")
        return True

    except Exception as exc:
        log(f"[SETTINGS] ERRORE: {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Helpers privati
# ──────────────────────────────────────────────────────────────────────────────

def _cache_state_path() -> Path:
    """Path di `data/cache_state.json` (rispetta env DOOMSDAY_ROOT)."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "cache_state.json"


def _today_utc() -> str:
    """Stringa data UTC formato YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cache_pulita_oggi(nome_istanza: str) -> bool:
    """True se `data/cache_state.json[nome] == oggi UTC`. Failsafe → False."""
    try:
        path = _cache_state_path()
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get(nome_istanza) == _today_utc()
    except Exception:
        return False


def _marca_cache_pulita(nome_istanza: str) -> None:
    """Aggiorna `data/cache_state.json[nome] = oggi UTC` (atomic write)."""
    try:
        path = _cache_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data[nome_istanza] = _today_utc()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _cache_history_path() -> Path:
    """Path di `data/cache_history.jsonl` (rispetta env DOOMSDAY_ROOT)."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "cache_history.jsonl"


def _log_cache_history(nome_istanza: str, esito: str, durata_s: float, msg: str) -> None:
    """Appende un record audit (WU166) per OGNI tentativo di pulizia cache,
    ok o fallito. Best-effort: non deve mai interrompere il flow chiamante."""
    try:
        path = _cache_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "istanza": nome_istanza,
            "esito": esito,
            "durata_s": round(durata_s, 1),
            "msg": msg,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _save_cache_debug(ctx, log: Callable[[str], None], label: str) -> None:
    """07/06 diagnostica: salva screenshot del flow cache in data/cache_debug/.
    Gated da `_DEBUG_CACHE`. Best-effort, non solleva mai (non deve disturbare
    il flow). Serve a vedere il layout reale delle istanze che falliscono."""
    if not _DEBUG_CACHE or ctx.device is None:
        return
    try:
        import os, cv2
        from datetime import datetime, timezone
        screen = ctx.device.screenshot()
        frame = getattr(screen, "frame", None)
        if frame is None:
            return
        root = os.environ.get("DOOMSDAY_ROOT", ".")
        d = os.path.join(root, "data", "cache_debug")
        os.makedirs(d, exist_ok=True)
        nome = getattr(ctx, "instance_name", "?")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(d, f"{nome}_{ts}_{label}.png")
        cv2.imwrite(path, frame)
        log(f"[CACHE] debug snap → {label}")
    except Exception:
        pass


def _pulisci_cache(ctx, log: Callable[[str], None]) -> bool:
    """
    Esegue il flow Help → Clear cache → polling CLOSE → CLOSE → BACK.
    PRECONDIZIONE: ctx in pannello SETTINGS (post Avatar+Settings tap).
    POSTCONDIZIONE: torna in SETTINGS via 1 BACK finale.

    Returns True se la pulizia è completata e CLOSE intercettato. False
    se timeout polling o errore device.
    """
    if ctx.device is None:
        log("[CACHE] device assente — abort")
        return False

    try:
        # Tap Help → pannello HELP
        log("[CACHE] tap Help (570, 235)")
        ctx.device.tap(*_TAP_HELP_BTN);   time.sleep(_DELAY_NAV)

        # Tap Clear cache → popup CLEAR CACHE. MATCH DINAMICO (07/06): la y del
        # bottone varia per istanza (menu HELP 5 o 6 voci). Fallback coord storica.
        _save_cache_debug(ctx, log, "01_help_panel")  # pannello HELP (pre-tap)
        _cx, _cy = _TAP_CLEAR_CACHE
        if ctx.matcher is not None:
            try:
                _scr = ctx.device.screenshot()
                if _scr is not None:
                    _r = ctx.matcher.find_one(
                        _scr, _TPL_CLEAR_CACHE_BTN,
                        threshold=_SOGLIA_CLEAR_CACHE, zone=_ROI_CLEAR_CACHE,
                    )
                    if _r.found:
                        _cx, _cy = _r.cx, _r.cy
                        log(f"[CACHE] Clear cache match ({_cx},{_cy}) score={_r.score:.3f}")
                    else:
                        log(f"[CACHE] Clear cache NO match (score={_r.score:.3f}) "
                            f"— fallback ({_cx},{_cy})")
            except Exception as _exc:
                log(f"[CACHE] Clear cache match errore: {_exc} — fallback ({_cx},{_cy})")
        log(f"[CACHE] tap Clear cache ({_cx},{_cy})")
        ctx.device.tap(_cx, _cy); time.sleep(_DELAY_NAV)

        # Tap icona Clear centrale → avvia pulizia + progress 0..N/N
        log("[CACHE] tap Clear icon (480, 200) — avvio pulizia")
        ctx.device.tap(*_TAP_CLEAR_ICON);  time.sleep(_DELAY_TOGGLE)
        _save_cache_debug(ctx, log, "02_after_clear_icon")  # popup pulizia/CLOSE

        # Polling CLOSE: pulizia veloce (~3s, 31 file FAU_10) o lenta (file molti)
        if not _attendi_close(ctx, log):
            log("[CACHE] timeout polling CLOSE — abort")
            return False

        # Tap CLOSE → ritorna a HELP
        log("[CACHE] tap CLOSE (480, 445)")
        ctx.device.tap(*_TAP_CLOSE_BTN);   time.sleep(_DELAY_NAV)

        # BACK extra: HELP → SETTINGS (i 2 BACK finali del flow principale
        # chiuderanno SETTINGS → COMMANDER → HOME)
        log("[CACHE] BACK extra (HELP → SETTINGS)")
        ctx.device.back();                 time.sleep(_DELAY_BACK)

        return True

    except Exception as exc:
        log(f"[CACHE] errore: {exc}")
        return False


def _attendi_close(ctx, log: Callable[[str], None]) -> bool:
    """
    Polling ogni _POLL_CLOSE_S su template CLOSE finché compare (pulizia
    terminata) o timeout _TIMEOUT_PULIZIA_S. Returns True se trovato.
    """
    if ctx.matcher is None:
        log("[CACHE] matcher assente — fallback sleep fisso 10s")
        time.sleep(10.0)
        return True

    t0 = time.time()
    iter_n = 0
    while time.time() - t0 < _TIMEOUT_PULIZIA_S:
        time.sleep(_POLL_CLOSE_S)
        iter_n += 1
        try:
            screen = ctx.device.screenshot()
            if screen is None:
                continue
            result = ctx.matcher.find_one(
                screen, _TPL_CLOSE,
                threshold=_SOGLIA_CLOSE, zone=_ROI_CLOSE,
            )
            if result.found:
                log(f"[CACHE] CLOSE rilevato dopo {time.time()-t0:.0f}s "
                    f"(iter {iter_n}, score={result.score:.3f})")
                return True
            log(f"[CACHE] polling iter {iter_n}: score={result.score:.3f} "
                f"({time.time()-t0:.0f}s elapsed)")
        except Exception as exc:
            log(f"[CACHE] polling errore iter {iter_n}: {exc}")
    log(f"[CACHE] timeout {_TIMEOUT_PULIZIA_S:.0f}s senza CLOSE")
    return False


def _is_optimize_low_attivo(ctx, log: Callable[[str], None]) -> bool:
    """
    Verifica via template matching se il toggle Optimize Mode "Low" è attivo
    (riquadro arancione vs grigio). Pessimistico: se OCR/matcher non
    disponibili o screenshot fallisce, ritorna False (→ tap eseguito).
    """
    if ctx.matcher is None:
        log("[SETTINGS] matcher non disponibile — assumo non attivo")
        return False
    try:
        screen = ctx.device.screenshot()
        if screen is None:
            log("[SETTINGS] screenshot None — assumo non attivo")
            return False
        result = ctx.matcher.find_one(
            screen,
            _TPL_OPTIMIZE_LOW,
            threshold=_SOGLIA_OPTIMIZE,
            zone=_ROI_OPTIMIZE_LOW,
        )
        log(f"[SETTINGS] check Optimize: score={result.score:.3f} "
            f"(soglia {_SOGLIA_OPTIMIZE:.2f})")
        return bool(result.found)
    except Exception as exc:
        log(f"[SETTINGS] check Optimize errore: {exc} — assumo non attivo")
        return False
