# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/morfeus_state.py
#
#  Stato globale del destinatario rifornimento (FauMorfeus o altro account).
#  Tutte le istanze inviano allo STESSO destinatario, quindi il "Daily
#  Receiving Limit" è un valore globale: l'ultima istanza che fa rifornimento
#  aggiorna il file, la dashboard e gli altri task lo leggono.
#
#  Storage: data/morfeus_state.json (atomic write tmp+fsync+os.replace)
#
#  Schema:
#    {
#      "daily_recv_limit": 52099994,
#      "ts":               "2026-04-27T13:25:14.123456+00:00",
#      "letto_da":         "FAU_03",
#      "tassa_pct":        0.24
#    }
#
#  Failsafe: tutte le funzioni catturano eccezioni — un disco pieno o un
#  permesso negato non deve bloccare il task di rifornimento.
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _state_path() -> Path:
    """Risolve il path del file morfeus_state.json — coerente con orchestrator."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "morfeus_state.json"


def save(daily_recv_limit: int,
         letto_da: str,
         tassa_pct: float | None = None) -> bool:
    """
    Aggiorna data/morfeus_state.json con l'ultimo Daily Receiving Limit letto.

    `daily_recv_limit` = RESIDUO corrente del master (= quanto può ancora
    ricevere oggi). 0 = saturo, valore > 0 = ricevibile residuo. Il valore
    decresce nella giornata, si resetta a mezzanotte UTC.

    08/05: traccia anche `daily_recv_limit_max` (max monotone osservato) +
    `daily_recv_limit_max_ts` (data UTC). Il max si resetta al cambio data UTC
    per stimare il limite TOTALE giornaliero (= residuo letto subito dopo
    reset). Usato dall'adaptive scheduler per calcolare la % residuo.

    Returns:
        True se salvato, False se fallito (silenzioso — non solleva).
    """
    try:
        if daily_recv_limit < 0:
            return False
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Max monotone con reset giornaliero UTC
        oggi_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prev_max = 0
        prev_max_date = ""
        try:
            if path.exists():
                with open(path, encoding="utf-8") as _f:
                    _prev = json.load(_f)
                prev_max      = int(_prev.get("daily_recv_limit_max", 0) or 0)
                prev_max_date = str(_prev.get("daily_recv_limit_max_date", "") or "")
        except Exception:
            pass
        if prev_max_date != oggi_utc:
            # Cambio giorno UTC → reset max monotone
            prev_max = 0
        new_max = max(prev_max, int(daily_recv_limit))

        payload = {
            "daily_recv_limit":          int(daily_recv_limit),
            "daily_recv_limit_max":      int(new_max),
            "daily_recv_limit_max_date": oggi_utc,
            "ts":                        datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "letto_da":                  str(letto_da or "?"),
        }
        if tassa_pct is not None:
            payload["tassa_pct"] = round(float(tassa_pct), 4)

        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load() -> Optional[dict]:
    """
    Legge data/morfeus_state.json. Ritorna None se file mancante o corrotto.
    """
    try:
        path = _state_path()
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
