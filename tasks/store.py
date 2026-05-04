# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/store.py                → C:\doomsday-engine\tasks\store.py
#
#  Task: acquisto automatico Mysterious Merchant Store.
#
#  Flusso (porta identica V5):
#    1. Assicura HOME via navigator
#    2. Collassa banner eventi (libera viewport)
#    3. Scan griglia spirale 25 passi → trova edificio Store
#    4. Tap Store → verifica label / mercante diretto → tap carrello
#    5. Verifica merchant aperto
#    6. Acquista tutti i pulsanti gialli (pin_legno/pomodoro/acciaio) per pagina
#    7. Swipe → pagina 2 → pagina 3
#    8. Free Refresh (una sola volta) se disponibile
#    9. Ripete acquisti dopo refresh
#   10. BACK → chiude negozio
#   11. Ripristina banner
#   12. Verifica HOME finale
#
#  Templates richiesti in templates/store/:
#    pin_store.png           pin_store_attivo.png    pin_carrello.png
#    pin_merchant.png        pin_mercante.png
#    pin_banner_aperto.png   pin_banner_chiuso.png
#    pin_legno.png           pin_pomodoro.png        pin_acciaio.png
#    pin_free_refresh.png    pin_no_refresh.png
#
#  Scheduling: periodic, interval_h=4, priority=20.
#  Outcome:
#    TaskResult.ok()   → completato (anche acquistati=0 = niente da comprare)
#    TaskResult.skip() → store non trovato, non in home, disabilitato
#    TaskResult.fail() → errore strutturale
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# Debug buffer — WU115 migrato a shared/debug_buffer (hot-reload via config).
# Toggle: globali.debug_tasks.store (default False) in runtime_overrides.json.
# Sostituisce WU85 _DEBUG_STORE_FAIL_DUMP modulo-level con architettura unificata.
# ==============================================================================


# ==============================================================================
# StoreConfig
# ==============================================================================

@dataclass
class StoreConfig:
    """Parametri configurabili per StoreTask."""

    # ── Soglie template matching ──────────────────────────────────────────────
    soglia_store:        float = 0.65   # 0.675 → 0.65 (auto-WU4): cattura re-match drift su take-max (FAU_09 caso 0.665)
    soglia_store_early_exit: float = 0.80  # Issue #71 (26/04/2026): se score >= early_exit, interrompi scan e procedi diretto
    soglia_banner:       float = 0.85
    soglia_store_attivo: float = 0.65
    soglia_carrello:     float = 0.65
    soglia_merchant:     float = 0.75
    soglia_mercante:     float = 0.75
    soglia_acquisto:     float = 0.80
    soglia_free_refresh: float = 0.80
    soglia_no_refresh:   float = 0.80

    # ── Scan spirale ──────────────────────────────────────────────────────────
    passo_scan:   int = 300   # pixel per swipe mappa
    max_pagine:   int = 3     # pagine negozio da scorrere

    # ── Coordinate fisse (960×540) ────────────────────────────────────────────
    swipe_cx:           int = 480
    swipe_cy:           int = 300
    swipe_dur_ms:       int = 600
    merchant_swipe_dy:  int = 180
    merchant_swipe_dur: int = 500
    banner_tap_x:       int = 345
    banner_tap_y:       int = 63
    nms_dist:           int = 40

    # ── ROI (x1, y1, x2, y2) ─────────────────────────────────────────────────
    roi_home_banner_aperto: tuple = (0, 115, 960, 470)
    roi_home_banner_chiuso: tuple = (0,  70, 960, 470)
    roi_banner_pin:         tuple = (330, 40, 365, 90)
    roi_negozio:            tuple = (100, 100, 870, 455)
    roi_footer:             tuple = (100, 450, 870, 540)

    # ── Attese ────────────────────────────────────────────────────────────────
    wait_tap:     float = 0.8
    wait_back:    float = 0.8
    wait_swipe:   float = 0.7
    wait_refresh: float = 1.5
    wait_post_acquisto: float = 0.5
    wait_back_extra:    float = 0.5
    wait_swipe_extra:   float = 0.1

    # ── Template paths (relativi a templates/) ────────────────────────────────
    tmpl_store:         str = "pin/pin_store.png"
    tmpl_store_attivo:  str = "pin/pin_store_attivo.png"
    tmpl_carrello:      str = "pin/pin_carrello.png"
    tmpl_merchant:       str = "pin/pin_merchant.png"
    tmpl_merchant_close: str = "pin/pin_merchant_close.png"
    tmpl_mercante:       str = "pin/pin_mercante.png"
    tmpl_banner_aperto: str = "pin/pin_banner_aperto.png"
    tmpl_banner_chiuso: str = "pin/pin_banner_chiuso.png"
    tmpl_legno:         str = "pin/pin_legno.png"
    tmpl_pomodoro:      str = "pin/pin_pomodoro.png"
    tmpl_acciaio:       str = "pin/pin_acciaio.png"
    tmpl_free_refresh:  str = "pin/pin_free_refresh.png"
    tmpl_no_refresh:    str = "pin/pin_no_refresh.png"

    @property
    def pin_acquisto(self) -> list[str]:
        """Lista template pulsanti acquistabili (esclude items a pagamento)."""
        return [self.tmpl_legno, self.tmpl_pomodoro, self.tmpl_acciaio]

    # ── Griglia spirale 5×5 (dx, dy) — identica V5 ───────────────────────────
    @property
    def griglia(self) -> list[tuple[int, int]]:
        p = self.passo_scan
        return [
            (  0,   0),
            (+ p,   0), (  0, -p), (-p,  0), (-p,  0),
            (  0, + p), (  0, +p), (+p,  0), (+p,  0),
            (+ p,   0), (  0, -p), ( 0, -p), ( 0, -p),
            (- p,   0), (- p,  0), (-p,  0), (-p,  0),
            (  0, + p), (  0, +p), ( 0, +p), ( 0, +p),
            (+ p,   0), (+ p,  0), (+p,  0), (+p,  0),
        ]


# ==============================================================================
# Esiti interni
# ==============================================================================

class _Esito:
    COMPLETATO           = "completato"
    STORE_NON_TROVATO    = "store_non_trovato"
    NON_IN_HOME          = "non_in_home"
    LABEL_NON_TROVATA    = "label_non_trovata"
    CARRELLO_NON_TROVATO = "carrello_non_trovato"
    MERCHANT_NON_APERTO  = "merchant_non_aperto"
    ERRORE_SCREENSHOT    = "errore_screenshot"
    ERRORE               = "errore"


# ==============================================================================
# StoreTask
# ==============================================================================

class StoreTask(Task):
    """
    Acquista automaticamente gli oggetti del Mysterious Merchant Store.

    Scheduling: periodic, interval_h=4, priority=20.
    Registrato in scheduler come:
        scheduler.register("store", kind="periodic", interval_h=4, priority=20)

    Il task è non-bloccante: store non trovato → skip() (non fail).
    Solo errori strutturali producono fail().
    """

    def __init__(self, config: StoreConfig | None = None) -> None:
        self._cfg = config or StoreConfig()

    # ── ABC: name ─────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "store"

    # ── ABC: should_run ───────────────────────────────────────────────────────

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("store")
        return True

    # ── ABC: run ──────────────────────────────────────────────────────────────

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg     = self._cfg
        device  = ctx.device
        matcher = ctx.matcher

        def log(msg: str) -> None:
            # log
                ctx.log_msg(f"[STORE] {msg}")

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.store)
        from shared.debug_buffer import DebugBuffer
        self._debug_buf = DebugBuffer.for_task(
            "store",
            getattr(ctx, "instance_name", "_unknown"),
        )

        # ── Step 0: assicura HOME ─────────────────────────────────────────────
        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="assicura_home")
        else:
            log("Navigator non disponibile — assumo HOME corrente")

        try:
            esito, acquistati, refreshed = self._esegui_store(
                device, matcher, log, cfg
            )
        except Exception as exc:
            self._debug_buf.snap("exception", device.screenshot())
            self._debug_buf.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione non gestita: {exc}", step="esegui_store")

        # WU115 — flush condizionale: anomalia = esito != COMPLETATO
        successo  = (esito == _Esito.COMPLETATO)
        anomalia  = not successo
        self._debug_buf.flush(success=True, force=anomalia, log_fn=log)

        return self._mappa_esito(esito, acquistati, refreshed, log)

    def _snap(self, device, label: str) -> None:
        """Cattura screenshot in buffer debug (no-op se debug disabilitato)."""
        self._debug_buf.snap(label, device.screenshot())

    # ── Flusso principale ─────────────────────────────────────────────────────

    def _esegui_store(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     StoreConfig,
    ) -> tuple[str, int, bool]:
        """
        Flusso completo store.
        Ritorna (esito: str, acquistati: int, refreshed: bool).
        """

        # ── Gestione banner ───────────────────────────────────────────────────
        self._snap(device, "00_pre_banner")
        stato_banner = self._comprimi_banner(device, matcher, log, cfg)
        self._snap(device, "01_post_banner")
        roi_corrente = (
            cfg.roi_home_banner_chiuso
            if stato_banner in ("aperto", "chiuso")
            else cfg.roi_home_banner_aperto
        )

        # ── Scan griglia spirale (take-max + multi-candidate auto-WU23) ─────
        # WU23: invece di salvare solo il best step, accumula TUTTI i match
        # >= soglia_store. Permette fallback al 2°/3° best se il delta-swipe
        # del best fallisce per swipe non-idempotente sui bordi mappa.
        # Bug osservato 26/04: best step alto ma re-match score=0.439 perché
        # swipe parzialmente assorbito dal bordo mappa.
        log(f"Scan griglia {len(cfg.griglia)} posizioni  passo={cfg.passo_scan}px")

        best_score = -1.0
        best_step  = -1
        cum_x = cum_y = 0
        cumulative: list[tuple[int, int]] = []
        candidates: list[tuple[int, float]] = []  # (step_n, score) — tutti i match

        for n, (dx, dy) in enumerate(cfg.griglia):
            if dx != 0 or dy != 0:
                self._swipe_mappa(device, dx, dy, cfg)
            cum_x += dx
            cum_y += dy
            cumulative.append((cum_x, cum_y))

            shot = device.screenshot()
            result = matcher.find_one(shot, cfg.tmpl_store,
                                      threshold=cfg.soglia_store,
                                      zone=roi_corrente)
            log(
                f"passo {n:02d} → score={result.score:.3f} ({result.cx},{result.cy})"
                + ("  *** match ***" if result.found else "")
            )

            if result.found:
                candidates.append((n, result.score))

            if result.score > best_score:
                best_score = result.score
                best_step  = n

            # Issue #71 — early exit: score molto alto = match certo dello store.
            # Interrompi scan immediatamente per risparmiare tempo (~30-40s
            # quando il match avviene precocemente) e procedi diretto al tap.
            if result.score >= cfg.soglia_store_early_exit:
                log(
                    f"Score {result.score:.3f} >= {cfg.soglia_store_early_exit:.2f} "
                    f"— early exit scan al passo {n}"
                )
                break

        if not candidates:
            self._snap(device, f"02_no_candidates_best{best_score:.2f}".replace(".", "_"))
            log(f"Store NON trovato dopo {len(cfg.griglia)} posizioni"
                f" (best score={best_score:.3f} < soglia={cfg.soglia_store:.2f})")
            return _Esito.STORE_NON_TROVATO, 0, False

        # Sort candidate per score desc — tentativi in cascata
        candidates.sort(key=lambda c: -c[1])
        log(f"Candidati validi: {len(candidates)} match >= {cfg.soglia_store:.2f}. "
            f"Top: {[(s,f'{sc:.3f}') for s,sc in candidates[:5]]}")

        # ── Re-navigazione + re-match per ogni candidato in cascata ──────────
        p = cfg.passo_scan
        end_x, end_y = cumulative[-1]
        result = None
        cx_fin = cy_fin = -1

        for cand_idx, (cand_step, cand_score) in enumerate(candidates):
            tgt_x, tgt_y = cumulative[cand_step]
            delta_x = tgt_x - end_x
            delta_y = tgt_y - end_y
            log(f"Tentativo {cand_idx+1}/{len(candidates)}: step={cand_step} "
                f"score_atteso={cand_score:.3f} — delta swipe ({delta_x},{delta_y})")

            # Apply delta swipes
            if delta_x != 0:
                sign_x = 1 if delta_x > 0 else -1
                for _ in range(abs(delta_x) // p):
                    self._swipe_mappa(device, sign_x * p, 0, cfg)
            if delta_y != 0:
                sign_y = 1 if delta_y > 0 else -1
                for _ in range(abs(delta_y) // p):
                    self._swipe_mappa(device, 0, sign_y * p, cfg)

            # Aggiorna end_x/end_y per il prossimo delta-from
            end_x, end_y = tgt_x, tgt_y

            shot = device.screenshot()
            result = matcher.find_one(shot, cfg.tmpl_store,
                                      threshold=cfg.soglia_store,
                                      zone=roi_corrente)
            log(f"  Re-match: score={result.score:.3f} ({result.cx},{result.cy})"
                + ("  *** TROVATO ***" if result.found else "  fallito"))

            if result.found:
                cx_fin, cy_fin = result.cx, result.cy
                if cand_idx > 0:
                    log(f"  ✓ Recovery via candidate fallback (best falliva)")
                break
            # else: continua al prossimo candidato

        if not result or not result.found:
            self._snap(device, "03_rematch_fail")
            log(f"Store re-match fallito per tutti i {len(candidates)} candidati")
            return _Esito.STORE_NON_TROVATO, 0, False

        # ── Gestione negozio ──────────────────────────────────────────────────
        esito_neg, acquistati, refreshed = self._gestisci_negozio(
            device, matcher, cx_fin, cy_fin, log, cfg
        )

        # auto-WU10: rimosso _ripristina_banner — banner resta chiuso permanentemente
        # (closed at startup in main.py via comprimi_banner_home, persists across tasks)

        # ── Verifica HOME finale ──────────────────────────────────────────────
        shot = device.screenshot()
        home_ok = matcher.exists(shot, "pin/pin_region.png", threshold=0.80)
        if not home_ok:
            log("WARN: non in home dopo store — BACK")
            device.back()
            time.sleep(cfg.wait_back)

        return esito_neg, acquistati, refreshed

    # ── Negozio ───────────────────────────────────────────────────────────────

    def _gestisci_negozio(
        self,
        device:   "MuMuDevice | FakeDevice",
        matcher:  "TemplateMatcher",
        cx_store: int,
        cy_store: int,
        log,
        cfg:      StoreConfig,
    ) -> tuple[str, int, bool]:
        """
        Flusso completo negozio dopo aver trovato lo store.
        Ritorna (esito, acquistati, refreshed).
        """
        # Pre-tap: cerca pin_mercante sull'edificio
        # Se trovato → tap preciso su (cx_merc, cy_merc) apre popup direttamente
        # Se non trovato → tap su edificio → label + carrello
        self._snap(device, "10_pre_tap_mercante")
        shot_pre = device.screenshot()
        r_merc = matcher.find_one(shot_pre, cfg.tmpl_mercante,
                                  threshold=cfg.soglia_mercante,
                                  zone=cfg.roi_negozio)
        log(f"Pre-tap mercante: score={r_merc.score:.3f} (soglia={cfg.soglia_mercante:.2f})")

        if r_merc.found:
            log(f"Mercante visibile — tap diretto ({r_merc.cx},{r_merc.cy})")
            device.tap(r_merc.cx, r_merc.cy)
            time.sleep(cfg.wait_tap)
            self._snap(device, "11_post_tap_diretto")
        else:
            log(f"Tap edificio ({cx_store},{cy_store})")
            device.tap(cx_store, cy_store)
            time.sleep(cfg.wait_tap)
            self._snap(device, "11_post_tap_edificio")

            shot = device.screenshot()

            # Flusso standard: label → carrello
            s_label = matcher.score(shot, cfg.tmpl_store_attivo)
            log(f"Label: score={s_label:.3f} (soglia={cfg.soglia_store_attivo:.2f})")
            if s_label < cfg.soglia_store_attivo:
                self._snap(device, f"12_label_fail_{s_label:.2f}".replace(".", "_"))
                log("Label non trovata — abort")
                device.back()
                time.sleep(cfg.wait_back)
                return _Esito.LABEL_NON_TROVATA, 0, False

            r_carr = matcher.find_one(shot, cfg.tmpl_carrello,
                                      threshold=cfg.soglia_carrello)
            log(f"Carrello: score={r_carr.score:.3f} (soglia={cfg.soglia_carrello:.2f})")
            if not r_carr.found:
                self._snap(device, f"13_carrello_fail_{r_carr.score:.2f}".replace(".", "_"))
                log("Carrello non trovato — abort")
                device.back()
                time.sleep(cfg.wait_back)
                return _Esito.CARRELLO_NON_TROVATO, 0, False

            log(f"Tap carrello ({r_carr.cx},{r_carr.cy})")
            device.tap(r_carr.cx, r_carr.cy)
            # auto-WU12 (26/04): regola DELAY UI — 0.3s → 2.0s.
            # Pre-fix: screenshot subito dopo tap catturava frame transiente
            # con BOTH tmpl_merchant=0.94 e tmpl_merchant_close=0.99 alti
            # (animazione overlay non finita). Polling rompeva al primo
            # match open>=0.75, ma post-loop close>open → abort "VIP Store".
            # Post-fix: 2.0s permettono al popup di stabilizzarsi prima
            # del primo screenshot.
            time.sleep(2.0)

        # Verifica merchant aperto: doppio match open vs close
        # auto-WU12 (26/04): polling con stability check — break solo se
        # OPEN > CLOSE (popup mercante stabile, non frame transiente).
        # Pre-fix: break al primo open>=0.75 → spesso esce con close>open
        # → false abort "VIP Store" su animazione lenta.
        for _tent in range(8):
            shot = device.screenshot()
            if shot is not None:
                s_open  = matcher.score(shot, cfg.tmpl_merchant)
                s_close = matcher.score(shot, cfg.tmpl_merchant_close)
                if s_open >= cfg.soglia_merchant and s_open > s_close:
                    break
            time.sleep(0.5)
        s_merch_open  = matcher.score(shot, cfg.tmpl_merchant)
        s_merch_close = matcher.score(shot, cfg.tmpl_merchant_close)
        log(f"Merchant open={s_merch_open:.3f}  close={s_merch_close:.3f}"
            f" (soglia={cfg.soglia_merchant:.2f})")

        merchant_ok = (
            s_merch_open >= cfg.soglia_merchant
            and s_merch_open > s_merch_close
        )
        if not merchant_ok:
            self._snap(
                device,
                f"14_merch_open{s_merch_open:.2f}_close{s_merch_close:.2f}".replace(".", "_"),
            )
            if s_merch_close >= cfg.soglia_merchant and s_merch_close > s_merch_open:
                log("VIP Store attivo — Mysterious Merchant assente — abort")
            else:
                log("Merchant non confermato — abort")
            device.back()
            time.sleep(cfg.wait_back)
            return _Esito.MERCHANT_NON_APERTO, 0, False

        # ── Cicli acquisto ────────────────────────────────────────────────────
        totale    = 0
        refreshed = False

        for ciclo in range(2):
            if ciclo == 1 and not refreshed:
                break

            log(f"Ciclo acquisti {ciclo + 1}")

            for pagina in range(cfg.max_pagine):
                n_acq = self._acquista_pagina(
                    device, matcher,
                    pagina_n=ciclo * 10 + pagina + 1,
                    log=log, cfg=cfg
                )
                totale += n_acq

                if pagina < cfg.max_pagine - 1:
                    log(f"Swipe ↓ pagina {pagina + 1} → {pagina + 2}")
                    self._swipe_merchant(device, verso_basso=True, cfg=cfg)

            # Torna in cima
            for _ in range(cfg.max_pagine - 1):
                self._swipe_merchant(device, verso_basso=False, cfg=cfg)
            time.sleep(0.5)

            if ciclo == 1:
                break

            # Controlla refresh
            shot = device.screenshot()

            s_noref = matcher.score(shot, cfg.tmpl_no_refresh, zone=cfg.roi_footer)
            if s_noref >= cfg.soglia_no_refresh:
                log(f"Refresh a pagamento (score={s_noref:.3f}) — skip")
                break

            r_free = matcher.find_one(shot, cfg.tmpl_free_refresh,
                                      threshold=cfg.soglia_free_refresh,
                                      zone=cfg.roi_footer)
            log(f"Free Refresh: score={r_free.score:.3f} (soglia={cfg.soglia_free_refresh:.2f})")
            if not r_free.found:
                log("Free Refresh non disponibile")
                break

            log(f"Tap Free Refresh ({r_free.cx},{r_free.cy})")
            device.tap(r_free.cx, r_free.cy)
            time.sleep(cfg.wait_refresh)
            refreshed = True
            log("Free Refresh eseguito ✓")

        # Chiudi negozio
        log("Chiusura → BACK")
        device.back()
        time.sleep(cfg.wait_back + cfg.wait_back_extra)

        log(f"Completato — acquistati: {totale}  refresh: {refreshed}")
        return _Esito.COMPLETATO, totale, refreshed

    # ── Acquisto pagina ───────────────────────────────────────────────────────

    def _acquista_pagina(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        pagina_n: int,
        log,
        cfg:     StoreConfig,
    ) -> int:
        """Acquista tutti i pulsanti gialli visibili. Ritorna n acquisti."""
        shot = device.screenshot()
        candidati = self._conta_pulsanti(shot, matcher, cfg)
        log(f"Pagina {pagina_n}: {len(candidati)} pulsanti trovati")

        if not candidati:
            return 0

        for i, (cy, cx, score, pin_file) in enumerate(candidati):
            log(f"Acquisto #{i}: tap ({cx},{cy}) [{pin_file} {score:.3f}]")
            device.tap(cx, cy)
            time.sleep(cfg.wait_tap)

        # Verifica finale
        time.sleep(cfg.wait_post_acquisto)
        shot_after = device.screenshot()
        rimasti = self._conta_pulsanti(shot_after, matcher, cfg)
        if rimasti:
            log(f"ATTENZIONE: {len(rimasti)} pulsanti ancora presenti dopo acquisto")
        else:
            log(f"Pagina {pagina_n}: tutti acquistati ({len(candidati)}/{len(candidati)}) ✓")

        return len(candidati)

    def _conta_pulsanti(
        self,
        shot,
        matcher: "TemplateMatcher",
        cfg:     StoreConfig,
    ) -> list[tuple[int, int, float, str]]:
        """
        Ritorna lista (cy, cx, score, pin_file) dei pulsanti acquistabili,
        ordinata per cy (acquisto top-down).
        """
        candidati = []
        for pin_file in cfg.pin_acquisto:
            results = matcher.find_all(
                shot, pin_file,
                threshold=cfg.soglia_acquisto,
                zone=cfg.roi_negozio,
                cluster_px=cfg.nms_dist,
            )
            for r in results:
                candidati.append((r.cy, r.cx, r.score, pin_file))
        candidati.sort()
        return candidati

    # ── Banner ────────────────────────────────────────────────────────────────

    def _comprimi_banner(
        self,
        device:  "MuMuDevice | FakeDevice",
        matcher: "TemplateMatcher",
        log,
        cfg:     StoreConfig,
    ) -> str:
        """Collassa il banner eventi. Ritorna stato originale."""
        shot = device.screenshot()
        stato = self._rileva_banner(shot, matcher, cfg)
        if stato == "aperto":
            log(f"Banner: collasso → tap ({cfg.banner_tap_x},{cfg.banner_tap_y})")
            device.tap(cfg.banner_tap_x, cfg.banner_tap_y)
            time.sleep(0.5)
            shot2 = device.screenshot()
            if self._rileva_banner(shot2, matcher, cfg) == "chiuso":
                log("Banner collassato ✓")
            else:
                log("Banner collasso non confermato — procedo")
        elif stato == "chiuso":
            log("Banner già collassato")
        else:
            log("Banner sconosciuto — procedo")
        return stato

    def _ripristina_banner(
        self,
        device:       "MuMuDevice | FakeDevice",
        stato_orig:   str,
        log,
        cfg:          StoreConfig,
    ) -> None:
        if stato_orig != "aperto":
            return
        log(f"Banner: ripristino → tap ({cfg.banner_tap_x},{cfg.banner_tap_y})")
        device.tap(cfg.banner_tap_x, cfg.banner_tap_y)
        time.sleep(0.5)

    def _rileva_banner(self, shot, matcher: "TemplateMatcher", cfg: StoreConfig) -> str:
        s_ap = matcher.score(shot, cfg.tmpl_banner_aperto, zone=cfg.roi_banner_pin)
        s_ch = matcher.score(shot, cfg.tmpl_banner_chiuso, zone=cfg.roi_banner_pin)
        if s_ap >= cfg.soglia_banner and s_ap > s_ch:
            return "aperto"
        if s_ch >= cfg.soglia_banner and s_ch > s_ap:
            return "chiuso"
        return "sconosciuto"

    # ── Swipe helpers ─────────────────────────────────────────────────────────

    def _swipe_mappa(
        self,
        device: "MuMuDevice | FakeDevice",
        dx: int,
        dy: int,
        cfg: StoreConfig,
    ) -> None:
        """Swipe sulla mappa per lo scan spirale."""
        if dx == 0 and dy == 0:
            return
        x2 = max(10,  min(950, cfg.swipe_cx - dx))
        y2 = max(130, min(450, cfg.swipe_cy - dy))
        device.swipe(
            cfg.swipe_cx, cfg.swipe_cy, x2, y2,
            duration_ms=cfg.swipe_dur_ms,
        )
        time.sleep(cfg.wait_swipe)

    def _swipe_merchant(
        self,
        device:      "MuMuDevice | FakeDevice",
        verso_basso: bool,
        cfg:         StoreConfig,
    ) -> None:
        """Scorre la lista del merchant su/giù."""
        sy = 300
        ey = (300 - cfg.merchant_swipe_dy) if verso_basso else (300 + cfg.merchant_swipe_dy)
        ey = max(120, min(440, ey))
        device.swipe(480, sy, 480, ey, duration_ms=cfg.merchant_swipe_dur)
        time.sleep(cfg.wait_swipe + cfg.wait_swipe_extra)

    # ── Mapping esito → TaskResult ────────────────────────────────────────────

    @staticmethod
    def _mappa_esito(
        esito:      str,
        acquistati: int,
        refreshed:  bool,
        log,
    ) -> TaskResult:
        if esito == _Esito.COMPLETATO:
            return TaskResult.ok(
                f"Store completato — acquistati: {acquistati}",
                data={"acquistati": acquistati, "refreshed": refreshed},
            )
        if esito == _Esito.STORE_NON_TROVATO:
            log(f"Outcome={esito!r} → fail")
            return TaskResult.fail("Store non trovato nella griglia")

        skip_esiti = {
            _Esito.NON_IN_HOME:          "Non in home — skip",
            _Esito.LABEL_NON_TROVATA:    "Label store non trovata",
            _Esito.CARRELLO_NON_TROVATO: "Carrello non trovato",
            _Esito.MERCHANT_NON_APERTO:  "Merchant non confermato",
        }
        if esito in skip_esiti:
            log(f"Outcome={esito!r} → skip")
            return TaskResult.skip(skip_esiti[esito])
        log(f"Outcome={esito!r} → fail")
        return TaskResult.fail(f"Errore store: {esito}")

    def __repr__(self) -> str:
        return f"StoreTask(config={self._cfg})"
