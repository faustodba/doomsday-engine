# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/messaggi.py
#
#  Task: raccolta ricompense dalla sezione Messaggi (tab Alliance + System).
#  SINCRONO (Step 25) — time.sleep, ctx.log_msg, navigator sincrono.
#
#  FIX RT-08a: chiusura con navigator.vai_in_home() invece di n_back_close fissi.
#  Gestisce correttamente sia il caso con popup ricompense sia senza.
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult


@dataclass
class MessaggiConfig:
    tap_icona_messaggi: tuple[int, int] = (928, 430)
    tap_tab_alliance:   tuple[int, int] = (325, 35)
    tap_tab_system:     tuple[int, int] = (453, 36)
    tap_read_all:       tuple[int, int] = (108, 511)
    tap_close:          tuple[int, int] = (930, 36)
    roi_alliance:       tuple[int, int, int, int] = (283, 23, 367, 47)
    roi_system:         tuple[int, int, int, int] = (417, 23, 490, 50)
    roi_read:           tuple[int, int, int, int] = (61, 499, 156, 523)
    soglia_alliance:    float = 0.80
    soglia_system:      float = 0.80
    soglia_read:        float = 0.85
    wait_open:          float = 2.0
    wait_tab:           float = 1.0
    wait_read:          float = 2.0
    wait_close:         float = 1.5
    retry_tab:          int   = 2
    retry_sleep:        float = 1.0
    retry_sleep_open:   float = 1.5
    retry_sleep_read:   float = 1.0
    tmpl_alliance:      str   = "pin/pin_msg_02_alliance.png"
    tmpl_system:        str   = "pin/pin_msg_03_system.png"
    tmpl_read:          str   = "pin/pin_msg_04_read.png"


class _Esito:
    COMPLETATO           = "completato"
    SCHERMATA_NON_APERTA = "schermata_non_aperta"
    ERRORE               = "errore"


class MessaggiTask(Task):
    """Raccoglie ricompense Messaggi (Alliance + System). Scheduling: periodic 4h."""

    def __init__(self, config: MessaggiConfig | None = None) -> None:
        self._cfg = config or MessaggiConfig()

    def name(self) -> str:
        return "messaggi"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("messaggi")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg     = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            ctx.log_msg(f"[MSG] {msg}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="assicura_home")

        try:
            esito, alliance_ok, system_ok = self._esegui_messaggi(
                device, matcher, ctx.navigator, log, cfg
            )
        except Exception as exc:
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_messaggi")

        return self._mappa_esito(esito, alliance_ok, system_ok, log)

    def _esegui_messaggi(self, device, matcher, navigator, log, cfg):
        log(f"Tap icona messaggi {cfg.tap_icona_messaggi}")
        device.tap(*cfg.tap_icona_messaggi)
        time.sleep(cfg.wait_open)

        ok_open = self._verifica_pin(device, matcher, cfg.tmpl_alliance,
                                     cfg.soglia_alliance, cfg.roi_alliance,
                                     retry=2, retry_sleep=cfg.retry_sleep_open,
                                     log=log, label="PRE-OPEN")
        if not ok_open:
            log("ANOMALIA: schermata non aperta — BACK + abort")
            device.back()
            return _Esito.SCHERMATA_NON_APERTA, False, False

        log("[PRE-OPEN] schermata messaggi aperta — OK")

        alliance_ok = self._gestisci_tab(device, matcher,
                                         cfg.tap_tab_alliance, cfg.tmpl_alliance,
                                         cfg.soglia_alliance, cfg.roi_alliance,
                                         "Alliance", log, cfg)
        system_ok   = self._gestisci_tab(device, matcher,
                                         cfg.tap_tab_system, cfg.tmpl_system,
                                         cfg.soglia_system, cfg.roi_system,
                                         "System", log, cfg)

        log(f"Tap X chiudi {cfg.tap_close}")
        device.tap(*cfg.tap_close)
        time.sleep(cfg.wait_close)

        # Ritorno in HOME robusto: gestisce popup ricompense e stack screen
        if navigator is not None:
            ok_home = navigator.vai_in_home()
            log(f"[POST-CLOSE] vai_in_home → {'OK' if ok_home else 'FALLITO'}")
        else:
            log("[POST-CLOSE] navigator non disponibile — nessun recovery")

        return _Esito.COMPLETATO, alliance_ok, system_ok

    def _gestisci_tab(self, device, matcher, tab_tap, tab_tmpl, tab_soglia,
                      tab_roi, nome_tab, log, cfg):
        log(f"Tap tab {nome_tab} {tab_tap}")
        device.tap(*tab_tap)
        time.sleep(cfg.wait_tab)

        ok_tab = self._verifica_pin(device, matcher, tab_tmpl, tab_soglia, tab_roi,
                                    retry=cfg.retry_tab, retry_sleep=cfg.retry_sleep,
                                    log=log, label=f"PRE-{nome_tab.upper()}")
        if not ok_tab:
            log(f"ANOMALIA: tab {nome_tab} non attivo — skip")
            return False
        log(f"[PRE-{nome_tab.upper()}] tab attivo — OK")

        ok_read = self._verifica_pin(device, matcher, cfg.tmpl_read, cfg.soglia_read,
                                     cfg.roi_read, retry=1, retry_sleep=cfg.retry_sleep_read,
                                     log=log, label="PRE-READ")
        if ok_read:
            log("Tap Read and claim all")
            device.tap(*cfg.tap_read_all)
            time.sleep(cfg.wait_read)
        else:
            log(f"[PRE-READ] bottone non visibile — nessun messaggio su {nome_tab}")
        return True

    def _verifica_pin(self, device, matcher, tmpl, soglia, roi,
                      retry, retry_sleep, log, label) -> bool:
        for t in range(retry + 1):
            shot  = device.screenshot()
            score = matcher.score(shot, tmpl, zone=roi)
            found = score >= soglia
            log(f"[{label}] score={score:.3f} → {'OK' if found else 'NO'}")
            if found:
                return True
            if t < retry:
                time.sleep(retry_sleep)
        return False

    @staticmethod
    def _mappa_esito(esito, alliance_ok, system_ok, log) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok("Messaggi completati", alliance=alliance_ok, system=system_ok)
        if esito == _Esito.SCHERMATA_NON_APERTA:
            return TaskResult.skip("Schermata messaggi non aperta")
        return TaskResult.fail(f"Errore messaggi: {esito}")
