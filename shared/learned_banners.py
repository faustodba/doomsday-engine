#  ============================================================================
#  DOOMSDAY ENGINE V6 — shared/learned_banners.py
#  ============================================================================
#  [DEPRECATO WU110 — 03/05/2026]
#  Storage del BannerLearner (deprecato). Il file `data/learned_banners.json`
#  non viene mai creato perché la pipeline learn non scatta (vedi
#  shared/banner_learner.py per dettagli). `load_all()` ritorna lista vuota
#  → catalog runtime usa solo entry statiche di shared/banner_catalog.py.
#
#  Storage persistente JSON per banner appresi automaticamente dal
#  BannerLearner. Compatibile con BANNER_CATALOG: load_learned_as_specs()
#  ritorna list[BannerSpec] da concatenare al catalog statico.
#
#  Schema JSON (data/learned_banners.json):
#    {
#      "version": 1,
#      "banners": [
#        {
#          "name": "learned_20260502T113000Z_a1b2",
#          "title_path": "templates/pin/learned/title_xxx.png",
#          "x_path": "templates/pin/learned/x_xxx.png",
#          "x_coords": [825, 54],
#          "x_size": [55, 51],
#          "title_roi": [40, 20, 410, 70],
#          "created_at": "2026-05-02T11:30:00Z",
#          "hit_count": 5,
#          "success_count": 4,
#          "fail_count": 1,
#          "last_used": "2026-05-02T13:45:00Z",
#          "enabled": true
#        }
#      ]
#    }
#
#  POLICY:
#    - Cap massimo 25 entry. Se supera → LRU eviction (last_used più vecchio).
#    - Dedup via template_similarity > 0.85: nuovo banner simile a esistente
#      non viene registrato (incrementa hit_count su esistente).
#    - Revoca: dopo 3 fail consecutivi (success_streak < 0 dopo run-length 3)
#      l'entry viene disabilitata (enabled=False) ma rimane in storage per audit.
#  ============================================================================

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from shared.banner_learner import template_similarity


# ============================================================================
# Paths e costanti
# ============================================================================

def _resolve_root() -> Path:
    """Root del progetto. Onora DOOMSDAY_ROOT env var (prod vs dev)."""
    env_root = os.environ.get("DOOMSDAY_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)
    # Fallback: parent di shared/
    return Path(__file__).resolve().parents[1]


def _store_path() -> Path:
    return _resolve_root() / "data" / "learned_banners.json"


def _learned_templates_dir() -> Path:
    return _resolve_root() / "templates" / "pin" / "learned"


MAX_ENTRIES = 25
DEDUP_SIMILARITY_THRESHOLD = 0.85
FAIL_STREAK_DISABLE = 3

_lock = threading.Lock()


# ============================================================================
# Data model
# ============================================================================

@dataclass
class LearnedBanner:
    name: str
    title_path: str        # relativo a root (es. "templates/pin/learned/title_xxx.png")
    x_path: str            # relativo a root
    x_coords: tuple[int, int]
    x_size: tuple[int, int]
    title_roi: tuple[int, int, int, int]
    created_at: str
    hit_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    fail_streak: int = 0   # streak consecutivo di tap che NON hanno sbloccato
    last_used: Optional[str] = None
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title_path": self.title_path,
            "x_path": self.x_path,
            "x_coords": list(self.x_coords),
            "x_size": list(self.x_size),
            "title_roi": list(self.title_roi),
            "created_at": self.created_at,
            "hit_count": self.hit_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "fail_streak": self.fail_streak,
            "last_used": self.last_used,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LearnedBanner":
        return cls(
            name=d["name"],
            title_path=d["title_path"],
            x_path=d["x_path"],
            x_coords=tuple(d["x_coords"]),
            x_size=tuple(d["x_size"]),
            title_roi=tuple(d["title_roi"]),
            created_at=d["created_at"],
            hit_count=int(d.get("hit_count", 0)),
            success_count=int(d.get("success_count", 0)),
            fail_count=int(d.get("fail_count", 0)),
            fail_streak=int(d.get("fail_streak", 0)),
            last_used=d.get("last_used"),
            enabled=bool(d.get("enabled", True)),
        )


# ============================================================================
# Storage
# ============================================================================

def _load_raw() -> dict:
    """Carica raw JSON. Crea struttura vuota se file mancante."""
    path = _store_path()
    if not path.exists():
        return {"version": 1, "banners": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "banners": []}


def _save_raw(data: dict) -> None:
    """Salvataggio atomico: write tmp + rename."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_all() -> list[LearnedBanner]:
    """Carica tutti i learned banners (anche disabilitati, per audit)."""
    with _lock:
        data = _load_raw()
    return [LearnedBanner.from_dict(b) for b in data.get("banners", [])]


def load_active() -> list[LearnedBanner]:
    """Solo entry enabled=True (per inclusione runtime nel catalog)."""
    return [b for b in load_all() if b.enabled]


def save_all(banners: list[LearnedBanner]) -> None:
    with _lock:
        _save_raw({"version": 1, "banners": [b.to_dict() for b in banners]})


# ============================================================================
# Operazioni alto livello
# ============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def find_duplicate(title_img: np.ndarray) -> Optional[LearnedBanner]:
    """Cerca un banner esistente con title template simile (similarity > soglia).
    Ritorna il match o None. Caller incrementa hit_count su esistente invece di
    creare nuovo."""
    root = _resolve_root()
    for b in load_all():
        try:
            existing = cv2.imread(str(root / b.title_path))
            if existing is None:
                continue
            sim = template_similarity(title_img, existing)
            if sim >= DEDUP_SIMILARITY_THRESHOLD:
                return b
        except Exception:
            continue
    return None


def register_new(title_img: np.ndarray, x_img: np.ndarray,
                 x_coords: tuple[int, int],
                 title_roi: tuple[int, int, int, int]) -> LearnedBanner:
    """
    Registra nuovo learned banner. Salva i 2 PNG e aggiunge entry a JSON.
    Applica LRU se supera MAX_ENTRIES.

    NOTA: caller dovrebbe prima chiamare find_duplicate() per evitare push
    di duplicati; questa funzione non controlla similarità.
    """
    root = _resolve_root()
    learned_dir = _learned_templates_dir()
    learned_dir.mkdir(parents=True, exist_ok=True)

    ts = _now_compact()
    suffix = f"{ts}_{abs(hash(x_coords)) % 0x10000:04x}"
    name = f"learned_{suffix}"
    title_rel = f"templates/pin/learned/title_{suffix}.png"
    x_rel = f"templates/pin/learned/x_{suffix}.png"

    cv2.imwrite(str(root / title_rel), title_img)
    cv2.imwrite(str(root / x_rel), x_img)

    h, w = x_img.shape[:2]
    entry = LearnedBanner(
        name=name,
        title_path=title_rel,
        x_path=x_rel,
        x_coords=x_coords,
        x_size=(w, h),
        title_roi=title_roi,
        created_at=_now_iso(),
        hit_count=1,
        success_count=1,
        fail_count=0,
        fail_streak=0,
        last_used=_now_iso(),
        enabled=True,
    )

    with _lock:
        data = _load_raw()
        banners = [LearnedBanner.from_dict(b) for b in data.get("banners", [])]
        banners.append(entry)
        # LRU eviction
        if len(banners) > MAX_ENTRIES:
            banners.sort(key=lambda b: (b.last_used or b.created_at))
            banners = banners[-MAX_ENTRIES:]
        _save_raw({"version": 1, "banners": [b.to_dict() for b in banners]})

    return entry


def record_outcome(name: str, success: bool) -> Optional[LearnedBanner]:
    """
    Aggiorna metriche di un learned banner dopo un tentativo di dismiss.
    Se fail_streak raggiunge FAIL_STREAK_DISABLE → enabled=False (autoretract).
    Ritorna l'entry aggiornata o None se non trovata.
    """
    with _lock:
        data = _load_raw()
        banners = [LearnedBanner.from_dict(b) for b in data.get("banners", [])]
        target = None
        for b in banners:
            if b.name == name:
                target = b
                break
        if target is None:
            return None
        target.hit_count += 1
        target.last_used = _now_iso()
        if success:
            target.success_count += 1
            target.fail_streak = 0
        else:
            target.fail_count += 1
            target.fail_streak += 1
            if target.fail_streak >= FAIL_STREAK_DISABLE:
                target.enabled = False
        _save_raw({"version": 1, "banners": [b.to_dict() for b in banners]})
        return target


def set_enabled(name: str, enabled: bool) -> bool:
    """Abilita/disabilita manualmente un learned banner. Per dashboard.
    Ritorna True se trovato e modificato."""
    with _lock:
        data = _load_raw()
        banners = [LearnedBanner.from_dict(b) for b in data.get("banners", [])]
        for b in banners:
            if b.name == name:
                b.enabled = enabled
                if enabled:
                    b.fail_streak = 0  # reset streak su riabilitazione manuale
                _save_raw({"version": 1, "banners": [x.to_dict() for x in banners]})
                return True
    return False


def delete(name: str) -> bool:
    """Elimina un learned banner + i suoi template PNG. Per dashboard."""
    root = _resolve_root()
    with _lock:
        data = _load_raw()
        banners = [LearnedBanner.from_dict(b) for b in data.get("banners", [])]
        target = next((b for b in banners if b.name == name), None)
        if target is None:
            return False
        # Rimuovi PNG (best effort)
        for p in (target.title_path, target.x_path):
            try:
                (root / p).unlink(missing_ok=True)
            except Exception:
                pass
        banners = [b for b in banners if b.name != name]
        _save_raw({"version": 1, "banners": [b.to_dict() for b in banners]})
    return True


# ============================================================================
# Bridge con BANNER_CATALOG
# ============================================================================

def load_learned_as_specs():
    """
    Converte i learned banners in BannerSpec compatibili con BANNER_CATALOG.

    Tutti i learned hanno priority=4 (dopo i banner statici 0-3, prima del
    fallback X cerchio dorato). Il dismiss è "tap_template" su template X
    appreso, ROI = bbox della X originale (con tolleranza ±30px).

    Solo entry enabled=True vengono ritornate.
    """
    from shared.banner_catalog import BannerSpec
    specs = []
    for b in load_active():
        x_cx, x_cy = b.x_coords
        x_w, x_h = b.x_size
        # ROI dismiss intorno alla X (con margine tolleranza)
        margin = 30
        roi_x1 = max(0, x_cx - x_w // 2 - margin)
        roi_y1 = max(0, x_cy - x_h // 2 - margin)
        roi_x2 = min(960, x_cx + x_w // 2 + margin)
        roi_y2 = min(540, x_cy + x_h // 2 + margin)
        try:
            specs.append(BannerSpec(
                name=b.name,
                template=b.title_path.replace("templates/", ""),  # BANNER_CATALOG path è relativo a templates/
                roi=tuple(b.title_roi),
                threshold=0.78,  # leggermente meno aggressivo per learned
                dismiss_action="tap_template",
                dismiss_template=b.x_path.replace("templates/", ""),
                dismiss_template_roi=(roi_x1, roi_y1, roi_x2, roi_y2),
                dismiss_template_soglia=0.70,
                wait_after_s=1.5,
                priority=4,
            ))
        except Exception:
            continue
    return specs
