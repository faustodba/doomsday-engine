"""
tasks/daily_mission_auto.py — DailyMissionAutoTask V6
=====================================================
Task custom master #1 (20/07/2026). La pagina Daily Missions ha, per il
master, un pulsante "Auto Complete" che esegue automaticamente tutte le
missioni giornaliere. Struttura a DUE FASI differite (once/day, reset UTC),
gestite da `ctx.state.daily_mission` (DailyMissionState):

  Fase TRIGGER (tick N):
    HOME -> apri pannello (33,398) -> tab Daily -> tap Auto Complete (843,225).
    Parte un timer "Auto ends in ~1-3 min" (nessun popup di conferma —
    verificato live su FauMorfeus). Conferma via comparsa di pin_auto_ends.
    -> state.segna_trigger() (registra timestamp).

  Fase CLAIM (tick successivo, dopo wait_claim_min dal trigger):
    HOME -> apri pannello -> tab Daily -> loop CLAIM (pin_btn_claim_mission,
    con SCROLL: la lista auto-completata è lunga, ~29 missioni) -> chest
    milestone con OCR Current AP (riuso _leggi_current_ap di MainMission).
    -> state.segna_claim().

Un tick esegue UNA sola fase (guidata dallo stato). Il claim differito evita
di dover coordinare trigger+claim nello stesso tick (nessun hook fine-tick nel
bot). Se il pulsante Auto Complete non c'è (istanza senza la funzione) ->
segna_non_disponibile() per non riprovare a vuoto tutto il giorno.

Navigazione + claim daily + OCR AP riusano coordinate/logica validate in
tasks/main_mission.py.

Registrazione: solo master (via master_task_whitelist). schedule "always"
(il gate once/day è nello stato, non nello schedule). Priority 23.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from core.task import Task, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DailyMissionAutoConfig:
    # --- Apertura pannello (riuso MainMission) ---
    tap_apri_pannello: tuple[int, int] = (33, 398)
    # Il pannello apre di default sul tab Daily (verificato); tap esplicito
    # per robustezza (no-op se già lì). Layout 2-tab master: Main/Daily.
    tap_tab_daily:     tuple[int, int] = (50, 185)

    # --- Auto Complete (calibrato live master 20/07) ---
    tap_auto_complete:  tuple[int, int] = (843, 225)
    pin_auto_complete:  str = "pin/pin_auto_complete.png"
    pin_auto_ends:      str = "pin/pin_auto_ends.png"
    soglia_auto:        float = 0.80

    # --- CLAIM daily (riuso MainMission) ---
    pin_claim:       str = "pin/pin_btn_claim_mission.png"
    soglia_claim:    float = 0.80
    roi_claim_daily: tuple[int, int, int, int] = (810, 210, 895, 460)
    max_claim_loop:  int = 40           # lista lunga (auto-complete ~29 missioni)
    max_scroll_vuoti: int = 3           # stop dopo N scroll senza nuovi CLAIM
    # Scroll lista missioni (contenuto sale = vedi missioni sotto)
    scroll_x:        int = 480
    scroll_y_start:  int = 400
    scroll_y_end:    int = 250
    scroll_dur_ms:   int = 400

    # --- Chest milestone / "pacchi" (calibrato live master 20/07) ---
    # Con l'auto-complete il master fa TUTTE le missioni → AP arriva a ~170 e
    # TUTTI e 5 i chest (20/40/60/80/100) sono raggiunti. Li tappiamo tutti
    # incondizionatamente (no OCR AP: il _leggi_current_ap di MainMission ha
    # cap 100 e scarterebbe 170; e comunque con auto-complete sono sempre
    # tutti raggiunti). Tap su chest già ritirato = no-op silente (verificato).
    # L'header AP+chest è FISSO in cima (non scrolla con la lista missioni),
    # quindi queste coord sono sempre valide anche dopo lo scroll del claim.
    chest_coords: tuple = ((397, 160), (517, 160), (633, 160), (751, 160), (873, 160))

    # --- Chiusura ---
    tap_chiudi_popup:   tuple[int, int] = (480, 80)
    tap_chiudi_pannello: tuple[int, int] = (906, 74)

    # --- Timing ---
    wait_apri_pannello: float = 3.0
    wait_tab_switch:    float = 2.5
    wait_post_auto:     float = 1.5    # dopo tap Auto Complete, prima di verificare
    wait_post_claim:    float = 3.0    # animazione popup reward
    wait_post_tap:      float = 2.0
    wait_scroll:        float = 1.5
    wait_back:          float = 2.0

    # Attesa minima tra trigger e claim (le missioni impiegano ~1-3 min a
    # completarsi; margine di sicurezza). Il claim avviene comunque al tick
    # successivo, quindi in pratica sono passati ~30 min di sleep ciclo.
    wait_claim_min:     float = 3.0    # minuti


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class DailyMissionAutoTask(Task):
    """
    Auto-complete daily mission del master, due fasi once/day via
    DailyMissionState. Vedi docstring modulo per il flusso completo.
    """

    def __init__(self, config: DailyMissionAutoConfig | None = None) -> None:
        self._cfg = config or DailyMissionAutoConfig()

    def name(self) -> str:
        return "daily_mission_auto"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("daily_mission_auto"):
                return False
        stato = ctx.state.daily_mission
        if not stato.should_run():
            ctx.log_msg(f"[DAILY_MISSION] {stato.log_stato()} → skip")
            return False
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg = self._cfg
        log = ctx.log_msg
        stato = ctx.state.daily_mission

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("daily_mission_auto", getattr(ctx, "instance_name", "_unknown"))

        try:
            if not stato.trigger_fatto:
                return self._fase_trigger(ctx, cfg, log, stato, debug)
            # trigger già fatto: valuta la fase claim
            if not stato.claim_pronto(cfg.wait_claim_min):
                log(f"[DAILY_MISSION] trigger fatto, attendo completamento missioni "
                    f"(< {cfg.wait_claim_min}min) → skip, riprovo al prossimo tick")
                return TaskResult.skip("Attendo completamento auto-complete")
            return self._fase_claim(ctx, cfg, log, stato, debug)
        except Exception as exc:
            log(f"[DAILY_MISSION] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")

    # ------------------------------------------------------------------
    # Fase TRIGGER
    # ------------------------------------------------------------------

    def _fase_trigger(self, ctx, cfg, log, stato, debug) -> TaskResult:
        log("[DAILY_MISSION] fase TRIGGER — apro pannello daily mission")
        self._apri_pannello_daily(ctx, cfg)
        debug.snap("01_daily_panel", ctx.device.screenshot())

        shot = ctx.device.screenshot()
        m_auto = ctx.matcher.find_one(shot, cfg.pin_auto_complete, threshold=cfg.soglia_auto)
        if not m_auto.found:
            # Pulsante assente: istanza senza la funzione Auto Complete (o già
            # in corso). Non riproviamo a vuoto tutto il giorno.
            log(f"[DAILY_MISSION] pulsante Auto Complete assente "
                f"(score={m_auto.score:.3f}) → non disponibile su questa istanza")
            self._chiudi_pannello(ctx, cfg)
            stato.segna_non_disponibile()
            debug.flush(success=True, force=True, log_fn=log)
            return TaskResult.skip("Auto Complete non disponibile su questa istanza")

        log(f"[DAILY_MISSION] tap Auto Complete {cfg.tap_auto_complete}")
        ctx.device.tap(*cfg.tap_auto_complete)
        time.sleep(cfg.wait_post_auto)

        # Conferma trigger partito: compare "Auto ends in ..." (il pulsante
        # Auto Complete scompare durante il timer). Verificato live.
        shot2 = ctx.device.screenshot()
        m_ends = ctx.matcher.find_one(shot2, cfg.pin_auto_ends, threshold=cfg.soglia_auto)
        if m_ends.found:
            log(f"[DAILY_MISSION] Auto Complete PARTITO (auto_ends score={m_ends.score:.3f})")
        else:
            # Il tap potrebbe essere andato a buon fine anche senza catturare
            # 'Auto ends' (timing). Registriamo comunque il trigger: il claim
            # differito verificherà lo stato reale. Log per diagnostica.
            log(f"[DAILY_MISSION] 'Auto ends' non rilevato (score={m_ends.score:.3f}) — "
                f"registro trigger comunque, il claim differito verificherà")

        self._chiudi_pannello(ctx, cfg)
        stato.segna_trigger()
        log(f"[DAILY_MISSION] {stato.log_stato()}")
        debug.snap("02_post_trigger", ctx.device.screenshot())
        debug.flush(success=True, log_fn=log)
        return TaskResult.ok("Auto Complete attivato", fase="trigger")

    # ------------------------------------------------------------------
    # Fase CLAIM
    # ------------------------------------------------------------------

    def _fase_claim(self, ctx, cfg, log, stato, debug) -> TaskResult:
        log("[DAILY_MISSION] fase CLAIM — recupero ricompense")
        self._apri_pannello_daily(ctx, cfg)
        debug.snap("10_claim_panel", ctx.device.screenshot())

        n_claim = self._loop_claim_daily(ctx, cfg, log)
        log(f"[DAILY_MISSION] CLAIM daily: {n_claim}")

        # Ritiro chest/pacchi: tappo tutti e 5 (con auto-complete tutti raggiunti)
        n_chest = self._ritira_chest(ctx, cfg, log)
        log(f"[DAILY_MISSION] chest/pacchi ritirati: {n_chest}")

        self._chiudi_pannello(ctx, cfg)
        stato.segna_claim()
        log(f"[DAILY_MISSION] {stato.log_stato()}")
        debug.snap("11_post_claim", ctx.device.screenshot())
        # Anomalia: 0 claim e 0 chest (missioni non pronte? OCR fail?)
        anomalia = (n_claim == 0 and n_chest == 0)
        debug.flush(success=True, force=anomalia, log_fn=log)
        return TaskResult.ok(f"Ricompense recuperate — claim={n_claim} chest={n_chest}",
                             fase="claim", daily_claim=n_claim, chest_claim=n_chest)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apri_pannello_daily(self, ctx, cfg) -> None:
        ctx.device.tap(*cfg.tap_apri_pannello)
        time.sleep(cfg.wait_apri_pannello)
        ctx.device.tap(*cfg.tap_tab_daily)
        time.sleep(cfg.wait_tab_switch)

    def _chiudi_pannello(self, ctx, cfg) -> None:
        ctx.device.tap(*cfg.tap_chiudi_pannello)
        time.sleep(cfg.wait_back)

    def _loop_claim_daily(self, ctx, cfg, log) -> int:
        """Loop CLAIM daily con SCROLL — la lista auto-completata è lunga
        (~29 missioni). Cerca CLAIM in ROI, tappa il match, chiude il popup
        reward; quando la ROI non ha più CLAIM, scrolla la lista e riprova.
        Stop dopo `max_scroll_vuoti` scroll consecutivi senza nuovi CLAIM."""
        n = 0
        scroll_vuoti = 0
        for _ in range(cfg.max_claim_loop):
            screen = ctx.device.screenshot()
            if screen is None:
                break
            r = ctx.matcher.find_one(
                screen, cfg.pin_claim, threshold=cfg.soglia_claim,
                zone=cfg.roi_claim_daily,
            )
            if r.found:
                log(f"[DAILY_MISSION] claim {n+1} → tap ({r.cx},{r.cy}) score={r.score:.3f}")
                ctx.device.tap(r.cx, r.cy)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)
                time.sleep(cfg.wait_post_tap)
                n += 1
                scroll_vuoti = 0
                continue
            # niente CLAIM in ROI → scrolla per vedere missioni sotto
            if scroll_vuoti >= cfg.max_scroll_vuoti:
                log(f"[DAILY_MISSION] nessun CLAIM dopo {scroll_vuoti} scroll — stop a {n}")
                break
            ctx.device.swipe(cfg.scroll_x, cfg.scroll_y_start,
                             cfg.scroll_x, cfg.scroll_y_end, cfg.scroll_dur_ms)
            time.sleep(cfg.wait_scroll)
            scroll_vuoti += 1
        return n

    def _ritira_chest(self, ctx, cfg, log) -> int:
        """Ritira i chest/pacchi milestone. Con l'auto-complete l'AP è sempre
        al massimo → tappo TUTTI e 5 i chest incondizionatamente. Ogni tap su
        un chest raggiunto apre il popup 'Congratulations! You got' che si
        chiude con un tap in zona vuota (tap_chiudi_popup). Tap su chest già
        ritirato = no-op silente (chiuso comunque dal tap successivo).
        Verificato live sul master: 5/5 chest ritirati, badge a 0."""
        n = 0
        for coord in cfg.chest_coords:
            log(f"[DAILY_MISSION] chest → tap {coord}")
            ctx.device.tap(*coord)
            time.sleep(cfg.wait_post_claim)
            ctx.device.tap(*cfg.tap_chiudi_popup)  # chiude popup Congratulations
            time.sleep(cfg.wait_post_tap)
            n += 1
        return n
