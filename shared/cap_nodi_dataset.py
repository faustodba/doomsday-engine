# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/cap_nodi_dataset.py
#
#  Logger campioni capacità nodo durante raccolta.
#
#  Scrive 1 record JSONL per ogni nodo aperto (tap nodo + popup gather):
#    {ts, instance, tipo, livello, capacita}
#
#  - capacita -1 = OCR fallita
#  - capacita > 0 = valore letto (può essere < max nominale = nodo già parzialmente raccolto)
#
#  Uso analitico (cfr tools/analisi_cap_nodi.py):
#    - max(capacita per (tipo, livello)) → capacità nominale
#    - capacita / max → % residuo
#    - inviate × load_squadra vs capacita_attuale → saturazione invio
#
#  Storage: data/cap_nodi_dataset.jsonl (append-only).
#  Retention: nessuna (file cresce ~12 istanze × ~3 nodi/ciclo × ~18 cicli/die ≈ 650/die).
# ==============================================================================

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()


def _root_dir() -> Path:
    """Dir base del progetto (env DOOMSDAY_ROOT o cwd se non set).

    Coerente con altri moduli (config_manager, telemetry).
    """
    root = os.environ.get("DOOMSDAY_ROOT")
    if root:
        return Path(root)
    return Path(os.getcwd())


def _dataset_path() -> Path:
    p = _root_dir() / "data" / "cap_nodi_dataset.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def registra_cap_sample(instance: str, tipo: str, livello: int,
                        capacita: int) -> None:
    """Append 1 record JSONL.

    Args:
        instance: nome istanza ("FAU_07" / "FauMorfeus" / ...)
        tipo:     "campo" | "segheria" | "acciaio" | "petrolio"
        livello:  6 / 7 / -1 se non letto
        capacita: valore Quantity letto da OCR popup, -1 se OCR fallita

    Non solleva eccezioni: errore I/O = silent skip (logging best-effort).
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "instance": instance,
        "tipo": tipo,
        "livello": livello,
        "capacita": capacita,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _lock:
            with _dataset_path().open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        # Silent: non rompere il task se il dataset non è scrivibile
        pass
