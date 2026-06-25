# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/store_position.py
#
#  Posizione memorizzata dell'edificio Mysterious Merchant Store, per istanza.
#
#  L'edificio è fisso nel mondo di gioco per ogni istanza (la base non si
#  sposta mai). Lo scan a griglia spirale (`tasks/store.py`, fino a 25 passi,
#  early-exit a score>=0.80) per ritrovarlo ad ogni esecuzione è costoso
#  (~20-40s anche con early-exit) quando la posizione è già nota.
#
#  Regola (WU172): prova prima l'offset di swipe (dx,dy) memorizzato
#  dall'ultimo ritrovamento riuscito — un'unica sequenza di swipe diretta
#  + 1 screenshot — invece dello scan completo. Se la verifica fallisce
#  (es. mappa scrollata da un altro task, drift) → fallback allo scan
#  classico, che poi aggiorna la memoria con la nuova posizione trovata.
#
#  Seed iniziale (23/06/2026): valori mined dai log storici di produzione
#  (passo con punteggio più alto per istanza, "*** match ***" su più giorni).
#  Risultato: passo 7 → offset (0,+300) vincente per 10/11 istanze, passo 8
#  → offset (+300,+300) per FAU_07. Da qui in avanti la memoria si aggiorna
#  da sola ad ogni esecuzione del task.
#
#  Storage: data/store_position.json (atomic write tmp+fsync+os.replace)
#  Schema:
#    {
#      "FAU_00": {"dx": 0, "dy": 300, "score": 0.807, "ts": "2026-...+00:00"},
#      ...
#    }
#
#  Failsafe: tutte le funzioni catturano eccezioni — un disco pieno o un
#  file corrotto non deve mai bloccare il task store (fallback allo scan).
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _path() -> Path:
    """Risolve il path del file store_position.json — coerente con orchestrator."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "store_position.json"


def load(instance_name: str) -> Optional[dict]:
    """
    Ritorna {"dx": int, "dy": int, "score": float, "ts": str} per l'istanza,
    o None se non memorizzata / file assente / corrotto.
    """
    try:
        path = _path()
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pos = data.get(instance_name)
        if not isinstance(pos, dict) or "dx" not in pos or "dy" not in pos:
            return None
        return {
            "dx":    int(pos["dx"]),
            "dy":    int(pos["dy"]),
            "score": float(pos.get("score", 0.0)),
            "ts":    str(pos.get("ts", "")),
        }
    except Exception:
        return None


def save(instance_name: str, dx: int, dy: int, score: float) -> bool:
    """
    Aggiorna la posizione memorizzata per l'istanza. Merge con le altre
    istanze già presenti nel file. Atomic write, best-effort (non solleva).
    """
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        data[instance_name] = {
            "dx":    int(dx),
            "dy":    int(dy),
            "score": round(float(score), 4),
            "ts":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False
