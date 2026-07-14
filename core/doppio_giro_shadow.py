"""core/doppio_giro_shadow.py — WU218 SHADOW osservativo del "doppio giro".

Valuta, a FINE ciclo, se l'istanza candidata (FAU_00, la più veloce) avrebbe
qualificato per un 2° passaggio raccolta-only nello stesso ciclo — cioè se i
suoi raccoglitori sono già rientrati (slack) e ha abbastanza slot liberi da
giustificare il boot.

PURA OSSERVAZIONE: non esegue nulla, non altera il ciclo. Scrive solo
`data/doppio_giro_shadow.jsonl` (1 riga/ciclo) + una riga in bot.log. Serve a
raccogliere su ~1 settimana la **fire-rate** reale + gli **slot liberi** per
chiudere il cost/benefit (Fase 0) prima di decidere se attivare il 2° passaggio
live.

Analisi offline attesa (dopo N cicli):
  - % cicli con qualifica = SI  (quanto spesso scatterebbe)
  - slot liberi medi quando scatta  (quanto rende)
  - correlazione con durata_giro   (scatta nei giri lunghi, come atteso)
  - netto = (slot × capacità FAU_00) − (costo giro esteso × altre istanze)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Istanza candidata: la più veloce (raccolta ~2h09m vs ~2h48m delle altre) →
# unica con slack reale in un giro fisso. NON generalizzare a soglia (se tutte
# diventassero veloci lo slack sparirebbe — vedi ragionamento WU218).
CANDIDATO = "FAU_00"

# Soglie di qualifica (allineate all'analisi Fase 0):
#  - elapsed: i raccoglitori di FAU_00 rientrano a ~129min; 120 dà un margine.
#  - slot:    rilanciare per <3 slot non ripaga il boot (~10min).
SOGLIA_ELAPSED_MIN = 120.0
SOGLIA_SLOT = 3


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def valuta_shadow(ciclo: int, durata_giro_s: float = 0.0, log_fn=None) -> None:
    """Osserva (senza eseguire) se il candidato avrebbe un 2° passaggio.

    Chiamata a fine ciclo dal main loop. Failsafe totale: qualsiasi errore →
    no-op silenzioso (non deve mai impattare il ciclo)."""
    try:
        from core.adaptive_scheduler import compute_slot_liberi_atteso
        s = compute_slot_liberi_atteso(CANDIDATO, t_offset_min=0.0)
    except Exception:
        return

    elapsed = float(s.get("elapsed_min") if s.get("elapsed_min") is not None else -1)
    free_now = int(s.get("slot_liberi_now") or 0)
    free_att = int(s.get("slot_liberi_atteso") or 0)
    totali = int(s.get("totali") or 0)

    # Gate sulla PREDIZIONE (slot_liberi_atteso), non su slot_liberi_now: al
    # punto d'inserimento del 2° passaggio non possiamo leggere gli slot reali
    # senza boot, quindi la decisione si basa sulla stima dei rientri (come farà
    # il 2° passaggio live). `slot_liberi_now` è la lettura post-dispaccio (spesso
    # stantia = 0) → la registro solo per confronto.
    qualifica = elapsed >= SOGLIA_ELAPSED_MIN and free_att >= SOGLIA_SLOT

    rec = {
        "ts":                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ciclo":              ciclo,
        "candidato":          CANDIDATO,
        "elapsed_min":        round(elapsed, 1),
        "slot_liberi_now":    free_now,
        "slot_liberi_atteso": free_att,
        "totali":             totali,
        "durata_giro_s":      int(durata_giro_s or 0),
        "qualifica":          qualifica,
    }

    try:
        p = _root() / "data" / "doppio_giro_shadow.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if log_fn is not None:
        try:
            log_fn(
                f"[DOPPIO-GIRO-SHADOW] {CANDIDATO}: elapsed={elapsed:.0f}m "
                f"free_now={free_now}/{totali} atteso={free_att} · "
                f"giro={int((durata_giro_s or 0) // 60)}m → "
                f"2°passaggio={'SI' if qualifica else 'no'} "
                f"(soglie elapsed≥{SOGLIA_ELAPSED_MIN:.0f}m slot≥{SOGLIA_SLOT})"
            )
        except Exception:
            pass
