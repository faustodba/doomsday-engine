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
from datetime import datetime, timezone

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
    # --- District Foray (fase 2 post-loop_monitoring) ---
    pin_district_foray: str      = "pin/pin_district_foray.png"
    pin_dado: str                = "pin/pin_dado.png"
    # --- Influence Rewards (fase 3 — claim chiavi da statue alleanza) ---
    pin_influence_rewards: str   = "pin/pin_influence_rewards.png"
    # Red-dot rilevato via pixel-check BGR (stesso pattern di radar._ha_badge):
    # no template PNG richiesto, robusto ad animazione/flash del badge.
    red_dot_r_min: int           = 150   # canale R minimo (rosso puro)
    red_dot_g_max: int           = 85    # canale G massimo
    red_dot_b_max: int           = 85    # canale B massimo
    red_dot_min_pixels: int      = 5     # soglia pixel rossi per confermare
    # ROI 60×60 attorno a tap_collect_all (572, 485) — popup Foray reward
    roi_red_dot: tuple           = field(default_factory=lambda: (540, 455, 605, 520))

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
    # District Foray — tap "Collect All" nel popup reward
    tap_collect_all: tuple       = field(default_factory=lambda: (572, 485))
    # Influence Rewards — tap chiave nel popup "Alliance Influence"
    tap_claim_key: tuple         = field(default_factory=lambda: (781, 148))
    # Icone nella barra top della mappa DS (coordinate misurate 960×540)
    tap_foray_icon: tuple        = field(default_factory=lambda: (680, 30))
    tap_fund_raid_icon: tuple    = field(default_factory=lambda: (837, 39))
    tap_influence_icon: tuple    = field(default_factory=lambda: (918, 30))
    # Achievement Rewards — 3a fase post-dadi
    tap_achievement_icon: tuple  = field(default_factory=lambda: (939, 238))  # apre popup
    tap_claim_all: tuple         = field(default_factory=lambda: (882, 129))  # claim singolo = tutte
    # Fund Raid — fase 5: seleziona prima alleanza da "Last Raided"
    tap_fund_raid_select: tuple  = field(default_factory=lambda: (802, 161))  # bottone Select prima alleanza
    # Fund Raid attack — bottone colpo + OCR box contatore chiavi residue
    tap_fund_raid_attack: tuple  = field(default_factory=lambda: (443, 450))  # tap raid ripetuto
    roi_fund_counter:     tuple  = field(default_factory=lambda: (384, 386, 560, 428))  # OCR counter
    max_fund_raid_attacks: int   = 20   # safety cap iterazioni loop (legacy, non usato post-WU14)
    # auto-WU14 (26/04 fund raid burst): tap-burst rapido a blocchi.
    # Modello mutuato da DonazioneTask._loop_donate (auto-WU11): N tap
    # consecutivi senza screenshot intermedio → screenshot+OCR counter
    # post-block → loop finché counter=0 o cap max_blocks raggiunto.
    fund_raid_taps_per_block:  int   = 30      # tap consecutivi prima di check OCR
    fund_raid_wait_tap:        float = 0.25    # delay tra tap nel block
    fund_raid_max_blocks:      int   = 5       # cap blocchi (30×5 = 150 attack safety)
    fund_raid_wait_post_block: float = 1.0     # attesa stabilizzazione UI dopo burst prima OCR

    # --- Finestre temporali evento (UTC) ---
    # Evento District Showdown: VEN 00:00 UTC → LUN 00:00 UTC (3 giorni esatti).
    # Lunedì (anche alle 00:00) → fuori evento, should_run False.
    ds_start_weekday: int        = 4     # 4=venerdì (Python weekday)
    ds_start_hour:    int        = 0     # 00:00 UTC
    ds_end_weekday: int          = 0     # 0=lunedì
    ds_end_hour:    int          = 0     # 00:00 UTC (lunedì escluso)

    # Fund Raid (fase 5): DOM 20:00 UTC → LUN 00:00 UTC (ultime 4 ore).
    fund_raid_start_weekday: int = 6     # 6=domenica
    fund_raid_start_hour:    int = 20    # 20:00 UTC
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
    delay_foray: float           = 7.0   # delay tra tap popup ricompense (Foray/Influence/Achievement) e verifiche

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
        # Gate device/matcher
        if ctx.device is None or ctx.matcher is None:
            return False
        # auto-WU17 (27/04): gate temporale override del flag manuale.
        # Il task DS è completamente time-driven: si auto-attiva durante
        # l'evento (Ven 00:00 → Lun 00:00 UTC) e auto-disattiva fuori,
        # indipendentemente da task_abilitato("district_showdown"). Evita
        # il rischio "flag dimenticato disabilitato" durante l'evento.
        # Il sub-step 5 (Fund Raid) ha gate proprio `_is_in_fund_raid_window`
        # (Dom 20:00 → Lun 00:00 UTC).
        return self._is_in_event_window()

    def e_dovuto(self, ctx: TaskContext) -> bool:  # noqa: ARG002
        return True  # always scheduling — guard in should_run

    # ------------------------------------------------------------------
    # Helper finestre temporali evento (UTC)
    # ------------------------------------------------------------------

    def _is_in_event_window(self) -> bool:
        """
        True se l'ora UTC corrente è nella finestra evento District Showdown:
            Venerdi' 00:00 UTC  →  Lunedì 01:00 UTC

        Fuori (lun 01:00 → ven 00:00) → False.
        Configurabile via DistrictShowdownConfig.ds_start_*/ds_end_*.
        """
        cfg = self._cfg
        now = datetime.now(timezone.utc)
        wd  = now.weekday()   # 0=lun … 6=dom
        h   = now.hour

        # Caso A — lunedì: attivo solo prima di ds_end_hour
        if wd == cfg.ds_end_weekday:
            return h < cfg.ds_end_hour
        # Caso B — venerdì: attivo solo da ds_start_hour in poi
        if wd == cfg.ds_start_weekday:
            return h >= cfg.ds_start_hour
        # Caso C — sabato, domenica: sempre attivo (pieno weekend evento)
        if wd in (5, 6):
            return True
        # Caso D — mar/mer/gio: fuori finestra
        return False

    def _is_in_fund_raid_window(self) -> bool:
        """
        True se l'ora UTC corrente è nella finestra Fund Raid:
            Domenica 22:00 UTC  →  Lunedì 01:00 UTC
        """
        cfg = self._cfg
        now = datetime.now(timezone.utc)
        wd  = now.weekday()
        h   = now.hour
        # Domenica dalle fund_raid_start_hour in poi
        if wd == cfg.fund_raid_start_weekday and h >= cfg.fund_raid_start_hour:
            return True
        # Lunedì prima di ds_end_hour (fine evento)
        if wd == cfg.ds_end_weekday and h < cfg.ds_end_hour:
            return True
        return False

    # ------------------------------------------------------------------
    # Helper navigazione — stato-aware back verso mappa DS
    # ------------------------------------------------------------------

    def _torna_a_mappa_ds(self, ctx: TaskContext, max_attempts: int = 5) -> bool:
        """
        Navigatore adattivo: torna alla MAPPA del gioco District Showdown.

        Algoritmo:
          loop max_attempts:
            1. Dove sono? (screenshot)
            2. Se MAPPA (pin_dado visibile) → OK, return True
            3. Se HOME del gioco (Screen.HOME) → rientra: tap icona evento
               DS nella barra top → wait pin_dado
            4. Altrimenti (stato intermedio: popup qualsiasi) → back + retry

        Casi gestiti:
          - popup singolo sopra mappa → 1 back
          - popup doppio (Item Source + Auto Roll) → 2 back
          - uscita oltre mappa (HOME gioco) → rientra via icona evento
          - stato sconosciuto → tentativi fino a max_attempts

        Ritorna:
          True  — sono nella mappa DS con pin_dado visibile
          False — dopo max_attempts non sono riuscito (stato anomalo)
        """
        cfg = self._cfg
        matcher = ctx.matcher

        for i in range(max_attempts):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg(f"[DS-NAV] tent {i}: screenshot None — wait")
                time.sleep(cfg.delay_dopo_tap_minor)
                continue

            # 1. Siamo nella MAPPA?
            dado = matcher.find_one(
                screen, cfg.pin_dado, threshold=cfg.tm_threshold,
            )
            if dado.found:
                ctx.log_msg(
                    f"[DS-NAV] mappa raggiunta al tent {i} "
                    f"(pin_dado score={dado.score:.3f})"
                )
                return True

            # 2. Siamo tornati alla HOME del gioco? (oltre la mappa)
            try:
                from core.navigator import Screen
                schermata = ctx.navigator.schermata_corrente()
                if schermata == Screen.HOME:
                    ctx.log_msg(
                        f"[DS-NAV] tent {i}: HOME rilevata (troppo back) — "
                        f"rientro tappando icona evento"
                    )
                    # Cerca icona pin_district_showdown nella barra top HOME + tap
                    res = matcher.find_one(
                        screen, cfg.pin_district_showdown,
                        threshold=cfg.tm_threshold,
                        zone=cfg.roi_barra_eventi,
                    )
                    # auto-WU20: se icona non trovata, prova comprimi_banner_home
                    # + 1s wait + re-screenshot + retry. Pattern visto su
                    # FAU_00/02/03: HOME rilevata ma banner/popup nasconde icona.
                    if not res.found:
                        ctx.log_msg(
                            "[DS-NAV] icona DS non trovata — provo comprimi banner + retry"
                        )
                        try:
                            from shared.ui_helpers import comprimi_banner_home
                            comprimi_banner_home(ctx, ctx.log_msg)
                        except Exception as exc:
                            ctx.log_msg(f"[DS-NAV] comprimi_banner errore: {exc}")
                        time.sleep(1.0)
                        screen2 = ctx.device.screenshot()
                        if screen2 is not None:
                            res = matcher.find_one(
                                screen2, cfg.pin_district_showdown,
                                threshold=cfg.tm_threshold,
                                zone=cfg.roi_barra_eventi,
                            )
                    if res.found:
                        ctx.device.tap(res.cx, res.cy)
                        # Wait adattivo su pin_dado dopo re-entry
                        ready = self._wait_template_ready(
                            ctx, cfg.pin_dado,
                            max_wait=15.0, poll_interval=0.5,
                            threshold=0.80, stable_polls=2,
                        )
                        if ready is not None:
                            ctx.log_msg(
                                f"[DS-NAV] rientrato nella mappa "
                                f"(pin_dado score={ready.score:.3f})"
                            )
                            return True
                        ctx.log_msg("[DS-NAV] rientro fallito — pin_dado non appare")
                    else:
                        ctx.log_msg(
                            "[DS-NAV] icona evento DS non trovata in HOME — abort"
                        )
                    return False
            except Exception as exc:
                ctx.log_msg(f"[DS-NAV] check HOME errore: {exc}")

            # 3. Stato intermedio (popup qualsiasi sopra mappa) → back
            ctx.log_msg(f"[DS-NAV] tent {i}: stato intermedio — back")
            ctx.device.back()
            time.sleep(cfg.delay_dopo_tap_minor)

        ctx.log_msg(
            f"[DS-NAV] max_attempts={max_attempts} raggiunti, mappa non raggiunta"
        )
        return False

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

        # 4. Loop monitoring dadi (fase 1)
        esito = self._loop_monitoring(ctx)
        ctx.log_msg(f"[DS] Fine fase 1: {esito}")

        # Fasi 2, 3 e 4 — reclamo reward SOLO se dadi realmente completati.
        # Se esito e' "uscita_rilevata" o "timeout" il gioco non e' completato
        # e le reward non sono ancora sbloccate → skip.
        if esito == "dadi_esauriti":
            # 5. District Foray — reclamo reward secondario (fase 2)
            self._district_foray(ctx)

            # 6. Influence Rewards — reclamo chiavi Alliance Influence (fase 3)
            self._influence_rewards(ctx)

            # 7. Achievement Rewards — claim milestone dadi usati (fase 4)
            self._achievement_rewards(ctx)

            # 8. Fund Raid — select prima alleanza Last Raided (fase 5)
            self._fund_raid(ctx)
        else:
            ctx.log_msg(
                f"[DS] Skip fase 2/3/4/5 (Foray + Influence + Achievement + FundRaid) "
                f"— esito='{esito}' (reward disponibili solo dopo dadi completati)"
            )

        # 7. Esci dalla mappa evento DS prima di tornare in HOME.
        # Bug 25/04 (auto-WU5): _fund_raid/_achievement_rewards possono lasciare
        # il bot sulla mappa DS (pin_dado=1.0 ma navigator vede UNKNOWN).
        # vai_in_home alterna tap_overlay/back e il tap_overlay puo' riaprire
        # il popup evento, impedendo l'uscita. Soluzione: 4 back() puri prima
        # di vai_in_home() per scappare popup/mappa evento DS.
        for _ in range(4):
            ctx.device.back()
            time.sleep(cfg.delay_dopo_tap_minor)
        ctx.navigator.vai_in_home()
        return TaskResult(success=True, message=esito)

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

        # ATTESA ADATTIVA — pin_dado sentinel della maschera evento stabilizzata.
        # pin_dado è l'icona dado Gold visibile in basso-destra durante tutto il
        # gameplay District Showdown — indicatore più stabile di pin_autoplay
        # (che può essere sovrapposto dai popup Auto Roll durante animazioni).
        ready = self._wait_template_ready(
            ctx, cfg.pin_dado,
            max_wait=15.0, poll_interval=0.5,
            threshold=0.80, stable_polls=2,
        )
        if ready is None:
            ctx.log_msg(
                "[DS] Maschera evento NON stabilizzata in 15s "
                "(pin_dado non trovato) — fallback delay lungo"
            )
            time.sleep(cfg.delay_dopo_tap_popup * 2)
        else:
            ctx.log_msg(
                f"[DS] Maschera evento stabilizzata — "
                f"pin_dado score={ready.score:.3f} pos=({ready.cx},{ready.cy})"
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
                # Navigatore stato-aware verso mappa DS (back adattivi + rientro
                # automatico se usciamo oltre la mappa in HOME gioco).
                self._torna_a_mappa_ds(ctx, max_attempts=5)
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
        """Access Prohibited: polling 5s sincronizzato con 4 stati possibili.

        Problema sleep fisso: il popup dura 60s nel gioco ma quando il bot lo
        rileva può essere già aperto da N secondi (polling monitoring 15s).
        Un `time.sleep(70)` fisso porta desincronizzazione.

        Nuova logica: polling ogni 5s, ad ogni poll cerca 4 stati (ordine
        di verifica = priorità dalla più specifica alla più generica):
          A) pin_stop_auto_roll  → popup Auto Roll con Auto attivo → back + return
          B) pin_start_auto_roll → popup Auto Roll con Start visibile → tap + return
          C) pin_dado (gameplay) → popup AP chiuso, siamo tornati al tabellone
                                   District Showdown con Auto Roll che continua
                                   autonomamente → return (niente da fare)
          D) pin_access_prohibited → popup AP ancora visibile (normale) → continua

        Se nessuno dei 4 → transizione UI effimera, continua polling.
        Timeout safety 90s → back + _reenable_auto fallback.
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

            # Stato A — popup Auto Roll con Auto attivo
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

            # Stato B — popup Auto Roll con Start visibile
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

            # Stato C — pagina gioco (pin_dado visibile) con Auto Roll in
            # autoprosegue. Questo e' il caso piu' comune dopo AP: il popup
            # si chiude e il gioco riparte da solo, senza popup Auto Roll.
            has_dado = matcher.find_one(
                screen, cfg.pin_dado,
                threshold=cfg.tm_threshold,
            )
            if has_dado.found:
                ctx.log_msg(
                    f"[DS] AP chiuso dopo {elapsed:.0f}s — pagina gioco attiva "
                    f"(pin_dado score={has_dado.score:.3f}) → Auto prosegue, return"
                )
                return

            # Stato D — popup Access Prohibited ancora visibile (attesa normale)
            has_ap = matcher.find_one(
                screen, cfg.pin_access_prohibited,
                threshold=cfg.tm_threshold,
            )
            if has_ap.found:
                ctx.log_msg(
                    f"[DS] AP poll {poll_idx} ({elapsed:.0f}s): popup ancora attivo — wait 5s"
                )
            else:
                # Nessuno dei 4 — transizione UI effimera (animazione chiusura
                # popup, scene change). Continua polling finche' appare uno stato.
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

    # ------------------------------------------------------------------
    # Fase 2 — District Foray (reward secondario post dadi)
    # ------------------------------------------------------------------

    def _ha_red_dot(self, ctx: TaskContext) -> bool:
        """
        Pixel-check BGR del badge rosso nel popup District Foray.

        Stesso pattern di `tasks/radar._ha_badge`: invece di template PNG
        usa numpy per contare pixel rossi puri in una zona ristretta.
        Vantaggi:
          - Nessun PNG richiesto (robustezza setup).
          - Immune ad animazioni/flash del badge (size variabile).
          - Immune a shift sub-pixel su device diversi.

        Soglie da config (red_dot_r_min/g_max/b_max/min_pixels).
        ROI: `cfg.roi_red_dot` (bbox x1,y1,x2,y2) — calibrato attorno al
        bottone "Collect All" dove tipicamente compare il badge notifica.

        Fail-safe: True su eccezione (evita di perdere reward per errore).
        """
        cfg = self._cfg
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[DS-FORAY] red_dot: screenshot None — fail-safe True")
            return True
        try:
            import numpy as np  # lazy import
            frame = screen.frame
            x1, y1, x2, y2 = cfg.roi_red_dot
            zona = frame[y1:y2, x1:x2, :3]   # BGR
            b_ch = zona[:, :, 0].astype(int)
            g_ch = zona[:, :, 1].astype(int)
            r_ch = zona[:, :, 2].astype(int)
            rossi = (
                (r_ch > cfg.red_dot_r_min)
                & (g_ch < cfg.red_dot_g_max)
                & (b_ch < cfg.red_dot_b_max)
            )
            n_rossi = int(rossi.sum())
            trovato = n_rossi >= cfg.red_dot_min_pixels
            ctx.log_msg(
                f"[DS-FORAY] red_dot pixel_rossi={n_rossi} "
                f"(soglia={cfg.red_dot_min_pixels}) → "
                f"{'TROVATO' if trovato else 'assente'}"
            )
            return trovato
        except Exception as exc:
            ctx.log_msg(f"[DS-FORAY] red_dot errore (fail-safe True): {exc}")
            return True

    def _district_foray(self, ctx: TaskContext) -> None:
        """
        Dopo il loop monitoring (dadi esauriti/uscita rilevata), verifica
        l'icona District Foray nella barra eventi e reclama le ricompense
        accumulate se il badge rosso è visibile.

        Flusso:
          0. Gate readiness: wait adattivo su pin_dado per confermare che
             siamo nella MAPPA del gioco DS (non in popup residuo / transizione
             animazione). Se pin_dado non appare entro 10s → skip (non nella mappa).
          1. Cerca pin_district_foray nella roi_barra_eventi.
             Se non trovato → log + return (feature non presente o chiusa).
          2. Tap icona → attende delay_foray.
          3. Pixel-check red_dot (NO template PNG — vedi _ha_red_dot):
             - trovato  → tap tap_collect_all + delay + back + delay
             - assente  → solo delay + back + delay
          4. Verifica pin_dado per conferma ritorno schermata evento:
             - trovato  → log "schermata evento confermata"
             - assente  → log + vai_in_home() di sicurezza
        """
        cfg = self._cfg
        matcher = ctx.matcher

        # 0. GATE READINESS — navigatore stato-aware.
        # Se non sono nella mappa (es. uscito dopo item source), tenta rientro
        # automatico via tap icona evento. Dopo ritorno True → mappa stabile.
        if not self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-FORAY] impossibile raggiungere mappa — skip")
            return
        ctx.log_msg("[DS-FORAY] mappa confermata")

        # 1. Tap hardcoded sull'icona District Foray (coord misurate)
        # Template match fallisce sulla barra top per basso contrasto/animazione
        # → tap diretto su coordinate calibrate.
        ctx.log_msg(f"[DS-FORAY] tap icona {cfg.tap_foray_icon}")
        ctx.device.tap(*cfg.tap_foray_icon)
        time.sleep(cfg.delay_foray)

        # 3. Tap DIRETTO su Collect All — no check red_dot (sempre clicca).
        # Se non c'è reward, il tap va a vuoto (nessun danno, popup resta aperto).
        # Se c'è reward, claim immediato. Scelta più semplice e robusta del
        # pixel-check che dipendeva da calibrazione ROI esatta.
        ctx.log_msg(f"[DS-FORAY] tap Collect All {cfg.tap_collect_all}")
        ctx.device.tap(*cfg.tap_collect_all)
        time.sleep(cfg.delay_foray)
        ctx.device.back()
        time.sleep(cfg.delay_foray)

        # 4. Verifica ritorno schermata evento (pin_dado)
        screen = ctx.device.screenshot()
        if screen is None:
            ctx.log_msg("[DS-FORAY] screenshot None post-back — skip verifica")
            return
        res_dado = matcher.find_one(
            screen, cfg.pin_dado,
            threshold=cfg.tm_threshold,
        )
        if res_dado.found:
            ctx.log_msg(
                f"[DS-FORAY] schermata evento confermata "
                f"(pin_dado score={res_dado.score:.3f})"
            )
        else:
            # auto-WU7: pin_dado assente → _torna_a_mappa_ds (verifica
            # pin_dado nei primi tentativi, gestisce stato intermedio con
            # back, rientra solo se HOME). Evita round-trip HOME→evento.
            ctx.log_msg(
                "[DS-FORAY] pin_dado assente post-back — recovery adattivo"
            )
            self._torna_a_mappa_ds(ctx, max_attempts=5)

    # ------------------------------------------------------------------
    # Fase 3 — Influence Rewards (reclamo chiavi da statue alleanza)
    # ------------------------------------------------------------------

    def _influence_rewards(self, ctx: TaskContext) -> None:
        """
        Reclama ricompense "Alliance Influence" — chiavi accumulate dal
        punteggio influence dell'alleanza (reward milestone 100/200/300/500).

        Flusso:
          0. Gate readiness: wait adattivo su pin_dado per confermare che
             siamo nella MAPPA del gioco DS. Se non trovato in 10s → skip.
          1. Cerca pin_influence_rewards nella roi_barra_eventi (pagina gioco).
             Se non trovato → log + return.
          2. Tap icona → sleep delay_foray (apre popup "Alliance Influence").
          3. Tap tap_claim_key=(781,148) → sleep delay_foray
             (apre sub-popup claim chiave).
          4. Back → sleep delay_foray (chiude sub-popup, torna ad Alliance Influence).
          5. Back → sleep delay_foray (chiude Alliance Influence, torna pagina gioco).
          6. Verifica pin_dado per conferma pagina gioco:
             - trovato  → log + prosegue
             - assente  → vai_in_home sicurezza + return
          7. Back finale per uscire dalla pagina gioco → sleep delay_foray.
          8. Verifica schermata == HOME via navigator:
             - HOME   → log "HOME confermata"
             - altro  → vai_in_home sicurezza
        """
        cfg = self._cfg
        matcher = ctx.matcher

        # 0. GATE READINESS — navigatore stato-aware (con rientro automatico)
        if not self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-INFL] impossibile raggiungere mappa — skip")
            return
        ctx.log_msg("[DS-INFL] mappa confermata")

        # 1. Tap hardcoded sull'icona Influence Rewards (coord misurate)
        ctx.log_msg(f"[DS-INFL] tap icona {cfg.tap_influence_icon}")
        ctx.device.tap(*cfg.tap_influence_icon)
        time.sleep(cfg.delay_foray)

        # 3. Tap chiave posizione fissa → apre sub-popup claim
        ctx.log_msg(f"[DS-INFL] tap chiave {cfg.tap_claim_key}")
        ctx.device.tap(*cfg.tap_claim_key)
        time.sleep(cfg.delay_foray)

        # 4. Back — chiude sub-popup claim
        ctx.log_msg("[DS-INFL] back 1 (chiude sub-popup claim)")
        ctx.device.back()
        time.sleep(cfg.delay_foray)

        # 5. Recovery adattivo — auto-WU9: rimosso back 2 fisso che spesso
        # andava troppo lontano (back 1 chiudeva GIA' anche Alliance Influence
        # → back 2 finiva in HOME). _torna_a_mappa_ds verifica pin_dado nei
        # primi tentativi: se mappa OK → return. Se popup intermedio → back.
        # Se HOME → re-enter via icona evento. Tutti i casi gestiti.
        if not self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-INFL] recovery fallito — vai_in_home sicurezza")
            ctx.navigator.vai_in_home()
            return
        ctx.log_msg("[DS-INFL] pagina gioco confermata — fine, resto su mappa DS")
        # auto-WU8: rimosso back 3 + verifica HOME + vai_in_home sicurezza.
        # INFL ora resta sulla mappa DS. ACHV gate readiness _torna_a_mappa_ds
        # vedrà pin_dado e procederà direttamente senza round-trip HOME→evento.
        # Uscita finale dalla mappa DS gestita dal back x4 in run() (WU5).

    # ------------------------------------------------------------------
    # Fase 4 — Achievement Rewards (claim totale reward dadi usati)
    # ------------------------------------------------------------------

    def _achievement_rewards(self, ctx: TaskContext) -> None:
        """
        Reclama TUTTE le Achievement Rewards ("Used N Silver Dice" milestones).

        Il popup si apre cliccando un'icona nella mappa DS e permette di
        reclamare tutte le milestone raggiunte con un UNICO tap "Claim All".

        Flusso:
          0. Gate readiness — _torna_a_mappa_ds (rientra se uscito).
          1. Tap tap_achievement_icon=(939,238) → apre popup ACHIEVEMENT REWARDS
             → sleep delay_foray (attesa caricamento popup lento).
          2. Tap tap_claim_all=(882,129) → claim TUTTE le milestone disponibili
             → sleep delay_foray (attesa animazione claim).
          3. Back adattivo fino a pin_dado visibile (via _torna_a_mappa_ds).

        Attenzione delay: il gioco è lento, gli sleep tra tap sono necessari
        per evitare race UI (tap su schermata non ancora renderata).
        """
        cfg = self._cfg
        matcher = ctx.matcher

        # 0. Gate readiness — assicura di essere nella mappa DS
        if not self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-ACHV] impossibile raggiungere mappa — skip")
            return
        ctx.log_msg("[DS-ACHV] mappa confermata")

        # 1. Apri popup Achievement Rewards
        ctx.log_msg(f"[DS-ACHV] tap apertura {cfg.tap_achievement_icon}")
        ctx.device.tap(*cfg.tap_achievement_icon)
        time.sleep(cfg.delay_foray)   # attesa caricamento popup (gioco lento)

        # 2. Tap "Claim All" (singolo tap = tutte le milestone disponibili)
        ctx.log_msg(f"[DS-ACHV] tap Claim All {cfg.tap_claim_all}")
        ctx.device.tap(*cfg.tap_claim_all)
        time.sleep(cfg.delay_foray)   # attesa animazione claim + chiusura popup

        # auto-WU17: poll attivo pin_dado — panel ACHV auto-close lento, evita
        # cascata 2-back→HOME→rientro icona vista su FAU_01/FAU_02.
        ready = self._wait_template_ready(
            ctx, cfg.pin_dado,
            max_wait=5.0, poll_interval=0.5,
            threshold=0.80, stable_polls=1,
        )
        if ready is not None:
            ctx.log_msg(
                f"[DS-ACHV] completato — mappa già raggiunta "
                f"(pin_dado score={ready.score:.3f})"
            )
            return

        # 3. Back adattivo fino a mappa DS (fallback se panel ancora aperto)
        if self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-ACHV] completato — mappa DS ripristinata")
        else:
            ctx.log_msg("[DS-ACHV] mappa non ripristinata — vai_in_home sicurezza")
            ctx.navigator.vai_in_home()

    # ------------------------------------------------------------------
    # Fase 5 — Fund Raid (select prima alleanza "Last Raided")
    # ------------------------------------------------------------------

    def _fund_raid(self, ctx: TaskContext) -> None:
        """
        Avvia Fund Raid sulla prima alleanza della lista "Last Raided".

        Finestra temporale (UTC):
            Domenica 22:00 UTC  →  Lunedì 01:00 UTC
        Fuori da questa finestra → skip (raid non attivo in-game).

        Flusso:
          T0. Gate temporale (dom 22:00 → lun 01:00 UTC).
          0. Gate readiness — _torna_a_mappa_ds (rientra se uscito).
          1. Tap tap_fund_raid_icon=(837,39) → apre popup "Alliance List".
          2. Tap tap_fund_raid_select=(802,161) → Select prima alleanza.
          3. Loop attack fino a counter OCR = 0 (max_fund_raid_attacks safety).
          4. Back adattivo fino a mappa DS.
        """
        cfg = self._cfg

        # T0. Gate temporale — abilitato solo dom 22:00 → lun 01:00 UTC
        if not self._is_in_fund_raid_window():
            now_utc = datetime.now(timezone.utc)
            ctx.log_msg(
                f"[DS-RAID] fuori finestra Fund Raid "
                f"(now UTC {now_utc.strftime('%a %H:%M')}, "
                f"attiva dom {cfg.fund_raid_start_hour:02d}:00 → "
                f"lun {cfg.ds_end_hour:02d}:00) — skip"
            )
            return

        # 0. Gate readiness
        if not self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-RAID] impossibile raggiungere mappa — skip")
            return
        ctx.log_msg("[DS-RAID] mappa confermata")

        # 1. Apri popup Fund Raid
        ctx.log_msg(f"[DS-RAID] tap icona Fund Raid {cfg.tap_fund_raid_icon}")
        ctx.device.tap(*cfg.tap_fund_raid_icon)
        time.sleep(cfg.delay_foray)

        # 2. Select prima alleanza dalla lista "Last Raided"
        ctx.log_msg(f"[DS-RAID] tap Select {cfg.tap_fund_raid_select}")
        ctx.device.tap(*cfg.tap_fund_raid_select)
        time.sleep(cfg.delay_foray)

        # 3. Loop colpi — tap bottone attack finché il counter OCR mostra 0.
        # Il box `roi_fund_counter` contiene il numero di chiavi/colpi residui.
        # Si ferma quando il parsing legge "0" oppure dopo max_fund_raid_attacks
        # (safety cap per evitare loop infiniti se OCR fallisce).
        self._fund_raid_loop_attack(ctx)

        # 4. Back adattivo fino a mappa DS
        if self._torna_a_mappa_ds(ctx, max_attempts=5):
            ctx.log_msg("[DS-RAID] completato — mappa DS ripristinata")
        else:
            ctx.log_msg("[DS-RAID] mappa non ripristinata — vai_in_home sicurezza")
            ctx.navigator.vai_in_home()

    def _fund_raid_loop_attack(self, ctx: TaskContext) -> None:
        """
        Loop colpi Fund Raid a BLOCCHI di tap rapidi (auto-WU14).

        Pre-fix: tap singolo + screenshot + OCR + sleep delay_foray=7s ogni
        iterazione. 20 colpi * ~7.5s/iter ≈ 150s.
        Post-fix: blocchi di N tap consecutivi (delay 0.25s) senza
        screenshot intermedio. Dopo ogni block: screenshot + OCR counter
        per decidere se serve un altro block.
        Modello mutuato da DonazioneTask._loop_donate.

        Tempo: 30 tap in ~7.5s vs 30*7s=210s old → ~28× più veloce.
        Capacità: 30 × 5 block = 150 attack safety cap.

        Flusso per block:
          1. Burst di taps_per_block tap consecutivi
          2. Sleep wait_post_block (stabilizzazione UI)
          3. Screenshot → OCR counter chiavi/colpi residui
          4. Se counter="0" o cap max_blocks → stop
          5. Altrimenti next block
        """
        cfg = self._cfg
        try:
            from shared.ocr_helpers import ocr_cifre
        except ImportError:
            ctx.log_msg("[DS-RAID] ocr_cifre non disponibile — skip loop")
            return

        total_taps = 0
        for block_idx in range(cfg.fund_raid_max_blocks):
            ctx.log_msg(
                f"[DS-RAID] block {block_idx + 1}/{cfg.fund_raid_max_blocks} — "
                f"{cfg.fund_raid_taps_per_block} tap rapidi @ {cfg.tap_fund_raid_attack}"
            )

            # Burst di tap senza screenshot intermedio
            for _ in range(cfg.fund_raid_taps_per_block):
                ctx.device.tap(*cfg.tap_fund_raid_attack)
                time.sleep(cfg.fund_raid_wait_tap)
                total_taps += 1

            # Attesa stabilizzazione UI dopo burst
            time.sleep(cfg.fund_raid_wait_post_block)

            # Screenshot + OCR counter post-block
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg(
                    f"[DS-RAID] block {block_idx + 1}: screenshot None — stop"
                )
                break

            try:
                testo = ocr_cifre(screen.frame, zone=cfg.roi_fund_counter).strip()
            except Exception as exc:
                testo = ""
                ctx.log_msg(f"[DS-RAID] block {block_idx + 1}: OCR errore {exc}")

            # auto-WU15 (26/04 fix stop OCR): il counter ritorna come
            # "m,684" / "m.,384" / "m,0" — il prefisso "m" del formato
            # gioco confonde startswith("0"). Pre-fix: stop solo se intero
            # testo iniziava con "0" → mai matchato → 30 tap inutili nel
            # block finale. Post-fix: estrai ULTIMO numero dal testo;
            # se == 0 → stop.
            import re as _re_local
            nums = _re_local.findall(r"\d+", testo)
            last_num = int(nums[-1]) if nums else None
            ctx.log_msg(
                f"[DS-RAID] block {block_idx + 1} completato — "
                f"totale tap={total_taps}, counter OCR='{testo}' "
                f"(last_num={last_num})"
            )

            if last_num == 0:
                ctx.log_msg(
                    f"[DS-RAID] counter=0 dopo {total_taps} attack — stop"
                )
                break
            # OCR fail (nessun numero) o counter > 0 → prosegue prossimo block
        else:
            ctx.log_msg(
                f"[DS-RAID] max_blocks={cfg.fund_raid_max_blocks} raggiunto "
                f"— totale tap={total_taps}, stop safety"
            )
