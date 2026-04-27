# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/boost.py
#
#  Task: attivazione Gathering Speed Boost con scheduling intelligente.
#
#  REFACTORING 16/04/2026 — BoostState:
#    - Scheduling centralizzato in BoostState (core/state.py)
#    - should_run() legge ctx.state.boost.should_run() — nessuna logica in main.py
#    - Quando boost trovato GIÀ ATTIVO → registra_attivo("8h", now) (default)
#    - Quando boost attivato → registra_attivo(tipo, now)
#    - Quando nessun boost → registra_non_disponibile() → riprova al prossimo tick
#    - Interval fisso rimosso da _TASK_SETUP — la scadenza governa il timing
#
#  FIX 19/04/2026 — ripristino comportamento V5 sotto-maschera USE:
#    Dopo il tap su "Gathering Speed" veniva fatto 1 screenshot dopo 0.5s
#    fissi. Provato con polling 5s (commit a0f344a) → nessun miglioramento.
#    Provato con tap su (speed_cx, speed_cy) (commit 08069fc) → peggio,
#    il tap sull'icona non apriva la sotto-maschera.
#    Ripristinato V5: tap su (480, speed_cy) con X fisso centro schermo +
#    time.sleep(2.0) fisso + singolo screenshot. V5 produzione conferma
#    che questa combinazione apre correttamente la sotto-maschera USE.
#
#  FIX 19/04/2026 — ricentro riga Gathering Speed post-swipe:
#    Problema: dopo N swipe la lista popup ha un offset interno che rende
#    il tap (480, speed_cy) non responsivo (UI non cambia, pin_speed_use
#    mai trovato, score=-1.000 su tutte le istanze).
#    Causa: il tap viene eseguito ma il gioco non registra l'evento perché
#    la riga è in posizione "di scorrimento" instabile nel viewport.
#    Fix: quando pin_speed trovato dopo swipe > 0, eseguire un mini-swipe
#    inverso (giù) per riportare la riga verso il centro schermo, poi
#    ri-rilevare la posizione aggiornata prima del tap.
#    Fix aggiuntivi: delay post-tap-boost 1.5s (come V5), polling
#    pin_speed_use con timeout 4s invece di singolo screenshot.
#
#  Flusso:
#    1. should_run() → legge BoostState: skip se boost attivo e non in scadenza
#    2. Assicura HOME via navigator
#    3. Screenshot + tap TAP_BOOST → apre Manage Shelter
#    4. Verifica pin_manage → popup aperto
#    5. Scroll finché pin_speed visibile (max MAX_SWIPE)
#    6. Se pin_50_ visibile → boost già attivo → registra "8h" → chiudi popup
#    7. [FIX] Se swipe > 0 → ricentro riga con mini-swipe inverso + ri-rilevamento
#    8. Tap riga Gathering Speed (480, speed_cy)
#    9. [FIX] Polling fino a pin_speed_use visibile (timeout 4s)
#   10. Cerca pin_speed_8h + pin_speed_use → tap USE → registra "8h"
#   11. Fallback: cerca pin_speed_1d + pin_speed_use → tap USE → registra "1d"
#   12. Nessun boost → registra_non_disponibile() → chiudi popup
#
#  Logging BoostState:
#    [BOOST] stato: tipo=8h  scadenza=2026-04-16T16:00:00+00:00  ATTIVO (+7h45m)
#    [BOOST] → skip (boost attivo)
#    [BOOST] → entra (boost scaduto/in scadenza)
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult
from core.state import BoostState

if TYPE_CHECKING:
    from core.device import FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# Debug — salvataggio screenshot per ispezione UI
# ==============================================================================

# DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta (wait_after_tap_speed: 2.0s)
# Funzione mantenuta per riattivazione futura. Per riabilitare, decommentare le
# chiamate `_salva_debug_shot(...)` in _esegui_boost (cerca "DEBUG DISATTIVATO").
def _salva_debug_shot(screen, suffisso: str, log) -> None:
    """
    Salva screenshot corrente in debug_task/boost/.
    Filename: boost_{suffisso}_{YYYYMMDD_HHMMSS}.png
    Usa cv2.imwrite sul frame BGR. .gitignore esclude *.png.
    """
    try:
        import cv2
        from datetime import datetime as _dt
        frame = getattr(screen, "frame", None)
        if frame is None:
            return
        root = Path(__file__).resolve().parents[1]
        out_dir = root / "debug_task" / "boost"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"boost_{suffisso}_{ts}.png"
        filepath = out_dir / filename
        cv2.imwrite(str(filepath), frame)
        log(f"[DEBUG] screenshot salvato: debug_task/boost/{filename}")
    except Exception as exc:
        log(f"[DEBUG] salvataggio screenshot fallito: {exc}")


@dataclass
class BoostConfig:
    tap_boost:                tuple[int, int] = (142, 47)
    n_back_chiudi:            int             = 3
    max_swipe:                int             = 8
    swipe_x:                  int             = 480
    swipe_y_start:            int             = 380
    swipe_y_end:              int             = 280
    swipe_dur_ms:             int             = 400
    wait_after_tap_boost:     float           = 1.5    # FIX: come V5, prima del polling manage
    wait_after_swipe:         float           = 1.5
    wait_after_use:           float           = 1.5
    wait_after_back:          float           = 0.5
    wait_after_tap_speed:     float           = 2.0    # regola DELAY UI — da fix rifornimento 20/04/2026
    # FIX ricentro: mini-swipe inverso (dito scende = lista sale = riga scende nel viewport)
    ricentro_swipe_y_start:   int             = 280    # da dove parte il dito
    ricentro_swipe_y_end:     int             = 360    # dove arriva (80px verso il basso)
    ricentro_swipe_dur_ms:    int             = 300
    wait_after_ricentro:      float           = 1.2
    # FIX polling pin_speed_use dopo tap riga
    timeout_speed_use:        float           = 4.0    # polling finché sotto-maschera si apre
    poll_speed_use:           float           = 0.5
    tmpl_boost:               str             = "pin/pin_boost.png"
    tmpl_manage:              str             = "pin/pin_manage.png"
    tmpl_speed:               str             = "pin/pin_speed.png"
    tmpl_50:                  str             = "pin/pin_50_.png"
    tmpl_speed_8h:            str             = "pin/pin_speed_8h.png"
    tmpl_speed_1d:            str             = "pin/pin_speed_1d.png"
    tmpl_speed_use:           str             = "pin/pin_speed_use.png"
    soglia_boost:             float           = 0.80
    soglia_manage:            float           = 0.75
    soglia_speed:             float           = 0.75
    soglia_50:                float           = 0.75
    soglia_8h:                float           = 0.75
    soglia_1d:                float           = 0.75
    soglia_use:               float           = 0.75


class _Outcome:
    GIA_ATTIVO        = "boost_gia_attivo"
    ATTIVATO_8H       = "boost_attivato_8h"
    ATTIVATO_1D       = "boost_attivato_1d"
    NESSUN_BOOST      = "nessun_boost_disponibile"
    POPUP_NON_APERTO  = "popup_non_aperto"
    SPEED_NON_TROVATO = "speed_non_trovato"
    ERRORE            = "errore"


class BoostTask(Task):
    """
    Attiva Gathering Speed Boost con scheduling intelligente via BoostState.

    Scheduling: non usa interval fisso in _TASK_SETUP.
    La decisione di eseguire è delegata a ctx.state.boost.should_run():
      - boost attivo e non in scadenza → skip
      - boost scaduto / mai attivato / nessun boost trovato → esegue
    """

    def __init__(self, config: BoostConfig | None = None) -> None:
        self._cfg = config or BoostConfig()

    def name(self) -> str:
        return "boost"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("boost"):
                return False
        return ctx.state.boost.should_run()

    def run(self, ctx: TaskContext) -> TaskResult:
        def log(msg: str) -> None:
            ctx.log_msg(f"[BOOST] {msg}")

        # Log stato boost corrente
        log(f"stato: {ctx.state.boost.log_stato()}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="assicura_home")

        try:
            outcome, tipo_attivato = self._esegui_boost(ctx.device, ctx.matcher, log, self._cfg)
        except Exception as exc:
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_boost")

        # ── Aggiorna BoostState ───────────────────────────────────────────────
        now = datetime.now(timezone.utc)

        if outcome in (_Outcome.GIA_ATTIVO, _Outcome.ATTIVATO_8H, _Outcome.ATTIVATO_1D):
            tipo = tipo_attivato or "8h"
            ctx.state.boost.registra_attivo(tipo, riferimento=now)
            log(f"BoostState aggiornato → {ctx.state.boost.log_stato()}")

        elif outcome == _Outcome.NESSUN_BOOST:
            ctx.state.boost.registra_non_disponibile()
            log("BoostState → nessun boost disponibile, riprova al prossimo tick")

        # Per POPUP_NON_APERTO / SPEED_NON_TROVATO / ERRORE non alteriamo lo state:
        # il task riproverà al prossimo tick secondo la scadenza esistente.

        return self._mappa_outcome(outcome, log, tipo_attivato=tipo_attivato)

    # ── Flusso principale ─────────────────────────────────────────────────────

    def _esegui_boost(
        self,
        device,
        matcher,
        log,
        cfg: BoostConfig,
    ) -> tuple[str, str | None]:
        """
        Esegue il flusso boost.
        Ritorna (outcome, tipo) dove tipo è "8h" | "1d" | None.
        """

        # STEP 1 — tap boost
        shot    = device.screenshot()
        score_b = matcher.score(shot, cfg.tmpl_boost)
        log(f"pin_boost score={score_b:.3f} → tap {cfg.tap_boost}")
        device.tap(*cfg.tap_boost)

        # FIX: delay post-tap come V5 (1.5s) prima del polling manage
        # Senza questo delay il polling parte mentre l'animazione di apertura
        # del popup non è ancora iniziata.
        time.sleep(cfg.wait_after_tap_boost)

        # STEP 2 — attesa polling popup Manage Shelter (max 6s)
        # Nota: il sleep sopra già copre il primo secondo, quindi il timeout
        # effettivo è 6s aggiuntivi oltre al wait_after_tap_boost.
        score_m = self._attendi_template(
            device, matcher, cfg.tmpl_manage, cfg.soglia_manage,
            timeout=6.0, poll=0.5
        )
        log(f"pin_manage score={score_m:.3f}")
        if score_m < cfg.soglia_manage:
            log("Popup non aperto — abort")
            self._chiudi_popup(device, cfg)
            return _Outcome.POPUP_NON_APERTO, None

        # STEP 3 — scroll fino a pin_speed
        speed_trovato = False
        speed_cx      = -1
        speed_cy      = -1
        score_50_last = -1.0
        swipe_eseguiti = 0

        for swipe_n in range(cfg.max_swipe + 1):
            shot        = device.screenshot()
            score_speed = matcher.score(shot, cfg.tmpl_speed)
            score_50    = matcher.score(shot, cfg.tmpl_50)
            log(f"swipe {swipe_n:02d} → pin_speed={score_speed:.3f}  pin_50_={score_50:.3f}")

            if score_speed >= cfg.soglia_speed:
                match = matcher.find_one(shot, cfg.tmpl_speed, threshold=cfg.soglia_speed)
                if match and match.found:
                    speed_cx = match.cx
                    speed_cy = match.cy
                else:
                    speed_cx = 480
                    speed_cy = 270
                speed_trovato  = True
                score_50_last  = score_50
                swipe_eseguiti = swipe_n
                log(f"pin_speed TROVATO cx={speed_cx} cy={speed_cy} (dopo {swipe_n} swipe)")
                break

            score_50_last = max(score_50_last, score_50)
            if swipe_n < cfg.max_swipe:
                self._swipe_su(device, cfg)

        if not speed_trovato:
            log(f"pin_speed non trovato dopo {cfg.max_swipe} swipe — abort")
            self._chiudi_popup(device, cfg)
            return _Outcome.SPEED_NON_TROVATO, None

        # STEP 4 — boost già attivo?
        if score_50_last >= cfg.soglia_50:
            log(f"Boost GIÀ ATTIVO (pin_50_ score={score_50_last:.3f}) → registra 8h e chiudo")
            self._chiudi_popup(device, cfg)
            return _Outcome.GIA_ATTIVO, "8h"

        # STEP 4b — ricentro riga post-swipe RIMOSSO per test isolato
        # (test: verificare se tap su (speed_cx, speed_cy) centra correttamente
        # la riga sull'icona pin_speed senza passare per ricentro mini-swipe).

        # DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta. Per riabilitare,
        # decommentare le 3 righe sotto.
        # shot_pre = device.screenshot()
        # if shot_pre is not None:
        #     _salva_debug_shot(shot_pre, "pre_tap", log)

        # STEP 5 — tap riga Gathering Speed
        # TEST ISOLATO 19/04/2026: tap su (speed_cx, speed_cy) invece di
        # (480, speed_cy). Obiettivo: isolare l'effetto del tap esattamente
        # sul centro del match pin_speed, specie quando la riga è in fondo
        # alla lista (cy alto, es. 452 osservato) dove (480, cy) cadeva in
        # zona non responsiva.
        tap_speed = (speed_cx, speed_cy)
        log(f"Tap Gathering Speed {tap_speed}")
        device.tap(*tap_speed)

        # STEP 6 — FIX polling pin_speed_use (timeout 4s)
        # Sostituisce il singolo screenshot fisso a 2.0s.
        # La sotto-maschera USE impiega variabile 0.5–2.5s ad aprirsi
        # a seconda del carico del dispositivo. Il polling garantisce
        # di catturare il frame corretto indipendentemente dalla latenza.
        time.sleep(cfg.wait_after_tap_speed)  # attesa rendering popup USE (regola DELAY UI — da fix rifornimento 20/04/2026)
        shot = self._attendi_frame_use(device, matcher, cfg, log)

        # DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta. Per riabilitare,
        # decommentare le 2 righe sotto.
        # if shot is not None:
        #     _salva_debug_shot(shot, "post_tap", log)

        if shot is None:
            log("Screenshot fallito dopo tap speed — abort")
            self._chiudi_popup(device, cfg)
            return _Outcome.ERRORE, None

        # STEP 7-8 — boost 8h preferito, 1d fallback.
        # FIX 26/04 (auto-WU9): row alignment check tra template durata e
        # bottone USE. Pre-fix: `matcher.score()` ritornava la correlazione
        # max nell'INTERA immagine, sensibile a falsi positivi (pin_speed_8h
        # matchava elementi UI fuori dal popup), causando registrazione "8h"
        # quando in realtà il bot tappava USE associato al 1d.
        # Post-fix: `find_one()` con soglia + verifica |cy_durata - cy_use|
        # < 50px → garantisce che la durata associata a USE sia quella
        # registrata (stessa riga del popup).
        match_8h  = matcher.find_one(shot, cfg.tmpl_speed_8h, threshold=cfg.soglia_8h)
        match_1d  = matcher.find_one(shot, cfg.tmpl_speed_1d, threshold=cfg.soglia_1d)
        match_use = matcher.find_one(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)

        score_8h  = match_8h.score  if (match_8h  and match_8h.found)  else -1.0
        score_1d  = match_1d.score  if (match_1d  and match_1d.found)  else -1.0
        score_use = match_use.score if (match_use and match_use.found) else -1.0

        cy_8h     = match_8h.cy     if (match_8h  and match_8h.found)  else None
        cy_1d     = match_1d.cy     if (match_1d  and match_1d.found)  else None
        cy_use    = match_use.cy    if (match_use and match_use.found) else None

        log(f"pin_speed_8h={score_8h:.3f} (cy={cy_8h})  "
            f"pin_speed_1d={score_1d:.3f} (cy={cy_1d})  "
            f"pin_speed_use={score_use:.3f} (cy={cy_use})")

        if match_use is None or not match_use.found:
            log("Nessun pin_speed_use — chiudo popup")
            self._chiudi_popup(device, cfg)
            return _Outcome.NESSUN_BOOST, None

        ROW_TOL = 50  # tolleranza Y per "stessa riga"
        aligned_8h = cy_8h is not None and abs(cy_8h - cy_use) < ROW_TOL
        aligned_1d = cy_1d is not None and abs(cy_1d - cy_use) < ROW_TOL

        # Preferenza 8h (se allineato), altrimenti 1d (se allineato)
        if aligned_8h:
            log(f"Boost 8h ALLINEATO USE (Δcy={abs(cy_8h-cy_use)}) → tap USE "
                f"({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            time.sleep(cfg.wait_after_use)
            device.back()
            time.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_8H, "8h"

        if aligned_1d:
            log(f"Boost 1d ALLINEATO USE (Δcy={abs(cy_1d-cy_use)}) → tap USE "
                f"({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            time.sleep(cfg.wait_after_use)
            device.back()
            time.sleep(cfg.wait_after_back)
            return _Outcome.ATTIVATO_1D, "1d"

        log(f"USE presente ma nessuna durata (8h/1d) allineata sulla stessa riga "
            f"(Δcy_8h={abs(cy_8h-cy_use) if cy_8h is not None else 'n/a'}, "
            f"Δcy_1d={abs(cy_1d-cy_use) if cy_1d is not None else 'n/a'}) — "
            f"skip per evitare registrazione errata")
        self._chiudi_popup(device, cfg)
        return _Outcome.NESSUN_BOOST, None

        log("Nessun boost gratuito disponibile — chiudo popup")
        self._chiudi_popup(device, cfg)
        return _Outcome.NESSUN_BOOST, None

    # ── Helper ────────────────────────────────────────────────────────────────

    def _chiudi_popup(self, device, cfg: BoostConfig) -> None:
        for _ in range(cfg.n_back_chiudi):
            device.back()
            time.sleep(cfg.wait_after_back)

    def _swipe_su(self, device, cfg: BoostConfig) -> None:
        device.swipe(
            cfg.swipe_x, cfg.swipe_y_start,
            cfg.swipe_x, cfg.swipe_y_end,
            cfg.swipe_dur_ms,
        )
        time.sleep(cfg.wait_after_swipe)

    def _attendi_template(self, device, matcher, tmpl: str,
                          soglia: float, timeout: float = 5.0,
                          poll: float = 0.5) -> float:
        """
        Polling con timeout: verifica il template ogni `poll` secondi
        fino a timeout. Ritorna lo score al momento del rilevamento
        (>= soglia) oppure l'ultimo score se timeout.
        """
        t_start = time.time()
        score = 0.0
        while time.time() - t_start < timeout:
            shot = device.screenshot()
            if shot is None:
                time.sleep(poll)
                continue
            score = matcher.score(shot, tmpl)
            if score >= soglia:
                return score
            time.sleep(poll)
        return score

    def _attendi_frame_use(self, device, matcher, cfg: BoostConfig, log) -> object | None:
        """
        Polling post-tap riga: attende che pin_speed_use sia visibile
        oppure che il timeout sia scaduto.
        Ritorna il frame (screenshot) al momento del rilevamento, o
        l'ultimo frame valido se timeout.
        Logga lo score ad ogni poll per diagnostica.
        """
        t_start  = time.time()
        last_shot = None
        poll_n    = 0

        while time.time() - t_start < cfg.timeout_speed_use:
            shot = device.screenshot()
            if shot is None:
                time.sleep(cfg.poll_speed_use)
                poll_n += 1
                continue

            last_shot  = shot
            score_use  = matcher.score(shot, cfg.tmpl_speed_use)
            score_8h   = matcher.score(shot, cfg.tmpl_speed_8h)
            log(f"polling USE [{poll_n:02d}] pin_speed_use={score_use:.3f}  pin_speed_8h={score_8h:.3f}")

            if score_use >= cfg.soglia_use:
                log(f"pin_speed_use VISIBILE al poll {poll_n}")
                return shot

            time.sleep(cfg.poll_speed_use)
            poll_n += 1

        log(f"timeout {cfg.timeout_speed_use}s: pin_speed_use mai trovato — uso ultimo frame disponibile")
        return last_shot

    # ── Mapping outcome → TaskResult ──────────────────────────────────────────

    @staticmethod
    def _mappa_outcome(outcome: str, log, tipo_attivato: str | None = None) -> TaskResult:
        # Output telemetria — Issue #53 Step 3 (outcome + durata + tipo)
        mapping = {
            _Outcome.GIA_ATTIVO:        TaskResult.ok("Speed boost già attivo",
                                                       outcome="gia_attivo", durata=tipo_attivato),
            _Outcome.ATTIVATO_8H:       TaskResult.ok("Speed boost 8h attivato",
                                                       outcome="attivato", durata="8h"),
            _Outcome.ATTIVATO_1D:       TaskResult.ok("Speed boost 1d attivato",
                                                       outcome="attivato", durata="1d"),
            _Outcome.NESSUN_BOOST:      TaskResult.skip("Nessun boost gratuito disponibile"),
            _Outcome.POPUP_NON_APERTO:  TaskResult.skip("Manage Shelter non aperto"),
            _Outcome.SPEED_NON_TROVATO: TaskResult.skip("Riga Gathering Speed non trovata"),
            _Outcome.ERRORE:            TaskResult.fail("Errore generico boost"),
        }
        result = mapping.get(outcome, TaskResult.fail(f"Outcome sconosciuto: {outcome}"))
        log(f"Outcome={outcome!r} → {result}")
        return result
