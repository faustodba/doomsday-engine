"""
tasks/mega_armament.py — MegaArmamentTask V6
============================================================================
Task custom master (21/07/2026) — evento Special Promo → Mega Armament Sale.
Il più complesso della serie contest: oltre a traccia + collect all, ha una
SCELTA GIORNALIERA della "challenge del giorno" (once/day, irreversibile) e
una GRIGLIA di missioni +145 con pulsanti CLAIM/GO.

LOGICA (appresa live 21/07 sul master, dall'utente):
  1. Ogni giorno si sceglie l'evento fisso della giornata (bonus punti). Per il
     MASTER va scelta **"Radar Station Events"** perché il master esegue
     radar_master → completa la challenge → punti. Le altre missioni semplici
     (grid) danno punti minori.
  2. **Vincolo di ordine**: mega_armament deve girare PRIMA di radar_master
     (priority 21 < 24) così la challenge radar è già selezionata quando radar
     accumula gli eventi.

FLUSSO:
  - Sidebar → Mega Armament (base: apri promo + trova voce + gate pallino).
  - Apri Missions (tap fisso).
  - SELECT today's Challenge (once/day): se il "+" è presente (pin_select_plus)
    → non ancora scelta → apri carosello, scorri fino a pin_mega_radar_icon,
    SELECT (icona_cy + select_dy), conferma OK. Se il "+" è assente → già
    scelta oggi → skip (guard once/day).
  - Claim griglia: find_all(pin_mega_claim) VERDI → tap ognuno; le missioni
    claimate scivolano in fondo (Completed) e in prima posizione riappare
    sempre un CLAIM/GO → nessuno scroll, ri-scandisci finché niente verde.
    I GO (ambra, non completate) NON vanno premuti.
  - Back → vista Mega → Collect All (pin_mega_collect_all matcha solo quando
    attivo/ambra; grigio non matcha) → tap posizione fissa, loop.

REGOLA SICUREZZA: si tappano solo CLAIM verdi + Collect All (gratis) + il SELECT
della challenge radar (scelta corretta per il master). Mai GO, mai
Purchase Level/€. Il SELECT apre un dialog "once selected can't be changed";
si conferma OK (radar è la scelta giusta per il master).

Solo master, periodico 12h (via task_overrides + profilo master).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import TaskContext, TaskResult
from tasks.special_promo import SpecialPromoContestConfig, _SpecialPromoContestBase, _frame


@dataclass
class MegaArmamentConfig(SpecialPromoContestConfig):
    # Voce sidebar + identità
    pin_menu:  str = "pin/pin_mega_armament.png"
    menu_nome: str = "Mega Armament"

    # Apertura schermata Missions (pulsante in basso a sx della vista Mega)
    tap_missions: tuple[int, int] = (280, 460)
    wait_missions: float = 2.5

    # SELECT today's Challenge (once/day)
    pin_select_plus: str = "pin/pin_mega_select_plus.png"
    soglia_plus:     float = 0.80
    zona_plus:       tuple[int, int, int, int] = (0, 100, 300, 320)
    tap_plus:        tuple[int, int] = (155, 185)
    wait_carosello:  float = 2.0
    # carosello challenge: cerca l'icona radar, scorrendo
    pin_radar_icon:  str = "pin/pin_mega_radar_icon.png"
    soglia_radar:    float = 0.85
    # zona centrale: accetta il radar SOLO se centrato (il pulsante SELECT sotto
    # deve essere interamente on-screen). Al bordo (cx>~810) il SELECT esce dallo
    # schermo → non accettare, scrollare ancora. Validato FAU_00 21/07.
    zona_carosello:  tuple[int, int, int, int] = (140, 130, 810, 245)
    carosello_scroll: tuple[int, int, int, int] = (750, 300, 200, 300)
    carosello_scroll_dur_ms: int = 600
    max_carosello_scroll: int = 6
    select_dy:       int = 284   # SELECT sotto l'icona challenge
    # conferma "once selected can't be changed"
    pin_confirm_ok:  str = "pin/pin_mega_confirm_ok.png"
    soglia_confirm:  float = 0.80
    zona_confirm:    tuple[int, int, int, int] = (480, 355, 700, 410)
    tap_confirm_ok:  tuple[int, int] = (592, 382)
    wait_confirm:    float = 2.0

    # Griglia missioni +145 (CLAIM verdi)
    pin_mega_claim:  str = "pin/pin_mega_claim.png"
    soglia_claim:    float = 0.85
    zona_griglia:    tuple[int, int, int, int] = (300, 95, 960, 540)
    max_grid_claim:  int = 20
    wait_grid_claim: float = 1.5   # dopo un CLAIM (istantaneo, no popup) prima del re-scan

    # Collect All (attivo solo se matcha; grigio non matcha)
    pin_mega_collect: str = "pin/pin_mega_collect_all.png"
    soglia_collect:   float = 0.80
    zona_collect:     tuple[int, int, int, int] = (458, 486, 693, 520)
    tap_collect:      tuple[int, int] = (581, 505)
    max_collect:      int = 8
    wait_collect_anim: float = 2.5
    tap_chiudi_collect: tuple[int, int] = (480, 400)

    # back (dalla schermata Missions alla vista Mega)
    tap_back: tuple[int, int] = (30, 30)
    wait_back_missions: float = 2.0


class MegaArmamentTask(_SpecialPromoContestBase):
    """Mega Armament Sale: seleziona la challenge radar (once/day), claima le
    missioni +145 verdi e raccoglie la traccia. Solo master. run() custom."""

    def __init__(self, config: MegaArmamentConfig | None = None) -> None:
        super().__init__(config or MegaArmamentConfig())

    def name(self) -> str:
        return "mega_armament"

    # ------------------------------------------------------------------
    # SELECT today's Challenge (once/day)
    # ------------------------------------------------------------------

    def _seleziona_challenge_radar(self, ctx, cfg, log) -> str:
        """Se non ancora scelta oggi (pin_select_plus presente) sceglie la
        challenge Radar Station Events. Ritorna 'already'|'selected'|'not_found'."""
        shot = ctx.device.screenshot()
        m_plus = ctx.matcher.find_one(shot, cfg.pin_select_plus,
                                      threshold=cfg.soglia_plus, zone=cfg.zona_plus)
        if not m_plus.found:
            log(f"[MEGA_ARMAMENT] challenge già selezionata oggi "
                f"(no '+', score={m_plus.score:.3f}) → skip selezione")
            return "already"
        log(f"[MEGA_ARMAMENT] challenge non selezionata → apro carosello")
        ctx.device.tap(*cfg.tap_plus)
        time.sleep(cfg.wait_carosello)
        for i in range(cfg.max_carosello_scroll + 1):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_radar_icon,
                                     threshold=cfg.soglia_radar, zone=cfg.zona_carosello)
            if m.found:
                sel = (m.cx, m.cy + cfg.select_dy)
                log(f"[MEGA_ARMAMENT] Radar Station Events @({m.cx},{m.cy}) "
                    f"score={m.score:.3f} → SELECT {sel}")
                ctx.device.tap(*sel)
                time.sleep(cfg.wait_confirm)
                # conferma "once selected can't be changed"
                shot2 = ctx.device.screenshot()
                m_ok = ctx.matcher.find_one(shot2, cfg.pin_confirm_ok,
                                            threshold=cfg.soglia_confirm, zone=cfg.zona_confirm)
                if m_ok.found:
                    log(f"[MEGA_ARMAMENT] conferma OK @({m_ok.cx},{m_ok.cy})")
                    ctx.device.tap(m_ok.cx, m_ok.cy)
                else:
                    log(f"[MEGA_ARMAMENT] dialog conferma non rilevato "
                        f"(score={m_ok.score:.3f}) → tap OK fisso {cfg.tap_confirm_ok}")
                    ctx.device.tap(*cfg.tap_confirm_ok)
                time.sleep(cfg.wait_confirm)
                return "selected"
            log(f"[MEGA_ARMAMENT] radar non in vista (score={m.score:.3f}) → "
                f"scroll carosello {i+1}/{cfg.max_carosello_scroll}")
            x0, y0, x1, y1 = cfg.carosello_scroll
            ctx.device.swipe(x0, y0, x1, y1, cfg.carosello_scroll_dur_ms)
            time.sleep(cfg.wait_scroll)
        log(f"[MEGA_ARMAMENT] Radar Station Events NON trovato nel carosello "
            f"→ chiudo senza selezionare")
        ctx.device.tap(*cfg.tap_back)   # chiude il carosello
        time.sleep(cfg.wait_back_missions)
        return "not_found"

    # ------------------------------------------------------------------
    # Claim griglia missioni
    # ------------------------------------------------------------------

    def _claim_griglia(self, ctx, cfg, log) -> int:
        """Tappa ogni CLAIM verde nella griglia. Le claimate scivolano in fondo
        (Completed) e i CLAIM restano in alto → ri-scandisci, nessuno scroll.
        Salta i GO (ambra). Claim istantaneo (nessun popup)."""
        n = 0
        for _ in range(cfg.max_grid_claim):
            shot = ctx.device.screenshot()
            claims = ctx.matcher.find_all(shot, cfg.pin_mega_claim,
                                          threshold=cfg.soglia_claim, zone=cfg.zona_griglia)
            if not claims:
                break
            c = claims[0]
            log(f"[MEGA_ARMAMENT] grid CLAIM #{n+1} → tap ({c.cx},{c.cy}) score={c.score:.3f}")
            ctx.device.tap(c.cx, c.cy)
            time.sleep(cfg.wait_grid_claim)
            n += 1
        log(f"[MEGA_ARMAMENT] grid claim: {n}")
        return n

    # ------------------------------------------------------------------
    # Collect All traccia
    # ------------------------------------------------------------------

    def _collect_all_mega(self, ctx, cfg, log) -> int:
        """Collect All Mega: il template matcha SOLO quando attivo (ambra);
        grigio/spento non matcha. Tap posizione fissa, chiude l'animazione, loop."""
        n = 0
        for _ in range(cfg.max_collect):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_mega_collect,
                                     threshold=cfg.soglia_collect, zone=cfg.zona_collect)
            if not m.found:
                log(f"[MEGA_ARMAMENT] Collect All non attivo (score={m.score:.3f}) → stop")
                break
            log(f"[MEGA_ARMAMENT] Collect All attivo (score={m.score:.3f}) → tap {cfg.tap_collect}")
            ctx.device.tap(*cfg.tap_collect)
            time.sleep(cfg.wait_collect_anim)
            ctx.device.tap(*cfg.tap_chiudi_collect)   # chiude animazione ricompensa
            time.sleep(cfg.wait_post_close)
            n += 1
        log(f"[MEGA_ARMAMENT] Collect All: {n}")
        return n

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("mega_armament", getattr(ctx, "instance_name", "_unknown"))
        try:
            self._apri_special_promo(ctx, cfg, log)
            debug.snap("01_special_promo", ctx.device.screenshot())

            match, frame = self._trova_menu(ctx, cfg, log)
            if match is None:
                log("[MEGA_ARMAMENT] voce Mega Armament non trovata → skip")
                self._esci(ctx, cfg)
                debug.flush(success=True, force=True, log_fn=log)
                return TaskResult.skip("Mega Armament non disponibile")

            # Gate pallino rosso (utente 21/07): niente pallino → nessuna
            # ricompensa → skip. È SICURO per la selezione challenge perché la
            # prima missione del giorno è sempre "Daily Check-In" (login) → al
            # primo giro del giorno c'è SEMPRE il pallino → la challenge viene
            # selezionata; i giri successivi senza pallino saltano (challenge
            # già scelta, niente da claimare).
            if not self._ha_badge_rosso(frame, match.cy, log):
                log("[MEGA_ARMAMENT] nessun pallino rosso → nulla da fare → skip")
                self._esci(ctx, cfg)
                debug.flush(success=True, log_fn=log)
                return TaskResult.skip("Mega Armament: nessuna ricompensa (no pallino)")

            self._seleziona_menu(ctx, cfg, log, match)
            debug.snap("03_mega", ctx.device.screenshot())

            # Apri Missions
            ctx.device.tap(*cfg.tap_missions)
            time.sleep(cfg.wait_missions)
            debug.snap("04_missions", ctx.device.screenshot())

            esito_sel = self._seleziona_challenge_radar(ctx, cfg, log)
            debug.snap("05_post_select", ctx.device.screenshot())

            n_grid = self._claim_griglia(ctx, cfg, log)
            debug.snap("06_post_grid", ctx.device.screenshot())

            # Back alla vista Mega
            ctx.device.tap(*cfg.tap_back)
            time.sleep(cfg.wait_back_missions)
            debug.snap("07_mega_main", ctx.device.screenshot())

            n_collect = self._collect_all_mega(ctx, cfg, log)
            debug.snap("08_post_collect", ctx.device.screenshot())

            self._esci(ctx, cfg)
            log(f"[MEGA_ARMAMENT] completato — challenge={esito_sel} "
                f"grid_claim={n_grid} collect_all={n_collect}")
            debug.flush(success=True,
                        force=(esito_sel == "not_found" or (n_grid == 0 and n_collect == 0)),
                        log_fn=log)
            return TaskResult.ok(f"Mega Armament — challenge={esito_sel} "
                                 f"grid={n_grid} collect={n_collect}",
                                 challenge=esito_sel, grid=n_grid, collect_all=n_collect)
        except Exception as exc:
            log(f"[MEGA_ARMAMENT] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")
