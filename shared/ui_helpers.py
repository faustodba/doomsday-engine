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
