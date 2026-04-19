# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/adaptive_timing.py
#
#  Timing adattivo per-istanza. Ogni istanza mantiene uno storico dei tempi
#  reali (boot, home, stabilizzazione, ecc.) in una sliding window e calcola
#  dinamicamente timeout proporzionali al p90 storico.
#
#  Uso:
#      tm = AdaptiveTiming("FAU_00")
#      timeout = tm.get("boot_android_s", fallback=120.0)
#      t0 = time.time()
#      # ... esegui operazione ...
#      tm.record("boot_android_s", time.time() - t0)
#
#  Persistenza: state/<nome>_timing.json, sliding window 10 samples.
#  Fallback: se samples < MIN_SAMPLES, ritorna il fallback statico.
#  Cap inferiore: mai sotto fallback/2 per sicurezza.
# ==============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_WINDOW_SIZE  = 10      # numero max samples mantenuti
_MIN_SAMPLES  = 3       # sotto questa soglia -> usa fallback
_PERCENTILE   = 0.9     # p90 della finestra
_MARGIN_MULT  = 1.5     # moltiplicatore applicato al p90
_MARGIN_ADD_S = 10.0    # secondi aggiuntivi di margine

# State dir di default (relativo alla root del progetto, uguale a altri moduli)
_DEFAULT_STATE_DIR = Path(
    os.environ.get("DOOMSDAY_STATE_DIR")
    or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
)


class AdaptiveTiming:
    """Timing adattivo per una singola istanza."""

    def __init__(self, nome: str, state_dir: Optional[Path] = None):
        self.nome = nome
        self._dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
        self._path = self._dir / f"{nome}_timing.json"
        self._data: dict[str, list[float]] = self._load()

    # ── I/O persistente ──────────────────────────────────────────────────────

    def _load(self) -> dict[str, list[float]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            # Normalizza: solo liste di float
            out: dict[str, list[float]] = {}
            for k, v in raw.items():
                if isinstance(v, list):
                    out[k] = [float(x) for x in v if isinstance(x, (int, float))]
            return out
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except Exception:
            pass  # best-effort, non bloccare il bot se il disco e' pieno

    # ── API pubblica ─────────────────────────────────────────────────────────

    def get(self, key: str, fallback: float) -> float:
        """
        Calcola timeout dinamico per `key`.

        Regole:
          - Se samples < MIN_SAMPLES -> ritorna fallback statico.
          - Altrimenti: p90 * MARGIN_MULT + MARGIN_ADD_S.
          - Cap inferiore: mai sotto fallback/2.
          - Cap superiore: mai sopra fallback (sicurezza: se lo storico
            esplode per qualche motivo, non allarghiamo oltre il default).
        """
        vals = self._data.get(key, [])
        if len(vals) < _MIN_SAMPLES:
            return float(fallback)

        sorted_vals = sorted(vals)
        idx = int(_PERCENTILE * (len(sorted_vals) - 1))
        p = sorted_vals[idx]
        dynamic = p * _MARGIN_MULT + _MARGIN_ADD_S

        lower = float(fallback) / 2.0
        upper = float(fallback)
        return max(lower, min(dynamic, upper))

    def record(self, key: str, actual_s: float) -> None:
        """Registra un nuovo sample; mantiene sliding window ultimi N."""
        if actual_s is None or actual_s < 0:
            return
        vals = self._data.setdefault(key, [])
        vals.append(float(actual_s))
        if len(vals) > _WINDOW_SIZE:
            del vals[: len(vals) - _WINDOW_SIZE]
        self._save()

    def snapshot(self) -> dict[str, dict]:
        """Debug: ritorna stato corrente (min/max/mean/p90/n) per ogni key."""
        out = {}
        for k, vals in self._data.items():
            if not vals:
                continue
            s = sorted(vals)
            idx = int(_PERCENTILE * (len(s) - 1))
            out[k] = {
                "n":    len(s),
                "min":  s[0],
                "max":  s[-1],
                "mean": sum(s) / len(s),
                "p90":  s[idx],
            }
        return out
