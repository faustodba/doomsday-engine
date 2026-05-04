"""
core/cycle_predictor_recorder.py — Snapshot periodici del cycle predictor +
valutazione accuracy a fine ciclo.

WU-CycleAccuracy (04/05/2026) — registra ogni 15 minuti la predizione corrente
di T_ciclo e a fine ciclo bot calcola l'errore % delle varie predizioni rispetto
al valore reale osservato (`data/telemetry/cicli.json::durata_s`).

Storage:
  - `data/predictions/cycle_snapshots.jsonl`  (append-only, 1 record per snapshot)
  - `data/predictions/cycle_accuracy.jsonl`   (1 record per ciclo completato)

Schema snapshot:
    {ts, cycle_numero (in corso al momento dello snapshot),
     elapsed_min (dall'inizio ciclo), T_ciclo_predicted_min, n_istanze,
     confidence}

Schema accuracy (post-cycle):
    {cycle_numero, ts_start, ts_end, actual_min,
     snapshots: [{elapsed_min, predicted_min, error_pct}],
     n_snapshots}

Uso operativo:
  - `record_snapshot()`: chiamato ogni 15min da scheduler dashboard
  - `evaluate_cycles()`: chiamato periodicamente per cicli completati non ancora valutati
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SNAPSHOT_INTERVAL_MIN = 15

_lock = threading.Lock()


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _snapshots_path() -> Path:
    p = _root() / "data" / "predictions" / "cycle_snapshots.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _accuracy_path() -> Path:
    p = _root() / "data" / "predictions" / "cycle_accuracy.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cicli_path() -> Path:
    return _root() / "data" / "telemetry" / "cicli.json"


def _read_cicli_in_corso() -> Optional[dict]:
    """
    Legge `cicli.json` e ritorna il ciclo corrente in corso (ultimo record
    senza end_ts oppure con `completato=False`). None se nessuno trovato.
    """
    try:
        path = _cicli_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        cicli = data.get("cicli", data) if isinstance(data, dict) else data
        if not cicli:
            return None
        # Ultimo non completato
        for c in reversed(cicli):
            if not c.get("completato") and not c.get("aborted"):
                return c
        return None
    except Exception:
        return None


def record_snapshot(predicted_min: float,
                    n_istanze: int,
                    confidence: str = "?",
                    input_context: Optional[dict] = None,
                    extra: Optional[dict] = None) -> bool:
    """
    Salva uno snapshot della predizione corrente in cycle_snapshots.jsonl.

    Args:
        predicted_min: T_ciclo predetto al momento dello snapshot
        n_istanze: numero istanze coinvolte
        confidence: alta/media/bassa
        input_context: dict opzionale con i parametri di input che hanno
                       prodotto la predizione (per analisi/debug):
            {
              "istanze_abilitate": list[str],
              "task_globali_abilitati": list[str],
              "tasks_per_istanza_due": dict[istanza, list[task]],
              "per_istanza_predicted_s": dict[istanza, float],  # breakdown
              "tick_sleep_s": float,
            }
            Permette analisi what-if: se skippo istanza X, T_ciclo - X.T_s.
        extra: dict opzionale aggiuntivo

    Auto-correla con il ciclo bot in corso (legge `cicli.json`):
      - cycle_numero: dal record corrente
      - elapsed_min: minuti dall'inizio del ciclo

    Returns:
        True se snapshot scritto, False se errore I/O.
    """
    now = datetime.now(timezone.utc)
    ciclo = _read_cicli_in_corso()
    cycle_numero = None
    elapsed_min = 0.0
    if ciclo:
        cycle_numero = ciclo.get("numero")
        try:
            start = datetime.fromisoformat(ciclo.get("start_ts", ""))
            elapsed_min = (now - start).total_seconds() / 60
        except Exception:
            pass

    record = {
        "ts": now.isoformat(),
        "cycle_numero": cycle_numero,
        "elapsed_min": round(elapsed_min, 2),
        "predicted_min": round(predicted_min, 2),
        "n_istanze": n_istanze,
        "confidence": confidence,
    }
    if input_context:
        record["input_context"] = input_context
    if extra:
        record["extra"] = extra
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _lock:
            with _snapshots_path().open("a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:
        return False


def get_snapshot_for_cycle(cycle_numero: int,
                            elapsed_min: Optional[float] = None) -> Optional[dict]:
    """
    Ritorna lo snapshot del ciclo specificato.

    Args:
        cycle_numero: numero ciclo
        elapsed_min: opzionale, se specificato cerca snapshot più vicino a
                     questo elapsed; altrimenti ritorna il primo (a inizio ciclo)

    Returns:
        Dict snapshot o None se non trovato.
    """
    rows = [r for r in _read_jsonl(_snapshots_path())
            if r.get("cycle_numero") == cycle_numero]
    if not rows:
        return None
    if elapsed_min is None:
        # Primo snapshot (elapsed_min minimo) = inizio ciclo
        rows.sort(key=lambda r: r.get("elapsed_min", 0))
        return rows[0]
    # Trova snapshot con elapsed_min più vicino al target
    return min(rows, key=lambda r: abs(r.get("elapsed_min", 0) - elapsed_min))


def get_all_snapshots_for_cycle(cycle_numero: int) -> list[dict]:
    """Ritorna tutti gli snapshot del ciclo, sorted asc per elapsed_min."""
    rows = [r for r in _read_jsonl(_snapshots_path())
            if r.get("cycle_numero") == cycle_numero]
    rows.sort(key=lambda r: r.get("elapsed_min", 0))
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def _read_completed_cycles() -> list[dict]:
    """Lista cicli completati da cicli.json."""
    try:
        data = json.loads(_cicli_path().read_text(encoding="utf-8"))
        cicli = data.get("cicli", data) if isinstance(data, dict) else data
        return [c for c in cicli if c.get("completato") and not c.get("aborted")]
    except Exception:
        return []


def _read_evaluated_cycle_numeros() -> set[int]:
    """Set numeri ciclo già valutati (in cycle_accuracy.jsonl)."""
    out = set()
    for r in _read_jsonl(_accuracy_path()):
        n = r.get("cycle_numero")
        if isinstance(n, int):
            out.add(n)
    return out


def evaluate_cycles() -> int:
    """
    Per ogni ciclo completato non ancora valutato:
    - Leggi snapshots che ricadono nel ciclo (correlazione cycle_numero)
    - Calcola actual_min = end_ts - start_ts
    - Per ogni snapshot, errore_pct = |predicted - actual| / actual × 100
    - Append a cycle_accuracy.jsonl

    Returns:
        Numero cicli valutati in questa chiamata.
    """
    completed = _read_completed_cycles()
    already = _read_evaluated_cycle_numeros()
    new_to_eval = [c for c in completed if c.get("numero") not in already]
    if not new_to_eval:
        return 0

    snapshots_all = _read_jsonl(_snapshots_path())
    n_evaluated = 0

    for c in new_to_eval:
        try:
            cn = c.get("numero")
            start = datetime.fromisoformat(c.get("start_ts", ""))
            end   = datetime.fromisoformat(c.get("end_ts", ""))
            actual_min = (end - start).total_seconds() / 60
            if actual_min <= 0:
                continue
        except Exception:
            continue

        # Snapshot del ciclo (filtrati per cycle_numero matching)
        snaps = [s for s in snapshots_all
                 if s.get("cycle_numero") == cn]
        snaps.sort(key=lambda s: s.get("elapsed_min", 0))

        # Calcola errore per ogni snapshot
        errors = []
        for s in snaps:
            pred = float(s.get("predicted_min", 0))
            err_pct = abs(pred - actual_min) / actual_min * 100 if actual_min > 0 else 0
            errors.append({
                "elapsed_min":   s.get("elapsed_min"),
                "predicted_min": s.get("predicted_min"),
                "error_pct":     round(err_pct, 1),
                "confidence":    s.get("confidence", "?"),
            })

        record = {
            "cycle_numero": cn,
            "ts_start":     c.get("start_ts"),
            "ts_end":       c.get("end_ts"),
            "actual_min":   round(actual_min, 1),
            "n_snapshots":  len(errors),
            "snapshots":    errors,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            with _lock:
                with _accuracy_path().open("a", encoding="utf-8") as f:
                    f.write(line)
            n_evaluated += 1
        except Exception:
            pass

    return n_evaluated


# ──────────────────────────────────────────────────────────────────────────────
# Read API per dashboard
# ──────────────────────────────────────────────────────────────────────────────

def read_recent_accuracy(n_cycles: int = 10) -> list[dict]:
    """Ultimi N cicli valutati (desc per cycle_numero)."""
    rows = _read_jsonl(_accuracy_path())
    rows.sort(key=lambda r: r.get("cycle_numero", 0), reverse=True)
    return rows[:n_cycles]


def read_recent_snapshots(n: int = 50) -> list[dict]:
    """Ultimi N snapshot in tutti i cicli (desc per ts)."""
    rows = _read_jsonl(_snapshots_path())
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return rows[:n]
