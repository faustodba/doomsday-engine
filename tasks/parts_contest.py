"""
tasks/parts_contest.py — PartsContestTask V6
============================================================================
Task custom master (21/07/2026) — evento "Special Promo → Parts Contest".

CONTESTO (logica di gioco appresa live dall'utente 20-21/07):
  Special Promo è un pannello con una SIDEBAR di menù (alcuni fissi settimanali
  come Parts Contest, altri legati agli eventi). Ogni menù con ricompense da
  ritirare ha un PALLINO ROSSO. Parts Contest ha 3 SOTTO-TAB:
    [traccia] Parts Contest | Daily Missions | Challenges
  Completando missioni in Daily Missions/Challenges si accumula EXP → sale il
  livello della traccia → si sbloccano box gratuiti → "COLLECT ALL".

  FLUSSO (solo ricompense GRATIS):
    1. Apri Special Promo, seleziona Parts Contest.
    2. Nei sotto-tab Daily Missions e Challenges: tappa i pulsanti "Claim"
       VERDI (gratis) → l'EXP sale sulla traccia. Salta i pulsanti ambra
       "Keep Claiming" (= acquisto pass, A PAGAMENTO).
    3. Vai sulla traccia Parts Contest: se il pulsante in basso è VERDE
       "COLLECT ALL" → tappalo (recupera tutti i box gratuiti) → chiudi il
       popup ricompensa. Se è AMBRA "Keep Claiming" → non c'è nulla di gratis.

REGOLA DI SICUREZZA (vincolante, rischio soldi veri):
  Si tappa SOLO il VERDE. Ambra "Keep Claiming"/prezzo € = a pagamento, MAI.
  Il discriminante è per COLORE (validato live 21/07 al 100% anche su schermate
  miste: "Free" verde vs "€X.XX" ambra):
    - ambra-frac (hue 10-35, S/V alti) > soglia → PAGAMENTO → skip
    - verde-frac (hue 35-90) > soglia & ambra bassa → GRATIS → tap

POSIZIONAMENTO (nota utente 21/07):
  - La POSIZIONE del menù nella sidebar VARIA (dipende dagli eventi attivi +
    scroll) → navigazione via TEMPLATE MATCH (pin_parts_contest) + scroll.
  - Anche l'icona Special Promo nella barra eventi HOME VARIA → template match
    (pin_special_promo).
  - Una volta SELEZIONATO il menù, la STRUTTURA INTERNA è FISSA → sotto-tab,
    righe missione, pulsanti e COLLECT ALL a coordinate fisse + check colore.

Registrazione: solo master (via task_overrides + profilo master). Periodico
(interval 12h): l'evento matura ricompense durante la giornata (Daily Missions
reset 00:00 UTC), non serve girare ad ogni ciclo. Idempotente: se non c'è nulla
di verde, tutti no-op.

NOTA CALIBRAZIONE: coordinate interne e soglie colore validate su master
FauMorfeus (960×540). ROI/coord marcate `# LIVE` da riverificare nel test live
su un'istanza con ricompense fresche (il master ha Parts Contest esaurito).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from core.task import Task, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Frame helper (BGR numpy da Screenshot) — allineato a tasks/radar.py
# ---------------------------------------------------------------------------

def _frame(screen) -> np.ndarray | None:
    if screen is None:
        return None
    f = getattr(screen, "frame", None)
    if f is not None:
        return f
    if isinstance(screen, np.ndarray):
        return screen
    return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PartsContestConfig:
    # --- Apertura Special Promo (barra eventi HOME, posizione variabile) ---
    pin_special_promo: str = "pin/pin_special_promo.png"
    soglia_promo:      float = 0.80
    zona_barra_eventi: tuple[int, int, int, int] = (330, 38, 940, 100)  # top bar
    tap_promo_fallback: tuple[int, int] = (686, 52)  # LIVE — solo se match fallisce
    # Il template è icona+label; il centro match cade sulla label (non apre).
    # L'area cliccabile è l'ICONA sopra → tap a (cx, cy - promo_tap_dy).
    # Validato live FAU_01 21/07: y67(label) non apre, y52(icona) apre.
    promo_tap_dy: int = 15

    # --- Selezione Parts Contest nella sidebar (posizione variabile) ---
    pin_parts_contest: str = "pin/pin_parts_contest.png"
    soglia_sidebar:    float = 0.80
    zona_sidebar:      tuple[int, int, int, int] = (0, 40, 150, 540)
    # scroll sidebar per cercare la voce se non visibile
    sidebar_scroll:    tuple[int, int, int, int] = (75, 450, 75, 200)  # x0,y0,x1,y1
    sidebar_scroll_dur_ms: int = 600
    max_sidebar_scroll: int = 4

    # --- Struttura interna FISSA (una volta selezionato Parts Contest) ---
    # Sotto-tab (y=154): traccia / Daily Missions / Challenges
    tap_subtab_track:     tuple[int, int] = (290, 154)
    tap_subtab_daily:     tuple[int, int] = (549, 154)
    tap_subtab_challenges: tuple[int, int] = (808, 154)

    # Colonna dei pulsanti Claim/stato nei sotto-tab missioni (destra)
    col_pulsanti:  tuple[int, int, int, int] = (767, 195, 921, 478)  # LIVE
    # Scroll lista missioni (contenuto sale)
    lista_scroll:  tuple[int, int, int, int] = (480, 430, 480, 250)
    lista_scroll_dur_ms: int = 400
    max_claim_loop:   int = 25
    max_scroll_vuoti: int = 2

    # Pulsante traccia in basso: "COLLECT ALL" (gratis) vs "Keep Claiming"
    # (pass a pagamento). ATTENZIONE: COLLECT ALL è AMBRA come Keep Claiming
    # (scoperto live FAU_00 21/07) → il colore NON li distingue. Si discrimina
    # sul TESTO (template pin_collect_all): match 1.000 su COLLECT ALL vs 0.371
    # su Keep Claiming. "COLLECT ALL" appare solo per ricompense gratis → tap
    # sicuro; "Keep Claiming" (nessun match) = a pagamento → skip.
    pin_collect_all:    str = "pin/pin_collect_all.png"
    soglia_collect_all: float = 0.80
    roi_bottone_traccia: tuple[int, int, int, int] = (458, 486, 693, 520)
    tap_collect_all:     tuple[int, int] = (575, 503)  # fallback (usa match cx,cy)
    max_collect_loop:    int = 8

    # Chiusura popup ricompensa "Congratulations! You got" (tap zona vuota)
    tap_chiudi_popup: tuple[int, int] = (480, 400)  # LIVE

    # --- Discriminante colore (validato live 21/07) ---
    hue_ambra: tuple[int, int] = (10, 35)   # ambra "Keep Claiming" / pass a pagamento
    hue_verde: tuple[int, int] = (35, 90)   # verde "Claim" / "Free" / "COLLECT ALL"
    s_min: int = 80
    v_min: int = 80
    # soglie frazione pixel saturi
    verde_min_frac: float = 0.20   # >20% verde → candidato gratis
    ambra_max_frac: float = 0.15   # ambra deve restare sotto → evita falsi positivi
    ambra_paga_frac: float = 0.40  # >40% ambra → sicuramente a pagamento
    # scan bande verdi (righe) nella colonna pulsanti
    riga_verde_frac: float = 0.28  # una riga è "verde" se >28% pixel verdi
    riga_ambra_frac: float = 0.15
    banda_min_h:     int = 12      # altezza minima banda per considerarla un pulsante

    # --- Timing ---
    wait_apri_promo:  float = 3.0
    wait_sidebar:     float = 2.0
    wait_subtab:      float = 2.0
    wait_post_claim:  float = 3.0   # animazione popup reward
    wait_post_close:  float = 1.5
    wait_scroll:      float = 1.5
    wait_back:        float = 2.0


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class PartsContestTask(Task):
    """Ritira le ricompense GRATIS di Special Promo → Parts Contest. Solo master.
    Periodico (12h). Tappa esclusivamente pulsanti VERDI (mai a pagamento)."""

    def __init__(self, config: PartsContestConfig | None = None) -> None:
        self._cfg = config or PartsContestConfig()

    def name(self) -> str:
        return "parts_contest"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("parts_contest"):
                return False
        return True

    # ------------------------------------------------------------------
    # Discriminante colore (cuore anti-pagamento)
    # ------------------------------------------------------------------

    def _frazioni(self, frame, roi):
        """(verde_frac, ambra_frac) dei pixel saturi nella ROI."""
        cfg = self._cfg
        x0, y0, x1, y1 = roi
        sub = frame[y0:y1, x0:x1]
        if sub.size == 0:
            return 0.0, 0.0
        hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
        h = hsv[..., 0].astype(int); s = hsv[..., 1]; v = hsv[..., 2]
        sat = (s > cfg.s_min) & (v > cfg.v_min)
        n = int(sat.sum())
        if n < 20:
            return 0.0, 0.0
        al, ah = cfg.hue_ambra; vl, vh = cfg.hue_verde
        ambra = (((h >= al) & (h <= ah)) & sat).sum() / n
        verde = (((h >= vl) & (h <= vh)) & sat).sum() / n
        return float(verde), float(ambra)

    def _e_verde(self, frame, roi) -> bool:
        """True se il pulsante nella ROI è VERDE (gratis) e NON ambra."""
        verde, ambra = self._frazioni(frame, roi)
        return verde > self._cfg.verde_min_frac and ambra < self._cfg.ambra_max_frac

    def _bande_verdi(self, frame) -> list[tuple[int, int]]:
        """Scandisce la colonna pulsanti e ritorna i centri (cx,cy) delle bande
        verticali VERDI (pulsanti Claim gratis). Salta l'ambra. Robusto alla Y
        variabile delle righe tra Daily Missions e Challenges."""
        cfg = self._cfg
        x0, y0, x1, y1 = cfg.col_pulsanti
        sub = frame[y0:y1, x0:x1]
        if sub.size == 0:
            return []
        hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
        h = hsv[..., 0].astype(int); s = hsv[..., 1]; v = hsv[..., 2]
        sat = (s > cfg.s_min) & (v > cfg.v_min)
        al, ah = cfg.hue_ambra; vl, vh = cfg.hue_verde
        green = ((h >= vl) & (h <= vh)) & sat
        amber = ((h >= al) & (h <= ah)) & sat
        w = sub.shape[1]
        frac_g = green.sum(axis=1) / w
        frac_a = amber.sum(axis=1) / w
        riga_verde = (frac_g > cfg.riga_verde_frac) & (frac_a < cfg.riga_ambra_frac)
        bande = []
        y = 0; nrow = len(riga_verde)
        while y < nrow:
            if riga_verde[y]:
                y2 = y
                while y2 < nrow and riga_verde[y2]:
                    y2 += 1
                if (y2 - y) >= cfg.banda_min_h:
                    cy = y0 + (y + y2) // 2
                    cx = (x0 + x1) // 2
                    bande.append((cx, cy))
                y = y2
            else:
                y += 1
        return bande

    # ------------------------------------------------------------------
    # Navigazione
    # ------------------------------------------------------------------

    def _apri_special_promo(self, ctx, cfg, log) -> bool:
        shot = ctx.device.screenshot()
        m = ctx.matcher.find_one(shot, cfg.pin_special_promo,
                                 threshold=cfg.soglia_promo, zone=cfg.zona_barra_eventi)
        if m.found:
            ty = m.cy - cfg.promo_tap_dy   # tap sull'icona (non la label)
            log(f"[PARTS_CONTEST] Special Promo trovato @({m.cx},{m.cy}) score={m.score:.3f} "
                f"→ tap icona ({m.cx},{ty})")
            ctx.device.tap(m.cx, ty)
        else:
            log(f"[PARTS_CONTEST] Special Promo NON trovato (score={m.score:.3f}) → "
                f"fallback {cfg.tap_promo_fallback}")
            ctx.device.tap(*cfg.tap_promo_fallback)
        time.sleep(cfg.wait_apri_promo)
        return True

    def _seleziona_parts_contest(self, ctx, cfg, log) -> bool:
        """Trova Parts Contest nella sidebar (posizione variabile) con scroll e
        lo seleziona. Ritorna False se non trovato dopo max scroll."""
        for tentativo in range(cfg.max_sidebar_scroll + 1):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_parts_contest,
                                     threshold=cfg.soglia_sidebar, zone=cfg.zona_sidebar)
            if m.found:
                log(f"[PARTS_CONTEST] voce Parts Contest @({m.cx},{m.cy}) "
                    f"score={m.score:.3f} → seleziono")
                ctx.device.tap(m.cx, m.cy)
                time.sleep(cfg.wait_sidebar)
                return True
            if tentativo < cfg.max_sidebar_scroll:
                log(f"[PARTS_CONTEST] Parts Contest non visibile (score={m.score:.3f}) → "
                    f"scroll sidebar {tentativo+1}/{cfg.max_sidebar_scroll}")
                x0, y0, x1, y1 = cfg.sidebar_scroll
                ctx.device.swipe(x0, y0, x1, y1, cfg.sidebar_scroll_dur_ms)
                time.sleep(cfg.wait_scroll)
        return False

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    def _claim_subtab(self, ctx, cfg, log, tap_subtab, nome) -> int:
        """Apre un sotto-tab (Daily/Challenges) e tappa tutti i Claim VERDI,
        con scroll. Ritorna il numero di claim verdi tappati."""
        log(f"[PARTS_CONTEST] sotto-tab {nome} → apro")
        ctx.device.tap(*tap_subtab)
        time.sleep(cfg.wait_subtab)
        n = 0
        scroll_vuoti = 0
        for _ in range(cfg.max_claim_loop):
            frame = _frame(ctx.device.screenshot())
            if frame is None:
                break
            bande = self._bande_verdi(frame)
            if bande:
                cx, cy = bande[0]
                log(f"[PARTS_CONTEST] {nome}: Claim VERDE #{n+1} → tap ({cx},{cy})")
                ctx.device.tap(cx, cy)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)  # chiude popup ricompensa
                time.sleep(cfg.wait_post_close)
                n += 1
                scroll_vuoti = 0
                continue
            if scroll_vuoti >= cfg.max_scroll_vuoti:
                break
            x0, y0, x1, y1 = cfg.lista_scroll
            ctx.device.swipe(x0, y0, x1, y1, cfg.lista_scroll_dur_ms)
            time.sleep(cfg.wait_scroll)
            scroll_vuoti += 1
        log(f"[PARTS_CONTEST] {nome}: {n} claim verdi")
        return n

    def _collect_all_traccia(self, ctx, cfg, log) -> int:
        """Va sulla traccia Parts Contest; se il bottone in basso (posizione
        FISSA) porta il testo "COLLECT ALL" (gratis) lo tappa e chiude il popup,
        in loop finché resta COLLECT ALL. Se è "Keep Claiming" (nessun match =
        pass a pagamento) salta. Discriminazione sul TESTO, non sul colore
        (COLLECT ALL è ambra come Keep Claiming). Ritorna n. di collect."""
        log("[PARTS_CONTEST] traccia → verifico COLLECT ALL (match testo)")
        ctx.device.tap(*cfg.tap_subtab_track)
        time.sleep(cfg.wait_subtab)
        n = 0
        for _ in range(cfg.max_collect_loop):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_collect_all,
                                     threshold=cfg.soglia_collect_all,
                                     zone=cfg.roi_bottone_traccia)
            if m.found:
                log(f"[PARTS_CONTEST] COLLECT ALL presente (score={m.score:.3f}) "
                    f"→ tap posizione fissa {cfg.tap_collect_all}")
                ctx.device.tap(*cfg.tap_collect_all)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)
                time.sleep(cfg.wait_post_close)
                n += 1
                continue
            log(f"[PARTS_CONTEST] COLLECT ALL non presente (score={m.score:.3f}) → "
                f"'Keep Claiming' (a pagamento) o nulla di gratis → skip")
            break
        log(f"[PARTS_CONTEST] COLLECT ALL: {n}")
        return n

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("parts_contest", getattr(ctx, "instance_name", "_unknown"))
        try:
            self._apri_special_promo(ctx, cfg, log)
            debug.snap("01_special_promo", ctx.device.screenshot())

            if not self._seleziona_parts_contest(ctx, cfg, log):
                log("[PARTS_CONTEST] voce Parts Contest non trovata → skip")
                debug.snap("02_no_parts_contest", ctx.device.screenshot())
                self._esci(ctx, cfg)
                debug.flush(success=True, force=True, log_fn=log)
                return TaskResult.skip("Parts Contest non disponibile")

            debug.snap("03_parts_contest", ctx.device.screenshot())

            # Claim nei sotto-tab (verde = gratis). Visitiamo entrambi: claimare
            # in uno recupera anche l'altro, ma la doppia visita è idempotente e
            # robusta (nel secondo non troverà più verde).
            n_daily = self._claim_subtab(ctx, cfg, log, cfg.tap_subtab_daily, "Daily Missions")
            debug.snap("04_post_daily", ctx.device.screenshot())
            n_chal = self._claim_subtab(ctx, cfg, log, cfg.tap_subtab_challenges, "Challenges")
            debug.snap("05_post_challenges", ctx.device.screenshot())

            # Traccia: COLLECT ALL (verde)
            n_collect = self._collect_all_traccia(ctx, cfg, log)
            debug.snap("06_post_collect", ctx.device.screenshot())

            self._esci(ctx, cfg)
            tot = n_daily + n_chal + n_collect
            log(f"[PARTS_CONTEST] completato — daily={n_daily} challenges={n_chal} "
                f"collect_all={n_collect}")
            # Anomalia diagnostica: nessun claim (nulla di verde ovunque)
            debug.flush(success=True, force=(tot == 0), log_fn=log)
            return TaskResult.ok(f"Parts Contest — claim verdi={n_daily+n_chal} "
                                 f"collect_all={n_collect}",
                                 daily=n_daily, challenges=n_chal, collect_all=n_collect)
        except Exception as exc:
            log(f"[PARTS_CONTEST] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")

    def _esci(self, ctx, cfg) -> None:
        """Chiude il pannello Special Promo tornando verso HOME (back in alto a
        sinistra). Il Navigator riporterà comunque in HOME al prossimo task."""
        ctx.device.tap(30, 30)
        time.sleep(cfg.wait_back)
        if ctx.navigator is not None:
            ctx.navigator.vai_in_home()
