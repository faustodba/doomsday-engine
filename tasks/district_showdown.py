"""
DistrictShowdownTask — Doomsday Engine V6
==========================================

Evento mensile "District Showdown" (durata 3 giorni).
Lancia tutti i dadi Gold disponibili tramite Auto Roll.

Flusso:
    HOME
    → cerca pin_district_showdown nella barra eventi (ROI top)
    → tap icona evento
    → tap Auto (39, 151)
    → popup Auto Roll: verifica 3 toggle ON → tap Start
    → loop monitoring ogni 10s:
        - pin_gang_leader   → tap Request Help (472, 412)
                              → re-enable auto se necessario
                              → gestisci eventuale pin_assistance_progress
        - pin_access_prohibited → sleep 65s → re-enable auto
        - pin_item_source   → tap BACK → EXIT (dadi esauriti)
        - nessuno           → continua monitoring
    → vai_in_home

Scheduling: always (interval=0.0) — guard su flag district_showdown abilitato.
Priority: 107 — dopo DonazioneTask (105), prima RaccoltaTask (110).

Attivazione: flag `task.district_showdown` in runtime_overrides.json
             oppure toggle dashboard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.task import Task, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DistrictShowdownConfig:
    # Template paths (tutti in templates/pin/)
    pin_district_showdown: str   = "pin/pin_district_showdown.png"
    pin_autoplay: str            = "pin/pin_autoplay.png"
    pin_check_auto_roll: str     = "pin/pin_check_auto_roll.png"
    pin_no_check_auto_roll: str  = "pin/pin_no_check_auto_roll.png"
    pin_start_auto_roll: str     = "pin/pin_start_auto_roll.png"
    pin_stop_auto_roll: str      = "pin/pin_stop_auto_roll.png"
    pin_gang_leader: str         = "pin/pin_gang_leader.png"
    pin_access_prohibited: str   = "pin/pin_access_prohibited.png"
    pin_item_source: str         = "pin/pin_item_source.png"
    pin_assistance_progress: str = "pin/pin_assistance_progress.png"

    # ROI ricerca icona evento nella barra top (x1,y1,x2,y2)
    roi_barra_eventi: tuple = field(default_factory=lambda: (350, 40, 900, 110))

    # Coordinate fisse (960x540)
    tap_autoplay: tuple          = field(default_factory=lambda: (39, 151))
    tap_toggle_1: tuple          = field(default_factory=lambda: (672, 181))
    tap_toggle_2: tuple          = field(default_factory=lambda: (672, 233))
    tap_toggle_3: tuple          = field(default_factory=lambda: (672, 296))
    tap_start: tuple             = field(default_factory=lambda: (473, 389))
    tap_request_help: tuple      = field(default_factory=lambda: (472, 412))
    tap_ok_assistance: tuple     = field(default_factory=lambda: (589, 379))
    # Toggle "Skip animation" sulla maschera evento — velocizza il gameplay
    # saltando l'animazione dei dadi. Posizione fissa sullo schermo del gioco.
    tap_skip_check: tuple        = field(default_factory=lambda: (840, 371))
    # ROI stretta attorno al toggle skip per ricerca pin_check
    roi_skip_check: tuple        = field(default_factory=lambda: (810, 340, 870, 400))

    # Soglie template matching
    tm_threshold: float          = 0.75
    # Threshold alto per pin Auto Roll (start/stop) — evita falsi positivi
    # su UI residua quando il popup non è ancora completamente renderato.
    tm_threshold_autoplay: float = 0.88

    # Delay UI — MuMu Win11 lento: margin extra su popup + minor tap
    delay_dopo_tap_popup: float  = 3.5   # dopo tap che apre popup/overlay
    delay_dopo_tap_minor: float  = 2.0   # dopo back/tap minore
    delay_monitoring: float      = 15.0  # ciclo monitoring
    delay_access_prohibited: float = 70.0  # wait popup access_prohibited

    # Sicurezza
    max_monitoring_cicli: int    = 200   # ~33 minuti max per sessione


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class DistrictShowdownTask(Task):
    """Lancia tutti i dadi Gold disponibili nell'evento District Showdown."""

    def __init__(self) -> None:
        self._cfg = DistrictShowdownConfig()

    # ------------------------------------------------------------------
    # V6 API obbligatoria
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "district_showdown"

    def should_run(self, ctx: TaskContext) -> bool:
        # Gate device/matcher + flag abilitazione globale (V6 API _InstanceCfg)
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("district_showdown")
        return True

    def e_dovuto(self, ctx: TaskContext) -> bool:  # noqa: ARG002
        return True  # always scheduling — guard in should_run

    # ------------------------------------------------------------------
    # Helper adattivo — attesa stabilizzazione template
    # ------------------------------------------------------------------

    def _wait_template_ready(
        self,
        ctx: TaskContext,
        template: str,
        *,
        max_wait: float = 15.0,
        poll_interval: float = 0.5,
        threshold: float = 0.80,
        stable_polls: int = 2,
        zone=None,
    ):
        """
        Poll dello screenshot fino a quando `template` appare con
        score >= `threshold` per `stable_polls` cicli consecutivi.

        Utile dopo tap che apre maschera/popup: invece di sleep fisso,
        aspetta che il template sentinel (es. pin_autoplay) sia presente
        e stabile → segnale che UI è renderata e pronta per interazione.

        Ritorna MatchResult del match finale se trovato, None se timeout.
        """
        import time as _t
        t0 = _t.time()
        consecutive = 0
        last_result = None
        while _t.time() - t0 < max_wait:
            screen = ctx.device.screenshot()
            if screen is None:
                _t.sleep(poll_interval)
                continue
            res = ctx.matcher.find_one(
                screen, template, threshold=threshold, zone=zone,
            )
            if res.found:
                last_result = res
                consecutive += 1
                if consecutive >= stable_polls:
                    return res
            else:
                consecutive = 0
            _t.sleep(poll_interval)
        return last_result if (last_result and last_result.found) else None

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg = self._cfg
        ctx.log_msg("[DS] Avvio DistrictShowdownTask")

        # 1. Naviga alla home come punto di partenza stabile
        ctx.navigator.vai_in_home()
        time.sleep(cfg.delay_dopo_tap_minor)

        # 2. Cerca e tap icona evento nella barra top
        if not self._apri_evento(ctx):
            ctx.log_msg("[DS] Icona district_showdown non trovata — skip")
            ctx.navigator.vai_in_home()
            return TaskResult(success=False, message="icona evento non trovata")

        # 3. Attiva Auto Roll
        if not self._attiva_auto_roll(ctx):
            ctx.log_msg("[DS] Auto Roll non avviato — back e skip")
            ctx.device.back()
            time.sleep(cfg.delay_dopo_tap_minor)
            ctx.navigator.vai_in_home()
            return TaskResult(success=False, message="auto roll non avviato")

        # 4. Loop monitoring dadi
        esito = self._loop_monitoring(ctx)

        # 5. Torna home
        ctx.navigator.vai_in_home()

        if esito == "dadi_esauriti":
            ctx.log_msg("[DS] Dadi esauriti — task completato")
            return TaskResult(success=True, message="dadi esauriti")
        else:
            ctx.log_msg(f"[DS] Loop terminato: {esito}")
            return TaskResult(success=False, message=esito)

    # ------------------------------------------------------------------
    # Step 1 — Apri evento
    # ------------------------------------------------------------------

    def _apri_evento(self, ctx: TaskContext) -> bool:
        cfg = self._cfg
        matcher = ctx.matcher
        screen = ctx.device.screenshot()

        roi = cfg.roi_barra_eventi
        result = matcher.find_one(
            screen,
            cfg.pin_district_showdown,
            threshold=cfg.tm_threshold,
            zone=roi,
        )
        if not result.found:
            return False

        cx, cy = result.cx, result.cy
        ctx.log_msg(f"[DS] Icona trovata a ({cx}, {cy})")
        ctx.device.tap(cx, cy)

        # ATTESA ADATTIVA — pin_autoplay sentinel della maschera evento stabilizzata.
        # Su MuMu lento la maschera può tardare 5-15s a caricarsi. Invece di delay
        # fisso, poll fino a quando l'icona Auto appare stabilmente.
        ready = self._wait_template_ready(
            ctx, cfg.pin_autoplay,
            max_wait=15.0, poll_interval=0.5,
            threshold=0.80, stable_polls=2,
        )
        if ready is None:
            ctx.log_msg(
                "[DS] Maschera evento NON stabilizzata in 15s "
                "(pin_autoplay non trovato) — fallback delay lungo"
            )
            time.sleep(cfg.delay_dopo_tap_popup * 2)
        else:
            ctx.log_msg(
                f"[DS] Maschera evento stabilizzata — "
                f"pin_autoplay score={ready.score:.3f} pos=({ready.cx},{ready.cy})"
            )

        # ── Skip animation check ─────────────────────────────────────────
        # Se il toggle "Skip animation" NON è attivo, lo attiva con tap fisso
        # (840, 371). Velocizza il gameplay saltando l'animazione dei dadi.
        # Template `pin_check_auto_roll` cercato in ROI stretta intorno al toggle.
        screen = ctx.device.screenshot()
        if screen is not None:
            check_res = matcher.find_one(
                screen, cfg.pin_check_auto_roll,
                threshold=cfg.tm_threshold,
                zone=cfg.roi_skip_check,
            )
            if check_res.found:
                ctx.log_msg(
                    f"[DS] Skip animation già attivo (score={check_res.score:.3f})"
                )
            else:
                ctx.log_msg(
                    f"[DS] Skip animation NON attivo — tap {cfg.tap_skip_check}"
                )
                ctx.device.tap(*cfg.tap_skip_check)
                time.sleep(cfg.delay_dopo_tap_minor)
        return True

    # ------------------------------------------------------------------
    # Step 2 — Attiva Auto Roll
    # ------------------------------------------------------------------

    def _attiva_auto_roll(self, ctx: TaskContext) -> bool:
        """Tap Auto → popup Auto Roll → verifica toggle ON → Start.

        Attesa adattiva: dopo tap su pin_autoplay, poll fino a quando
        pin_start_auto_roll OR pin_stop_auto_roll appare stabile (threshold
        0.88). Evita sia i falsi positivi su UI non ancora renderata che
        i falsi negativi su MuMu lento.
        """
        cfg = self._cfg
        matcher = ctx.matcher

        # Tap pulsante Auto — usa coordinate match di pin_autoplay se presente
        # (robusto a layout leggermente diversi).
        screen = ctx.device.screenshot()
        autoplay_res = matcher.find_one(
            screen, cfg.pin_autoplay, threshold=cfg.tm_threshold,
        )
        if autoplay_res.found:
            ctx.log_msg(
                f"[DS] tap pin_autoplay pos=({autoplay_res.cx},{autoplay_res.cy}) "
                f"score={autoplay_res.score:.3f}"
            )
            ctx.device.tap(autoplay_res.cx, autoplay_res.cy)
        else:
            ctx.log_msg(
                f"[DS] pin_autoplay non trovato — fallback hardcoded {cfg.tap_autoplay}"
            )
            ctx.device.tap(*cfg.tap_autoplay)

        # ATTESA ADATTIVA — poll fino a quando Start OR Stop appare stabile.
        # Cerchiamo entrambi: se trovato prima has_stop → auto già attiva; se
        # trovato has_start → procediamo col tap Start. max_wait alto per MuMu lento.
        import time as _t
        t0 = _t.time()
        max_wait = 12.0
        poll_interval = 0.5
        consecutive_start = 0
        consecutive_stop = 0
        has_start = None
        has_stop = None
        while _t.time() - t0 < max_wait:
            screen = ctx.device.screenshot()
            if screen is None:
                _t.sleep(poll_interval); continue
            hs = matcher.find_one(
                screen, cfg.pin_start_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
            hp = matcher.find_one(
                screen, cfg.pin_stop_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
            if hp.found:
                has_stop = hp
                consecutive_stop += 1
                if consecutive_stop >= 2:
                    break
            else:
                consecutive_stop = 0
            if hs.found:
                has_start = hs
                consecutive_start += 1
                if consecutive_start >= 2:
                    break
            else:
                consecutive_start = 0
            _t.sleep(poll_interval)

        # Fallback se nessuno dei due trovato stabile → retry screenshot
        if has_stop is None and has_start is None:
            screen = ctx.device.screenshot()
            has_start = matcher.find_one(
                screen, cfg.pin_start_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
            has_stop = matcher.find_one(
                screen, cfg.pin_stop_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
        # Normalizza a MatchResult per gli if successivi
        if has_start is None:
            has_start = matcher.find_one(
                screen, cfg.pin_start_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
        if has_stop is None:
            has_stop = matcher.find_one(
                screen, cfg.pin_stop_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )

        if has_stop.found:
            # Auto già attiva — back e continua
            ctx.log_msg(
                f"[DS] Auto Roll già attivo (score={has_stop.score:.3f}) — back"
            )
            ctx.device.back()
            time.sleep(cfg.delay_dopo_tap_minor)
            return True

        if not has_start.found:
            ctx.log_msg("[DS] Popup Auto Roll non rilevato (né start né stop)")
            return False

        ctx.log_msg(
            f"[DS] Popup Auto Roll aperto, Start visibile score={has_start.score:.3f} "
            f"pos=({has_start.cx},{has_start.cy})"
        )

        # Verifica e abilita i 3 toggle
        self._verifica_toggle(ctx)

        # Tap Start — coordinate del match (non hardcoded), robuste a
        # layout leggermente diversi (risoluzione, scroll popup).
        # Fallback su tap_start hardcoded solo se find_one fallisce.
        ctx.device.tap(has_start.cx, has_start.cy)
        time.sleep(cfg.delay_dopo_tap_popup)
        ctx.log_msg(f"[DS] Auto Roll avviato — tap ({has_start.cx},{has_start.cy})")
        return True

    def _verifica_toggle(self, ctx: TaskContext) -> None:
        """Controlla i 3 toggle: se OFF (pin_no_check) → tap per abilitare."""
        cfg = self._cfg
        matcher = ctx.matcher
        screen = ctx.device.screenshot()

        toggles = [
            (cfg.tap_toggle_1, "Mysterious Merchant"),
            (cfg.tap_toggle_2, "Supply Cache"),
            (cfg.tap_toggle_3, "Street Duel"),
        ]

        for (tx, ty), nome in toggles:
            # Controlla se il toggle è OFF cercando pin_no_check_auto_roll
            # in una ROI ristretta intorno alla coordinata del toggle
            roi = (tx - 40, ty - 20, tx + 40, ty + 20)
            result = matcher.find_one(
                screen,
                cfg.pin_no_check_auto_roll,
                threshold=cfg.tm_threshold,
                zone=roi,
            )
            if result.found:
                ctx.log_msg(f"[DS] Toggle {nome} OFF → abilito")
                ctx.device.tap(tx, ty)
                time.sleep(cfg.delay_dopo_tap_minor)
                # Aggiorna screenshot dopo tap
                screen = ctx.device.screenshot()
            else:
                ctx.log_msg(f"[DS] Toggle {nome} già ON")

    # ------------------------------------------------------------------
    # Step 3 — Loop monitoring
    # ------------------------------------------------------------------

    def _loop_monitoring(self, ctx: TaskContext) -> str:
        """
        Monitora la schermata ogni delay_monitoring s e gestisce:
        - Gang Leader       → Request Help → re-enable auto
        - Access Prohibited → sleep 70s → re-enable auto
        - Item Source       → back×3 → dadi esauriti (EXIT)
        - Evento uscito     → EXIT (gioco non più in foreground / schermata HOME del gioco)

        Early exit: se per MAX_UNKNOWN_STREAK cicli consecutivi NESSUN pin è
        rilevato, significa che il bot è uscito dalla maschera evento (gioco
        in HOME del gioco, HOME Android, crash). Esce per evitare loop infinito
        fino a max_monitoring_cicli=200 (~50 min).

        Ritorna: "dadi_esauriti" | "timeout" | "uscita_rilevata" | "errore"
        """
        cfg = self._cfg
        matcher = ctx.matcher
        MAX_UNKNOWN_STREAK = 3     # 3 cicli × 15s = 45s senza pin → uscita
        unknown_streak = 0

        for ciclo in range(cfg.max_monitoring_cicli):
            time.sleep(cfg.delay_monitoring)
            screen = ctx.device.screenshot()

            # --- Caso 1: Gang Leader (Request Help) ---
            if matcher.find_one(screen, cfg.pin_gang_leader,
                                 threshold=cfg.tm_threshold).found:
                ctx.log_msg(f"[DS] Ciclo {ciclo}: Gang Leader rilevato")
                self._gestisci_gang_leader(ctx)
                unknown_streak = 0
                continue

            # --- Caso 2: Access Prohibited (Break Free) ---
            if matcher.find_one(screen, cfg.pin_access_prohibited,
                                 threshold=cfg.tm_threshold).found:
                ctx.log_msg(f"[DS] Ciclo {ciclo}: Access Prohibited — attendo 70s")
                self._gestisci_access_prohibited(ctx)
                unknown_streak = 0
                continue

            # --- Caso 3: Item Source (dadi esauriti) ---
            if matcher.find_one(screen, cfg.pin_item_source,
                                 threshold=cfg.tm_threshold).found:
                ctx.log_msg(f"[DS] Ciclo {ciclo}: Item Source — dadi esauriti")
                for i in range(3):
                    ctx.device.back()
                    time.sleep(cfg.delay_dopo_tap_minor)
                    ctx.log_msg(f"[DS] back {i+1}/3 dopo Item Source")
                return "dadi_esauriti"

            # --- Caso 4: Auto_roll confermato visibile (pin_autoplay) ---
            # Se vediamo pin_autoplay ma nessuno dei 3 trigger, siamo ancora
            # nella maschera evento con dadi in corso → reset streak.
            if matcher.find_one(screen, cfg.pin_autoplay,
                                 threshold=cfg.tm_threshold).found:
                unknown_streak = 0
                ctx.log_msg(f"[DS] Ciclo {ciclo}: auto in corso...")
                continue

            # --- Caso 5: nessun pin → streak uscita ---
            unknown_streak += 1
            ctx.log_msg(
                f"[DS] Ciclo {ciclo}: nessun pin rilevato "
                f"(streak uscita {unknown_streak}/{MAX_UNKNOWN_STREAK})"
            )
            if unknown_streak >= MAX_UNKNOWN_STREAK:
                ctx.log_msg(
                    f"[DS] EXIT — {MAX_UNKNOWN_STREAK} cicli consecutivi "
                    f"senza pin evento → bot uscito dalla maschera"
                )
                return "uscita_rilevata"

        ctx.log_msg("[DS] Timeout monitoring raggiunto")
        return "timeout"

    # ------------------------------------------------------------------
    # Gestori interruzioni
    # ------------------------------------------------------------------

    def _gestisci_gang_leader(self, ctx: TaskContext) -> None:
        """
        Gang Leader: tap Request Help → controlla assistance_progress
        → re-enable auto se necessario.
        """
        cfg = self._cfg
        matcher = ctx.matcher

        # Tap Request Help
        ctx.device.tap(*cfg.tap_request_help)
        time.sleep(cfg.delay_dopo_tap_popup)

        screen = ctx.device.screenshot()

        # Caso C: popup "Assistance in progress, is the replacement confirmed?"
        if matcher.find_one(screen, cfg.pin_assistance_progress,
                             threshold=cfg.tm_threshold).found:
            ctx.log_msg("[DS] Assistance in progress → tap OK")
            ctx.device.tap(*cfg.tap_ok_assistance)
            time.sleep(cfg.delay_dopo_tap_popup)

        # Ora siamo tornati alla schermata evento — re-enable auto
        self._reenable_auto(ctx)

    def _gestisci_access_prohibited(self, ctx: TaskContext) -> None:
        """Access Prohibited: polling 5s sincronizzato con 3 stati possibili.

        Problema sleep fisso: il popup dura 60s nel gioco ma quando il bot lo
        rileva può essere già aperto da N secondi (polling monitoring 15s).
        Un `time.sleep(70)` fisso porta desincronizzazione: il popup si chiude
        al T+60, ma il bot aspetta fino a T+70, e nel frattempo la UI è già
        cambiata (Auto Roll riattivato, popup chiuso, altro stato).

        Nuova logica: polling ogni 5s, ad ogni poll cerca 3 stati:
          A) pin_stop_auto_roll  → Auto Roll già riattivato → back + return
          B) pin_start_auto_roll → Auto Roll non attivo → tap Start + return
          C) pin_access_prohibited (ancora) → continua polling

        Se nessuno dei 3 → transizione UI, continua polling fino a timeout safety.
        """
        cfg = self._cfg
        matcher = ctx.matcher
        poll_interval = 5.0
        max_wait = 90.0     # safety: popup max 60s nel gioco, +30s buffer
        t0 = time.time()
        poll_idx = 0

        while time.time() - t0 < max_wait:
            elapsed = time.time() - t0
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg(f"[DS] AP poll {poll_idx}: screenshot None — wait 5s")
                time.sleep(poll_interval)
                poll_idx += 1
                continue

            # Stato A — Auto Roll già riattivato (pin_stop visibile)
            has_stop = matcher.find_one(
                screen, cfg.pin_stop_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
            if has_stop.found:
                ctx.log_msg(
                    f"[DS] AP chiuso dopo {elapsed:.0f}s — Auto attivo "
                    f"(stop score={has_stop.score:.3f}) → back"
                )
                ctx.device.back()
                time.sleep(cfg.delay_dopo_tap_minor)
                return

            # Stato B — Popup Auto Roll aperto con Start visibile
            has_start = matcher.find_one(
                screen, cfg.pin_start_auto_roll,
                threshold=cfg.tm_threshold_autoplay,
            )
            if has_start.found:
                ctx.log_msg(
                    f"[DS] AP chiuso dopo {elapsed:.0f}s — Start visibile "
                    f"(score={has_start.score:.3f} pos=({has_start.cx},{has_start.cy})) → tap"
                )
                self._verifica_toggle(ctx)
                ctx.device.tap(has_start.cx, has_start.cy)
                time.sleep(cfg.delay_dopo_tap_popup)
                return

            # Stato C — popup Access Prohibited ancora visibile (normale)
            has_ap = matcher.find_one(
                screen, cfg.pin_access_prohibited,
                threshold=cfg.tm_threshold,
            )
            if has_ap.found:
                ctx.log_msg(
                    f"[DS] AP poll {poll_idx} ({elapsed:.0f}s): popup ancora attivo — wait 5s"
                )
            else:
                # Nessuno dei 3 — fase transizione (popup chiuso ma UI non ancora
                # al popup Auto Roll). Continua polling.
                ctx.log_msg(
                    f"[DS] AP poll {poll_idx} ({elapsed:.0f}s): transizione, nessun pin — wait 5s"
                )

            time.sleep(poll_interval)
            poll_idx += 1

        # Timeout safety: popup bloccato o UI anomala → back + prova re-enable
        ctx.log_msg(
            f"[DS] AP timeout dopo {max_wait:.0f}s — back sicurezza + re-enable"
        )
        ctx.device.back()
        time.sleep(cfg.delay_dopo_tap_minor)
        self._reenable_auto(ctx)

    def _reenable_auto(self, ctx: TaskContext) -> None:
        """
        Tap Auto → controlla stato popup:
        - Stop Auto (rosso) → auto già attiva → back
        - Start (giallo)    → verifica toggle ON → tap Start
        """
        cfg = self._cfg
        matcher = ctx.matcher

        ctx.device.tap(*cfg.tap_autoplay)
        time.sleep(cfg.delay_dopo_tap_popup)

        # Doppio screenshot per stabilità popup
        screen = ctx.device.screenshot()
        time.sleep(cfg.delay_dopo_tap_minor)
        screen = ctx.device.screenshot()

        # Threshold autoplay alto (0.88) — evita falsi positivi
        has_stop = matcher.find_one(screen, cfg.pin_stop_auto_roll,
                                     threshold=cfg.tm_threshold_autoplay)
        if has_stop.found:
            ctx.log_msg(f"[DS] Re-enable: auto già attiva (score={has_stop.score:.3f}) → back")
            ctx.device.back()
            time.sleep(cfg.delay_dopo_tap_minor)
            return

        # Auto non attiva → verifica toggle + Start
        has_start = matcher.find_one(screen, cfg.pin_start_auto_roll,
                                      threshold=cfg.tm_threshold_autoplay)
        if has_start.found:
            ctx.log_msg(
                f"[DS] Re-enable: Start visibile score={has_start.score:.3f} "
                f"pos=({has_start.cx},{has_start.cy}) → toggle+tap"
            )
            self._verifica_toggle(ctx)
            # Tap sulla coordinata del match (non hardcoded)
            ctx.device.tap(has_start.cx, has_start.cy)
            time.sleep(cfg.delay_dopo_tap_popup)
            return

        # Popup non rilevato — situazione inattesa, back di sicurezza
        ctx.log_msg("[DS] Re-enable: popup Auto Roll non rilevato — back sicurezza")
        ctx.device.back()
        time.sleep(cfg.delay_dopo_tap_minor)
