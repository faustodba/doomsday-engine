# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/nodi_mappa.py
#
#  Dataset osservazioni nodi mappa raccolta: coordinata (X_Y) -> tipo + livello.
#
#  Ipotesi utente (25/06/2026): un nodo terminato scompare, ma dopo un certo
#  periodo ne viene creato un altro nella stessa posizione — eventualmente di
#  tipo/livello diverso. Caso osservato: coordinata 696_532 registrata come
#  "campo" il 23/05 (blacklist_fuori_globale.json) ma "petrolio" in 46
#  osservazioni concordi a fine giugno — coerente con un respawn a distanza
#  di settimane, restando però stabile su scala di giorni.
#
#  FASE 1 (questo modulo): raccolta passiva delle osservazioni. Ogni volta
#  che `tasks/raccolta.py` legge chiave+tipo+livello da una ricerca CERCA
#  (nodo trovato/prenotato O scartato perché fuori territorio — in entrambi
#  i casi la lettura è certa, viene dalla stessa schermata), viene appesa una
#  osservazione. Nessun cambio al comportamento del task — solo osservabilità.
#  Il dataset si auto-alimenta al passare dei cicli su tutte le istanze
#  (mappa condivisa, confermato — vedi analisi 25/06).
#
#  FASE 2 (futura, NON implementata qui): quando il dataset è ritenuto
#  abbastanza completo/attendibile dall'utente, un sistema successivo userà
#  il catalogo aggregato (`tools/costruisci_catalogo_nodi.py`) per saltare
#  la scansione CERCA e navigare direttamente alla coordinata nota.
#
#  Esclusioni note: FauMorfeus (raccolta_only/master) ha lettura coordinate
#  NON attendibile — osservato 23/06: la lente legge ripetutamente la stessa
#  chiave (708_531, coincidente col proprio rifugio/castello) con 3 tipi
#  diversi in 16 minuti, segno di un bug nella lettura del popup coordinate
#  per quell'istanza specifica. Le sue osservazioni vengono scartate qui,
#  alla fonte — non solo nell'eventuale analisi successiva.
#
#  Storage: data/nodi_mappa_observations.jsonl (append-only, mai modificato
#  o compattato — è lo storico grezzo, ricostruibile in qualunque momento.
#  Gitignored come gli altri dataset *.jsonl del progetto — runtime-only).
#
#  Schema per riga:
#    {
#      "ts":       "2026-06-25T09:00:00.123456+00:00",
#      "instance": "FAU_03",
#      "chiave":   "699_550",
#      "cx":       699,
#      "cy":       550,
#      "tipo":     "segheria",
#      "livello":  6,
#      "esito":    "trovato" | "fuori_territorio"
#    }
#
#  Failsafe: tutte le funzioni catturano eccezioni — un disco pieno o un
#  permesso negato non deve mai bloccare il task raccolta.
# ==============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Istanze le cui osservazioni coordinate sono note come non attendibili.
ISTANZE_ESCLUSE = frozenset({"FauMorfeus"})

_ESITI_VALIDI = frozenset({"trovato", "fuori_territorio"})


def _path() -> Path:
    """Risolve il path del file nodi_mappa_observations.jsonl."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "nodi_mappa_observations.jsonl"


def registra_osservazione(
    instance_name: str,
    chiave: str,
    tipo: str,
    livello: int,
    esito: str,
) -> bool:
    """
    Appende una osservazione (chiave, tipo, livello) al dataset grezzo.

    Scarta silenziosamente (ritorna False, nessuna eccezione) se:
      - chiave non valida (None, vuota, formato non "X_Y")
      - istanza in ISTANZE_ESCLUSE (lettura coordinate non attendibile)
      - esito non riconosciuto

    Ritorna True se la riga è stata scritta su disco.
    """
    try:
        if not chiave or "_" not in chiave:
            return False
        if instance_name in ISTANZE_ESCLUSE:
            return False
        if esito not in _ESITI_VALIDI:
            return False

        cx_s, cy_s = chiave.split("_", 1)
        cx, cy = int(cx_s), int(cy_s)

        record = {
            "ts":       datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "instance": str(instance_name),
            "chiave":   chiave,
            "cx":       cx,
            "cy":       cy,
            "tipo":     str(tipo),
            "livello":  int(livello),
            "esito":    str(esito),
        }

        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False
