# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/services/log_reader.py
#
#  Read-only — tail di bot.log e logs/FAU_XX.jsonl per la dashboard UI.
#
#  API pubblica:
#    get_bot_log(n=100)                                 -> list[str]
#    get_instance_log(nome, n=200)                      -> list[dict]
#    get_instance_log_filtered(nome, n, level, module)  -> list[dict]
#    get_instance_errors(nome, n=100)                   -> list[dict]
#
#  Schema jsonl per istanza: {ts, level, instance, module, msg}
#  Righe non JSON vengono incluse come {msg: raw, level: "RAW", ts: "", module: ""}.
#
#  _tail_lines e' ottimizzato: seek dalla fine, blocchi da 8KB — non carica
#  l'intero file in memoria (utile su bot.log/FAU_XX.jsonl da diversi MB).
# ==============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# ==============================================================================
# Path costanti — coerenti con main.py
# ==============================================================================
# dashboard/services/log_reader.py -> parents: [services, dashboard, project root]
_ROOT     = Path(__file__).parent.parent.parent
_BOT_LOG  = _ROOT / "bot.log"
_LOGS_DIR = _ROOT / "logs"


# ==============================================================================
# Helpers
# ==============================================================================

def _tail_lines(path: Path, n: int) -> list[str]:
    """
    Legge le ultime n righe di un file di testo in modo efficiente
    (senza caricare l'intero file in memoria).

    Strategia: seek dalla fine, leggi blocchi da 8KB finche' non ci sono
    abbastanza righe. Gestisce correttamente righe a cavallo di blocco
    (concateno il resto del blocco precedente come prefisso).

    Failsafe: [] su file mancante, vuoto, o errore.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return []
        with open(path, "rb") as f:
            block = 8192
            lines_found: list[bytes] = []
            remainder = b""
            pos = size
            while pos > 0 and len(lines_found) < n + 1:
                read_size = min(block, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size) + remainder
                lines_in_chunk = chunk.split(b"\n")
                remainder = lines_in_chunk[0]
                lines_found = lines_in_chunk[1:] + lines_found
            if remainder:
                lines_found = [remainder] + lines_found
            # Filtra righe vuote (es. ultimo \n del file) PRIMA dello slice
            # altrimenti un '\n' finale consuma uno slot di tail[-n:].
            # Rimuovi anche '\r' residuo su file Windows CRLF.
            nonempty = [l.rstrip(b"\r") for l in lines_found if l.rstrip(b"\r")]
            tail = nonempty[-n:] if len(nonempty) >= n else nonempty
            return [l.decode("utf-8", errors="replace") for l in tail]
    except Exception:
        return []


# ==============================================================================
# API pubblica
# ==============================================================================

def get_bot_log(n: int = 100) -> list[str]:
    """
    Restituisce le ultime n righe di bot.log come lista di stringhe.
    Failsafe: [] su errore.
    """
    return _tail_lines(_BOT_LOG, n)


def get_instance_log(nome: str, n: int = 200) -> list[dict]:
    """
    Restituisce le ultime n entry di logs/FAU_XX.jsonl come lista di dict.
    Ogni entry valida ha schema: {ts, level, instance, module, msg}.
    Righe non parsabili come JSON vengono incluse come:
        {msg: raw_line, level: "RAW", ts: "", module: ""}
    Failsafe: [] su file mancante o errore.
    """
    path = _LOGS_DIR / f"{nome}.jsonl"
    lines = _tail_lines(path, n)
    result: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except Exception:
            result.append({"msg": line, "level": "RAW", "ts": "", "module": ""})
    return result


def get_instance_log_filtered(
    nome: str,
    n: int = 500,
    level: Optional[str] = None,
    module: Optional[str] = None,
) -> list[dict]:
    """
    Come get_instance_log ma con filtri opzionali su level e module.
    Legge n righe dal fondo, poi filtra — il risultato puo' essere < n.
    Utile per la dashboard: filtrare solo ERROR, o solo module=task.
    """
    entries = get_instance_log(nome, n)
    if level:
        entries = [e for e in entries if e.get("level", "").upper() == level.upper()]
    if module:
        entries = [e for e in entries if e.get("module", "") == module]
    return entries


def get_instance_errors(nome: str, n: int = 100) -> list[dict]:
    """Shortcut: ultime n righe con level=ERROR di logs/FAU_XX.jsonl."""
    return get_instance_log_filtered(nome, n=500, level="ERROR")
