"""
tasks/titan_approaches.py — TitanApproachesTask V6
============================================================================
Task (22/07/2026, mappato dal vivo su FAU_00 con guida diretta dell'utente,
passo-passo, ogni coordinata/pulsante confermato) — evento "Titan Approaches"
nell'hub Event Center: 3 attacchi giornalieri gratuiti contro un boss
("Blood Spider" o simile), con ricompense (risorse) indipendentemente
dall'esito (osservato: "Our Troop Tier is too low to resist the enemy" non
ha impedito il completamento dei 3 attacchi né l'incasso della reward).

FLUSSO (confermato dall'utente, 3 attacchi in sequenza):
  - Apro hub Event Center (stessa apertura/retry di event_center_claims).
  - Cerco la riga "Titan Approaches" nella sidebar (template dedicato,
    scroll come event_center_claims — NON il sistema di identità-riga
    generico di claim_catalog: qui l'evento è noto e specifico, non in
    discovery).
  - Se nessun pallino rosso sulla riga → nessun attacco disponibile oggi
    (già fatti, o non ancora attivo) → skip.
  - Tap sulla riga → apre la scheda dettaglio (boss + reward preview).
  - Loop fino a 3 volte (o finché non trovo più un pulsante d'azione):
      * "Quick Battle" presente (2°/3° attacco) → tap → risoluzione
        ISTANTANEA (nessuna animazione) → schermata risultato → tap
        punto neutro per chiudere.
      * "Quick Battle" assente, "GO" presente (1° attacco, richiede lo
        schieramento) → tap GO → schermata "Deployment Queue" (schieramento
        PREIMPOSTATO — su FAU_00/master NON si tocca, si accetta così com'è,
        per istanze ordinarie stesso comportamento finché non richiesto
        diversamente) → tap "CHALLENGE" → animazione battaglia → tap
        freccia skip (in basso a destra, termina subito l'animazione) →
        schermata risultato → tap punto neutro per chiudere.
      * Né l'uno né l'altro → nessun attacco rimasto (o schermata
        inattesa) → stop pulito, nessun tap alla cieca.
  - Back → vai_in_home() di sicurezza.

REGOLA SICUREZZA: si tappano SOLO i 4 pulsanti dedicati (Quick Battle, GO,
CHALLENGE, freccia skip animazione) via template match verificato — mai un
tap esplorativo. "GO" qui è il via libera a una battaglia gratuita con le
proprie truppe (non un acquisto — significato diverso dal "GO" vietato in
altri contest come mega_armament, dove indicava un acquisto in denaro).
Lo schieramento (Deployment Queue) non viene mai toccato: si usa quello
preimpostato dal gioco.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.task import Task, TaskContext, TaskResult
from shared.claim_catalog import (
    TAP_HOME_ICON,
    HOME_BADGE_ROI,
    TAP_HUB_BACK,
    PIN_HUB_OPEN,
    HUB_OPEN_ZONE,
    HUB_OPEN_SOGLIA,
    HUB_OPEN_MAX_RETRY,
    BADGE_RED_MIN_FRAC,
    SIDEBAR_SCROLL_RESET,
    SIDEBAR_SCROLL_RESET_N,
    SIDEBAR_SCROLL_FWD,
    MAX_SCROLL_DEPTH,
    ROW_TAP_X,
    SIDEBAR_ZONE_ROI,
    frazione_pallino_rosso,
)


@dataclass
class TitanApproachesConfig:
    # Riga sidebar — identità dedicata (evento noto, non discovery generica)
    pin_riga:      str = "pin/pin_titan_approaches_row.png"
    soglia_riga:   float = 0.85
    badge_riga_dx: tuple[int, int] = (185, 220)   # offset X dal match riga per il pallino
    # offset Y del pallino rispetto al centro del match riga — il badge si
    # sovrappone all'angolo alto dell'icona, NON è centrato sul testo.
    # Calibrato empiricamente su FAU_01 (analisi pixel HSV): banda densa
    # rossa a dy=[-30,-9] dal centro riga, picco dy=-19. ROI (m.cy-15,
    # m.cy+15) usata in v1 catturava solo la coda inferiore della macchia
    # → frazione diluita sotto soglia (4-5% invece di 28%) → falsi
    # negativi "nessun pallino" con badge realmente presente.
    badge_riga_dy: tuple[int, int] = (-33, -6)

    # Pulsanti scheda dettaglio / battaglia
    pin_quick_battle: str = "pin/pin_titan_quick_battle.png"
    soglia_quick:     float = 0.85
    pin_go:           str = "pin/pin_titan_go.png"
    soglia_go:        float = 0.85
    pin_challenge:    str = "pin/pin_titan_challenge.png"
    soglia_challenge: float = 0.85
    pin_battle_skip:  str = "pin/pin_titan_battle_skip.png"
    soglia_skip:      float = 0.80
    zona_pulsanti:    tuple[int, int, int, int] = (250, 460, 960, 540)

    # Deployment Queue — 2 situazioni possibili dopo GO (utente 22/07):
    # (a) schieramento PREIMPOSTATO (FAU_00/master, istanze con progressione)
    #     → 3/3 già pieno, non si tocca, si passa dritti a CHALLENGE.
    # (b) schieramento MANCANTE (istanze nuove) → 3 slot vuoti con "+";
    #     tap "+" propone una coppia comandante/truppe di default, tap
    #     "READY" la conferma nello slot. Ripetuto fino a 3 volte finché
    #     non c'è più nessun "+" in vista (schieramento completo).
    pin_slot_plus:    str = "pin/pin_titan_slot_plus.png"
    soglia_slot_plus: float = 0.85
    zona_deployment_queue: tuple[int, int, int, int] = (875, 80, 960, 270)
    pin_ready:        str = "pin/pin_titan_ready.png"
    soglia_ready:     float = 0.85
    zona_ready:       tuple[int, int, int, int] = (250, 460, 960, 540)
    max_slot_riempimento: int = 3
    wait_slot_plus:   float = 2.0
    wait_ready:       float = 2.0

    # Punto neutro per chiudere la schermata risultato (tap-anywhere)
    tap_dismiss: tuple[int, int] = (480, 270)

    max_attacchi:       int = 3
    wait_hub_open:      float = 2.0
    wait_scroll_s:      float = 1.5
    wait_open_riga:     float = 2.0
    wait_quick_battle:  float = 2.5
    wait_go:             float = 2.5
    wait_challenge:      float = 2.0
    max_skip_retry:      int = 4
    wait_skip_retry:      float = 1.5
    wait_dismiss:         float = 2.0
    wait_hub_back:        float = 1.5


class TitanApproachesTask(Task):
    """3 attacchi giornalieri gratuiti Titan Approaches (hub Event Center).
    Vedi docstring modulo per il flusso e la regola di sicurezza."""

    def __init__(self, config: TitanApproachesConfig | None = None) -> None:
        self._cfg = config or TitanApproachesConfig()

    def name(self) -> str:
        return "titan_approaches"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato(self.name()):
                return False
        return True

    # ------------------------------------------------------------------

    def _posiziona_sidebar(self, ctx, n_scroll: int) -> None:
        cfg = self._cfg
        for _ in range(SIDEBAR_SCROLL_RESET_N):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_RESET
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)
        for _ in range(n_scroll):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_FWD
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)

    def _trova_riga_titan(self, ctx, log):
        """Scrolla la sidebar cercando la riga 'Titan Approaches'. Ritorna
        (y_riga, ha_pallino) o (None, False) se non trovata in nessuna
        profondità (evento non presente su questa istanza — non un errore,
        stesso comportamento già osservato per Login Rewards su alcune
        istanze)."""
        cfg = self._cfg
        for depth in range(MAX_SCROLL_DEPTH):
            self._posiziona_sidebar(ctx, depth)
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_riga,
                                     threshold=cfg.soglia_riga, zone=SIDEBAR_ZONE_ROI)
            if m.found:
                x0, x1 = cfg.badge_riga_dx
                dy0, dy1 = cfg.badge_riga_dy
                roi = (x0, m.cy + dy0, x1, m.cy + dy1)
                frac = frazione_pallino_rosso(shot.frame, roi)
                ha_pallino = frac > BADGE_RED_MIN_FRAC
                log(f"[TITAN_APPROACHES] riga trovata depth={depth} y={m.cy} "
                    f"score={m.score:.3f} pallino={ha_pallino} (red%={frac*100:.1f})")
                return m.cy, ha_pallino
            log(f"[TITAN_APPROACHES] riga non in vista depth={depth} "
                f"(score={m.score:.3f})")
        return None, False

    def _termina_animazione(self, ctx, log) -> bool:
        """Dopo CHALLENGE: attende che compaia la freccia skip (l'animazione
        impiega qualche secondo a partire) e la preme per risolvere subito
        la battaglia. Retry invece di un singolo sleep fisso — timing
        variabile osservato dal vivo."""
        cfg = self._cfg
        for tentativo in range(1, cfg.max_skip_retry + 1):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_battle_skip,
                                     threshold=cfg.soglia_skip, zone=cfg.zona_pulsanti)
            if m.found:
                log(f"[TITAN_APPROACHES] skip animazione trovato "
                    f"(tentativo {tentativo}, score={m.score:.3f}) → tap ({m.cx},{m.cy})")
                ctx.device.tap(m.cx, m.cy)
                return True
            log(f"[TITAN_APPROACHES] skip non ancora visibile "
                f"(tentativo {tentativo}/{cfg.max_skip_retry}, score={m.score:.3f})")
            time.sleep(cfg.wait_skip_retry)
        log("[TITAN_APPROACHES] skip animazione mai trovato — la battaglia "
            "si risolverà da sola (nessun tap forzato)")
        return False

    def _riempi_schieramento_se_necessario(self, ctx, log) -> int:
        """Dopo GO: su istanze con schieramento già preimpostato (FAU_00/
        master) la Deployment Queue è 3/3 e non c'è nessun '+' — la
        funzione ritorna subito 0, nessun tap. Su istanze nuove la coda è
        vuota (0/3, tre '+'): tap '+' propone una coppia comandante/truppe
        di default, tap READY la conferma. Ripete finché non trova più
        nessun '+' in vista (schieramento completo) o max_slot_riempimento
        raggiunto. Il '+' successivo appare nella stessa zona una volta
        chiuso lo slot precedente — non serve tracciare la posizione."""
        cfg = self._cfg
        n = 0
        for _ in range(cfg.max_slot_riempimento):
            shot = ctx.device.screenshot()
            m_plus = ctx.matcher.find_one(shot, cfg.pin_slot_plus,
                                          threshold=cfg.soglia_slot_plus,
                                          zone=cfg.zona_deployment_queue)
            if not m_plus.found:
                if n == 0:
                    log(f"[TITAN_APPROACHES] Deployment Queue già piena "
                        f"(score={m_plus.score:.3f}) → schieramento preimpostato, "
                        f"non tocco")
                break
            log(f"[TITAN_APPROACHES] slot vuoto #{n+1} (score={m_plus.score:.3f}) "
                f"→ tap ({m_plus.cx},{m_plus.cy})")
            ctx.device.tap(m_plus.cx, m_plus.cy)
            time.sleep(cfg.wait_slot_plus)

            shot2 = ctx.device.screenshot()
            m_ready = ctx.matcher.find_one(shot2, cfg.pin_ready,
                                           threshold=cfg.soglia_ready, zone=cfg.zona_ready)
            if not m_ready.found:
                log(f"[TITAN_APPROACHES] READY non trovato dopo tap '+' "
                    f"(score={m_ready.score:.3f}) → stop pulito, nessun tap oltre")
                break
            log(f"[TITAN_APPROACHES] READY (score={m_ready.score:.3f}) "
                f"→ tap ({m_ready.cx},{m_ready.cy})")
            ctx.device.tap(m_ready.cx, m_ready.cy)
            time.sleep(cfg.wait_ready)
            n += 1
        if n:
            log(f"[TITAN_APPROACHES] schieramento completato — {n} slot riempiti")
        return n

    def _esegui_attacco(self, ctx, log) -> str:
        """Un giro del loop battaglie. Ritorna 'quick'|'go'|'none'."""
        cfg = self._cfg
        shot = ctx.device.screenshot()

        m_quick = ctx.matcher.find_one(shot, cfg.pin_quick_battle,
                                       threshold=cfg.soglia_quick, zone=cfg.zona_pulsanti)
        if m_quick.found:
            log(f"[TITAN_APPROACHES] Quick Battle (score={m_quick.score:.3f}) "
                f"→ tap ({m_quick.cx},{m_quick.cy})")
            ctx.device.tap(m_quick.cx, m_quick.cy)
            time.sleep(cfg.wait_quick_battle)
            ctx.device.tap(*cfg.tap_dismiss)
            time.sleep(cfg.wait_dismiss)
            return "quick"

        m_go = ctx.matcher.find_one(shot, cfg.pin_go,
                                    threshold=cfg.soglia_go, zone=cfg.zona_pulsanti)
        if m_go.found:
            log(f"[TITAN_APPROACHES] GO (score={m_go.score:.3f}) "
                f"→ tap ({m_go.cx},{m_go.cy})")
            ctx.device.tap(m_go.cx, m_go.cy)
            time.sleep(cfg.wait_go)

            self._riempi_schieramento_se_necessario(ctx, log)

            shot2 = ctx.device.screenshot()
            m_chall = ctx.matcher.find_one(shot2, cfg.pin_challenge,
                                           threshold=cfg.soglia_challenge, zone=cfg.zona_pulsanti)
            if not m_chall.found:
                log(f"[TITAN_APPROACHES] CHALLENGE non trovato dopo GO "
                    f"(score={m_chall.score:.3f}) → stop pulito, nessun tap oltre")
                return "none"
            log(f"[TITAN_APPROACHES] CHALLENGE (score={m_chall.score:.3f}) "
                f"→ tap ({m_chall.cx},{m_chall.cy})")
            ctx.device.tap(m_chall.cx, m_chall.cy)
            time.sleep(cfg.wait_challenge)

            self._termina_animazione(ctx, log)
            time.sleep(cfg.wait_quick_battle)
            ctx.device.tap(*cfg.tap_dismiss)
            time.sleep(cfg.wait_dismiss)
            return "go"

        log(f"[TITAN_APPROACHES] né Quick Battle né GO trovati "
            f"(quick={m_quick.score:.3f} go={m_go.score:.3f}) → nessun attacco rimasto")
        return "none"

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("titan_approaches", getattr(ctx, "instance_name", "_unknown"))
        try:
            shot_home = ctx.device.screenshot()
            frac_home = frazione_pallino_rosso(shot_home.frame, HOME_BADGE_ROI)
            if frac_home <= BADGE_RED_MIN_FRAC:
                log(f"[TITAN_APPROACHES] nessun pallino su icona HOME "
                    f"(red%={frac_home*100:.1f}) → skip")
                return TaskResult.skip("nessun pallino icona HOME")

            ctx.device.tap(*TAP_HOME_ICON)
            time.sleep(cfg.wait_hub_open)

            hub_aperto = False
            for tentativo in range(1, HUB_OPEN_MAX_RETRY + 1):
                shot_check = ctx.device.screenshot()
                m_hub = ctx.matcher.find_one(shot_check, PIN_HUB_OPEN,
                                             threshold=HUB_OPEN_SOGLIA, zone=HUB_OPEN_ZONE)
                if m_hub.found:
                    log(f"[TITAN_APPROACHES] hub aperto confermato "
                        f"(tentativo {tentativo}, score={m_hub.score:.3f})")
                    hub_aperto = True
                    break
                log(f"[TITAN_APPROACHES] hub NON aperto (tentativo {tentativo}/"
                    f"{HUB_OPEN_MAX_RETRY}, score={m_hub.score:.3f}) → ritap")
                ctx.device.tap(*TAP_HOME_ICON)
                time.sleep(cfg.wait_hub_open)
            if not hub_aperto:
                log("[TITAN_APPROACHES] hub non apribile → abort pulito")
                if ctx.navigator is not None:
                    ctx.navigator.vai_in_home()
                debug.flush(success=False, force=True, log_fn=log)
                return TaskResult.fail("hub Event Center non apribile", step="apri_hub")

            y_riga, ha_pallino = self._trova_riga_titan(ctx, log)
            if y_riga is None:
                log("[TITAN_APPROACHES] riga 'Titan Approaches' non trovata "
                    "in nessuna profondità → evento non presente su questa istanza")
                ctx.device.tap(*TAP_HUB_BACK)
                time.sleep(cfg.wait_hub_back)
                if ctx.navigator is not None:
                    ctx.navigator.vai_in_home()
                debug.flush(success=True, log_fn=log)
                return TaskResult.skip("Titan Approaches non presente su questa istanza")

            if not ha_pallino:
                log("[TITAN_APPROACHES] nessun pallino sulla riga → nessun "
                    "attacco disponibile oggi → skip")
                ctx.device.tap(*TAP_HUB_BACK)
                time.sleep(cfg.wait_hub_back)
                if ctx.navigator is not None:
                    ctx.navigator.vai_in_home()
                debug.flush(success=True, log_fn=log)
                return TaskResult.skip("nessun attacco disponibile")

            ctx.device.tap(ROW_TAP_X, y_riga)
            time.sleep(cfg.wait_open_riga)
            debug.snap("01_scheda", ctx.device.screenshot())

            n_quick, n_go = 0, 0
            for i in range(cfg.max_attacchi):
                esito = self._esegui_attacco(ctx, log)
                debug.snap(f"02_attacco{i+1}_{esito}", ctx.device.screenshot())
                if esito == "quick":
                    n_quick += 1
                elif esito == "go":
                    n_go += 1
                else:
                    break

            ctx.device.tap(*TAP_HUB_BACK)
            time.sleep(cfg.wait_hub_back)
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            debug.snap("03_home", ctx.device.screenshot())

            tot = n_quick + n_go
            log(f"[TITAN_APPROACHES] completato — go={n_go} quick_battle={n_quick} "
                f"(tot={tot})")
            debug.flush(success=True, force=(tot == 0), log_fn=log)
            return TaskResult.ok(f"Titan Approaches — go={n_go} quick={n_quick}",
                                 go=n_go, quick_battle=n_quick, tot=tot)
        except Exception as exc:
            log(f"[TITAN_APPROACHES] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")
