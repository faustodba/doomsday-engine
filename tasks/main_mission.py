"""
tasks/main_mission.py — MainMissionTask V6
==========================================
Recupera ricompense Main Mission + Daily Mission dal pannello mission.

Flusso (validato live FAU_02 01/05):
  HOME -> tap apri pannello (33, 398)
  -> Tab Main Mission (50, 100)  [sx alto]
  -> Loop CLAIM Main: find_one in ROI (790,265,880,305) finché trovato.
     Tap fisso (832, 284) — la lista auto-scrolla dopo ogni claim.
  -> Tab Daily Mission (50, 185)  [sx basso]
  -> Loop CLAIM Daily: find_one in ROI ampia (810,210,895,460), tap dinamico
     sul match (cx, cy). Niente auto-scroll garantito.
     IMPORTANTE: completare missioni daily aggiunge punti AP.
  -> OCR Current AP DOPO i claim daily (ROI 180,130,240,175, upscale 3x
     + threshold>200 + PSM7). AP puó essere aumentato dai claim del passo precedente.
  -> Per ogni chest milestone <= AP: tap chest coord, chiusura popup
  -> BACK x1

Coord chest: 20=(397,160), 40=(517,160), 60=(633,160), 80=(751,160), 100=(873,160)

Pattern visivo chest:
  - chest "raggiunta + non claimata" -> CLAIM disponibile (tap effettivo)
  - chest "raggiunta + giá claimata" -> alone dorato (tap = no-op silente)
  - chest "non raggiunta" -> dim/scuro (tap = popup "non disponibile",
    chiuso dal tap_chiudi_popup successivo)

Chiusura popup reward: tap (480, 80) zona alta vuota.
  Pre-fix WU88: era (480, 270) centro pannello -> se popup non c'era cliccava
  una missione random e chiudeva il pannello, perdendo OCR AP successivo.

Scheduling: periodic 12h interval (registrato in task_setup.json).
Priority: 22 (dopo donazione=20, prima zaino=25).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from core.task import Task as BaseTask, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MainMissionConfig:
    # --- Apertura pannello ---
    tap_apri_pannello: tuple[int, int] = (33, 398)

    # --- Tab (validate live FAU_00/02 01/05 + FAU_08 3-tab variant) ---
    # Lato sinistro pannello: tab verticali, layout dinamico:
    #   2-tab (default): Main Missions (alto), Daily Missions (sotto)
    #   3-tab (Chapter unlocked): Chapter Missions, Main Missions, Daily Missions
    # Default all'apertura: Daily Missions attivo.
    # Detection runtime via OCR testo "Chapter" in ROI tab top.
    tap_tab_main_2t:    tuple[int, int] = (50, 100)
    tap_tab_daily_2t:   tuple[int, int] = (50, 185)
    tap_tab_chapter_3t: tuple[int, int] = (50, 105)
    tap_tab_main_3t:    tuple[int, int] = (50, 185)
    tap_tab_daily_3t:   tuple[int, int] = (50, 265)
    # ROI OCR per detection Chapter tab (zona top-sx tab list)
    ocr_chapter_roi:    tuple[int, int, int, int] = (10, 75, 110, 135)
    # CLAIM Chapter — pulsante singolo in basso-destra (verde se 7/7, grigio else)
    # Tap cieco safe: grigio = no-op silente.
    tap_claim_chapter:  tuple[int, int] = (850, 455)

    # --- CLAIM template (Main + Daily — stesso pulsante UI verde) ---
    pin_claim:      str = "pin/pin_btn_claim_mission.png"
    soglia_claim:   float = 0.80
    max_claim_loop: int = 30

    # --- Main Mission CLAIM ROI (lista verticale missioni) ---
    # Tap dinamico sul match (validato FAU_08 01/05: niente auto-scroll garantito).
    roi_claim_main: tuple[int, int, int, int] = (790, 100, 890, 470)

    # --- Daily Mission CLAIM ROI (lista verticale missioni) ---
    # Tap dinamico sul match (no auto-scroll garantito).
    roi_claim_daily: tuple[int, int, int, int] = (810, 210, 895, 460)

    # --- Chest milestone ---
    chest_coords: tuple = (
        (20,  (397, 160)),
        (40,  (517, 160)),
        (60,  (633, 160)),
        (80,  (751, 160)),
        (100, (873, 160)),
    )

    # --- OCR Current AP ---
    ocr_ap_roi: tuple[int, int, int, int] = (180, 130, 240, 175)

    # --- Chiusura popup reward ---
    # WU88 — (480, 80) zona alta vuota popup invece di (480, 270) centro.
    # Pre-fix: (480, 270) cliccava una missione random se popup non c'era,
    # chiudendo il pannello e perdendo OCR AP successivo.
    tap_chiudi_popup: tuple[int, int] = (480, 80)

    # --- Delay (PC lento — valori conservativi) ---
    wait_apri_pannello: float = 3.0
    wait_tab_switch:    float = 2.5
    wait_post_tap:      float = 2.0
    wait_post_claim:    float = 3.0  # popup reward animation
    wait_back:          float = 2.0


# ---------------------------------------------------------------------------
# OCR Current AP
# ---------------------------------------------------------------------------

def _detect_chapter_tab(screen, roi: tuple[int, int, int, int]) -> bool:
    """True se la tab Chapter Missions è visibile (3-tab layout).

    OCR testo zona tab top-sx: cerca substring "chapter" / "chap" / "cha".
    Su istanze 2-tab quella zona contiene "Main Missions" (no match).
    Best-effort: in caso di errore ritorna False (assume 2-tab default).
    """
    try:
        from shared.ocr_helpers import _run_tesseract  # type: ignore
        frame = getattr(screen, "frame", None)
        if frame is None:
            return False
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        h, w = crop.shape[:2]
        up = cv2.resize(crop, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        # Testo bianco su sfondo scuro - threshold inverso
        _, binv = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        cfg = "--psm 6"
        txt = _run_tesseract(binv, cfg).lower()
        # Match permissivo (font rendering può saltare lettere)
        return any(s in txt for s in ("chapter", "chap", "cha"))
    except Exception:
        return False


_AP_MAX_PLAUSIBILE = 100  # cap reale AP giornaliero (milestone top=100)


def _leggi_current_ap(screen, roi: tuple[int, int, int, int]) -> int:
    """Legge il valore Current AP dal pannello Daily Mission.

    Cascade preprocessing (validato live):
      1. PSM 8 raw upscale 3x      (legge bene '75' su FAU_09)
      2. PSM 7 binv threshold>200  (legge bene '55' su FAU_01)
      3. PSM 7 raw fallback
      4. PSM 8 binv fallback

    Sanity: valori > 100 considerati misread OCR (cap realistico AP=100).
    Pattern misread: bordo esagono contenitore numero -> '4' parassita
    es. '75' letto come '475' (FAU_09 01/05). Cascade raw evita preprocessing
    che amplifica il bordo.

    Returns int (-1 se tutti i pass falliscono o valore implausibile).
    """
    try:
        from shared.ocr_helpers import _run_tesseract  # type: ignore
        frame = getattr(screen, "frame", None)
        if frame is None:
            return -1
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        h, w = crop.shape[:2]
        up_rgb = cv2.resize(crop, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(up_rgb, cv2.COLOR_BGR2GRAY)
        _, binv = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        cfg7 = "--psm 7 -c tessedit_char_whitelist=0123456789"
        cfg8 = "--psm 8 -c tessedit_char_whitelist=0123456789"

        # Cascade 4 pass — return primo valore plausibile (0..100)
        for img_in, cfg in [
            (up_rgb, cfg8),  # 1. raw + PSM8 (FAU_09 '75')
            (binv,   cfg7),  # 2. binv + PSM7 (FAU_01 '55')
            (up_rgb, cfg7),  # 3. raw + PSM7
            (binv,   cfg8),  # 4. binv + PSM8 fallback
        ]:
            txt = _run_tesseract(img_in, cfg)
            if txt and txt.isdigit():
                val = int(txt)
                if 0 <= val <= _AP_MAX_PLAUSIBILE:
                    return val
        return -1
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class MainMissionTask(BaseTask):
    """
    Recupera ricompense Main Mission + Daily Mission.

    Scheduling: periodic 12h interval (registrato in task_setup.json).
    Priority: 22 (dopo donazione=20, prima zaino=25).

    Output data:
      - main_claim:  numero CLAIM Main Mission tappati
      - daily_claim: numero CLAIM Daily Mission tappati
      - chest_claim: numero chest milestone tappati (incl. eventuali già claimati)
    """

    def __init__(self) -> None:
        self.cfg = MainMissionConfig()

    # ------------------------------------------------------------------
    # V6 Task ABC
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "main_mission"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("main_mission")
        return True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg = self.cfg
        log = ctx.log_msg

        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("main_mission"):
                log("[MAIN_MISSION] disabilitato — skip")
                return TaskResult(success=True, skipped=True)

        log("[MAIN_MISSION] avvio")

        try:
            # Step 0: assicura HOME
            if ctx.navigator is not None:
                if not ctx.navigator.vai_in_home():
                    return TaskResult.fail("Navigator non ha raggiunto HOME",
                                           step="vai_in_home")

            # Step 1: apri pannello mission
            ctx.device.tap(*cfg.tap_apri_pannello)
            time.sleep(cfg.wait_apri_pannello)

            # Step 2: detect layout 2-tab vs 3-tab via OCR top tab.
            # Default all'apertura: Daily attivo (tab in fondo). Se Chapter
            # esiste è in cima; OCR testo per distinguere.
            screen_init = ctx.device.screenshot()
            has_chapter = _detect_chapter_tab(screen_init, cfg.ocr_chapter_roi) if screen_init else False
            if has_chapter:
                tap_main  = cfg.tap_tab_main_3t
                tap_daily = cfg.tap_tab_daily_3t
                log(f"[MAIN_MISSION] layout 3-tab (Chapter+Main+Daily)")
            else:
                tap_main  = cfg.tap_tab_main_2t
                tap_daily = cfg.tap_tab_daily_2t
                log(f"[MAIN_MISSION] layout 2-tab (Main+Daily)")

            # Step 2b: tab Chapter Missions (se presente) - tap CLAIM cieco
            n_chapter = 0
            if has_chapter:
                ctx.device.tap(*cfg.tap_tab_chapter_3t)
                time.sleep(cfg.wait_tab_switch)
                # Tap cieco CLAIM Chapter (grigio = no-op safe, verde = claim batch)
                log(f"[MAIN_MISSION] Chapter: tap CLAIM {cfg.tap_claim_chapter}")
                ctx.device.tap(*cfg.tap_claim_chapter)
                time.sleep(cfg.wait_post_claim)
                ctx.device.tap(*cfg.tap_chiudi_popup)
                time.sleep(cfg.wait_post_tap)
                n_chapter = 1  # tap eseguito (potrebbe essere stato no-op)

            # Step 3: tab Main Mission
            ctx.device.tap(*tap_main)
            time.sleep(cfg.wait_tab_switch)

            # Step 4: loop CLAIM Main Mission (tap fisso, lista auto-scrolla)
            n_main = self._loop_claim_main(ctx)
            log(f"[MAIN_MISSION] Main: {n_main} claim")

            # Step 5: tab Daily Mission
            ctx.device.tap(*tap_daily)
            time.sleep(cfg.wait_tab_switch)

            # Step 6: loop CLAIM Daily (tap dinamico — completare missioni dà AP).
            # AP letto DOPO i claim: completare le missioni daily aggiunge punti AP,
            # quindi i chest milestone vanno valutati con AP aggiornato.
            n_daily = self._loop_claim_daily(ctx)
            log(f"[MAIN_MISSION] Daily: {n_daily} claim")

            # Step 7: OCR Current AP DOPO i claim daily (AP aggiornato)
            screen_post = ctx.device.screenshot()
            ap = _leggi_current_ap(screen_post, cfg.ocr_ap_roi) if screen_post else -1
            log(f"[MAIN_MISSION] Current AP (post-claim)={ap}")

            # Step 8: claim chest milestone con AP aggiornato
            n_chest = self._claim_chest_milestone_with_ap(ctx, ap)
            log(f"[MAIN_MISSION] Daily chest: {n_chest} tap")

            # Step 7: chiusura pannello
            ctx.device.key("KEYCODE_BACK")
            time.sleep(cfg.wait_back)

            log(f"[MAIN_MISSION] completato — chapter={n_chapter} main={n_main} "
                f"daily={n_daily} chest={n_chest}")
            return TaskResult.ok(
                f"Main Mission completata — chapter={n_chapter} main={n_main} "
                f"daily={n_daily} chest={n_chest}",
                chapter_claim=n_chapter, main_claim=n_main,
                daily_claim=n_daily, chest_claim=n_chest,
            )

        except Exception as exc:
            log(f"[MAIN_MISSION] eccezione: {exc}")
            return TaskResult.fail(f"Eccezione: {exc}", step="run")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _loop_claim_main(self, ctx: TaskContext) -> int:
        """Loop CLAIM Main Mission - tap dinamico su match template.

        WU88-bis fix: alcune missioni hanno il pulsante CLAIM in posizione
        non standard (es. su FAU_08 'Warfare: Upgrade Battle Center' a y=165
        invece di y=284). Tap dinamico al match center robusto.
        """
        cfg = self.cfg
        n = 0
        for i in range(cfg.max_claim_loop):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MAIN_MISSION] screenshot None — break")
                break
            r = ctx.matcher.find_one(
                screen, cfg.pin_claim,
                threshold=cfg.soglia_claim,
                zone=cfg.roi_claim_main,
            )
            if not r.found:
                ctx.log_msg(
                    f"[MAIN_MISSION] no claim Main (score={r.score:.3f}) "
                    f"— stop a {n}/{cfg.max_claim_loop}"
                )
                break
            ctx.log_msg(
                f"[MAIN_MISSION] claim Main {n+1} -> tap ({r.cx},{r.cy}) "
                f"score={r.score:.3f}"
            )
            ctx.device.tap(r.cx, r.cy)
            time.sleep(cfg.wait_post_claim)
            ctx.device.tap(*cfg.tap_chiudi_popup)
            time.sleep(cfg.wait_post_tap)
            n += 1
        return n

    def _loop_claim_daily(self, ctx: TaskContext) -> int:
        """Loop tap CLAIM Daily Mission — tap dinamico su match (no auto-scroll).

        Cerca CLAIM verde in ROI lista verticale Daily, tappa al centro del match
        finché trovato. Differisce da Main per:
          - tap dinamico (cx, cy) del match invece di coord fissa
          - ROI ampia (810, 210, 895, 460) lista missioni Daily
        """
        cfg = self.cfg
        n = 0
        for i in range(cfg.max_claim_loop):
            screen = ctx.device.screenshot()
            if screen is None:
                ctx.log_msg("[MAIN_MISSION] screenshot None — break")
                break
            r = ctx.matcher.find_one(
                screen, cfg.pin_claim,
                threshold=cfg.soglia_claim,
                zone=cfg.roi_claim_daily,
            )
            if not r.found:
                ctx.log_msg(
                    f"[MAIN_MISSION] no claim Daily (score={r.score:.3f}) "
                    f"— stop a {n}/{cfg.max_claim_loop}"
                )
                break
            ctx.log_msg(
                f"[MAIN_MISSION] claim Daily {n+1} -> tap ({r.cx},{r.cy}) "
                f"score={r.score:.3f}"
            )
            ctx.device.tap(r.cx, r.cy)
            time.sleep(cfg.wait_post_claim)
            ctx.device.tap(*cfg.tap_chiudi_popup)
            time.sleep(cfg.wait_post_tap)
            n += 1
        return n

    def _claim_chest_milestone_with_ap(self, ctx: TaskContext, ap: int) -> int:
        """Tap chest milestone con AP >= soglia. AP letto a monte dal caller."""
        cfg = self.cfg
        if ap < 0:
            ctx.log_msg("[MAIN_MISSION] AP non letto — skip chest")
            return 0
        n = 0
        for milestone, coord in cfg.chest_coords:
            if ap >= milestone:
                ctx.log_msg(
                    f"[MAIN_MISSION] chest {milestone} (AP={ap}) -> tap {coord}"
                )
                ctx.device.tap(*coord)
                time.sleep(cfg.wait_post_claim)
                # Chiudi popup reward (no-op se chest già claimata)
                ctx.device.tap(*cfg.tap_chiudi_popup)
                time.sleep(cfg.wait_post_tap)
                n += 1
            else:
                ctx.log_msg(
                    f"[MAIN_MISSION] chest {milestone} non raggiunta "
                    f"(AP={ap} < {milestone}) — skip resto"
                )
                break  # i seguenti hanno milestone più alta, skip diretto
        return n
