# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/produzione_report.py                       WU204
#
#  Fonte di verità CANONICA per la produzione oraria per-istanza calcolata dal
#  Tab Report (resa reale dei nodi raccolti), immune alle anomalie della metrica
#  castello (produzione_storico = Δcastello − zaino + rifornimento_inviato, che
#  un rifornimento/zaino gonfia enormemente — es. FAU_00 = 209 M/h per un
#  rifornimento_inviato.petrolio = 999M pari al cap di config).
#
#  Somma `quantita_totale` (base + bonus alleanza) da
#  data/report_raccolta_dataset.jsonl per (istanza, risorsa), mappando i nomi
#  dei nodi (campo/segheria) ai nomi risorsa (pomodoro/legno), con pesi
#  pomodoro-equivalente {pomodoro:1, legno:1, acciaio:2, petrolio:5} (coerenti
#  con shared/prod_unificata.py::PESI).
#
#  Due modalità:
#    - giorno="YYYY-MM-DD" (UTC): aggrega i report con `ts_raccolta` in quel
#      giorno, denominatore 24h  (per il daily report di una data specifica).
#    - altrimenti: finestra rolling ultime `window_h` ore, denominatore window_h
#      (per dashboard / telegram "tasso corrente").
#
#  NB semantica: misura SOLO la resa della raccolta (non produzione passiva
#  edifici / ricompense) — per questa farm >90% della produzione. Include TUTTE
#  le istanze presenti nel report (master compreso): l'esclusione del master
#  dagli aggregati e il completamento a zero delle istanze senza dati sono
#  responsabilità del chiamante.
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

RISORSE = ("pomodoro", "legno", "acciaio", "petrolio")
PESI: dict[str, float] = {"pomodoro": 1.0, "legno": 1.0, "acciaio": 2.0, "petrolio": 5.0}
# I report usano i nomi dei nodi; li mappiamo ai nomi risorsa.
_TIPO2RISORSA = {"campo": "pomodoro", "segheria": "legno",
                 "acciaio": "acciaio", "petrolio": "petrolio"}


def _root(root: Optional[str] = None) -> Path:
    if root:
        return Path(root)
    env = os.environ.get("DOOMSDAY_ROOT")
    return Path(env) if env else Path(os.getcwd())


def _path_report(root: Optional[str] = None) -> Path:
    return _root(root) / "data" / "report_raccolta_dataset.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(s)
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def produzione_per_istanza(giorno: Optional[str] = None,
                           window_h: float = 24.0,
                           root: Optional[str] = None) -> dict:
    """Produzione oraria per istanza dal Tab Report. Vedi header modulo.

    Ritorna:
        {
          "per_istanza": {
              inst: {"risorse":  {risorsa: qta_totale},
                     "qta_h":    {risorsa: qta_totale / den_h},
                     "pom_eq_h": M pom-eq / h,
                     "n_report": int},
              ...
          },
          "den_h":    float,               # denominatore orario usato
          "modalita": "giorno" | "rolling",
        }
    """
    rows = _load_jsonl(_path_report(root))

    if giorno:
        modalita = "giorno"
        den_h = 24.0

        def _in_finestra(t: datetime) -> bool:
            return t.astimezone(timezone.utc).strftime("%Y-%m-%d") == giorno
    else:
        modalita = "rolling"
        den_h = float(window_h) if window_h > 0 else 24.0
        cutoff = datetime.now(timezone.utc) - timedelta(hours=den_h)

        def _in_finestra(t: datetime) -> bool:
            return t >= cutoff

    agg: dict[str, dict[str, float]] = {}
    n_report: dict[str, int] = {}
    for r in rows:
        t = _parse_ts(r.get("ts_raccolta") or "")
        if t is None or not _in_finestra(t):
            continue
        ris = _TIPO2RISORSA.get(r.get("tipo"))
        inst = r.get("instance")
        q = r.get("quantita_totale")
        if not inst or not ris or not isinstance(q, (int, float)):
            continue
        d = agg.setdefault(inst, {})
        d[ris] = d.get(ris, 0.0) + float(q)
        n_report[inst] = n_report.get(inst, 0) + 1

    per_istanza: dict[str, dict] = {}
    for inst, d in agg.items():
        risorse = {r: d.get(r, 0.0) for r in RISORSE}
        pom_eq = sum(risorse[r] * PESI[r] for r in RISORSE)
        per_istanza[inst] = {
            "risorse":  risorse,
            "qta_h":    {r: risorse[r] / den_h for r in RISORSE},
            "pom_eq_h": pom_eq / den_h / 1_000_000,
            "n_report": n_report.get(inst, 0),
        }

    return {"per_istanza": per_istanza, "den_h": den_h, "modalita": modalita}
