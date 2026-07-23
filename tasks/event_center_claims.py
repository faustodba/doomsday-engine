"""
tasks/event_center_claims.py — EventCenterClaimsTask V6
============================================================================
Task (22/07/2026, redesign stesso giorno dopo v1 a posizione fissa) — claim
gratuiti nell'hub "Event Center": l'icona rotante in alto a destra su HOME
che alterna label ("Event Center"/"Water War"/"Arms Race"/ecc. a seconda
dell'evento in vetrina del giorno — stesso tap target indipendentemente
dalla label mostrata).

IDENTITÀ = IMMAGINE DELLA RIGA SIDEBAR (icona+etichetta), non posizione,
non il titolo del sottomenu aperto. Osservazione utente: la stessa voce
sidebar può comparire a profondità di scroll diverse su istanze diverse
(o nel tempo, con eventi che ruotano) — coordinate fisse non sono
un'identità affidabile, né lo è l'OCR del titolo (troppo rumoroso:
"Survival Preparations" letto come "> a Survival Preparat"). Il crop
della riga sidebar (icona+etichetta, stesso principio già validato per
il pulsante CLAIM) è un'identità robusta e indipendente dalla posizione
— riconosciuto via template matching (`shared/claim_catalog.py`).

Fix 22/07 (v2, stesso giorno dopo v1 a identità-titolo-post-tap):
riconoscere DALLA SCREENSHOT DELLA SIDEBAR, PRIMA di aprire il
sottomenu — non più tap-poi-riconosci. Motivo (utente, dal vivo): le
voci già catalogate come non-claimabili venivano comunque APERTE ogni
volta solo per leggerne il titolo e scoprire che non c'era nulla da
fare — tempo sprecato. Il crop riga (icona+etichetta) è visibile e
stabile già nello screenshot usato per `trova_pallini_sidebar`, quindi
il riconoscimento non costa uno screenshot né un tap in più.

FLUSSO (un run = una scansione completa, già schedulato 1×/giorno per
istanza via task_setup.json "daily" — nessun gate interno aggiuntivo):
  - HOME → pallino su icona HOME (posizione fissa, non scorre)? No → skip.
  - Apro hub. Per ogni profondità di scroll (reset a inizio lista +
    N swipe avanti): trovo pallini rossi GENERICI nella colonna sidebar
    (posizione — solo per SAPERE QUALI RIGHE guardare in QUESTO giro).
  - Per ogni pallino (bx,by): riconosco SUBITO la riga (crop dalla
    screenshot già in mano) via template matching contro tutte le righe
    già note (catalogo condiviso dev+prod, cresce nel tempo):
      * Riga nota e claimabile     → tap per aprire, verifico/clicco il
        widget CLAIM.
      * Riga nota e non claimabile → skip immediato, ZERO tap — questo
        è l'intero punto del redesign.
      * Riga mai vista              → tap per aprire (unico caso in cui
        si apre "per scoprire"), verifico SOLO il widget CLAIM già noto
        (mai un tap esplorativo su qualcosa di ignoto) → imparo il
        risultato E salvo il crop RIGA (quello di PRIMA del tap) per
        riconoscerla la prossima volta, su qualunque istanza, senza
        più aprirla.
    → la sidebar resta sempre visibile, nessun "ritorno" necessario tra
      una riga e l'altra.
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
    carica_crop_righe,
    salva_crop_riga,
    riconosci_riga,
    ritaglia_riga,
    prossimo_id,
    ts_ora,
    deve_rivalutare,
    RIVALUTAZIONE_GIORNI,
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
            crops = carica_crop_righe()
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
                    # Riconoscimento PRIMA di aprire — crop dalla screenshot
                    # già in mano (stessa usata per trova_pallini_sidebar),
                    # zero screenshot/tap extra. Questo è ciò che permette
                    # di saltare le righe già note come non claimabili
                    # SENZA mai aprirle.
                    riga_id, score = riconosci_riga(shot.frame, by, crops)

                    if riga_id is not None:
                        dati = catalogo.get(riga_id, {})
                        label = dati.get("label", riga_id)
                        if riga_id in processate_run:
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' già processata "
                                f"in questo giro (vista a più profondità) → skip")
                            continue
                        dati["last_seen"] = ts_ora()
                        catalogo[riga_id] = dati
                        processate_run.add(riga_id)
                        if not dati.get("claimable"):
                            if not deve_rivalutare(dati):
                                log(f"[EVENT_CENTER_CLAIMS] '{label}' nota non "
                                    f"claimabile (score={score:.3f}) → skip, "
                                    f"nessun tap")
                                continue
                            # Rivalutazione periodica (23/07) — voci CICLICHE
                            # come Login Rewards si rinnovano ogni giorno; se
                            # il primo incontro cade in un giorno senza nulla
                            # da reclamare, "claimable=False" fissato per
                            # sempre le farebbe skippare anche nei giorni in
                            # cui il premio torna disponibile. Riapre per
                            # riverificare — stesso costo di una riga nuova.
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' nota non "
                                f"claimabile ma rivalutazione scaduta "
                                f"(>={RIVALUTAZIONE_GIORNI}gg) → riapro per "
                                f"riverificare")
                            ctx.device.tap(ROW_TAP_X, by)
                            time.sleep(cfg.wait_open_s)
                            shot2 = ctx.device.screenshot()
                            m = ctx.matcher.find_one(shot2, CLAIM_TEMPLATE,
                                                     threshold=CLAIM_THRESHOLD, zone=CLAIM_ZONE)
                            claimable_ora = bool(m.found)
                            dati["claimable"] = claimable_ora
                            dati["last_checked"] = ts_ora()
                            catalogo[riga_id] = dati
                            log(f"[EVENT_CENTER_CLAIMS] '{label}' rivalutata "
                                f"→ claimabile={claimable_ora} (score={m.score:.3f})")
                            if claimable_ora:
                                n = self._claim_loop(ctx, log)
                                risultati[label] = risultati.get(label, 0) + n
                            debug.snap(f"02_{riga_id}_rivalutata", shot2)
                            continue
                        log(f"[EVENT_CENTER_CLAIMS] '{label}' nota claimabile "
                            f"(score={score:.3f}) → apro e verifico")
                        ctx.device.tap(ROW_TAP_X, by)
                        time.sleep(cfg.wait_open_s)
                        shot2 = ctx.device.screenshot()
                        dati["last_checked"] = ts_ora()
                        catalogo[riga_id] = dati
                        n = self._claim_loop(ctx, log)
                        risultati[label] = risultati.get(label, 0) + n
                        debug.snap(f"02_{riga_id}", shot2)
                        continue

                    # Riga mai vista — unico caso in cui si apre "per
                    # scoprire". Salvo il crop di QUESTA screenshot (prima
                    # del tap): è la riga sidebar, non il titolo aperto.
                    riga_id = prossimo_id(crops)
                    salva_crop_riga(riga_id, shot.frame, by)
                    crops[riga_id] = ritaglia_riga(shot.frame, by)

                    ctx.device.tap(ROW_TAP_X, by)
                    time.sleep(cfg.wait_open_s)
                    shot2 = ctx.device.screenshot()
                    m = ctx.matcher.find_one(shot2, CLAIM_TEMPLATE,
                                             threshold=CLAIM_THRESHOLD, zone=CLAIM_ZONE)
                    claimable = bool(m.found)
                    log(f"[EVENT_CENTER_CLAIMS] NUOVA riga '{riga_id}' "
                        f"(depth={depth}, y={by}) → claimabile={claimable} "
                        f"(score={m.score:.3f})")
                    catalogo[riga_id] = {
                        "claimable": claimable,
                        "label": riga_id,
                        "first_seen": ts_ora(),
                        "last_seen": ts_ora(),
                        "last_checked": ts_ora(),
                    }
                    processate_run.add(riga_id)
                    if claimable:
                        n = self._claim_loop(ctx, log)
                        risultati[riga_id] = risultati.get(riga_id, 0) + n
                    debug.snap(f"02_{riga_id}", shot2)
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
