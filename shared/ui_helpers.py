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


# ==============================================================================
# Loading splash detection (auto-WU22)
# ==============================================================================

# Anchor splash gioco — 2 template OR per resilienza a cambio sfondo (29/04/2026):
#  1. Live Chat (testo+icona cuffia, basso-sx) — primario
#  2. Version (testo "Version" alto-dx) — fallback se sfondo splash cambia
# Match OR: se UNO dei due ≥ soglia → splash attivo.
# Posizione invariante (la grafica di sfondo cambia per evento ma testo+UI no).
_SPLASH_TMPL_LIVECHAT = "pin/pin_loading_livechat.png"
_SPLASH_ROI_LIVECHAT  = (20, 470, 160, 525)   # basso-sx, larga
_SPLASH_TMPL_VERSION  = "pin/pin_loading_version.png"
_SPLASH_ROI_VERSION   = (810, 22, 900, 55)    # alto-dx, ampia per tolleranza
_SPLASH_SOGLIA        = 0.75


def is_loading_splash(ctx, log_fn=None) -> bool:
    """
    Verifica se la schermata corrente è il LOADING SPLASH del gioco.

    Detection: cerca uno di 2 template anchor in zone separate:
      1. `pin_loading_livechat.png` nella ROI bottom-left ("Live Chat" widget)
      2. `pin_loading_version.png`  nella ROI top-right ("Version" testo)
    Se UNO dei due ≥ soglia → splash attivo. La logica OR rende il check
    resiliente al cambio dello sfondo grafico (eventi/season/update gioco):
    se anche il widget Live Chat cambia stile, il testo "Version" resta.

    Da chiamare quando schermata == UNKNOWN per decidere strategia:
      - splash=True  → wait passivo (no BACK, lascia caricare)
      - splash=False → popup persistente, prova dismiss_banners_loop / BACK

    Args:
        ctx: oggetto con .device + .matcher
        log_fn: logger opzionale

    Returns:
        True se siamo in loading splash, False altrimenti.
    """
    log = log_fn or (lambda _msg: None)
    if ctx.device is None or ctx.matcher is None:
        return False
    try:
        screen = ctx.device.screenshot()
        if screen is None:
            return False

        # Anchor 1: Live Chat
        try:
            score_lc = ctx.matcher.score(screen, _SPLASH_TMPL_LIVECHAT, zone=_SPLASH_ROI_LIVECHAT)
        except FileNotFoundError:
            score_lc = 0.0
        if score_lc >= _SPLASH_SOGLIA:
            log(f"[SPLASH] Live Chat rilevato (score={score_lc:.3f}) — gioco in caricamento")
            return True

        # Anchor 2: Version (fallback)
        try:
            score_ver = ctx.matcher.score(screen, _SPLASH_TMPL_VERSION, zone=_SPLASH_ROI_VERSION)
        except FileNotFoundError:
            score_ver = 0.0
        if score_ver >= _SPLASH_SOGLIA:
            log(f"[SPLASH] Version rilevato (score={score_ver:.3f}) — gioco in caricamento")
            return True

        return False
    except Exception as exc:
        log(f"[SPLASH] errore detection: {exc}")
        return False


# ==============================================================================
# Banner catalog — dismissal pipeline (auto-WU21)
# ==============================================================================

def dismiss_banners_loop(ctx, max_iter: int = 8, log_fn=None) -> dict[str, int]:
    """
    Itera screenshot + match contro BANNER_CATALOG e applica l'azione di
    chiusura specifica per ogni banner riconosciuto. Continua finché:
      - nessun banner viene trovato in un'iterazione (uscita pulita), OR
      - max_iter raggiunto (safety cap).

    Da chiamare in `attendi_home` PRIMA del polling cieco BACK per ridurre
    UNKNOWN polls e tempo di stabilizzazione.

    Args:
        ctx:      TaskContext con device + matcher
        max_iter: cap iterazioni (default 8)
        log_fn:   logger opzionale

    Returns:
        dict {banner_name: count} = quante volte ogni banner è stato chiuso.
        Vuoto se nessun banner trovato.
    """
    import time as _t
    from shared.banner_catalog import BANNER_CATALOG

    log = log_fn or (lambda _msg: None)
    counts: dict[str, int] = {}

    if ctx.device is None or ctx.matcher is None:
        return counts

    # Catalog ordinato per priority
    catalog = sorted(BANNER_CATALOG, key=lambda b: b.priority)

    for it in range(max_iter):
        screen = ctx.device.screenshot()
        if screen is None:
            log(f"[BANNER-LOOP] iter {it+1}: screenshot None — break")
            break

        any_dismissed = False
        for spec in catalog:
            try:
                score = ctx.matcher.score(screen, spec.template, zone=spec.roi)
            except FileNotFoundError:
                # Template placeholder non ancora estratto — ignora silenziosamente
                continue
            except Exception as exc:
                log(f"[BANNER-LOOP] {spec.name} match errore: {exc}")
                continue

            if score >= spec.threshold:
                # Apply dismiss action — auto-WU22 supporta 2 pattern principali
                # ("tap_template" per pulsanti dinamici, "tap_x_topright" per X)
                # + legacy ("back", "tap_coords", "tap_center").
                action_done = False
                action_label = ""

                if spec.dismiss_action == "tap_template" and spec.dismiss_template:
                    # PATTERN 1 — pulsante con scritta (Continue/OK/Skip/...).
                    # find_one del template e tap sulla posizione del match.
                    btn_roi = spec.dismiss_template_roi or spec.roi
                    btn_soglia = spec.dismiss_template_soglia or spec.threshold
                    try:
                        match = ctx.matcher.find_one(
                            screen, spec.dismiss_template,
                            threshold=btn_soglia, zone=btn_roi,
                        )
                    except FileNotFoundError:
                        log(f"[BANNER-LOOP] {spec.name} dismiss_template non trovato: {spec.dismiss_template} — skip")
                        continue
                    except Exception as exc:
                        log(f"[BANNER-LOOP] {spec.name} dismiss_template errore: {exc}")
                        continue
                    if match is not None and match.found:
                        ctx.device.tap(match.cx, match.cy)
                        action_label = f"tap_template@({match.cx},{match.cy}) score={match.score:.3f}"
                        action_done = True
                    else:
                        # Pulsante non rilevato sebbene banner sì → fallback X top-right
                        from shared.banner_catalog import DEFAULT_X_TOPRIGHT
                        x, y = spec.dismiss_coords or DEFAULT_X_TOPRIGHT
                        ctx.device.tap(x, y)
                        action_label = f"tap_template→fallback_X@({x},{y})"
                        action_done = True

                elif spec.dismiss_action == "tap_x_topright":
                    # PATTERN 2 — X close in alto a destra (canonico o override)
                    from shared.banner_catalog import DEFAULT_X_TOPRIGHT
                    x, y = spec.dismiss_coords or DEFAULT_X_TOPRIGHT
                    ctx.device.tap(x, y)
                    action_label = f"tap_X@({x},{y})"
                    action_done = True

                elif spec.dismiss_action == "tap_coords" and spec.dismiss_coords:
                    ctx.device.tap(*spec.dismiss_coords)
                    action_label = f"tap_coords@{spec.dismiss_coords}"
                    action_done = True

                elif spec.dismiss_action == "tap_center":
                    ctx.device.tap(480, 270)
                    action_label = "tap_center"
                    action_done = True

                elif spec.dismiss_action == "back":
                    ctx.device.back()
                    action_label = "back"
                    action_done = True

                else:
                    log(f"[BANNER-LOOP] {spec.name} dismiss_action sconosciuta: {spec.dismiss_action} — skip")
                    continue

                if action_done:
                    _t.sleep(spec.wait_after_s)
                    counts[spec.name] = counts.get(spec.name, 0) + 1
                    any_dismissed = True
                    log(f"[BANNER-LOOP] {spec.name} chiuso (score={score:.3f}) {action_label} iter {it+1}")
                    break  # ricomincia screenshot da zero

        if not any_dismissed:
            # Nessun banner CATALOGATO trovato in questa iter.
            # Issue #66 — strategia universale 3-step:
            #   (A) Match X universale in zona top-right ampia → tap su match
            #   (B) Check HOME/MAP via pin_region/pin_shelter → break clean
            #   (C) Altrimenti → break (caller gestisce con BACK/fallback)

            # Step A1 — match X cerchio dorato (eventi promo: Pompeii, AFK reward).
            # ROI ampia (700,0,960,200) per coprire posizioni note: Pompeii
            # (870,97), AFK Region (825,138), e simili.
            try:
                xres = ctx.matcher.find_one(
                    screen, "pin/pin_btn_x_close.png",
                    threshold=0.75, zone=(700, 0, 960, 200),
                )
                if xres is not None and xres.found:
                    ctx.device.tap(xres.cx, xres.cy)
                    counts["_unmatched_tap_x"] = counts.get("_unmatched_tap_x", 0) + 1
                    log(
                        f"[BANNER-LOOP] iter {it+1} X cerchio dorato match "
                        f"score={xres.score:.3f} → tap@({xres.cx},{xres.cy})"
                    )
                    _t.sleep(1.0)
                    continue
            except FileNotFoundError:
                pass  # template non deployato → step A2
            except Exception as exc:
                log(f"[BANNER-LOOP] X match errore: {exc}")

            # Step A2 — match freccia BACK (schermate nidificate: Alliance,
            # Hero, Bag, profili, sub-tab). ROI top-left ristretta (no avatar
            # HOME). Soglia 0.85 più alta — simbolo distintivo.
            try:
                bres = ctx.matcher.find_one(
                    screen, "pin/pin_btn_back_arrow.png",
                    threshold=0.85, zone=(0, 0, 100, 80),
                )
                if bres is not None and bres.found:
                    ctx.device.tap(bres.cx, bres.cy)
                    counts["_unmatched_tap_back"] = counts.get("_unmatched_tap_back", 0) + 1
                    log(
                        f"[BANNER-LOOP] iter {it+1} freccia BACK match "
                        f"score={bres.score:.3f} → tap@({bres.cx},{bres.cy})"
                    )
                    _t.sleep(1.0)
                    continue
            except FileNotFoundError:
                pass
            except Exception as exc:
                log(f"[BANNER-LOOP] BACK arrow match errore: {exc}")

            # Step B — HOME/MAP raggiunta? break pulito
            try:
                score_home = ctx.matcher.score(screen, "pin/pin_region.png")
                score_map = ctx.matcher.score(screen, "pin/pin_shelter.png")
                if score_home >= 0.70 or score_map >= 0.70:
                    log(f"[BANNER-LOOP] HOME/MAP pulita dopo {it} iter, dismissed={counts}")
                    break
            except Exception:
                pass

            # Step C — break: caller (vai_in_home / attendi_home) gestisce con
            # BACK o fallback proprio.
            if it == 0:
                log("[BANNER-LOOP] nessun banner riconosciuto al primo scan")
            else:
                log(f"[BANNER-LOOP] no banner+no X+no HOME dopo {it} iter — break")
            break
    else:
        log(f"[BANNER-LOOP] max_iter={max_iter} raggiunto, dismissed={counts}")

    return counts
