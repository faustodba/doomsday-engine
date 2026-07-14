"""shared/rifornimento_livelli.py — lookup livelli edificio trasporto (WU213).

Legge `config/rifornimento_livelli_trasporto.json` (WU212) con cache invalidata
su mtime. Fornisce i valori DETERMINISTICI di invio per livello, sostituendo
l'OCR del valore clampato dalla maschera (inaffidabile: leggeva 999M/garbage
per FAU_00 — vedi analisi bug).

Semantica (v2, verificata dal log):
  capacita_trasporto = NETTO che arriva al master (valore tabella gioco)
  lordo_debitato     = capacita/(1-tassa) = "capacita + tassa" = quanto esce
                       dal castello mittente = SOGLIA minima di deposito
  netto = lordo * (1 - tassa)  →  netto == capacita_trasporto

Il livello per istanza sta in config: `livello_trasporto` (WU211), letto dal bot
come `ctx.config.livello_trasporto`.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_CACHE: dict = {"mtime": None, "livelli": None}

_MIN_LIV = 1
_MAX_LIV = 25
_LIV_DEFAULT = 20   # coerente con config_loader._InstanceCfg.livello_trasporto


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _path() -> Path:
    return _root() / "config" / "rifornimento_livelli_trasporto.json"


def _carica() -> dict:
    """Ritorna il dict `livelli` (chiave = livello str). Cache su mtime_ns."""
    p = _path()
    try:
        mtime = p.stat().st_mtime_ns
    except Exception:
        return {}
    with _LOCK:
        if _CACHE["mtime"] == mtime and _CACHE["livelli"] is not None:
            return _CACHE["livelli"]
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            livelli = raw.get("livelli") or {}
        except Exception:
            livelli = {}
        _CACHE["mtime"] = mtime
        _CACHE["livelli"] = livelli
        return livelli


def _clamp(livello) -> int:
    try:
        liv = int(livello)
    except Exception:
        liv = _LIV_DEFAULT
    return max(_MIN_LIV, min(_MAX_LIV, liv))


def dati_livello(livello: int) -> Optional[dict]:
    """Dict completo del livello (clampato 1-25). None se tabella assente."""
    return _carica().get(str(_clamp(livello)))


def netto_al_master(livello: int) -> Optional[int]:
    """Risorse ricevute dal master per spedizione (= capacita_trasporto)."""
    r = dati_livello(livello)
    return int(r["capacita_trasporto"]) if r else None


def lordo_debitato(livello: int) -> Optional[int]:
    """Risorse che escono dal castello mittente per spedizione (= soglia)."""
    r = dati_livello(livello)
    return int(r["lordo_debitato"]) if r else None


def tassa_pct(livello: int) -> Optional[int]:
    r = dati_livello(livello)
    return int(r["tassa_pct"]) if r else None


def tassa_importo(livello: int) -> Optional[int]:
    r = dati_livello(livello)
    return int(r["tassa_importo"]) if r else None


def soglia_minima_m(livello: int) -> Optional[float]:
    """Soglia MINIMA di deposito (in Milioni) per garantire un invio al massimo
    = lordo_debitato / 1e6. Sotto questa il gioco clampa a meno (invio parziale)
    e la contabilita' deterministica non varrebbe piu'."""
    lordo = lordo_debitato(livello)
    return round(lordo / 1_000_000, 4) if lordo is not None else None


def soglia_minima_richiesta_m(livelli) -> tuple:
    """Dato un iterabile di livelli istanza, ritorna (soglia_minima_m, livello):
    la soglia di deposito minima (in Milioni) che garantisce un invio al massimo
    per TUTTE le istanze = max( soglia_minima_m(liv) ), col livello che la guida.
    (None, None) se l'iterabile e' vuoto o la tabella e' assente.

    Usato dal vincolo dashboard (WU213): una soglia sotto questo valore
    provocherebbe invii parziali sull'istanza col livello piu' alto, rompendo
    la contabilita' deterministica."""
    best_m = None
    best_liv = None
    for liv in (livelli or []):
        m = soglia_minima_m(liv)
        if m is None:
            continue
        if best_m is None or m > best_m:
            best_m = m
            best_liv = _clamp(liv)
    return best_m, best_liv
