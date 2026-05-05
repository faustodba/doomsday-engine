# ==============================================================================
# DOOMSDAY ENGINE V6 — tasks/radar_census.py                        Step 18
#
# Radar Census (TRAINING) — traduzione V5 → V6.
#
# Scheduling : periodic, intervallo=24h (chiamato anche da RadarTask)
#
# Flusso:
#   1. Carica detector (radar_tool.detector) e classifier RF (opzionale)
#   2. Screenshot dalla schermata radar già aperta (ctx.device)
#   3. Detect icone → estrai crops → classifica RF → cataloga
#   4. Salva map_full.png, map_annotated.png, crops/, census.json
#      in radar_archive/census/YYYYMMDD_HHMMSS_{istanza}/
#
# Dipendenze:
#   radar_tool/ — deve essere in C:\doomsday-engine\radar_tool\
#     templates/   (template .png)
#     dataset/classifier.pkl  (RF opzionale)
#     detector.py, classifier.py
#
# Path output:
#   C:\doomsday-engine\radar_archive\census\YYYYMMDD_HHMMSS_{istanza}\
#
# FIX 14/04/2026 — traduzione V5 → V6:
#   - Rimossi import adb, config V5
#   - Screenshot da ctx.device.screenshot() + screen.frame (numpy BGR)
#   - Logging via ctx.log_msg() invece di logger(nome, msg)
#   - ROOT risolto da __file__ (C:\doomsday-engine\)
#   - Implementata classe RadarCensusTask con API V6 standard
# ==============================================================================

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from core.task import Task, TaskContext, TaskResult


# ──────────────────────────────────────────────────────────────────────────────
# Path
# ──────────────────────────────────────────────────────────────────────────────

# ROOT = C:\doomsday-engine\
_ROOT = Path(__file__).resolve().parent.parent

RADAR_TOOL_DIR = _ROOT / "radar_tool"
TEMPLATES_DIR  = RADAR_TOOL_DIR / "templates"
RF_MODEL_PATH  = RADAR_TOOL_DIR / "dataset" / "classifier.pkl"
ARCHIVE_ROOT   = _ROOT / "radar_archive" / "census"


# ──────────────────────────────────────────────────────────────────────────────
# Label ufficiali (allineate a radar_tool/labeler.py)
# ──────────────────────────────────────────────────────────────────────────────

OFFICIAL_LABELS = {
    "pedone", "auto", "camion", "skull",
    "avatar", "numero", "card", "paracadute",
    "fiamma", "bottiglia", "soldati", "sconosciuto",
}

ACTION_LABELS = {
    "pedone", "auto", "camion", "skull",
    "avatar", "numero", "card", "paracadute",
    "fiamma", "bottiglia", "soldati",
}


# ──────────────────────────────────────────────────────────────────────────────
# Soglie
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLD_TMPL = 0.65
TMPL_READY_MIN = 0.80
TMPL_WARN_MIN  = 0.70
RF_READY_MIN   = 0.70
RF_WARN_MIN    = 0.60
ANNOTATE_BOX   = 64

# Colori per categoria — BGR (cv2)
LABEL_COLORS = {
    "pedone":      (243, 150,  33),
    "auto":        (  0, 152, 255),
    "camion":      ( 72,  85, 121),
    "skull":       ( 54,  67, 244),
    "avatar":      (  7, 193, 255),
    "numero":      (158, 158, 158),
    "card":        ( 59, 235, 255),
    "paracadute":  ( 80, 175,  76),
    "fiamma":      ( 34,  87, 255),
    "bottiglia":   (244, 169,   3),
    "soldati":     (176,  39, 156),
    "sconosciuto": (120, 120, 120),
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_token(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^0-9A-Za-z_\-]+", "", s)
    return s or "x"


def _semaforo(conf) -> tuple:
    """Colore semaforo BGR per cv2."""
    if conf is None:
        return (120, 120, 120)
    try:
        c = float(conf)
    except Exception:
        return (120, 120, 120)
    if c >= RF_READY_MIN:
        return (80, 175, 76)    # verde
    if c >= RF_WARN_MIN:
        return (7, 193, 255)    # giallo
    return (54, 67, 244)        # rosso


def _categoria_da_template(template_name: str, tipo: str) -> str:
    """Heuristica fallback: normalizza verso OFFICIAL_LABELS."""
    s = f"{template_name or ''} {tipo or ''}".lower()
    if "skull"  in s:                                    return "skull"
    if "sold"   in s or "troop" in s:                   return "soldati"
    if "ped"    in s or "pawn"  in s:                   return "pedone"
    if "camion" in s or "truck" in s:                   return "camion"
    if "auto"   in s or ("car" in s and "card" not in s): return "auto"
    if "para"   in s or "parach" in s:                  return "paracadute"
    if "card"   in s:                                   return "card"
    if "bott"   in s or "bottle" in s:                  return "bottiglia"
    if "fiam"   in s or "flame" in s or "fire" in s:   return "fiamma"
    if "num"    in s or "digit" in s:                   return "numero"
    if "avatar" in s or re.search(r"\bav\d+\b", s):    return "avatar"
    return "sconosciuto"


def _catalogo_finale(rec: dict) -> tuple:
    """Ritorna (categoria, source, conf, ready, reason)."""
    rf_label  = rec.get("rf_label")
    rf_conf   = rec.get("rf_conf")
    conf_tmpl = rec.get("conf_tmpl")
    tmpl      = rec.get("template")
    tipo      = rec.get("tipo")

    if rf_label in OFFICIAL_LABELS and rf_conf is not None:
        if rf_conf >= RF_READY_MIN:
            ready  = rf_label in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return rf_label, "rf", round(float(rf_conf), 3), ready, reason
        if rf_conf >= RF_WARN_MIN:
            return rf_label, "rf_low", round(float(rf_conf), 3), False, "low_conf"

    cat_t = _categoria_da_template(tmpl, tipo)
    if cat_t != "sconosciuto" and conf_tmpl is not None:
        if conf_tmpl >= TMPL_READY_MIN:
            ready  = cat_t in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return cat_t, "template", round(float(conf_tmpl), 3), ready, reason
        if conf_tmpl >= TMPL_WARN_MIN:
            return cat_t, "template_low", round(float(conf_tmpl), 3), False, "low_conf"

    return "sconosciuto", "none", 0.0, False, "unknown"


def _annota_mappa(map_full_path: str,
                  out_path: str,
                  records: list,
                  log) -> bool:
    """Genera map_annotated.png con bbox colorati per label + score."""
    try:
        img = cv2.imread(map_full_path)
        if img is None:
            log(f"Annotazione: impossibile aprire {map_full_path}")
            return False

        H, W  = img.shape[:2]
        font  = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.38
        thick = 1

        for r in records:
            cx    = int(r.get("cx", 0))
            cy    = int(r.get("cy", 0))
            cat   = r.get("categoria", "sconosciuto")
            cconf = r.get("categoria_conf")
            ready = bool(r.get("ready", False))

            sem_bgr = _semaforo(cconf)
            lbl_bgr = LABEL_COLORS.get(cat, (120, 120, 120))

            x1 = max(0, cx - ANNOTATE_BOX // 2)
            y1 = max(0, cy - ANNOTATE_BOX // 2)
            x2 = min(W - 1, x1 + ANNOTATE_BOX)
            y2 = min(H - 1, y1 + ANNOTATE_BOX)

            cv2.rectangle(img, (x1, y1), (x2, y2), sem_bgr, 2)
            cv2.circle(img, (cx, cy), 3, (255, 255, 255), -1)

            pct = int(float(cconf) * 100) if cconf is not None else 0
            tag = "OK" if ready else "??"
            txt = f"{cat} {pct}% {tag}"

            (tw, th), baseline = cv2.getTextSize(txt, font, scale, thick)
            tx = x1
            ty = max(th + baseline + 4, y1 - 2)

            cv2.rectangle(img,
                          (tx, ty - th - baseline - 2),
                          (tx + tw + 6, ty + 2),
                          (0, 0, 0), -1)
            cv2.putText(img, txt, (tx + 3, ty - baseline),
                        font, scale, lbl_bgr, thick, cv2.LINE_AA)

        cv2.imwrite(out_path, img)
        log("Mappa annotata salvata: map_annotated.png")
        return True
    except Exception as exc:
        log(f"Annotazione errore: {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────────────────────────────────────

class RadarCensusTask(Task):
    """
    Radar Census — periodic 12h (governato da config/task_setup.json).
    Priority 100 (dopo radar=90, prima raccolta_chiusura=200).

    Cataloga le icone visibili nella schermata radar aperta.
    Richiede che la schermata radar sia già aperta (chiamato da RadarTask
    dopo il loop pallini, oppure standalone via run_task.py).

    Output persistente in:
        C:\\doomsday-engine\\radar_archive\\census\\YYYYMMDD_HHMMSS_{istanza}\\
    """

    def name(self) -> str:
        return "radar_census"

    def schedule_type(self) -> Literal["daily", "periodic"]:
        # V5 legacy non usato dall'orchestrator V6 (dispatcha su task_setup.json).
        return "periodic"

    def interval_hours(self) -> float:
        # V5 legacy non usato dall'orchestrator V6 (dispatcha su task_setup.json).
        return 12.0

    def priority(self) -> int:
        # V5 legacy non usato dall'orchestrator V6 (dispatcha su task_setup.json).
        return 100

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("radar_census")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        def log(msg: str) -> None:
            ctx.log_msg(f"[CENSUS] {msg}")

        nome = ctx.instance_name

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.radar_census)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("radar_census", nome or "_unknown")
        debug.snap("00_pre_census", ctx.device.screenshot())

        # Verifica templates
        if not TEMPLATES_DIR.is_dir():
            log(f"templates/ non trovato: {TEMPLATES_DIR}")
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail("templates/ mancante",
                                   icone_rilevate=0)

        # Carica detector
        log("Caricamento detector...")
        try:
            from radar_tool.detector import load_templates, detect, extract_crop
        except Exception as exc:
            log(f"ERRORE import radar_tool.detector: {exc}")
            return TaskResult.fail(f"import detector: {exc}",
                                   icone_rilevate=0)

        try:
            templates = load_templates(TEMPLATES_DIR)
        except Exception as exc:
            log(f"ERRORE load_templates: {exc}")
            return TaskResult.fail(f"load_templates: {exc}",
                                   icone_rilevate=0)

        if not templates:
            log(f"Nessun template in: {TEMPLATES_DIR}")
            return TaskResult.fail("nessun template",
                                   icone_rilevate=0)

        log(f"Detector OK — {len(templates)} template caricati")

        # Carica classifier RF (opzionale)
        rf = self._carica_rf(log)

        # Screenshot
        log("Screenshot schermata radar...")
        screen = ctx.device.screenshot()
        if screen is None:
            log("Screenshot fallito")
            return TaskResult.fail("screenshot fallito", icone_rilevate=0)

        # Estrai frame numpy BGR
        frame = getattr(screen, "frame", None)
        if frame is None and isinstance(screen, np.ndarray):
            frame = screen
        if frame is None:
            log("Frame non disponibile")
            return TaskResult.fail("frame non disponibile", icone_rilevate=0)

        # Detect icone
        threshold = 0.65
        cfg = getattr(ctx, "config", {}) or {}
        if hasattr(cfg, "get"):
            threshold = float(cfg.get("RADAR_TOOL_THRESHOLD", threshold))

        log(f"Detect icone (threshold={threshold})...")
        try:
            matches = detect(frame, templates, threshold=threshold)
        except Exception as exc:
            log(f"ERRORE detect: {exc}")
            return TaskResult.fail(f"detect: {exc}", icone_rilevate=0)

        if not matches:
            log("Nessuna icona rilevata dal detector")
            # Anomalia: census attivato ma 0 detection → potenziale UI cambiata
            debug.flush(success=True, force=True, log_fn=log)
            return TaskResult.ok("nessuna icona rilevata", icone_rilevate=0)

        log(f"Rilevate {len(matches)} icone — catalogazione...")
        debug.snap("01_post_detect", ctx.device.screenshot())
        # Detection riuscita — flush solo se debug attivo (no anomalia)
        debug.flush(success=True, force=False, log_fn=log)

        # Prepara directory output
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = ARCHIVE_ROOT / f"{ts}_{nome}"
        crops_dir = out_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        # Salva map_full.png dal frame numpy
        map_full_path = str(out_dir / "map_full.png")
        try:
            cv2.imwrite(map_full_path, frame)
            log("map_full.png salvato")
        except Exception as exc:
            log(f"WARN: impossibile salvare map_full.png: {exc}")

        # Processa matches
        records = []
        for i, m in enumerate(sorted(matches, key=lambda x: x.get("cy", 0)), 1):
            cx        = int(m.get("cx", 0))
            cy        = int(m.get("cy", 0))
            tipo      = str(m.get("tipo", ""))
            tmpl      = str(m.get("template", ""))
            conf_tmpl = float(m.get("conf", 0.0))

            # Estrai crop
            try:
                crop = extract_crop(frame, cx, cy, 64)
            except Exception:
                crop = frame[max(0,cy-32):cy+32, max(0,cx-32):cx+32]

            crop_name = (f"crop_{cx:04d}_{cy:04d}_"
                         f"{_safe_token(tipo)}_{_safe_token(tmpl)}.png")
            crop_path = str(crops_dir / crop_name)
            try:
                cv2.imwrite(crop_path, crop)
            except Exception:
                pass

            # Classifica RF
            rf_label, rf_conf = None, None
            if rf is not None:
                try:
                    rf_label, rf_conf = rf.predict(crop)
                    rf_conf = float(rf_conf)
                except Exception:
                    pass

            rec = {
                "n":          i,
                "cx":         cx,
                "cy":         cy,
                "tipo":       tipo,
                "template":   tmpl,
                "conf_tmpl":  round(conf_tmpl, 3),
                "crop_file":  str(Path("crops") / crop_name),
                "rf_label":   rf_label,
                "rf_conf":    round(rf_conf, 3) if rf_conf is not None else None,
                "istanza":    nome,
                "timestamp":  ts,
            }

            cat, src, cconf, ready, reason = _catalogo_finale(rec)
            rec["categoria"]        = cat
            rec["categoria_source"] = src
            rec["categoria_conf"]   = cconf
            rec["ready"]            = bool(ready)
            rec["reason"]           = reason

            records.append(rec)

        # Salva census.json
        json_path = str(out_dir / "census.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            log(f"census.json salvato ({len(records)} record)")
        except Exception as exc:
            log(f"ERRORE salvataggio JSON: {exc}")

        # Mappa annotata
        _annota_mappa(map_full_path,
                      str(out_dir / "map_annotated.png"),
                      records, log)

        # Riepilogo
        counts: dict[str, int] = {}
        ready_count = 0
        for r in records:
            k = r.get("categoria", "sconosciuto")
            counts[k] = counts.get(k, 0) + 1
            if r.get("ready"):
                ready_count += 1

        top = ", ".join(
            f"{k}={v}"
            for k, v in sorted(counts.items(),
                                key=lambda kv: (-kv[1], kv[0]))[:10]
        )
        log(f"Catalogazione: {top}")
        log(f"Ready: {ready_count}/{len(records)}")
        log(f"Output: {out_dir}")
        log(f"Completato — {len(records)} icone rilevate")

        return TaskResult.ok(
            f"{len(records)} icone rilevate",
            icone_rilevate=len(records),
            ready_count=ready_count,
            output_dir=str(out_dir),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _carica_rf(self, log):
        """Carica il classifier RF (opzionale). Ritorna None se non disponibile."""
        try:
            from radar_tool.classifier import Classifier
        except Exception as exc:
            log(f"RF: modulo radar_tool.classifier non disponibile: {exc}")
            return None

        if not RF_MODEL_PATH.exists():
            log(f"RF: modello non trovato (opzionale): {RF_MODEL_PATH}")
            return None

        try:
            clf = Classifier()
            clf.load(str(RF_MODEL_PATH))
            if getattr(clf, "trained", False):
                log("RF: modello caricato ✓")
            else:
                log("RF: modello caricato ma non risulta trained")
            return clf
        except Exception as exc:
            log(f"RF: errore caricamento: {exc}")
            return None
