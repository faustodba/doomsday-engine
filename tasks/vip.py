# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/vip.py                  → C:\doomsday-engine\tasks\vip.py
#
#  Task: ritiro ricompense VIP giornaliere (cassaforte + claim free daily).
#
#  Flusso (macchina a stati con max 3 tentativi — identico V5):
#
#    STEP 1 — HOME pulita via navigator
#    STEP 2 — Tap badge VIP (85,52) → [PRE-VIP] pin_vip_01_store visibile?
#               NO → 3×BACK + retry
#    STEP 3 — CASSAFORTE:
#               pin_vip_02_cass_chiusa → disponibile  → tap Claim
#                 [PRE-POPUP-C] pin_vip_06_popup_cass → dismiss
#                 [GATE-C] polling pin_vip_01_store tornato (max 5s, retry 1)
#                 [POST-C] pin_vip_03_cass_aperta → cass_ok=True
#               pin_vip_03_cass_aperta → già ritirata → cass_ok=True
#    STEP 4 — CLAIM FREE:
#               pin_vip_04_free_chiuso → disponibile → tap Claim Free
#                 [PRE-POPUP-F] pin_vip_07_popup_free → dismiss TAP_CHIUDI_REWARD_FREE
#                 [GATE-F] polling pin_vip_01_store tornato (max 8s, retry 1)
#                 [POST-F] pin_vip_05_free_aperto → free_ok=True
#               pin_vip_05_free_aperto → già ritirato → free_ok=True
#    STEP 5 — cass_ok AND free_ok → BACK×3 + HOME → ok
#               altrimenti → prossimo tentativo
#
#  Templates richiesti in templates/pin/:
#    pin_vip_01_store.png       pin_vip_02_cass_chiusa.png
#    pin_vip_03_cass_aperta.png pin_vip_04_free_chiuso.png
#    pin_vip_05_free_aperto.png pin_vip_06_popup_cass.png
#    pin_vip_07_popup_free.png
#
#  Scheduling: daily, priority=15.
#  Outcome:
#    TaskResult.ok()   → entrambe le ricompense ritirate (o già ritirate)
#    TaskResult.skip() → maschera VIP non aperta dopo tutti i tentativi
#    TaskResult.fail() → errore strutturale
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# VipConfig
# ==============================================================================

@dataclass
class VipConfig:
    """Parametri configurabili per VipTask."""

    # ── Coordinate UI (960×540) ───────────────────────────────────────────────
    tap_badge:           tuple[int, int] = (85,  52)
    tap_claim_cassaforte:tuple[int, int] = (830, 160)
    tap_claim_free:      tuple[int, int] = (526, 444)
    tap_dismiss_cass:    tuple[int, int] = (481, 381)
    tap_dismiss_free:    tuple[int, int] = (483, 391)
    tap_chiudi_reward_free: tuple[int, int] = (456, 437)

    # ── ROI template matching (x1, y1, x2, y2) ───────────────────────────────
    roi_store:       tuple = (118, 109, 287, 158)
    roi_cass_chiusa: tuple = (778,  98, 866, 203)
    roi_cass_aperta: tuple = (799,  89, 866, 172)
    roi_free_chiuso: tuple = (465, 423, 674, 483)
    roi_free_aperto: tuple = (540, 298, 605, 368)
    roi_popup_cass:  tuple = (308, 345, 654, 417)
    roi_popup_free:  tuple = (308, 345, 654, 417)

    # ── Soglie template matching ──────────────────────────────────────────────
    soglia_store:       float = 0.80
    soglia_cass_chiusa: float = 0.80
    soglia_cass_aperta: float = 0.75
    soglia_free_chiuso: float = 0.80
    soglia_free_aperto: float = 0.80
    soglia_popup_cass:  float = 0.80
    soglia_popup_free:  float = 0.80

    # ── Template paths (relativi a templates/) ────────────────────────────────
    tmpl_store:       str = "pin/pin_vip_01_store.png"
    tmpl_cass_chiusa: str = "pin/pin_vip_02_cass_chiusa.png"
    tmpl_cass_aperta: str = "pin/pin_vip_03_cass_aperta.png"
    tmpl_free_chiuso: str = "pin/pin_vip_04_free_chiuso.png"
    tmpl_free_aperto: str = "pin/pin_vip_05_free_aperto.png"
    tmpl_popup_cass:  str = "pin/pin_vip_06_popup_cass.png"
    tmpl_popup_free:  str = "pin/pin_vip_07_popup_free.png"

    # ── Logica tentativi ──────────────────────────────────────────────────────
    max_tentativi:   int   = 3
    gate_max_poll:   int   = 5     # secondi polling GATE-C
    gate_f_max_poll: int   = 8     # secondi polling GATE-F
    retry_screen:    int   = 1
    retry_sleep:     float = 1.0

    # ── Attese ────────────────────────────────────────────────────────────────
    wait_open_badge:  float = 2.0
    wait_claim_cass:  float = 2.5
    wait_claim_free:  float = 2.0
    wait_gate_poll:   float = 1.0
    wait_back:        float = 0.5
    wait_back_pre:    float = 0.4
    n_back_chiudi:    int   = 3


# ==============================================================================
# Esiti interni
# ==============================================================================

class _Esito:
    COMPLETATO         = "completato"
    PARZIALE           = "parziale"           # una sola ricompensa
    MASCHERA_NON_APERTA = "maschera_non_aperta"
    ERRORE             = "errore"


# ==============================================================================
# VipTask
# ==============================================================================

class VipTask(Task):
    """
    Ritira le ricompense VIP giornaliere (cassaforte + claim free daily).

    Scheduling: daily, priority=15.
    Registrato in scheduler come:
        scheduler.register("vip", kind="daily", priority=15)

    Riprova fino a max_tentativi se la maschera non si apre o
    le ricompense non vengono confermate.
    """

    def __init__(self, config: VipConfig | None = None) -> None:
        self._cfg = config or VipConfig()

    # ── ABC: name ─────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "vip"

    # ── ABC: should_run ───────────────────────────────────────────────────────

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("vip")
        return True

    # ── ABC: run ──────────────────────────────────────────────────────────────

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg     = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            # log
                ctx.log_msg(f"[VIP] {msg}")

        try:
            esito, cass_ok, free_ok = self._esegui_vip(
                device, matcher, ctx.navigator, log, cfg
            )
        except Exception as exc:
            return TaskResult.fail(f"Eccezione non gestita: {exc}", step="esegui_vip")

        return self._mappa_esito(esito, cass_ok, free_ok, log)

    # ── Flusso principale con retry ───────────────────────────────────────────

    def _esegui_vip(
        self,
        device:    "MuMuDevice | FakeDevice",
        matcher:   "TemplateMatcher",
        navigator,
        log,
        cfg:       VipConfig,
    ) -> tuple[str, bool, bool]:
        """
        Flusso VIP con max_tentativi retry.
        Ritorna (esito, cass_ok, free_ok).
        """
        for tentativo in range(1, cfg.max_tentativi + 1):
            log(f"Tentativo {tentativo}/{cfg.max_tentativi}")

            # ── STEP 1: HOME ─────────────────────────────────────────────────
            if navigator is not None:
                if not navigator.vai_in_home():
                    log(f"HOME non raggiungibile (t={tentativo}) — prossimo tentativo")
                    continue
            else:
                log("Navigator non disponibile — assumo HOME corrente")

            # ── STEP 2: apri maschera VIP ─────────────────────────────────────
            log(f"Tap badge VIP {cfg.tap_badge}")
            device.tap(*cfg.tap_badge)
            time.sleep(cfg.wait_open_badge)

            ok_store = self._check_pin(
                device, matcher,
                cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
                retry=cfg.retry_screen, retry_sleep=cfg.retry_sleep,
                log=log, label="PRE-VIP"
            )
            if not ok_store:
                log("[PRE-VIP] maschera non aperta → 3×BACK + retry")
                for _ in range(cfg.n_back_chiudi):
                    device.back()
                    time.sleep(cfg.wait_back_pre)
                continue

            log("[PRE-VIP] pin_vip_01_store visibile — maschera aperta OK")

            # ── STEP 3: CASSAFORTE ────────────────────────────────────────────
            cass_ok = self._gestisci_cassaforte(
                device, matcher, log, cfg
            )

            # ── STEP 4: CLAIM FREE ────────────────────────────────────────────
            free_ok = self._gestisci_claim_free(
                device, matcher, log, cfg
            )

            # ── STEP 5: verifica successo ─────────────────────────────────────
            log(f"Stato finale → cass={'OK' if cass_ok else 'KO'} "
                f"free={'OK' if free_ok else 'KO'}")

            # Chiudi maschera VIP prima di tornare in home
            for _ in range(cfg.n_back_chiudi):
                device.back()
                time.sleep(cfg.wait_back)

            if navigator is not None:
                navigator.vai_in_home()

            if cass_ok and free_ok:
                log("Entrambe le ricompense confermate — completato ✓")
                return _Esito.COMPLETATO, True, True

            if cass_ok or free_ok:
                log(f"Tentativo {tentativo} parziale — "
                    + ("altro tentativo" if tentativo < cfg.max_tentativi else "fallito"))
            else:
                log(f"Tentativo {tentativo} fallito — "
                    + ("altro tentativo" if tentativo < cfg.max_tentativi else "abbandonato"))

        log(f"Fallito dopo {cfg.max_tentativi} tentativi")
        return _Esito.MASCHERA_NON_APERTA, False, False

    # ── Gestione cassaforte ───────────────────────────────────────────────────

    def _gestisci_cassaforte(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     VipConfig,
    ) -> bool:
        """
        Gestisce il ritiro della cassaforte.
        Ritorna True se ritirata (o già ritirata), False se anomalia.
        """
        log("[1] Verifica stato cassaforte")
        shot = device.screenshot()

        cass_chiusa = matcher.score(shot, cfg.tmpl_cass_chiusa,
                                    zone=cfg.roi_cass_chiusa) >= cfg.soglia_cass_chiusa
        cass_aperta = matcher.score(shot, cfg.tmpl_cass_aperta,
                                    zone=cfg.roi_cass_aperta) >= cfg.soglia_cass_aperta

        if cass_aperta:
            log("[1] pin_vip_03 visibile — cassaforte già ritirata oggi → skip")
            return True

        if not cass_chiusa:
            log("[1] ANOMALIA: nessun pin cassaforte rilevato — skip")
            return False

        # Cassaforte disponibile → tap Claim
        log(f"[1] pin_vip_02 visibile → tap Claim {cfg.tap_claim_cassaforte}")
        device.tap(*cfg.tap_claim_cassaforte)
        time.sleep(cfg.wait_claim_cass)

        # [PRE-POPUP-C]
        ok_popup = self._check_pin(
            device, matcher,
            cfg.tmpl_popup_cass, cfg.soglia_popup_cass, cfg.roi_popup_cass,
            retry=cfg.retry_screen, retry_sleep=cfg.retry_sleep,
            log=log, label="PRE-POPUP-C"
        )
        if not ok_popup:
            log("[PRE-POPUP-C] ANOMALIA: popup_cass non visibile — tento dismiss")

        device.tap(*cfg.tap_dismiss_cass)

        # [GATE-C] polling pin_vip_01_store tornato
        gate_c = self._polling_gate(
            device, matcher,
            cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
            max_poll=cfg.gate_max_poll, poll_sleep=cfg.wait_gate_poll,
            log=log, label="GATE-C"
        )
        if not gate_c:
            log("[GATE-C] ANOMALIA: maschera non tornata — retry dismiss")
            device.tap(*cfg.tap_dismiss_cass)
            gate_c = self._polling_gate(
                device, matcher,
                cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
                max_poll=cfg.gate_max_poll, poll_sleep=cfg.wait_gate_poll,
                log=log, label="GATE-C retry"
            )
            if not gate_c:
                log("[GATE-C] ANOMALIA: maschera ancora non tornata — procedo")

        # [POST-C]
        cass_ok = self._check_pin(
            device, matcher,
            cfg.tmpl_cass_aperta, cfg.soglia_cass_aperta, cfg.roi_cass_aperta,
            retry=cfg.retry_screen, retry_sleep=cfg.retry_sleep,
            log=log, label="POST-C"
        )
        if cass_ok:
            log("[POST-C] pin_vip_03 visibile — cassaforte ritirata confermata OK")
        else:
            log("[POST-C] ANOMALIA: pin_vip_03 non visibile — cassaforte non confermata")

        return cass_ok

    # ── Gestione claim free ───────────────────────────────────────────────────

    def _gestisci_claim_free(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     VipConfig,
    ) -> bool:
        """
        Gestisce il ritiro del Claim Free Daily.
        Ritorna True se ritirato (o già ritirato), False se anomalia.
        """
        log("[2] Verifica stato Claim Free Daily")
        shot = device.screenshot()

        free_chiuso = matcher.score(shot, cfg.tmpl_free_chiuso,
                                    zone=cfg.roi_free_chiuso) >= cfg.soglia_free_chiuso
        free_aperto = matcher.score(shot, cfg.tmpl_free_aperto,
                                    zone=cfg.roi_free_aperto) >= cfg.soglia_free_aperto

        if free_aperto:
            log("[2] pin_vip_05 visibile — Claim Free già ritirato oggi → skip")
            return True

        if not free_chiuso:
            log("[2] ANOMALIA: nessun pin Claim Free rilevato — skip")
            return False

        # Claim Free disponibile → tap
        log(f"[2] pin_vip_04 visibile → tap Claim Free {cfg.tap_claim_free}")
        device.tap(*cfg.tap_claim_free)
        time.sleep(cfg.wait_claim_free)

        # [PRE-POPUP-F]
        ok_popup = self._check_pin(
            device, matcher,
            cfg.tmpl_popup_free, cfg.soglia_popup_free, cfg.roi_popup_free,
            retry=cfg.retry_screen, retry_sleep=cfg.retry_sleep,
            log=log, label="PRE-POPUP-F"
        )
        if not ok_popup:
            log("[PRE-POPUP-F] ANOMALIA: popup_free non visibile — tento dismiss")

        # Chiudi schermata ricompensa (richiede tap esplicito)
        log(f"Tap chiudi reward free {cfg.tap_chiudi_reward_free}")
        device.tap(*cfg.tap_chiudi_reward_free)

        # [GATE-F] polling pin_vip_01_store tornato
        gate_f = self._polling_gate(
            device, matcher,
            cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
            max_poll=cfg.gate_f_max_poll, poll_sleep=cfg.wait_gate_poll,
            log=log, label="GATE-F"
        )
        if not gate_f:
            log("[GATE-F] ANOMALIA: maschera non tornata — retry tap chiudi reward")
            device.tap(*cfg.tap_chiudi_reward_free)
            gate_f = self._polling_gate(
                device, matcher,
                cfg.tmpl_store, cfg.soglia_store, cfg.roi_store,
                max_poll=cfg.gate_f_max_poll, poll_sleep=cfg.wait_gate_poll,
                log=log, label="GATE-F retry"
            )
            if not gate_f:
                log("[GATE-F] ANOMALIA: maschera ancora non tornata — procedo")

        # [POST-F]
        free_ok = self._check_pin(
            device, matcher,
            cfg.tmpl_free_aperto, cfg.soglia_free_aperto, cfg.roi_free_aperto,
            retry=2, retry_sleep=cfg.retry_sleep,
            log=log, label="POST-F"
        )
        if free_ok:
            log("[POST-F] pin_vip_05 visibile — Claim Free ritirato confermato OK")
        else:
            log("[POST-F] ANOMALIA: pin_vip_05 non visibile — Claim Free non confermato")

        return free_ok

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_pin(
        self,
        device:      "MuMuDevice | FakeDevice",
        matcher:     "TemplateMatcher",
        tmpl:        str,
        soglia:      float,
        roi:         tuple,
        retry:       int,
        retry_sleep: float,
        log,
        label:       str,
    ) -> bool:
        """Verifica presenza pin con retry. Ritorna True se trovato."""
        for tentativo in range(retry + 1):
            shot  = device.screenshot()
            score = matcher.score(shot, tmpl, zone=roi)
            found = score >= soglia
            log(f"[{label}] {tmpl}: score={score:.3f} → {'OK' if found else 'NON trovato'}"
                + (f" (t={tentativo+1})" if retry > 0 else ""))
            if found:
                return True
            if tentativo < retry:
                time.sleep(retry_sleep)
        return False

    def _polling_gate(
        self,
        device:     "MuMuDevice | FakeDevice",
        matcher:    "TemplateMatcher",
        tmpl:       str,
        soglia:     float,
        roi:        tuple,
        max_poll:   int,
        poll_sleep: float,
        log,
        label:      str,
    ) -> bool:
        """
        Polling su un pin per max_poll secondi.
        Ritorna True appena trovato, False se esauriti i tentativi.
        """
        for t in range(max_poll):
            time.sleep(poll_sleep)
            shot  = device.screenshot()
            score = matcher.score(shot, tmpl, zone=roi)
            if score >= soglia:
                log(f"[{label}] pin tornato ({t+1}s) — OK")
                return True
        return False

    # ── Mapping esito → TaskResult ────────────────────────────────────────────

    @staticmethod
    def _mappa_esito(
        esito:   str,
        cass_ok: bool,
        free_ok: bool,
        log,
    ) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(
                "VIP completato — cassaforte e claim free ritirati",
                cass_ok=cass_ok,
                free_ok=free_ok,
            )
        if esito == _Esito.MASCHERA_NON_APERTA:
            log("Outcome=maschera_non_aperta → skip")
            return TaskResult.skip("Maschera VIP non aperta dopo tutti i tentativi")
        log(f"Outcome={esito!r} → fail")
        return TaskResult.fail(f"Errore VIP: {esito}")

    def __repr__(self) -> str:
        return f"VipTask(config={self._cfg})"
