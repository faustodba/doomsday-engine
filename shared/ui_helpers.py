# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/ui_helpers.py
#
#  Helper UI condivisi tra tutti i task.
#  Funzioni di attesa/polling per maschere e template.
# ==============================================================================

from __future__ import annotations
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.task import TaskContext


def attendi_template(
    ctx: "TaskContext",
    tmpl: str,
    soglia: float,
    timeout: float = 5.0,
    poll: float = 0.7,
    zone: Optional[tuple] = None,
    log_prefix: str = "",
    initial_delay: float = 0.0,
) -> float:
    """
    Polling con timeout: verifica il template ogni `poll` secondi
    fino a timeout. Ritorna lo score al momento del rilevamento
    (>= soglia) oppure l'ultimo score se timeout.

    Args:
        ctx:           TaskContext con device e matcher
        tmpl:          path template relativo a templates/
        soglia:        score minimo per considerare trovato
        timeout:       secondi massimi di attesa (default 5.0)
        poll:          intervallo tra tentativi in secondi (default 0.7,
                       margine per macchine con HDD lento)
        zone:          ROI opzionale (x1,y1,x2,y2) per limitare la ricerca
        log_prefix:    prefisso per il log (es. "[BOOST]")
        initial_delay: attesa iniziale prima del primo tentativo (default
                       0.0). Utile per UI in transizione dopo un tap.

    Returns:
        float: score al momento del rilevamento oppure ultimo score
    """
    if initial_delay > 0:
        time.sleep(initial_delay)
    t_start = time.time()
    score   = 0.0
    while time.time() - t_start < timeout:
        screen = ctx.device.screenshot()
        if screen is None:
            time.sleep(poll)
            continue
        if zone:
            r = ctx.matcher.find_one(screen, tmpl, threshold=soglia, zone=zone)
            score = r.score if r else 0.0
        else:
            score = ctx.matcher.score(screen, tmpl)
        elapsed = time.time() - t_start
        if score >= soglia:
            if log_prefix:
                ctx.log_msg(
                    f"{log_prefix} {tmpl}: score={score:.3f} → OK "
                    f"({elapsed:.1f}s)"
                )
            return score
        time.sleep(poll)
    if log_prefix:
        ctx.log_msg(
            f"{log_prefix} {tmpl}: timeout {timeout}s — "
            f"ultimo score={score:.3f}"
        )
    return score


def attendi_scomparsa_template(
    ctx: "TaskContext",
    tmpl: str,
    soglia: float,
    timeout: float = 5.0,
    poll: float = 0.7,
) -> bool:
    """
    Attende che il template scompaia (score < soglia).
    Utile per verificare chiusura popup, maschere, ecc.

    Returns:
        True  — template scomparso entro timeout
        False — template ancora presente a timeout
    """
    t_start = time.time()
    while time.time() - t_start < timeout:
        screen = ctx.device.screenshot()
        if screen is None:
            time.sleep(poll)
            continue
        score = ctx.matcher.score(screen, tmpl)
        if score < soglia:
            return True
        time.sleep(poll)
    return False


# ==============================================================================
# Banner eventi HOME — collasso permanente per migliorare visibilità campo
# ==============================================================================

# Coordinate e template del banner eventi (ROI in alto sulla HOME).
# Stessi valori di tasks/store.py (StoreConfig.banner_*) — duplicati qui per
# evitare import circolare. Aggiornare insieme se i template cambiano.
_BANNER_TAP_X       = 345
_BANNER_TAP_Y       = 63
_BANNER_ROI_PIN     = (330, 40, 365, 90)
_BANNER_TMPL_APERTO = "pin/pin_banner_aperto.png"
_BANNER_TMPL_CHIUSO = "pin/pin_banner_chiuso.png"
_BANNER_SOGLIA      = 0.85


def comprimi_banner_home(ctx: "TaskContext", log_fn=None) -> str:
    """
    Collassa il banner eventi della HOME una volta per tutte (auto-WU10).

    Da chiamare DOPO `attendi_home()` all'avvio dell'istanza, non durante
    i task: chiudere il banner aumenta la zona visibile del campo gioco
    (ROI utili passano da y=115 a y=70, +45px) e migliora i template match
    di tutti i task successivi.

    Idempotente: se il banner è già chiuso o non rilevato, non fa nulla.

    Returns:
        "aperto"      — banner era aperto, è stato collassato
        "chiuso"      — banner già chiuso, no-op
        "sconosciuto" — non rilevato, no-op
    """
    log = log_fn or (lambda _msg: None)
    screen = ctx.device.screenshot()
    if screen is None:
        log("[BANNER] screenshot None — skip")
        return "sconosciuto"

    s_ap = ctx.matcher.score(screen, _BANNER_TMPL_APERTO, zone=_BANNER_ROI_PIN)
    s_ch = ctx.matcher.score(screen, _BANNER_TMPL_CHIUSO, zone=_BANNER_ROI_PIN)

    if s_ap >= _BANNER_SOGLIA and s_ap > s_ch:
        log(f"[BANNER] aperto (score={s_ap:.3f}) — tap collasso ({_BANNER_TAP_X},{_BANNER_TAP_Y})")
        ctx.device.tap(_BANNER_TAP_X, _BANNER_TAP_Y)
        time.sleep(0.6)
        # Verifica chiusura
        shot2 = ctx.device.screenshot()
        if shot2 is not None:
            s_ch2 = ctx.matcher.score(shot2, _BANNER_TMPL_CHIUSO, zone=_BANNER_ROI_PIN)
            if s_ch2 >= _BANNER_SOGLIA:
                log(f"[BANNER] chiuso ✓ (score={s_ch2:.3f})")
            else:
                log(f"[BANNER] chiusura non confermata (score chiuso={s_ch2:.3f}) — procedo")
        return "aperto"

    if s_ch >= _BANNER_SOGLIA and s_ch > s_ap:
        log(f"[BANNER] già chiuso (score={s_ch:.3f}) — no-op")
        return "chiuso"

    log(f"[BANNER] non rilevato (aperto={s_ap:.3f} chiuso={s_ch:.3f}) — no-op")
    return "sconosciuto"
