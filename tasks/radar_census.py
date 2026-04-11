# tasks/radar_census.py
"""
Step 18 — Radar Census (periodic sub-task, in fase di testing).

Scheduling : chiamato da RadarTask dopo il loop pallini
             (se RADAR_CENSUS_ABILITATO=True in ctx.config).
             Può anche essere schedulato come task autonomo periodic 24h.

Funzione
─────────────────────────────────────────────────────────────────────────────
  Censisce tutte le icone visibili sulla mappa Radar Station:
  - Detection via radar_tool (template matching + NMS)
  - Classificazione via Random Forest (opzionale, se classifier.pkl presente)
  - Salva crops PNG + census.json + map_annotated.png in radar_archive/census/

Output (PERSISTENTE — non cancellato ai restart)
─────────────────────────────────────────────────────────────────────────────
  <ARCHIVE_ROOT>/<YYYYMMDD_HHMMSS>_<instance_id>/
    map_full.png
    map_annotated.png
    crops/crop_XXXX_YYYY_tipo_tmpl.png
    census.json

Label ufficiali
─────────────────────────────────────────────────────────────────────────────
  pedone, auto, camion, skull, avatar, numero, card,
  paracadute, fiamma, bottiglia, soldati, sconosciuto

Soglie
─────────────────────────────────────────────────────────────────────────────
  Template: ready>=0.80, warn>=0.70
  RF:       ready>=0.70, warn>=0.60
  Detection threshold: 0.65 (override via ctx.config["RADAR_TOOL_THRESHOLD"])

Dipendenze esterne (opzionali, non bloccanti)
─────────────────────────────────────────────────────────────────────────────
  radar_tool.detector   (load_templates, detect, extract_crop)
  radar_tool.classifier (Classifier)
  cv2 (annotazione mappa)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from typing import Literal

import numpy as np

from core.task import Task, TaskContext, TaskResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Costanti label
# ──────────────────────────────────────────────────────────────────────────────

OFFICIAL_LABELS: frozenset[str] = frozenset({
    "pedone", "auto", "camion", "skull",
    "avatar", "numero", "card", "paracadute",
    "fiamma", "bottiglia", "soldati", "sconosciuto",
})

ACTION_LABELS: frozenset[str] = OFFICIAL_LABELS - {"sconosciuto"}

# Colori BGR per annotazione cv2
_LABEL_COLORS: dict[str, tuple[int, int, int]] = {
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

# Soglie catalogazione
_TMPL_READY  = 0.80
_TMPL_WARN   = 0.70
_RF_READY    = 0.70
_RF_WARN     = 0.60
_DET_DEFAULT = 0.65

# Dimensione crop
_CROP_SIZE = 64
# Box annotazione
_ANNOT_BOX = 64


# ──────────────────────────────────────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────────────────────────────────────

class RadarCensusTask(Task):
    """
    Radar Census — periodic (o sub-task di RadarTask).

    Presuppone che la mappa Radar Station sia già aperta
    (viene chiamato da RadarTask dopo il loop pallini).
    """

    # ── Task ABC ──────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "radar_census"

    def schedule_type(self) -> Literal["daily", "periodic"]:
        return "periodic"

    def interval_hours(self) -> float:
        return 24.0

    def priority(self) -> int:
        return 31

    def should_run(self, ctx) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("radar_census")
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        enabled = (getattr(ctx, "config", {}) or {}).get(
            "RADAR_CENSUS_ABILITATO", False
        )
        if not enabled:
            logger.debug("[CENSUS] disabilitato — skip")
            return TaskResult(success=True,
                              data={"icone_rilevate": 0, "errore": None})

        icone, errore = self._esegui(ctx)
        return TaskResult(
            success=errore is None,
            data={"icone_rilevate": icone, "errore": errore},
        )

    # ── Logica principale ─────────────────────────────────────────────────────

    def _esegui(self, ctx: TaskContext) -> tuple[int, str | None]:
        """
        Ritorna (n_icone, errore|None).
        """
        cfg = getattr(ctx, "config", {}) or {}
        threshold = float(cfg.get("RADAR_TOOL_THRESHOLD", _DET_DEFAULT))
        archive_root = cfg.get("RADAR_ARCHIVE_ROOT",
                               os.path.join(".", "radar_archive", "census"))
        tmpl_dir = cfg.get("RADAR_TEMPLATES_DIR",
                           os.path.join(".", "radar_tool", "templates"))
        rf_path  = cfg.get("RADAR_RF_MODEL_PATH",
                           os.path.join(".", "radar_tool", "dataset", "classifier.pkl"))

        # Carica detector
        load_tmpl, detect, extract_crop = self._carica_detector(tmpl_dir)
        if not load_tmpl:
            return 0, "radar_tool.detector non disponibile"

        try:
            from pathlib import Path
            templates = load_tmpl(Path(tmpl_dir))
        except Exception as exc:
            return 0, f"load_templates errore: {exc}"

        if not templates:
            return 0, f"nessun template in {tmpl_dir}"

        rf = self._carica_rf(rf_path)

        # Screenshot (mappa già aperta da RadarTask)
        screen = ctx.device.screenshot()
        if screen is None:
            return 0, "screenshot fallito"

        frame = ctx.device.last_frame
        if frame is None:
            return 0, "frame numpy non disponibile"

        # Detection
        matches = detect(frame, templates, threshold=threshold)
        if not matches:
            logger.info("[CENSUS] nessuna icona rilevata")
            return 0, None

        # Output dir
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome    = ctx.instance_id
        out_dir = os.path.join(archive_root, f"{ts}_{nome}")
        crops_dir = os.path.join(out_dir, "crops")
        os.makedirs(crops_dir, exist_ok=True)

        # Salva map_full
        try:
            import cv2
            cv2.imwrite(os.path.join(out_dir, "map_full.png"), frame)
        except Exception:
            pass

        # Processa ogni match
        records: list[dict] = []
        for i, m in enumerate(
            sorted(matches, key=lambda x: x.get("cy", 0)), 1
        ):
            rec = self._processa_match(m, i, frame, crops_dir, ts, nome, rf, extract_crop)
            records.append(rec)

        # Salva JSON
        json_path = os.path.join(out_dir, "census.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[CENSUS] errore salvataggio JSON: %s", exc)

        # Mappa annotata
        self._annota_mappa(
            os.path.join(out_dir, "map_full.png"),
            os.path.join(out_dir, "map_annotated.png"),
            records,
        )

        # Riepilogo log
        counts: dict[str, int] = {}
        ready_count = 0
        for r in records:
            k = r.get("categoria", "sconosciuto")
            counts[k] = counts.get(k, 0) + 1
            if r.get("ready"):
                ready_count += 1

        top = ", ".join(
            f"{k}={v}"
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        )
        logger.info("[CENSUS] %s", top)
        logger.info("[CENSUS] ready=%d/%d — output: %s",
                    ready_count, len(records), out_dir)

        return len(records), None

    # ── Match processing ──────────────────────────────────────────────────────

    def _processa_match(self,
                        m: dict,
                        i: int,
                        frame: np.ndarray,
                        crops_dir: str,
                        ts: str,
                        nome: str,
                        rf,
                        extract_crop,
                        ) -> dict:
        cx        = int(m.get("cx", 0))
        cy        = int(m.get("cy", 0))
        tipo      = str(m.get("tipo", ""))
        tmpl      = str(m.get("template", ""))
        conf_tmpl = float(m.get("conf", 0.0))

        # Salva crop
        crop = extract_crop(frame, cx, cy, _CROP_SIZE)
        crop_name = (
            f"crop_{cx:04d}_{cy:04d}"
            f"_{_safe_token(tipo)}_{_safe_token(tmpl)}.png"
        )
        try:
            import cv2
            cv2.imwrite(os.path.join(crops_dir, crop_name), crop)
        except Exception:
            pass

        # RF prediction
        rf_label, rf_conf = None, None
        if rf is not None:
            try:
                rf_label, rf_conf = rf.predict(crop)
                rf_conf = float(rf_conf)
            except Exception:
                rf_label, rf_conf = None, None

        rec: dict = {
            "n":         i,
            "cx":        cx,
            "cy":        cy,
            "tipo":      tipo,
            "template":  tmpl,
            "conf_tmpl": round(conf_tmpl, 3),
            "crop_file": os.path.join("crops", crop_name),
            "rf_label":  rf_label,
            "rf_conf":   round(rf_conf, 3) if rf_conf is not None else None,
            "nome":      nome,
            "timestamp": ts,
        }

        cat, src, cconf, ready, reason = _catalogo_finale(rec)
        rec["categoria"]        = cat
        rec["categoria_source"] = src
        rec["categoria_conf"]   = cconf
        rec["ready"]            = bool(ready)
        rec["reason"]           = reason
        return rec

    # ── Detector / RF loader ──────────────────────────────────────────────────

    @staticmethod
    def _carica_detector(tmpl_dir: str):
        """Ritorna (load_templates, detect, extract_crop) o (None,None,None)."""
        if not os.path.isdir(tmpl_dir):
            logger.warning("[CENSUS] templates dir non trovata: %s", tmpl_dir)
            return None, None, None
        try:
            from radar_tool.detector import load_templates, detect, extract_crop
            return load_templates, detect, extract_crop
        except Exception as exc:
            logger.warning("[CENSUS] import radar_tool.detector: %s", exc)
            return None, None, None

    @staticmethod
    def _carica_rf(rf_path: str):
        """Ritorna istanza Classifier addestrata, o None (opzionale)."""
        if not os.path.exists(rf_path):
            logger.debug("[CENSUS] RF model non trovato (opzionale): %s", rf_path)
            return None
        try:
            from radar_tool.classifier import Classifier
            clf = Classifier()
            clf.load(rf_path)
            if getattr(clf, "trained", False):
                logger.info("[CENSUS] RF model caricato")
            return clf
        except Exception as exc:
            logger.warning("[CENSUS] errore caricamento RF: %s", exc)
            return None

    # ── Annotazione mappa ─────────────────────────────────────────────────────

    @staticmethod
    def _annota_mappa(src_path: str, dst_path: str, records: list[dict]) -> bool:
        """
        Genera map_annotated.png con bbox colorati (semaforo confidenza)
        e testo categoria (colori LABEL_COLORS). cv2 puro, nessun font esterno.
        """
        try:
            import cv2
            img = cv2.imread(src_path)
            if img is None:
                return False
            H, W = img.shape[:2]
            font  = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.38
            thick = 1

            for r in records:
                cx    = int(r.get("cx", 0))
                cy    = int(r.get("cy", 0))
                cat   = r.get("categoria", "sconosciuto")
                cconf = r.get("categoria_conf")
                ready = bool(r.get("ready", False))

                sem_bgr = _semaforo_bgr(cconf)
                lbl_bgr = _LABEL_COLORS.get(cat, (120, 120, 120))

                x1 = max(0, cx - _ANNOT_BOX // 2)
                y1 = max(0, cy - _ANNOT_BOX // 2)
                x2 = min(W - 1, x1 + _ANNOT_BOX)
                y2 = min(H - 1, y1 + _ANNOT_BOX)

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

            cv2.imwrite(dst_path, img)
            logger.info("[CENSUS] map_annotated.png salvata")
            return True
        except Exception as exc:
            logger.warning("[CENSUS] annotazione errore: %s", exc)
            return False


# ──────────────────────────────────────────────────────────────────────────────
# Utility pure (nessun accesso a ctx)
# ──────────────────────────────────────────────────────────────────────────────

def _semaforo_bgr(conf) -> tuple[int, int, int]:
    """Verde/giallo/rosso BGR in base alla confidenza."""
    if conf is None:
        return (120, 120, 120)
    try:
        c = float(conf)
    except Exception:
        return (120, 120, 120)
    if c >= _RF_READY: return ( 80, 175,  76)   # verde
    if c >= _RF_WARN:  return (  7, 193, 255)   # giallo
    return (54, 67, 244)                          # rosso


def _safe_token(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^0-9A-Za-z_\-]+", "", s)
    return s or "x"


def _categoria_da_template(template_name: str, tipo: str) -> str:
    """Heuristica template name → OFFICIAL_LABELS (fallback senza RF)."""
    s = f"{template_name or ''} {tipo or ''}".lower()
    if "skull"   in s:                              return "skull"
    if "sold"    in s or "troop" in s:              return "soldati"
    if "ped"     in s or "pawn"  in s:              return "pedone"
    if "camion"  in s or "truck" in s:              return "camion"
    if "auto"    in s or ("car" in s and "card" not in s): return "auto"
    if "para"    in s or "parach" in s:             return "paracadute"
    if "card"    in s:                              return "card"
    if "bott"    in s or "bottle" in s:             return "bottiglia"
    if "fiam"    in s or "flame" in s or "fire" in s: return "fiamma"
    if "num"     in s or "digit" in s:              return "numero"
    if "avatar"  in s or re.search(r"\bav\d+\b", s): return "avatar"
    return "sconosciuto"


def _catalogo_finale(rec: dict) -> tuple[str, str, float, bool, str]:
    """
    Determina categoria finale, source, confidenza, ready, reason.

    Priorità: RF (se conf >= soglia) > template heuristica > sconosciuto.
    """
    rf_label  = rec.get("rf_label")
    rf_conf   = rec.get("rf_conf")
    conf_tmpl = rec.get("conf_tmpl")
    tmpl      = rec.get("template")
    tipo      = rec.get("tipo")

    # RF ad alta confidenza
    if rf_label in OFFICIAL_LABELS and rf_conf is not None:
        if rf_conf >= _RF_READY:
            ready  = rf_label in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return rf_label, "rf", round(float(rf_conf), 3), ready, reason
        if rf_conf >= _RF_WARN:
            return rf_label, "rf_low", round(float(rf_conf), 3), False, "low_conf"

    # Fallback template heuristica
    cat_t = _categoria_da_template(tmpl, tipo)
    if cat_t != "sconosciuto" and conf_tmpl is not None:
        if conf_tmpl >= _TMPL_READY:
            ready  = cat_t in ACTION_LABELS
            reason = "" if ready else "not_in_action_labels"
            return cat_t, "template", round(float(conf_tmpl), 3), ready, reason
        if conf_tmpl >= _TMPL_WARN:
            return cat_t, "template_low", round(float(conf_tmpl), 3), False, "low_conf"

    return "sconosciuto", "none", 0.0, False, "unknown"
