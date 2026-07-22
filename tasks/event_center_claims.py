"""
tasks/event_center_claims.py — EventCenterClaimsTask V6
============================================================================
Task (22/07/2026, redesign stesso giorno dopo v1 a posizione fissa) — claim
gratuiti nell'hub "Event Center": l'icona rotante in alto a destra su HOME
che alterna label ("Event Center"/"Water War"/"Arms Race"/ecc. a seconda
dell'evento in vetrina del giorno — stesso tap target indipendentemente
dalla label mostrata).

IDENTITÀ = IMMAGINE DEL TITOLO, non posizione. Osservazione utente: la
stessa voce sidebar può comparire a profondità di scroll diverse su
istanze diverse (o nel tempo, con eventi che ruotano) — coordinate fisse
non sono un'identità affidabile, né lo è l'OCR del titolo (troppo
rumoroso: "Survival Preparations" letto come "> a Survival Preparat").
Il titolo del sottomenu (crop immagine, stesso principio già validato per
il pulsante CLAIM) è invece un'identità robusta e indipendente dalla
posizione — riconosciuto via template matching (`shared/claim_catalog.py`).

FLUSSO (un run = una scansione completa, già schedulato 1×/giorno per
istanza via task_setup.json "daily" — nessun gate interno aggiuntivo):
  - HOME → pallino su icona HOME (posizione fissa, non scorre)? No → skip.
  - Apro hub. Per ogni profondità di scroll (reset a inizio lista +
    N swipe avanti): trovo pallini rossi GENERICI nella colonna sidebar
    (posizione — solo per il tap di QUESTO giro).
  - Per ogni pallino: tap sulla riga → riconosco il titolo del sottomenu
    aperto via template matching contro tutti i titoli già noti
    (catalogo condiviso dev+prod, cresce nel tempo):
      * Titolo noto e claimabile    → verifico/clicco il widget CLAIM.
      * Titolo noto e non claimabile → skip immediato, nessun tap oltre
        l'apertura del sottomenu.
      * Titolo mai visto            → verifico SOLO il widget CLAIM già
        noto (mai un tap esplorativo su qualcosa di ignoto) → imparo il
        risultato E salvo il crop titolo per riconoscerlo la prossima
        volta, su qualunque istanza.
    → torno alla sidebar dell'hub.
  - Back → back → vai_in_home() di sicurezza.

REGOLA SICUREZZA: mai tap su un pulsante non verificato dal widget CLAIM
specifico già noto. Il pallino rosso è solo un pre-filtro posizionale per
sapere dove guardare in QUESTO giro, mai un segnale d'azione da solo, mai
una posizione da fidarsi in run futuri.
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
    CLAIM_TEMPLATE,
    CLAIM_ZONE,
    CLAIM_THRESHOLD,
    CLAIM_TAP_CLOSE_SAFE,
    MAX_CLAIMS_PER_VOCE,
    frazione_pallino_rosso,
    trova_pallini_sidebar,
    carica_catalogo,
    salva_catalogo,
    carica_crop_titoli,
    salva_crop_titolo,
    riconosci_titolo,
    prossimo_id,
    ts_ora,
)


@dataclass
class EventCenterClaimsConfig:
    wait_hub_open:  float = 2.0
    wait_hub_back:  float = 1.5
    wait_scroll_s:  float = 1.5
    wait_open_s:    float = 2.0
    wait_claim_s:   float = 2.0
    wait_close_s:   float = 1.5


class EventCenterClaimsTask(Task):
    """Claim gratuiti nell'hub Event Center — motore a identità-per-titolo
    su catalogo auto-appreso e condiviso (shared/claim_catalog.py). Vedi
    docstring modulo per il flusso e la regola di sicurezza."""

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

    def _posiziona_sidebar(self, ctx, n_scroll: int) -> None:
        """Riporta la sidebar in cima (overshoot sicuro) poi applica
        n_scroll swipe "avanti". Sempre dallo stesso punto di partenza
        noto — la profondità serve solo a coprire tutta la lista in
        questo giro, mai a "ricordare" dove sta una voce nota."""
        cfg = self._cfg
        for _ in range(SIDEBAR_SCROLL_RESET_N):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_RESET
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)
        for _ in range(n_scroll):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_FWD
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)

    def _claim_loop(self, ctx, log) -> int:
        """Nel sottomenu corrente: claima in loop finché il widget CLAIM
        matcha (o max raggiunto). Il gioco può risolvere più claim pronti
        in un solo tap (osservato live su Survival Preparations) — il
        loop find-then-tap resta corretto comunque."""
        cfg = self._cfg
        n = 0
        for _ in range(MAX_CLAIMS_PER_VOCE):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, CLAIM_TEMPLATE,
                                     threshold=CLAIM_THRESHOLD, zone=CLAIM_ZONE)
            if not m.found:
                break
            log(f"[EVENT_CENTER_CLAIMS] claim #{n+1} score={m.score:.3f} "
                f"→ tap ({m.cx},{m.cy})")
            ctx.device.tap(m.cx, m.cy)
            time.sleep(cfg.wait_claim_s)
            ctx.device.tap(*CLAIM_TAP_CLOSE_SAFE)
            time.sleep(cfg.wait_close_s)
            n += 1
        return n

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("event_center_claims", getattr(ctx, "instance_name", "_unknown"))
        try:
            # STEP 0 — pre-check pallino sull'icona HOME (posizione fissa,
            # non scorre — unico caso dove un check posizionale "cache"
            # ha senso, l'icona HOME è sempre nello stesso punto per design)
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

            # Verifica apertura hub (22/07 — trovato dal vivo: il tap a
            # volte non apre l'hub, es. animazione banner in corso; senza
            # questa verifica il task scansionava alla cieca la schermata
            # sbagliata per tutte le profondità, ~105s sprecati). Retry sul
            # tap, poi abort pulito se continua a non aprirsi — mai
            # procedere con lo scan su una schermata non verificata.
            hub_aperto = False
            for tentativo in range(1, HUB_OPEN_MAX_RETRY + 1):
                shot_check = ctx.device.screenshot()
                m_hub = ctx.matcher.find_one(shot_check, PIN_HUB_OPEN,
                                             threshold=HUB_OPEN_SOGLIA, zone=HUB_OPEN_ZONE)
                if m_hub.found:
                    log(f"[EVENT_CENTER_CLAIMS] hub aperto confermato "
                        f"(tentativo {tentativo}, score={m_hub.score:.3f})")
                    hub_aperto = True
                    break
                log(f"[EVENT_CENTER_CLAIMS] hub NON aperto (tentativo {tentativo}/"
                    f"{HUB_OPEN_MAX_RETRY}, score={m_hub.score:.3f}) → ritap")
                ctx.device.tap(*TAP_HOME_ICON)
                time.sleep(cfg.wait_hub_open)
            if not hub_aperto:
                log("[EVENT_CENTER_CLAIMS] hub non apribile dopo "
                    f"{HUB_OPEN_MAX_RETRY} tentativi → abort pulito")
                if ctx.navigator is not None:
                    ctx.navigator.vai_in_home()
                debug.flush(success=False, force=True, log_fn=log)
                return TaskResult.fail("hub Event Center non apribile", step="apri_hub")

            debug.snap("01_hub", ctx.device.screenshot())

            catalogo = carica_catalogo()
            crops = carica_crop_titoli()
            risultati: dict[str, int] = {}
            processate_run: set[str] = set()

            for depth in range(MAX_SCROLL_DEPTH):
                self._posiziona_sidebar(ctx, depth)
                shot = ctx.device.screenshot()
                pallini = trova_pallini_sidebar(shot.frame)
                if not pallini:
                    continue
                log(f"[EVENT_CENTER_CLAIMS] depth={depth}: {len(pallini)} pallini")
                for (_bx, by) in pallini:
                    ctx.device.tap(ROW_TAP_X, by)
                    time.sleep(cfg.wait_open_s)
                    shot2 = ctx.device.screenshot()
                    titolo_id, score = riconosci_titolo(shot2.frame, crops)

                    if titolo_id is None:
                        # Titolo mai visto — verifico SOLO il widget CLAIM
                        # già noto (mai tap esplorativo), poi imparo.
                        titolo_id = prossimo_id(crops)
                        salva_crop_titolo(titolo_id, shot2.frame)
                        crops[titolo_id] = shot2.frame[15:55, 40:500]
                        m = ctx.matcher.find_one(shot2, CLAIM_TEMPLATE,
                                                 threshold=CLAIM_THRESHOLD, zone=CLAIM_ZONE)
                        claimable = bool(m.found)
                        log(f"[EVENT_CENTER_CLAIMS] NUOVO titolo '{titolo_id}' "
                            f"(depth={depth}, y={by}) → claimabile={claimable} "
                            f"(score={m.score:.3f})")
                        catalogo[titolo_id] = {
                            "claimable": claimable,
                            "label": titolo_id,
                            "first_seen": ts_ora(),
                            "last_seen": ts_ora(),
                        }
                        if claimable:
                            n = self._claim_loop(ctx, log)
                            risultati[titolo_id] = risultati.get(titolo_id, 0) + n
                    else:
                        dati = catalogo.get(titolo_id, {})
                        label = dati.get("label", titolo_id)
                        dati["last_seen"] = ts_ora()
                        catalogo[titolo_id] = dati
                        if titolo_id in processate_run:
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' già processata "
                                f"in questo giro (vista a più profondità) → skip")
                        elif not dati.get("claimable"):
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' nota non claimabile "
                                f"(score={score:.3f}) → skip")
                        else:
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' nota claimabile "
                                f"(score={score:.3f}) → verifico")
                            n = self._claim_loop(ctx, log)
                            risultati[label] = risultati.get(label, 0) + n
                        processate_run.add(titolo_id)

                    debug.snap(f"02_{titolo_id}", shot2)
                    # NIENTE tap "back" qui: la sidebar resta SEMPRE visibile
                    # insieme al contenuto (verificato dal vivo navigando a
                    # mano tra le voci) — TAP_HUB_BACK chiude l'INTERO hub,
                    # non torna alla sola sidebar. La prossima iterazione
                    # (_posiziona_sidebar) riposiziona lo scroll direttamente,
                    # nessun bisogno di "tornare" da nessuna parte prima.

            salva_catalogo(catalogo)

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
