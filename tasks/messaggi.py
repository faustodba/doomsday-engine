# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/messaggi.py
#
#  Task: raccolta ricompense dalla sezione Messaggi (tab Alliance + System).
#  SINCRONO (Step 25) — time.sleep, ctx.log_msg, navigator sincrono.
#
#  FIX RT-08a: chiusura con navigator.vai_in_home() invece di n_back_close fissi.
#  Gestisce correttamente sia il caso con popup ricompense sia senza.
#
#  FIX PRE-OPEN DUAL-TAB:
#   - Il gioco può aprire la schermata messaggi con Alliance O System già attivo.
#   - _rileva_tab_attivo() verifica entrambi i template in sequenza (con retry)
#     e ritorna 'alliance' | 'system' | None.
#   - _gestisci_tab() riceve skip_tap=True sul tab già attivo per evitare
#     un ri-tap ridondante su un tab già selezionato dal gioco.
#   - soglia_open separata da soglia_alliance/soglia_system per taratura indipendente.
#
#  FIX RECALIBRAZIONE TAB BAR (18/06):
#   - Il client gioco ha aggiunto i tab REPORT/SENT/BOOK alla schermata messaggi
#     (era solo Alliance+System). Le tab Alliance/System si sono spostate a
#     sinistra: roi/tap aggiornati su misurazione pixel-precisa (cv2.matchTemplate)
#     su 104 screenshot debug reali — 0/104 match con le coordinate vecchie,
#     103/104 con quelle nuove.
#
#  FIX DEAD-CONFIG wait_open/wait_tab (18/06):
#   - cfg.wait_open e cfg.wait_tab erano definiti ma ignorati: il codice usava
#     time.sleep(3.0) hardcoded dopo il tap su icona/tab, rendendo inefficace
#     qualunque tuning manuale di questi due campi. Ora il codice usa
#     cfg.wait_open/cfg.wait_tab; wait_tab default alzato 2.0→3.0 per
#     preservare il timing reale già in esecuzione (nessun cambio comportamento).
#
#  FIX TELEMETRIA SCHERMATA_NON_APERTA → FAIL (18/06):
#   - Era TaskResult.skip() → success=True, indistinguibile da un vero
#     completamento in engine_status.json/dashboard "Performance task"
#     (esito = "ok" if lr.success else "err", non guarda lo skipped flag).
#     Risultato: il fallimento multi-giorno del tab bar stale risultava
#     "100% eseguiti" nello storico/dashboard, anche se la telemetria
#     granulare (data/telemetry/events, outcome=skip) lo registrava
#     correttamente. "Schermata non aperta" non è un no-op legittimo
#     (skip) ma una reale incapacità di eseguire il task → ora FAIL.
#     Effetto collaterale positivo: last_run non avanza su fail (vedi
#     WU79 in orchestrator.py) → retry al ciclo successivo invece di
#     aspettare le 4h piene dell'intervallo periodic.
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template


@dataclass
class MessaggiConfig:
    tap_icona_messaggi: tuple[int, int] = (928, 430)
    tap_tab_alliance:   tuple[int, int] = (198, 34)
    tap_tab_system:     tuple[int, int] = (328, 34)
    tap_read_all:       tuple[int, int] = (108, 511)
    tap_close:          tuple[int, int] = (930, 36)
    roi_alliance:       tuple[int, int, int, int] = (145, 15, 250, 50)
    roi_system:         tuple[int, int, int, int] = (280, 15, 377, 50)
    roi_read:           tuple[int, int, int, int] = (61, 499, 156, 523)
    # soglia_open: soglia unificata PRE-OPEN, usata da _rileva_tab_attivo()
    # su entrambi i template. Abbassabile indipendentemente da soglia_alliance/system.
    soglia_open:        float = 0.80
    soglia_alliance:    float = 0.80
    soglia_system:      float = 0.80
    soglia_read:        float = 0.85
    wait_open:          float = 3.0
    wait_tab:           float = 3.0
    wait_read:          float = 3.0
    wait_close:         float = 2.5
    retry_tab:          int   = 2
    retry_sleep:        float = 2.0
    retry_sleep_open:   float = 2.5
    retry_sleep_read:   float = 2.0
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

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.messaggi)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("messaggi", getattr(ctx, "instance_name", "_unknown"))
        self._dbg = debug

        try:
            esito, alliance_ok, system_ok = self._esegui_messaggi(
                device, matcher, ctx.navigator, log, cfg
            )
        except Exception as exc:
            debug.snap("99_exception", device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_messaggi")

        # Anomalia: schermata aperta ma 0 claim su entrambe le tab
        anomalia = (esito == _Esito.COMPLETATO and not alliance_ok and not system_ok)
        debug.flush(
            success=(esito == _Esito.COMPLETATO),
            force=anomalia,
            log_fn=log,
        )

        return self._mappa_esito(esito, alliance_ok, system_ok, log)

    def _esegui_messaggi(self, device, matcher, navigator, log, cfg):
        _dbg = getattr(self, "_dbg", None)
        if _dbg is not None:
            _dbg.snap("00_pre_open", device.screenshot())

        log(f"Tap icona messaggi {cfg.tap_icona_messaggi}")
        device.tap(*cfg.tap_icona_messaggi)
        time.sleep(cfg.wait_open)

        # PRE-OPEN: il gioco può aprire con Alliance o System già attivo (arancione).
        # _rileva_tab_attivo() verifica entrambi i template e ritorna quale è attivo.
        # Se nessuno dei due viene riconosciuto → schermata non aperta → abort.
        tab_attivo = self._rileva_tab_attivo(device, matcher, cfg, log)

        if _dbg is not None:
            _dbg.snap("01_post_open", device.screenshot())

        if tab_attivo is None:
            log("ANOMALIA: schermata non aperta (nessun tab rilevato) — BACK + abort")
            device.back()
            return _Esito.SCHERMATA_NON_APERTA, False, False

        log(f"[PRE-OPEN] schermata aperta — tab attivo: {tab_attivo}")

        # Processa Alliance: se già attivo al PRE-OPEN salta il tap (skip_tap=True)
        alliance_ok = self._gestisci_tab(
            device, matcher,
            cfg.tap_tab_alliance, cfg.tmpl_alliance,
            cfg.soglia_alliance, cfg.roi_alliance,
            "Alliance", log, cfg,
            skip_tap=(tab_attivo == "alliance"),
        )
        if _dbg is not None:
            _dbg.snap("02_post_alliance", device.screenshot())

        # Processa System: se già attivo al PRE-OPEN salta il tap (skip_tap=True)
        system_ok = self._gestisci_tab(
            device, matcher,
            cfg.tap_tab_system, cfg.tmpl_system,
            cfg.soglia_system, cfg.roi_system,
            "System", log, cfg,
            skip_tap=(tab_attivo == "system"),
        )
        if _dbg is not None:
            _dbg.snap("03_post_system", device.screenshot())

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

    def _rileva_tab_attivo(self, device, matcher, cfg, log) -> str | None:
        """PRE-OPEN dual-tab: verifica Alliance poi System come sentinel di apertura.
        Il tab attivo (arancione) viene riconosciuto dal template corrispondente.
        Un retry gestisce animazioni lente di apertura schermata.
        Ritorna: 'alliance' | 'system' | None (schermata non aperta).
        """
        shot = device.screenshot()

        score_a = matcher.score(shot, cfg.tmpl_alliance, zone=cfg.roi_alliance)
        score_s = matcher.score(shot, cfg.tmpl_system,   zone=cfg.roi_system)
        log(f"[PRE-OPEN] alliance={score_a:.3f} system={score_s:.3f}")

        if score_a >= cfg.soglia_open:
            return "alliance"
        if score_s >= cfg.soglia_open:
            return "system"

        # Retry: attendi animazione apertura e ricontrolla entrambi
        log(f"[PRE-OPEN] nessun tab rilevato — retry tra {cfg.retry_sleep_open}s")
        time.sleep(cfg.retry_sleep_open)
        shot = device.screenshot()

        score_a = matcher.score(shot, cfg.tmpl_alliance, zone=cfg.roi_alliance)
        score_s = matcher.score(shot, cfg.tmpl_system,   zone=cfg.roi_system)
        log(f"[PRE-OPEN RETRY] alliance={score_a:.3f} system={score_s:.3f}")

        if score_a >= cfg.soglia_open:
            return "alliance"
        if score_s >= cfg.soglia_open:
            return "system"

        return None

    def _gestisci_tab(self, device, matcher, tab_tap, tab_tmpl, tab_soglia,
                      tab_roi, nome_tab, log, cfg, skip_tap: bool = False):
        # skip_tap=True: tab già attivo dal PRE-OPEN, nessun tap necessario
        if skip_tap:
            log(f"[{nome_tab.upper()}] già attivo dal PRE-OPEN — tap skippato")
        else:
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
            return TaskResult.fail("Schermata messaggi non aperta")
        return TaskResult.fail(f"Errore messaggi: {esito}")
