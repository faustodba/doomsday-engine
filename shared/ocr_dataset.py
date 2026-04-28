# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/ocr_dataset.py                          WU55
#
#  Data collection per analisi OCR slot in MAPPA vs HOME.
#
#  CASO D'USO
#  L'OCR contatore slot squadre (zona 890,117,946,141) è tarato per HOME ma
#  fallisce in MAPPA (stessa zona, sfondo diverso). Per analizzare il
#  problema serve un dataset di coppie HOME (ground truth) ↔ MAPPA (sample).
#
#  PIPELINE
#  1. Bot in HOME legge slot via OCR → salva sample HOME + valore "vero"
#  2. Bot va in MAPPA → re-OCR shadow (passivo, no decisione) → salva sample
#     MAPPA + valore letto
#  3. Coppia (pair_id) accomuna i 2 sample → analisi offline
#
#  STORAGE
#  data/ocr_dataset/<istanza>_<pair_id>/
#    ├── home_screen.png       (960x540 full)
#    ├── home_crop.png         (zona slot ritagliata)
#    ├── home_crop_otsu.png    (preprocessing visibile)
#    ├── home_meta.json
#    ├── map_screen.png
#    ├── map_crop.png
#    ├── map_crop_otsu.png
#    └── map_meta.json
#
#  NOTA: il save NON cambia decisioni del bot. Si attiva via flag
#  RACCOLTA_OCR_DEBUG=true (override per istanza).
# ==============================================================================

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_OCR_SLOT_BOX = (890, 117, 946, 141)


def _dataset_root() -> Path:
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "ocr_dataset"


def new_pair_id() -> str:
    """Genera un pair_id univoco (timestamp + uuid hex 6)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"


def _to_pil(screen):
    """Converte Screenshot/ndarray a PIL Image."""
    try:
        from PIL import Image
        # AdbDevice screen ha .frame (BGR ndarray)
        if hasattr(screen, "frame"):
            arr = screen.frame
            # BGR → RGB
            return Image.fromarray(arr[:, :, ::-1])
        # ndarray diretto
        if hasattr(screen, "shape"):
            return Image.fromarray(screen[:, :, ::-1] if screen.shape[2] == 3 else screen)
        return None
    except Exception:
        return None


def _save_sample(
    istanza: str,
    pair_id: str,
    fase: str,
    screen,
    ocr_raw: str,
    attive: int,
    totale: int,
    extra: Optional[dict] = None,
) -> bool:
    """
    Salva sample (screen full + crop + meta) per fase HOME o MAP.

    Args:
        istanza: nome istanza (es. "FAU_01")
        pair_id: ID coppia (HOME+MAP condividono stesso pair_id)
        fase:    "home" | "map"
        screen:  Screenshot/ndarray
        ocr_raw: testo OCR raw (es. "5/5", "2/4")
        attive:  valore parsato attive (-1 se fail)
        totale:  valore parsato totale (-1 se fail)
        extra:   dict extra meta (es. presenza_banner, schermata, ecc.)
    """
    try:
        from PIL import Image
        d = _dataset_root() / f"{istanza}_{pair_id}"
        d.mkdir(parents=True, exist_ok=True)

        pil = _to_pil(screen)
        if pil is None:
            return False
        # Full screen
        pil.save(d / f"{fase}_screen.png")
        # Crop slot zone
        crop = pil.crop(_OCR_SLOT_BOX)
        crop.save(d / f"{fase}_crop.png")
        # Crop preprocessato (otsu) — utile per debug visivo
        try:
            import numpy as np
            from PIL import ImageOps
            gray = ImageOps.grayscale(crop)
            arr = np.array(gray)
            thr = arr.mean() + arr.std() * 0.3  # otsu approx
            otsu = (arr > thr).astype("uint8") * 255
            Image.fromarray(otsu).save(d / f"{fase}_crop_otsu.png")
        except Exception:
            pass

        # Meta JSON
        meta = {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "istanza":     istanza,
            "pair_id":     pair_id,
            "fase":        fase,                # "home" | "map"
            "ocr_zona":    _OCR_SLOT_BOX,
            "ocr_raw":     str(ocr_raw or ""),
            "attive":      int(attive),
            "totale":      int(totale),
        }
        if extra:
            meta.update(extra)

        with open(d / f"{fase}_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def save_home_sample(istanza: str, pair_id: str, screen,
                     ocr_raw: str, attive: int, totale: int,
                     extra: Optional[dict] = None) -> bool:
    """Salva sample HOME (ground truth)."""
    return _save_sample(istanza, pair_id, "home", screen, ocr_raw, attive, totale, extra)


def save_map_sample(istanza: str, pair_id: str, screen,
                    ocr_raw: str, attive: int, totale: int,
                    extra: Optional[dict] = None) -> bool:
    """Salva sample MAP (da analizzare)."""
    return _save_sample(istanza, pair_id, "map", screen, ocr_raw, attive, totale, extra)


def list_pairs() -> list[dict]:
    """
    Ritorna lista di tutte le coppie HOME+MAP nel dataset.
    Utile per analisi offline (agente AI).
    """
    out = []
    root = _dataset_root()
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        home_meta = d / "home_meta.json"
        map_meta  = d / "map_meta.json"
        try:
            home = json.load(open(home_meta, encoding="utf-8")) if home_meta.exists() else None
            mp   = json.load(open(map_meta,  encoding="utf-8")) if map_meta.exists()  else None
            out.append({
                "dir":      d,
                "pair_id":  d.name,
                "home":     home,
                "map":      mp,
                "complete": bool(home and mp),
            })
        except Exception:
            continue
    return out


def cleanup_dataset(keep_last_pairs: int = 0) -> int:
    """
    Rimuove tutto il dataset (o tiene gli ultimi N pair).
    Returns: numero directory rimosse.
    """
    import shutil
    pairs = list_pairs()
    to_remove = pairs[:-keep_last_pairs] if keep_last_pairs > 0 else pairs
    n = 0
    for p in to_remove:
        try:
            shutil.rmtree(p["dir"])
            n += 1
        except Exception:
            continue
    return n
