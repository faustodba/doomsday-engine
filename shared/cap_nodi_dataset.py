# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/cap_nodi_dataset.py
#
#  Logger campioni capacità nodo + carico squadra durante raccolta.
#
#  Scrive 1 record JSONL per ogni nodo aperto (tap nodo + popup gather):
#    {ts, instance, tipo, livello, capacita, load_squadra}
#
#  - capacita -1     = OCR fallita (popup gather)
#  - capacita > 0    = quantità residua nodo (può essere < nominale = nodo già parz. raccolto)
#  - load_squadra -1 = OCR fallita / marcia non eseguita (es. slot pieni, no squads)
#  - load_squadra >0 = quanto effettivamente la squadra raccoglierà = min(squadra_max, cap_residuo)
#
#  Uso analitico (cfr tools/analisi_cap_nodi.py):
#    - max(capacita per (tipo, livello)) → capacità nominale
#    - capacita / max → % residuo
#    - load_squadra / capacita → 100% squadra satura il nodo, <100% squadra underprovisioned
#    - load_squadra / cap_nominale_max → copertura per istanza (KPI obiettivo training truppe)
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
from typing import Optional

_lock = threading.Lock()


# ==============================================================================
#  Capacità nominale nodo (senza extra/bonus) per (tipo, livello).
#  Fonte di verità condivisa: confermata sui dati reali del report
#  (report_raccolta_dataset.jsonl::quantita_base — identica su tutti i
#  campioni per cella). Usata da:
#    - core.skip_predictor._calc_t_marcia_min  (saturazione = load / cap)
#    - shared.tempo_raccolta_estimator         (proporzione tempo fra livelli)
#  Costante di gioco: cambia solo se il gioco ridefinisce i nodi.
# ==============================================================================
CAP_NOMINALE: dict[tuple[str, int], int] = {
    ("campo", 6):    1_200_000, ("campo", 7):    1_320_000,
    ("segheria", 6): 1_200_000, ("segheria", 7): 1_320_000,
    ("acciaio", 6):    600_000, ("acciaio", 7):    660_000,
    ("petrolio", 6):   240_000, ("petrolio", 7):   264_000,
}


def cap_nominale(tipo: str, livello) -> Optional[int]:
    """Capacità nominale (senza extra) per (tipo, livello). None se non nota."""
    try:
        return CAP_NOMINALE.get((tipo, int(livello)))
    except (TypeError, ValueError):
        return None


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
                        capacita: int, load_squadra: int = -1) -> None:
    """Append 1 record JSONL.

    Args:
        instance:     nome istanza ("FAU_07" / "FauMorfeus" / ...)
        tipo:         "campo" | "segheria" | "acciaio" | "petrolio"
        livello:      6 / 7 / -1 se non letto
        capacita:     valore Quantity letto da OCR popup gather, -1 se OCR fallita
        load_squadra: valore "Load" letto da OCR maschera invio, -1 se non
                      disponibile (marcia fallita prima della maschera, OCR fail).
                      Se >0 indica quanto la squadra raccoglierà effettivamente
                      = min(squadra_max_truppe, cap_residuo_nodo).

    Non solleva eccezioni: errore I/O = silent skip (logging best-effort).
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "instance": instance,
        "tipo": tipo,
        "livello": livello,
        "capacita": capacita,
        "load_squadra": load_squadra,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _lock:
            with _dataset_path().open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        # Silent: non rompere il task se il dataset non è scrivibile
        pass
