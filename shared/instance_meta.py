"""
shared/instance_meta.py — metadati statici per categorizzare le istanze.

L'istanza MASTER è un rifugio destinatario: riceve risorse via rifornimento
dalle altre istanze ma non ne invia, va esclusa dai ranking/aggregati delle
istanze ordinarie (telemetria, predictor, dashboard analytics).

WU121 (04/05): hardcoded `_HARDCODED_MASTERS = frozenset({"FauMorfeus"})`.
Pre-WU121 leggeva il flag `master: bool` da `instances.json` /
`runtime_overrides.json`, ma utente ha richiesto eliminazione del check UI
per evitare misclick (toggle accidentale che escludeva master da aggregati).
Il check UI è stato rimosso e l'identità master è cablata nel codice —
modificabile solo da PR/commit, non runtime. Per cambiare master nel
futuro basta editare `_HARDCODED_MASTERS` in questo file.

API:
  is_master_instance(nome)  -> bool      # check vs _HARDCODED_MASTERS
  get_master_instances()    -> set[str]  # set hardcoded
  filter_ordinary(istanze)  -> list[str] # rimuove i master, preserva ordine
  invalidate_cache()                     # no-op (compat — niente da invalidare)
"""

from __future__ import annotations


# WU121 — Set master cablato nel codice. Modificare qui per cambiare master
# (richiede PR/commit, non modificabile runtime). Eliminato il check UI per
# evitare misclick accidentali che escludevano FauMorfeus da aggregati.
_HARDCODED_MASTERS: frozenset[str] = frozenset({"FauMorfeus"})


def invalidate_cache() -> None:
    """No-op (compat con caller esistenti). Nessuna cache da invalidare."""
    pass


def get_master_instances() -> frozenset[str]:
    """Set immutabile dei nomi istanza master (cablato nel codice)."""
    return _HARDCODED_MASTERS


def is_master_instance(nome: str | None) -> bool:
    """True se l'istanza è un rifugio destinatario (no aggregati ordinari)."""
    if not nome:
        return False
    return nome in _HARDCODED_MASTERS


def filter_ordinary(istanze: list[str]) -> list[str]:
    """Rimuove le istanze master, preserva l'ordine originale."""
    return [n for n in istanze if n not in _HARDCODED_MASTERS]
