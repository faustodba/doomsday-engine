"""
tasks/special_promo.py — base condivisa per i task contest di Special Promo
============================================================================
Base per i task che ritirano le ricompense GRATIS dei menù "contest" dentro
l'evento Special Promo (Parts Contest, Customization Contest, Vehicle Redesign,
Mega Armament, Chip Challenge, ...). Estratta da tasks/parts_contest.py il
21/07/2026 quando è emerso che i contest condividono navigazione + COLLECT ALL
e differiscono solo per: template della voce sidebar e presenza dei sotto-tab.

LOGICA COMUNE (appresa live dall'utente, validata 21/07 su FAU_00):
  Special Promo = pannello con SIDEBAR di menù; ogni menù con ricompense ha un
  PALLINO ROSSO (badge). Ogni contest ha una TRACCIA con box gratuiti per
  livello; il pulsante in basso "COLLECT ALL" (gratis) li raccoglie. Alcuni
  contest (es. Parts Contest) hanno anche i sotto-tab Daily Missions/Challenges
  con "Claim" VERDI; altri (es. Customization) hanno SOLO la traccia + COLLECT
  ALL.

REGOLA DI SICUREZZA (vincolante, soldi veri): si tappa SOLO il gratis:
  - Sotto-tab: pulsanti VERDI ("Claim"). Ambra "Keep Claiming"/"Go" = skip.
    Discriminante COLORE (verde hue 35-90 vs ambra hue 10-35).
  - Traccia: "COLLECT ALL" è AMBRA come "Keep Claiming" → il colore NON li
    distingue. Discriminazione sul TESTO (template pin_collect_all, 1.000 vs
    0.371). Mai "Keep Claiming"/€ (a pagamento).

GATE PALLINO ROSSO (richiesta utente 21/07): prima di processare, si verifica
il badge rosso sulla voce sidebar del menù. Nessun pallino → nessuna ricompensa
→ skip (evita navigazione sterile). Badge sempre sul bordo destro della sidebar
(~x118-162) alla riga del menù (offset Y dal match).

POSIZIONI: la barra eventi HOME e la sidebar hanno posizione VARIABILE (eventi
attivi + scroll) → navigazione via template (pin_special_promo, pin_menu) +
scroll. La struttura INTERNA (selezionato il menù) è FISSA → coord fisse.
Special Promo va tappato sull'ICONA (match.cy - promo_tap_dy), non la label.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from core.task import Task, TaskContext, TaskResult


def _frame(screen) -> np.ndarray | None:
    if screen is None:
        return None
    f = getattr(screen, "frame", None)
    if f is not None:
        return f
    if isinstance(screen, np.ndarray):
        return screen
    return None


@dataclass
class SpecialPromoContestConfig:
    # --- Identità del contest (impostata dalla sottoclasse) ---
    pin_menu:   str = ""             # template voce sidebar (es. pin/pin_parts_contest.png)
    menu_nome:  str = "Contest"      # nome per i log
    has_subtabs: bool = False        # True: claima verdi nei sotto-tab Daily/Challenges

    # --- Apertura Special Promo (barra eventi HOME, posizione variabile) ---
    pin_special_promo: str = "pin/pin_special_promo.png"
    soglia_promo:      float = 0.80
    zona_barra_eventi: tuple[int, int, int, int] = (330, 38, 940, 100)
    tap_promo_fallback: tuple[int, int] = (686, 52)
    promo_tap_dy: int = 15   # tap sull'icona (non la label, altrimenti non apre)

    # --- Selezione voce sidebar (posizione variabile) ---
    soglia_sidebar:    float = 0.80
    zona_sidebar:      tuple[int, int, int, int] = (0, 40, 155, 540)
    sidebar_scroll:    tuple[int, int, int, int] = (75, 450, 75, 200)
    sidebar_scroll_dur_ms: int = 600
    max_sidebar_scroll: int = 5

    # --- Gate pallino rosso (badge sul bordo destro della sidebar) ---
    badge_roi_x:  tuple[int, int] = (118, 162)   # colonna badge
    badge_roi_dy: tuple[int, int] = (-30, 4)     # offset Y dal centro match
    badge_red_min_frac: float = 0.03             # >3% pixel rossi → pallino presente
    badge_red_s_min: int = 120
    badge_red_v_min: int = 90

    # --- Struttura interna FISSA ---
    tap_subtab_track:      tuple[int, int] = (290, 154)
    tap_subtab_daily:      tuple[int, int] = (549, 154)
    tap_subtab_challenges: tuple[int, int] = (808, 154)

    col_pulsanti:  tuple[int, int, int, int] = (767, 195, 921, 478)
    lista_scroll:  tuple[int, int, int, int] = (480, 430, 480, 250)
    lista_scroll_dur_ms: int = 400
    max_claim_loop:   int = 25
    max_scroll_vuoti: int = 2

    # Pulsante traccia (COLLECT ALL / Keep Claiming) — posizione FISSA
    pin_collect_all:    str = "pin/pin_collect_all.png"
    soglia_collect_all: float = 0.80
    roi_bottone_traccia: tuple[int, int, int, int] = (458, 486, 693, 520)
    tap_collect_all:     tuple[int, int] = (575, 503)
    max_collect_loop:    int = 8

    # Chiusura popup ricompensa
    tap_chiudi_popup: tuple[int, int] = (480, 400)

    # --- Discriminante colore (sotto-tab verdi) ---
    hue_ambra: tuple[int, int] = (10, 35)
    hue_verde: tuple[int, int] = (35, 90)
    s_min: int = 80
    v_min: int = 80
    verde_min_frac: float = 0.20
    ambra_max_frac: float = 0.15
    riga_verde_frac: float = 0.28
    riga_ambra_frac: float = 0.15
    banda_min_h:     int = 12

    # --- Timing ---
    wait_apri_promo:  float = 3.0
    wait_sidebar:     float = 2.0
    wait_subtab:      float = 2.0
    wait_post_claim:  float = 3.0
    wait_post_close:  float = 1.5
    wait_scroll:      float = 1.5
    wait_back:        float = 2.0


class _SpecialPromoContestBase(Task):
    """Base astratta: sottoclassi definiscono name() e la config (pin_menu,
    menu_nome, has_subtabs). Tappa SOLO gratis (verdi + COLLECT ALL testo)."""

    def __init__(self, config: SpecialPromoContestConfig) -> None:
        self._cfg = config

    def name(self) -> str:  # pragma: no cover - override
        raise NotImplementedError

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato(self.name()):
                return False
        return True

    # ------------------------------------------------------------------
    # Colore (sotto-tab verdi)
    # ------------------------------------------------------------------

    def _bande_verdi(self, frame) -> list[tuple[int, int]]:
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
    # Gate pallino rosso
    # ------------------------------------------------------------------

    def _ha_badge_rosso(self, frame, menu_cy: int, log) -> bool:
        """True se la voce sidebar del menù (centro Y = menu_cy) ha il pallino
        rosso. Fail-safe: True in caso di errore (meglio processare che saltare
        ricompense). ROI: colonna badge (bordo destro sidebar) alla riga menù."""
        cfg = self._cfg
        try:
            x0, x1 = cfg.badge_roi_x
            y0 = max(0, menu_cy + cfg.badge_roi_dy[0])
            y1 = menu_cy + cfg.badge_roi_dy[1]
            roi = frame[y0:y1, x0:x1]
            if roi.size == 0:
                return True
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            h = hsv[..., 0]; s = hsv[..., 1]; v = hsv[..., 2]
            red = ((h <= 8) | (h >= 172)) & (s > cfg.badge_red_s_min) & (v > cfg.badge_red_v_min)
            frac = float(red.mean())
            presente = frac > cfg.badge_red_min_frac
            log(f"[{self.name().upper()}] gate pallino rosso: red%={frac*100:.1f} "
                f"→ {'RICOMPENSE' if presente else 'nessuna'}")
            return presente
        except Exception as exc:
            log(f"[{self.name().upper()}] gate pallino errore (fail-safe True): {exc}")
            return True

    # ------------------------------------------------------------------
    # Navigazione
    # ------------------------------------------------------------------

    def _apri_special_promo(self, ctx, cfg, log) -> bool:
        """Apre il pannello Special Promo dalla barra eventi HOME e VERIFICA
        l'apertura: a pannello aperto l'icona sparisce dalla barra (schermata
        coperta). Il tap singolo talvolta non apre → retry. Ritorna True se
        aperto entro i tentativi."""
        def _trova_icona():
            return ctx.matcher.find_one(ctx.device.screenshot(), cfg.pin_special_promo,
                                        threshold=cfg.soglia_promo, zone=cfg.zona_barra_eventi)

        for att in range(3):
            m = _trova_icona()
            if not m.found:
                # icona non in barra: o pannello già aperto (schermata coperta),
                # o transiente (banner/popup su HOME copre la barra un istante).
                # Ri-controlla un paio di volte prima di concludere "già aperto"
                # (evita di procedere a vuoto restando in HOME).
                transiente = False
                for _ in range(2):
                    time.sleep(1.0)
                    m = _trova_icona()
                    if m.found:
                        transiente = True
                        break
                if not transiente:
                    log(f"[{self.name().upper()}] icona non in barra (score={m.score:.3f}) "
                        f"→ pannello già aperto, procedo")
                    return True
                # era un transiente: ora l'icona c'è → prosegui a tapparla
            ty = m.cy - cfg.promo_tap_dy
            log(f"[{self.name().upper()}] Special Promo @({m.cx},{m.cy}) "
                f"score={m.score:.3f} → tap icona ({m.cx},{ty})")
            ctx.device.tap(m.cx, ty)
            time.sleep(cfg.wait_apri_promo)
            # verifica apertura: l'icona non deve più essere nella barra eventi
            if not _trova_icona().found:
                return True
            log(f"[{self.name().upper()}] pannello non aperto (icona ancora in barra) "
                f"→ retry {att+1}/3")
        log(f"[{self.name().upper()}] apertura Special Promo non confermata dopo 3 tentativi")
        return False

    def _trova_menu(self, ctx, cfg, log):
        """Trova la voce del menù nella sidebar (posizione variabile) con scroll.
        Ritorna (match, frame) se trovata (NON ancora selezionata), (None, None)
        se assente dopo max scroll."""
        for tentativo in range(cfg.max_sidebar_scroll + 1):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_menu,
                                     threshold=cfg.soglia_sidebar, zone=cfg.zona_sidebar)
            if m.found:
                log(f"[{self.name().upper()}] voce {cfg.menu_nome} @({m.cx},{m.cy}) "
                    f"score={m.score:.3f}")
                return m, _frame(shot)
            if tentativo < cfg.max_sidebar_scroll:
                log(f"[{self.name().upper()}] {cfg.menu_nome} non visibile "
                    f"(score={m.score:.3f}) → scroll {tentativo+1}/{cfg.max_sidebar_scroll}")
                x0, y0, x1, y1 = cfg.sidebar_scroll
                ctx.device.swipe(x0, y0, x1, y1, cfg.sidebar_scroll_dur_ms)
                time.sleep(cfg.wait_scroll)
        return None, None

    def _seleziona_menu(self, ctx, cfg, log, match) -> bool:
        """Tappa la voce menù e VERIFICA il cambio vista: quando il menù è
        selezionato il suo template (calibrato da non-selezionato) scende sotto
        soglia (sfondo highlight). Se resta sopra soglia il tap non ha
        commutato (osservato: un singolo tap talvolta non registra) → ritap.
        Ritorna True se confermato selezionato entro i tentativi."""
        for att in range(3):
            ctx.device.tap(match.cx, match.cy)
            time.sleep(cfg.wait_sidebar)
            shot = ctx.device.screenshot()
            m2 = ctx.matcher.find_one(shot, cfg.pin_menu,
                                      threshold=cfg.soglia_sidebar, zone=cfg.zona_sidebar)
            if not m2.found:   # selezionato (score sceso) → commutato
                log(f"[{self.name().upper()}] {cfg.menu_nome} selezionato "
                    f"(verifica score={m2.score:.3f})")
                return True
            log(f"[{self.name().upper()}] switch non confermato (score={m2.score:.3f}) "
                f"→ ritap {att+1}/3")
        log(f"[{self.name().upper()}] switch non confermato dopo 3 tap → procedo comunque")
        return False

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    def _claim_subtab(self, ctx, cfg, log, tap_subtab, nome) -> int:
        log(f"[{self.name().upper()}] sotto-tab {nome} → apro")
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
                log(f"[{self.name().upper()}] {nome}: Claim VERDE #{n+1} → tap ({cx},{cy})")
                ctx.device.tap(cx, cy)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)
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
        log(f"[{self.name().upper()}] {nome}: {n} claim verdi")
        return n

    def _collect_all_traccia(self, ctx, cfg, log) -> int:
        """Sulla traccia: se il bottone (posizione FISSA) porta il testo
        "COLLECT ALL" (match template) lo tappa e chiude il popup, in loop
        finché resta COLLECT ALL. "Keep Claiming" (nessun match) = a pagamento
        → skip. Per i contest con sotto-tab prima si va sul sotto-tab traccia."""
        if cfg.has_subtabs:   # NB: cfg passato (nel task globale i contest differiscono)
            log(f"[{self.name().upper()}] traccia → apro sotto-tab traccia")
            ctx.device.tap(*cfg.tap_subtab_track)
            time.sleep(cfg.wait_subtab)
        n = 0
        for _ in range(cfg.max_collect_loop):
            shot = ctx.device.screenshot()
            m = ctx.matcher.find_one(shot, cfg.pin_collect_all,
                                     threshold=cfg.soglia_collect_all,
                                     zone=cfg.roi_bottone_traccia)
            if m.found:
                log(f"[{self.name().upper()}] COLLECT ALL presente (score={m.score:.3f}) "
                    f"→ tap posizione fissa {cfg.tap_collect_all}")
                ctx.device.tap(*cfg.tap_collect_all)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)
                time.sleep(cfg.wait_post_close)
                n += 1
                continue
            log(f"[{self.name().upper()}] COLLECT ALL non presente (score={m.score:.3f}) "
                f"→ 'Keep Claiming'/nulla di gratis → skip")
            break
        log(f"[{self.name().upper()}] COLLECT ALL: {n}")
        return n

    def _esci(self, ctx, cfg) -> None:
        ctx.device.tap(30, 30)
        time.sleep(cfg.wait_back)
        if ctx.navigator is not None:
            ctx.navigator.vai_in_home()

    # ------------------------------------------------------------------
    # Processa UN menù contest (pannello GIÀ APERTO — non apre né chiude)
    # ------------------------------------------------------------------

    def _processa_menu(self, ctx, cfg, log, debug, prefix: str = "") -> dict:
        """Trova la voce (scroll sidebar) → gate pallino → seleziona → claim
        (sotto-tab se has_subtabs) → COLLECT ALL, per il contest `cfg`. Assume
        il pannello Special Promo GIÀ APERTO; NON apre né chiude. Usato sia dai
        task singoli (via run()) sia dal task globale SpecialPromoTask che lo
        chiama in loop su più contest tra un unico apri e chiudi.
        Ritorna dict con menu/esito/conteggi."""
        match, frame = self._trova_menu(ctx, cfg, log)
        if match is None:
            log(f"[{self.name().upper()}] voce {cfg.menu_nome} non trovata → skip")
            return {"menu": cfg.menu_nome, "esito": "assente"}
        if not self._ha_badge_rosso(frame, match.cy, log):
            log(f"[{self.name().upper()}] {cfg.menu_nome}: nessun pallino → skip")
            return {"menu": cfg.menu_nome, "esito": "no_pallino"}

        self._seleziona_menu(ctx, cfg, log, match)
        debug.snap(f"{prefix}menu", ctx.device.screenshot())

        n_daily = n_chal = 0
        if cfg.has_subtabs:
            n_daily = self._claim_subtab(ctx, cfg, log, cfg.tap_subtab_daily, "Daily Missions")
            n_chal = self._claim_subtab(ctx, cfg, log, cfg.tap_subtab_challenges, "Challenges")
        n_collect = self._collect_all_traccia(ctx, cfg, log)
        debug.snap(f"{prefix}collect", ctx.device.screenshot())
        log(f"[{self.name().upper()}] {cfg.menu_nome} — claim={n_daily+n_chal} collect={n_collect}")
        return {"menu": cfg.menu_nome, "esito": "ok",
                "daily": n_daily, "challenges": n_chal, "collect": n_collect}

    # ------------------------------------------------------------------
    # run (task singolo: apri + processa il proprio menù + chiudi)
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task(self.name(), getattr(ctx, "instance_name", "_unknown"))
        try:
            self._apri_special_promo(ctx, cfg, log)
            debug.snap("01_special_promo", ctx.device.screenshot())
            res = self._processa_menu(ctx, cfg, log, debug, prefix="02_")
            self._esci(ctx, cfg)
            if res["esito"] != "ok":
                debug.flush(success=True, force=(res["esito"] == "assente"), log_fn=log)
                return TaskResult.skip(f"{cfg.menu_nome}: {res['esito']}")
            tot = res["daily"] + res["challenges"] + res["collect"]
            debug.flush(success=True, force=(tot == 0), log_fn=log)
            return TaskResult.ok(f"{cfg.menu_nome} — claim verdi={res['daily']+res['challenges']} "
                                 f"collect_all={res['collect']}",
                                 daily=res["daily"], challenges=res["challenges"],
                                 collect_all=res["collect"])
        except Exception as exc:
            log(f"[{self.name().upper()}] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")


# ==========================================================================
# Task GLOBALE: processa tutti i contest COLLECT-ALL in un'unica sessione
# ==========================================================================

class SpecialPromoTask(_SpecialPromoContestBase):
    """Task globale (21/07): apre Special Promo UNA sola volta e processa in
    sequenza i contest COLLECT-ALL (parts, customization, vehicle, chip) SENZA
    uscire e rientrare dal pannello — 1 apri/chiudi invece di 4. mega_armament
    resta un task separato (deve precedere radar_master). Solo master.

    I contest sono in ordine top→bottom nella sidebar e `_trova_menu` scrolla
    verso il basso, quindi l'ordine della lista rispetta la sidebar (nessuna
    navigazione all'indietro). Ogni contest è gate-skippato se senza pallino."""

    _CONTESTS = [
        SpecialPromoContestConfig(pin_menu="pin/pin_parts_contest.png",
                                  menu_nome="Parts Contest", has_subtabs=True),
        SpecialPromoContestConfig(pin_menu="pin/pin_customization_contest.png",
                                  menu_nome="Customization Contest", has_subtabs=False),
        SpecialPromoContestConfig(pin_menu="pin/pin_vehicle_redesign.png",
                                  menu_nome="Vehicle Redesign", has_subtabs=False),
        SpecialPromoContestConfig(pin_menu="pin/pin_chip_challenge.png",
                                  menu_nome="Chip Challenge", has_subtabs=False),
    ]

    def __init__(self, config: SpecialPromoContestConfig | None = None) -> None:
        super().__init__(config or SpecialPromoContestConfig(menu_nome="Special Promo"))

    def name(self) -> str:
        return "special_promo"

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg, log = self._cfg, ctx.log_msg
        if ctx.navigator is not None and not ctx.navigator.vai_in_home():
            return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("special_promo", getattr(ctx, "instance_name", "_unknown"))
        try:
            self._apri_special_promo(ctx, cfg, log)
            debug.snap("01_special_promo", ctx.device.screenshot())

            risultati = []
            for i, contest in enumerate(self._CONTESTS):
                prefix = f"{i+2:02d}_{contest.menu_nome.split()[0].lower()}_"
                res = self._processa_menu(ctx, contest, log, debug, prefix=prefix)
                risultati.append(res)

            self._esci(ctx, cfg)
            ok = [r for r in risultati if r["esito"] == "ok"]
            tot_collect = sum(r.get("collect", 0) for r in ok)
            tot_claim = sum(r.get("daily", 0) + r.get("challenges", 0) for r in ok)
            dettaglio = ", ".join(f"{r['menu']}={r['esito']}" for r in risultati)
            log(f"[SPECIAL_PROMO] completato — {len(ok)}/{len(risultati)} processati, "
                f"claim={tot_claim} collect={tot_collect} | {dettaglio}")
            debug.flush(success=True, force=(tot_claim + tot_collect == 0), log_fn=log)
            return TaskResult.ok(f"Special Promo — {len(ok)}/{len(risultati)} contest, "
                                 f"claim={tot_claim} collect={tot_collect}",
                                 contest_ok=len(ok), claim=tot_claim, collect_all=tot_collect)
        except Exception as exc:
            log(f"[SPECIAL_PROMO] eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="run")
