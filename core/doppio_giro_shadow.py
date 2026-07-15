"""core/doppio_giro_shadow.py — WU218/WU221 "doppio giro" di FAU_00.

FAU_00 è l'unica istanza con raccolta nettamente più veloce (~2h09m vs ~2h48m)
→ in un giro fisso accumula slack (slot liberi mentre aspetta il giro dopo). Il
"doppio giro" la ri-schedula una 2ª volta nello stesso ciclo, in modalità
SOLO-RACCOLTA (come FauMorfeus), prima del master, per recuperare quello slack.

Questo modulo espone:
  - `valuta_qualifica(candidato)` → (bool, metrics): la logica di qualifica
    (raccoglitori rientrati via predizione + slot liberi ≥ soglia), condivisa
    da shadow (osserva) e live (esegue).
  - `doppio_giro_live_attivo()` → bool: flag `globali.doppio_giro_enabled`
    (default False). OFF ⇒ nessuna esecuzione, solo shadow → zero impatto.
  - `valuta_shadow(...)`: osserva (non esegue) e scrive
    `data/doppio_giro_shadow.jsonl` + log, per il cost/benefit (Fase 0).

Analisi offline (dopo N cicli): fire-rate, slot medi, correlazione con
durata_giro → netto M/giorno prima di attivare il live.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Istanza candidata: la più veloce (unica con slack reale in un giro fisso).
# NON generalizzare a soglia: se tutte diventassero veloci lo slack sparirebbe.
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


def doppio_giro_live_attivo() -> bool:
    """Flag `globali.doppio_giro_enabled` (default **False**).

    OFF ⇒ il 2° passaggio NON viene eseguito (resta solo lo shadow osservativo)
    → il ciclo è identico a prima. Letto a caldo dal runtime_overrides ad ogni
    valutazione (nessuna cache: si attiva/disattiva senza restart)."""
    try:
        p = _root() / "config" / "runtime_overrides.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        return bool((d.get("globali") or {}).get("doppio_giro_enabled", False))
    except Exception:
        return False


def valuta_qualifica(candidato: str = CANDIDATO) -> tuple:
    """Valuta se `candidato` qualifica per un 2° passaggio raccolta-only ADESSO.

    Ritorna `(qualifica: bool, metrics: dict)`.
    Qualifica = i raccoglitori del 1° passaggio sono rientrati (elapsed dal loro
    dispaccio ≥ SOGLIA_ELAPSED_MIN, via predizione) **e** gli slot liberi PREVISTI
    (`slot_liberi_atteso`, non la lettura stantia `now`) ≥ SOGLIA_SLOT.

    Failsafe: su qualsiasi errore → (False, {}). Non deve mai bloccare il ciclo."""
    try:
        from core.adaptive_scheduler import compute_slot_liberi_atteso
        s = compute_slot_liberi_atteso(candidato, t_offset_min=0.0)
    except Exception:
        return False, {}

    elapsed = float(s.get("elapsed_min") if s.get("elapsed_min") is not None else -1)
    free_now = int(s.get("slot_liberi_now") or 0)
    free_att = int(s.get("slot_liberi_atteso") or 0)
    totali = int(s.get("totali") or 0)

    qualifica = elapsed >= SOGLIA_ELAPSED_MIN and free_att >= SOGLIA_SLOT
    return qualifica, {
        "elapsed_min":        round(elapsed, 1),
        "slot_liberi_now":    free_now,
        "slot_liberi_atteso": free_att,
        "totali":             totali,
    }


def valuta_shadow(ciclo: int, durata_giro_s: float = 0.0, log_fn=None) -> None:
    """Osserva (SENZA eseguire) se il candidato avrebbe un 2° passaggio a fine
    ciclo. Scrive `data/doppio_giro_shadow.jsonl` (1 riga/ciclo) + log. Failsafe
    totale: qualsiasi errore → no-op silenzioso."""
    qualifica, m = valuta_qualifica(CANDIDATO)
    if not m:
        return

    rec = {
        "ts":                 datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ciclo":              ciclo,
        "candidato":          CANDIDATO,
        "elapsed_min":        m["elapsed_min"],
        "slot_liberi_now":    m["slot_liberi_now"],
        "slot_liberi_atteso": m["slot_liberi_atteso"],
        "totali":             m["totali"],
        "durata_giro_s":      int(durata_giro_s or 0),
        "qualifica":          qualifica,
        "live_attivo":        doppio_giro_live_attivo(),
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
                f"[DOPPIO-GIRO-SHADOW] {CANDIDATO}: elapsed={m['elapsed_min']:.0f}m "
                f"free_now={m['slot_liberi_now']}/{m['totali']} "
                f"atteso={m['slot_liberi_atteso']} · "
                f"giro={int((durata_giro_s or 0) // 60)}m → "
                f"2°passaggio={'SI' if qualifica else 'no'} "
                f"(soglie elapsed≥{SOGLIA_ELAPSED_MIN:.0f}m slot≥{SOGLIA_SLOT})"
            )
        except Exception:
            pass
