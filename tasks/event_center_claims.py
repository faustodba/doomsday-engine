"""
tasks/event_center_claims.py — EventCenterClaimsTask V6
============================================================================
Task (22/07/2026) — claim gratuiti nell'hub "Event Center": l'icona rotante
in alto a destra su HOME che alterna label ("Event Center"/"Water War"/
"Arms Race"/ecc. a seconda dell'evento in vetrina del giorno — stesso tap
target indipendentemente dalla label mostrata).

Motore generico su catalogo dichiarativo (`shared/claim_catalog.py`, stesso
pattern di `shared/banner_catalog.py`): ogni voce del catalogo è stata
VERIFICATA A MANO come claim gratuito prima di essere aggiunta (mai
scoperta/tap automatico alla cieca — un pallino rosso da solo non basta,
es. "Match Predictions" ha il pallino ma è un pronostico/scelta, non un
claim, e resta fuori dal catalogo).

GATE A 3 LIVELLI (dal più economico al più costoso):
  1. Pallino rosso sull'icona HOME stessa (`claim_catalog.HOME_BADGE_ROI`)
     — se assente, skip totale, nessuna navigazione (~1s).
  2. Pallino rosso sulla riga sidebar di ogni voce catalogata — se assente,
     skip quella voce, provo la successiva.
  3. Template del pulsante CLAIM verde SPECIFICO della voce — unico
     segnale che autorizza il tap. Il pallino rosso è solo un pre-filtro
     di velocità, mai l'unico segnale per agire.

FLUSSO:
  - HOME → screenshot → pallino su icona HOME? No → skip task.
  - Tap icona HOME (895,68) → entro nell'hub.
  - Per ogni voce del catalogo: riporto la sidebar in cima (overshoot
    sicuro) + applico gli swipe "avanti" calibrati per quella voce (alcune
    sono sotto la piega, es. Survival Preparations) → pallino sidebar?
    No → prossima voce. Sì → tap voce → loop claim (screenshot, cerca
    template, tap, chiudi popup in zona sicura, ripeti fino a max_claims o
    nessun claim trovato — nota: il gioco può risolvere più claim pronti
    in un solo tap, osservato live su Survival Preparations) → torno alla
    sidebar dell'hub (le voci sono tab della stessa sidebar, un tap sulla
    prossima voce basta, la posizione scroll viene sempre ripristinata).
  - Back → back → vai_in_home() di sicurezza.

REGOLA SICUREZZA: mai tap su un claim non verificato dal template
specifico. Mai il pallino rosso da solo come segnale d'azione.

Schedule: daily (via task_setup.json).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult
from shared.claim_catalog import (
    CLAIM_CATALOG,
    HOME_BADGE_ROI,
    TAP_HOME_ICON,
    TAP_HUB_BACK,
    BADGE_RED_MIN_FRAC,
    SIDEBAR_SCROLL_RESET,
    SIDEBAR_SCROLL_RESET_N,
    SIDEBAR_SCROLL_FWD,
    ClaimMenuSpec,
    frazione_pallino_rosso,
)


@dataclass
class EventCenterClaimsConfig:
    wait_hub_open:  float = 2.0
    wait_hub_back:  float = 1.5
    wait_scroll_s:  float = 0.6


class EventCenterClaimsTask(Task):
    """Claim gratuiti nell'hub Event Center, motore generico su catalogo
    dichiarativo (shared/claim_catalog.py). Vedi docstring modulo per il
    gate a 3 livelli."""

    def __init__(self, config: EventCenterClaimsConfig | None = None) -> None:
        self._cfg = config or EventCenterClaimsConfig()

    def name(self) -> str:
        return "event_center_claims"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato(self.name()):
                return False
        return True

    # ------------------------------------------------------------------

    def _posiziona_sidebar(self, ctx, spec: ClaimMenuSpec, log) -> None:
        """Riporta la sidebar in cima (overshoot sicuro, il rebound si
        ferma da solo a inizio lista) poi applica n_scroll swipe "avanti"
        per rivelare la voce catalogata. Sempre dallo stesso punto di
        partenza noto, indipendentemente da dove si trovava lo scroll
        prima — garantisce posizioni riproducibili."""
        cfg = self._cfg
        for _ in range(SIDEBAR_SCROLL_RESET_N):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_RESET
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)
        for _ in range(spec.n_scroll):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_FWD
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)

    def _claim_voce(self, ctx, spec: ClaimMenuSpec, log) -> int:
        """Entra nella voce sidebar catalogata e claima in loop finché il
        template CLAIM specifico matcha (o max_claims raggiunto)."""
        ctx.device.tap(*spec.tap_sidebar)
        time.sleep(spec.wait_open_s)
        n = 0
        for _ in range(spec.max_claims):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, spec.claim_template,
                                     threshold=spec.claim_threshold, zone=spec.claim_zone)
            if not m.found:
                break
            log(f"[EVENT_CENTER_CLAIMS] {spec.name}: claim #{n+1} "
                f"score={m.score:.3f} → tap ({m.cx},{m.cy})")
            ctx.device.tap(m.cx, m.cy)
            time.sleep(spec.wait_claim_s)
            ctx.device.tap(*spec.tap_close_safe)
            time.sleep(spec.wait_close_s)
            n += 1
        log(f"[EVENT_CENTER_CLAIMS] {spec.name}: {n} claim riscossi")
        return n

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("event_center_claims", getattr(ctx, "instance_name", "_unknown"))
        try:
            # STEP 0 — pre-check pallino sull'icona HOME (piu' economico)
            shot_home = ctx.device.screenshot()
            frac_home = frazione_pallino_rosso(shot_home.frame, HOME_BADGE_ROI)
            if frac_home <= BADGE_RED_MIN_FRAC:
                log(f"[EVENT_CENTER_CLAIMS] nessun pallino su icona HOME "
                    f"(red%={frac_home*100:.1f}) → skip")
                return TaskResult.skip("nessun pallino icona HOME")
            log(f"[EVENT_CENTER_CLAIMS] pallino icona HOME rilevato "
                f"(red%={frac_home*100:.1f}) → apro hub")

            ctx.device.tap(*TAP_HOME_ICON)
            time.sleep(cfg.wait_hub_open)
            debug.snap("01_hub", ctx.device.screenshot())

            risultati: dict[str, int] = {}
            for spec in CLAIM_CATALOG:
                self._posiziona_sidebar(ctx, spec, log)
                shot_sidebar = ctx.device.screenshot()
                frac = frazione_pallino_rosso(shot_sidebar.frame, spec.badge_roi)
                if frac <= BADGE_RED_MIN_FRAC:
                    log(f"[EVENT_CENTER_CLAIMS] {spec.name}: nessun pallino sidebar "
                        f"(red%={frac*100:.1f}) → skip")
                    continue
                log(f"[EVENT_CENTER_CLAIMS] {spec.name}: pallino sidebar rilevato "
                    f"(red%={frac*100:.1f}) → entro")
                risultati[spec.name] = self._claim_voce(ctx, spec, log)
                debug.snap(f"02_{spec.name}", ctx.device.screenshot())

            ctx.device.tap(*TAP_HUB_BACK)
            time.sleep(cfg.wait_hub_back)
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            debug.snap("03_home", ctx.device.screenshot())

            tot = sum(risultati.values())
            log(f"[EVENT_CENTER_CLAIMS] completato — {risultati} (tot={tot})")
            debug.flush(success=True, force=(tot == 0), log_fn=log)
            return TaskResult.ok(f"Event Center Claims — {risultati}", **risultati)
        except Exception as exc:
            log(f"[EVENT_CENTER_CLAIMS] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")
