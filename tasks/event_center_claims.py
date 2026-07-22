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
  - Per ogni voce del catalogo (statico + appreso, vedi DISCOVERY sotto):
    riporto la sidebar in cima (overshoot sicuro) + applico gli swipe
    "avanti" calibrati per quella voce (alcune sono sotto la piega, es.
    Survival Preparations) → pallino sidebar? No → prossima voce. Sì →
    tap voce → loop claim (screenshot, cerca template, tap, chiudi popup
    in zona sicura, ripeti fino a max_claims o nessun claim trovato — nota:
    il gioco può risolvere più claim pronti in un solo tap, osservato live
    su Survival Preparations) → torno alla sidebar dell'hub.
  - Se è il primo run della giornata (`claim_catalog.serve_discovery_oggi`,
    "la prima istanza che entra"): DISCOVERY — scansiona l'intera sidebar
    per profondità di scroll, trova pallini rossi generici (non solo sulle
    voci già note), per ognuno non ancora catalogato/appreso entra, legge
    il titolo via OCR, cerca il MEDESIMO widget CLAIM già verificato — se
    matcha lo tappa e segna "claimabile", altrimenti segna "non
    claimabile" (mai più ri-visitata). Aggiorna
    data/claim_catalog_learned.json. Mai un tap su qualcosa che non sia il
    widget claim già noto — niente esplorazione a bottoni ignoti.
  - Back → back → vai_in_home() di sicurezza.

REGOLA SICUREZZA: mai tap su un pulsante non verificato dal template
claim specifico. Mai il pallino rosso da solo come segnale d'azione. La
discovery scopre QUALI MENU hanno il widget noto, non inventa nuovi
pattern di tap.

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
    MAX_SCROLL_DEPTH,
    ROW_TAP_X,
    TITLE_OCR_ZONE,
    DISCOVERY_CLAIM_TEMPLATE,
    DISCOVERY_CLAIM_ZONE,
    DISCOVERY_CLAIM_THRESHOLD,
    ClaimMenuSpec,
    frazione_pallino_rosso,
    trova_pallini_sidebar,
    carica_appreso,
    salva_appreso,
    serve_discovery_oggi,
    segna_discovery_fatta,
)


@dataclass
class EventCenterClaimsConfig:
    wait_hub_open:  float = 2.0
    wait_hub_back:  float = 1.5
    # REGOLA DELAY UI (.claude/CLAUDE.md): l'animazione di scroll sidebar ha
    # inerzia/decelerazione — verificato dal vivo 22/07 che 0.6s produceva
    # 0/3 badge reali rilevati (screenshot a metà animazione), mentre un
    # test manuale con pause piu' larghe rilevava i badge correttamente.
    wait_scroll_s:  float = 1.5
    wait_ocr_s:     float = 2.0


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

    def _posiziona_sidebar(self, ctx, n_scroll: int, log) -> None:
        """Riporta la sidebar in cima (overshoot sicuro, il rebound si
        ferma da solo a inizio lista) poi applica n_scroll swipe "avanti"
        per rivelare quella profondità. Sempre dallo stesso punto di
        partenza noto, indipendentemente da dove si trovava lo scroll
        prima — garantisce posizioni riproducibili."""
        cfg = self._cfg
        for _ in range(SIDEBAR_SCROLL_RESET_N):
            x0, y0, x1, y1, dur = SIDEBAR_SCROLL_RESET
            ctx.device.swipe(x0, y0, x1, y1, dur)
            time.sleep(cfg.wait_scroll_s)
        for _ in range(n_scroll):
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
    # DISCOVERY — auto-apprendimento voci non catalogate
    # ------------------------------------------------------------------

    def _leggi_titolo(self, ctx) -> str:
        from shared.ocr_helpers import ocr_zona
        shot = ctx.device.screenshot()
        try:
            testo = ocr_zona(shot, TITLE_OCR_ZONE, preprocessor="otsu")
        except Exception:
            testo = ""
        return (testo or "").strip()

    @staticmethod
    def _posizione_key(depth: int, y: int) -> str:
        """Identità di posizione (depth + y arrotondato a bucket 20px, per
        tollerare jitter pixel tra run diversi). L'OCR del titolo è troppo
        rumoroso per essere usato come chiave di dedup (verificato dal vivo:
        '> a Survival Preparat' invece di 'Survival Preparations') — la
        posizione è deterministica (stesso reset+scroll ogni volta), il
        titolo OCR resta solo come etichetta leggibile nel catalogo."""
        return f"depth{depth}_y{round(y / 20) * 20}"

    def _discovery_scan(self, ctx, log, debug) -> dict:
        """Scansiona l'intera sidebar (tutte le profondità di scroll),
        trova pallini rossi GENERICI (non solo sulle voci già note), per
        ognuna posizione non ancora catalogata/appresa: entra, legge il
        titolo via OCR (solo per l'etichetta, non per il dedup), cerca il
        widget CLAIM già verificato (mai un template nuovo inventato al
        volo). Se matcha → tap + segna claimabile. Se no → segna non
        claimabile, mai più ri-visitata. Ritorna i nuovi claim riscossi in
        questo giro {nome: 1}."""
        appreso = carica_appreso()
        posizioni_note = {
            self._posizione_key(c.n_scroll, (c.badge_roi[1] + c.badge_roi[3]) // 2)
            for c in CLAIM_CATALOG
        }
        posizioni_note |= {
            self._posizione_key(int(d.get("n_scroll", 0)), int(d.get("tap_y", 0)))
            for d in appreso.values()
        }
        processate_run: set[str] = set()
        nuovi_claim: dict[str, int] = {}

        for depth in range(MAX_SCROLL_DEPTH):
            self._posiziona_sidebar(ctx, depth, log)
            shot = ctx.device.screenshot()
            pallini = trova_pallini_sidebar(shot.frame)
            if not pallini:
                continue
            log(f"[EVENT_CENTER_CLAIMS][DISCOVERY] depth={depth}: "
                f"{len(pallini)} pallini rilevati")
            for (_bx, by) in pallini:
                pos_key = self._posizione_key(depth, by)
                if pos_key in posizioni_note or pos_key in processate_run:
                    continue
                processate_run.add(pos_key)
                ctx.device.tap(ROW_TAP_X, by)
                time.sleep(self._cfg.wait_ocr_s)
                etichetta = self._leggi_titolo(ctx) or pos_key
                log(f"[EVENT_CENTER_CLAIMS][DISCOVERY] nuova posizione "
                    f"{pos_key} — titolo OCR: '{etichetta}'")
                shot2 = ctx.device.screenshot()
                m = ctx.matcher.find_one(shot2, DISCOVERY_CLAIM_TEMPLATE,
                                         threshold=DISCOVERY_CLAIM_THRESHOLD,
                                         zone=DISCOVERY_CLAIM_ZONE)
                claimable = bool(m.found)
                if claimable:
                    log(f"[EVENT_CENTER_CLAIMS][DISCOVERY] '{etichetta}' "
                        f"CLAIMABILE (score={m.score:.3f}) → tap")
                    ctx.device.tap(m.cx, m.cy)
                    time.sleep(self._cfg.wait_ocr_s)
                    ctx.device.tap(100, 450)
                    time.sleep(1.5)
                    nuovi_claim[pos_key] = 1
                else:
                    log(f"[EVENT_CENTER_CLAIMS][DISCOVERY] '{etichetta}' non "
                        f"claimabile (score={m.score:.3f}) → imparato, "
                        f"mai più ri-visitata")
                appreso[pos_key] = {
                    "label": etichetta,
                    "claimable": claimable,
                    "n_scroll": depth,
                    "tap_y": by,
                    "verified_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                debug.snap(f"discovery_{pos_key}", shot2)
                ctx.device.tap(*TAP_HUB_BACK)
                time.sleep(self._cfg.wait_hub_back)

        salva_appreso(appreso)
        segna_discovery_fatta()
        log(f"[EVENT_CENTER_CLAIMS][DISCOVERY] completata — "
            f"{len(processate_run)} nuove posizioni esaminate, "
            f"{len(nuovi_claim)} claimabili")
        return nuovi_claim

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

            # Catalogo effettivo = statico (verificato a mano) + appreso in
            # discovery nei giorni precedenti (claimable=True). Le voci
            # imparate come non-claimabili restano fuori per sempre (mai
            # ri-visitate).
            specs = list(CLAIM_CATALOG)
            for pos_key, dati in carica_appreso().items():
                if not dati.get("claimable"):
                    continue
                by = int(dati.get("tap_y", 0))
                specs.append(ClaimMenuSpec(
                    name=f"{pos_key} ({dati.get('label', '?')})",
                    tap_sidebar=(ROW_TAP_X, by),
                    badge_roi=(185, max(0, by - 15), 215, by + 15),
                    claim_template=DISCOVERY_CLAIM_TEMPLATE,
                    claim_zone=DISCOVERY_CLAIM_ZONE,
                    claim_threshold=DISCOVERY_CLAIM_THRESHOLD,
                    n_scroll=int(dati.get("n_scroll", 0)),
                ))

            risultati: dict[str, int] = {}
            for spec in specs:
                self._posiziona_sidebar(ctx, spec.n_scroll, log)
                shot_sidebar = ctx.device.screenshot()
                frac = frazione_pallino_rosso(shot_sidebar.frame, spec.badge_roi)
                if frac <= BADGE_RED_MIN_FRAC:
                    log(f"[EVENT_CENTER_CLAIMS] {spec.name}: nessun pallino sidebar "
                        f"(red%={frac*100:.1f}) → skip")
                    continue
                log(f"[EVENT_CENTER_CLAIMS] {spec.name}: pallino sidebar rilevato "
                    f"(red%={frac*100:.1f}) → entro")
                risultati[spec.name] = self._claim_voce(ctx, spec, log)
                debug.snap(f"02_{spec.name}"[:60], ctx.device.screenshot())

            # DISCOVERY — solo il primo run della giornata ("la prima
            # istanza che entra"). Trova voci nuove, mai catalogate né
            # imparate, e le impara (claimabile o no) per i run successivi.
            if serve_discovery_oggi():
                log("[EVENT_CENTER_CLAIMS] primo run di oggi → discovery completa")
                nuovi = self._discovery_scan(ctx, log, debug)
                for nome, n in nuovi.items():
                    risultati[nome] = risultati.get(nome, 0) + n

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
