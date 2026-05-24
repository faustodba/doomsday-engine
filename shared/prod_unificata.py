# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/prod_unificata.py
#
#  Produzione oraria unificata per istanza.
#
#  Metrica: M pomodoro-equivalente / ora attiva bot
#  Pesi derivati dai cap nominali L7 (nodo più comune in produzione):
#    pomodoro = 1.0  (base: 1.32M/nodo)
#    legno    = 1.0  (1.32M/nodo, identico)
#    acciaio  = 2.0  (1.32M / 660K)
#    petrolio = 5.0  (1.32M / 264K)
#
#  Fonte dati: data/istanza_metrics.jsonl (per-march cap_nodo + tick_total_s)
#  Finestra: ultime N ore (default 24h)
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT      = Path(__file__).parent.parent
_PROD_ROOT = Path(os.environ.get("DOOMSDAY_ROOT", str(_ROOT)))
_METRICS   = _PROD_ROOT / "data" / "istanza_metrics.jsonl"

# Mapping tipo raccolta (bot internal) → risorsa standard
_TIPO_TO_RISORSA: dict[str, str] = {
    "campo":    "pomodoro",
    "segheria": "legno",
    "acciaio":  "acciaio",
    "petrolio": "petrolio",
    # alias diretti (per robustezza)
    "pomodoro": "pomodoro",
    "legno":    "legno",
}

# Cap nominale (risorsa, livello) — fallback quando cap_nodo OCR = -1
_CAP_NOMINALE: dict[tuple[str, int], int] = {
    ("pomodoro", 6): 1_200_000,  ("pomodoro", 7): 1_320_000,
    ("legno",    6): 1_200_000,  ("legno",    7): 1_320_000,
    ("acciaio",  6):   600_000,  ("acciaio",  7):   660_000,
    ("petrolio", 6):   240_000,  ("petrolio", 7):   264_000,
}

# Pesi: cap_L7_pomodoro / cap_L7_risorsa
PESI: dict[str, float] = {
    "pomodoro": 1.0,
    "legno":    1.0,
    "acciaio":  2.0,
    "petrolio": 5.0,
}

_M = 1_000_000  # unità di misura output


def _empty_result() -> dict:
    return {
        "prod_unif_h":   -1.0,   # M pom-eq / h attiva  (-1 = dato non disponibile)
        "pom_eq_totale": 0,      # pom-eq assoluto raccolto nella finestra
        "ore_attive":    0.0,    # ore di attività bot nella finestra
        "n_invii":       0,      # marce contate nel calcolo
        "per_risorsa":   {},     # {risorsa: {cap_tot, n, pom_eq}}
    }


def compute_prod_unificata_all(hours: float = 24.0) -> dict[str, dict]:
    """
    Calcola prod_unif_h per TUTTE le istanze in un unico passaggio del file.
    Ritorna {istanza: result_dict}.
    """
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=hours)
    data: dict[str, dict] = {}   # {istanza: accumulatori}

    def _acc(istanza: str) -> dict:
        if istanza not in data:
            data[istanza] = {
                "pom_eq_totale": 0,
                "ore_attive":    0.0,
                "n_invii":       0,
                "per_risorsa":   {},
            }
        return data[istanza]

    try:
        if not _METRICS.exists():
            return {}
        with open(_METRICS, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue

                # Filtro finestra temporale
                ts_str = rec.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        continue
                except Exception:
                    continue

                istanza = rec.get("instance", "")
                if not istanza:
                    continue

                acc = _acc(istanza)
                acc["ore_attive"] += float(rec.get("tick_total_s", 0) or 0) / 3600.0

                for inv in rec.get("raccolta", {}).get("invii", []):
                    tipo    = str(inv.get("tipo", "")).lower()
                    livello = int(inv.get("livello") or 7)
                    risorsa = _TIPO_TO_RISORSA.get(tipo)
                    if not risorsa:
                        continue

                    cap = int(inv.get("cap_nodo") or -1)
                    if cap < 0:
                        cap = _CAP_NOMINALE.get(
                            (risorsa, livello),
                            _CAP_NOMINALE.get((risorsa, 7), 0)
                        )
                    if cap <= 0:
                        continue

                    peso   = PESI.get(risorsa, 1.0)
                    pom_eq = int(cap * peso)

                    acc["pom_eq_totale"] += pom_eq
                    acc["n_invii"]       += 1
                    pr = acc["per_risorsa"].setdefault(risorsa, {"cap_tot": 0, "n": 0, "pom_eq": 0})
                    pr["cap_tot"] += cap
                    pr["n"]       += 1
                    pr["pom_eq"]  += pom_eq

    except Exception:
        pass

    # Calcola prod_unif_h per ogni istanza
    result: dict[str, dict] = {}
    for istanza, acc in data.items():
        ore = acc["ore_attive"]
        peq = acc["pom_eq_totale"]
        if ore > 0 and peq > 0:
            prod_h = peq / ore / _M   # M pom-eq / h
        else:
            prod_h = -1.0
        result[istanza] = {
            "prod_unif_h":   round(prod_h, 3),
            "pom_eq_totale": peq,
            "ore_attive":    round(ore, 2),
            "n_invii":       acc["n_invii"],
            "per_risorsa":   acc["per_risorsa"],
        }
    return result


def compute_prod_unificata(istanza: str, hours: float = 24.0) -> dict:
    """Calcola prod_unif_h per una singola istanza. Usa il batch per efficienza."""
    all_results = compute_prod_unificata_all(hours=hours)
    return all_results.get(istanza, _empty_result())
