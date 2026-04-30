"""
core/settings_helper.py — Imposta i settings lightweight nel client gioco.

WU60 (29/04/2026) — Fix instabilità arena via aggiornamento MuMu + settings
gioco "lightweight". Con Graphics Low + Frame Rate Low + Optimized Mode Low
il flow del bot funziona pulito anche su istanze precedentemente problematiche
(verificato su FAU_01, FAU_02, FAU_03, FAU_04 il 29/04).

WU64 (29/04/2026) — Pulizia cache giornaliera integrata. Dopo i settings,
una volta al giorno per istanza, esegue Avatar → Settings → Help → Clear
cache → polling CLOSE → CLOSE. Stato persistito in `data/cache_state.json`
(granularità giornaliera UTC).

Strategia: la funzione viene eseguita ad OGNI avvio dell'istanza per
sicurezza (anche se i settings sono persistenti, un aggiornamento del
client gioco potrebbe resettarli).

GESTIONE TOGGLE STATEFUL:
- Graphics Quality (slider): IDEMPOTENTE — tap su LOW resta su LOW
- Frame Rate (3 radio button): IDEMPOTENTE — tap su Low resta Low
- Optimize Mode (toggle Low/High): NON IDEMPOTENTE — un secondo tap
  disattiva. Verifica visuale con template `pin_settings_optimize_low_active`
  prima di tappare. Se già attivo → skip.

Uso:
    from core.settings_helper import imposta_settings_lightweight
    imposta_settings_lightweight(ctx, log_fn=lambda m: ctx.log_msg(m))

Sequenza base (~22s, ~20s se Optimize già attivo):
    1. HOME → tap Avatar (48, 37)
    2. → tap icona Settings (135, 478)
    3. → tap voce System Settings (399, 141)
    4. → tap Graphics Quality LOW (695, 129) [idempotente]
    5. → tap Frame Rate LOW (623, 215) [idempotente]
    6. → screenshot + check template pin_settings_optimize_low_active
    7. → se non attivo: tap Optimize Mode (153, 337)
    8. BACK 1 (System Settings → Settings)
    9. SE pulizia cache giornaliera da fare:
       - tap Help (570, 235) → tap Clear cache (666, 375) → tap Clear icon
         (480, 200) → polling CLOSE ogni 5s max 120s → tap CLOSE (480, 445)
       - BACK extra (Help → Settings)
       - marca cache_state per oggi
    10. BACK × 2 (Settings → Commander → HOME)

Coordinate calibrate su MuMu Player 960×540, validate su FAU_10 il 29/04.
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

_TIMEOUT_PULIZIA_S  = 120.0  # safety cap polling CLOSE (file molti)
_POLL_CLOSE_S       = 5.0    # intervallo polling

# Delay tra step (calibrati su PC lento — priorità stabilità su velocità)
# 29/04 (post-test prod FAU_00): tutti +50% perché 22.5s totali ancora insufficienti
_DELAY_NAV       = 4.5  # navigazione tra schermate (3.0 → 4.5)
_DELAY_TOGGLE    = 3.0  # tap toggle dentro stessa schermata (2.0 → 3.0)
_DELAY_BACK      = 3.0  # tra BACK e BACK (2.0 → 3.0)
_DELAY_PRE_CHECK = 2.5  # prima dello screenshot per check Optimize (1.5 → 2.5)


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def imposta_settings_lightweight(
    ctx,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Esegue la sequenza per impostare i 3 setting lightweight:
      - Graphics Quality LOW (idempotente)
      - Frame Rate LOW (idempotente)
      - Optimize Mode LOW (NON idempotente — verifica visuale prima)

    Premessa: l'istanza deve essere in HOME stabile.
    Postcondizione: l'istanza torna in HOME via 3 BACK.

    Returns True se la sequenza è completata. False se device/matcher mancano
    o eccezione non gestita.
    """
    log = log_fn or (lambda m: None)

    if ctx.device is None:
        log("[SETTINGS] device non disponibile — skip")
        return False

    log("[SETTINGS] inizio sequenza lightweight")

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

        # ── Step 7: BACK 1/3 (System Settings → Settings) ────────────────────
        log("[SETTINGS] BACK 1/3 (System Settings → Settings)")
        ctx.device.back()
        time.sleep(_DELAY_BACK)

        # ── Step 8: pulizia cache giornaliera (1x/die per istanza) ───────────
        nome = getattr(ctx, "instance_name", None) or "_unknown"
        if _cache_pulita_oggi(nome):
            log(f"[SETTINGS] cache già pulita oggi per {nome} — skip")
        else:
            log(f"[SETTINGS] avvio pulizia cache giornaliera per {nome}")
            if _pulisci_cache(ctx, log):
                _marca_cache_pulita(nome)
                log(f"[SETTINGS] pulizia cache OK — marcata per {nome}")
            else:
                log("[SETTINGS] pulizia cache FALLITA — nessun mark")

        # ── Step 9-10: BACK 2/3 + 3/3 → HOME ────────────────────────────────
        for i in (2, 3):
            log(f"[SETTINGS] BACK {i}/3")
            ctx.device.back()
            time.sleep(_DELAY_BACK)

        log("[SETTINGS] sequenza completata — istanza in HOME")
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

        # Tap Clear cache → popup CLEAR CACHE
        log("[CACHE] tap Clear cache (666, 375)")
        ctx.device.tap(*_TAP_CLEAR_CACHE); time.sleep(_DELAY_NAV)

        # Tap icona Clear centrale → avvia pulizia + progress 0..N/N
        log("[CACHE] tap Clear icon (480, 200) — avvio pulizia")
        ctx.device.tap(*_TAP_CLEAR_ICON);  time.sleep(_DELAY_TOGGLE)

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
