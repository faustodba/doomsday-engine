# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/logger.py
#
#  Logger strutturato per il bot. Ogni messaggio è un dict JSON con campi
#  fissi (timestamp, level, instance, module, message) più campi extra opzionali.
#
#  Classi:
#    LogLevel        — enum livelli (DEBUG, INFO, WARNING, ERROR)
#    StructuredLogger — logger per una singola istanza, scrive su file e console
#    get_logger()    — factory globale (un logger per instance_name)
#
#  Design:
#    - Un file di log per istanza: logs/{instance_name}.jsonl
#    - Formato JSONL (JSON Lines) — una riga JSON per messaggio
#    - Rotazione automatica al superamento di max_bytes (default 5 MB)
#    - Console output opzionale con colori ANSI (disabilitabile)
#    - Thread-safe tramite threading.Lock
#    - Nessuna dipendenza da device.py o state.py
# ==============================================================================

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any


# ==============================================================================
# LogLevel
# ==============================================================================

class LogLevel(IntEnum):
    DEBUG   = 10
    INFO    = 20
    WARNING = 30
    ERROR   = 40

    def label(self) -> str:
        return self.name


# ==============================================================================
# Colori ANSI per console
# ==============================================================================

_ANSI = {
    LogLevel.DEBUG:   "\033[36m",   # cyan
    LogLevel.INFO:    "\033[32m",   # green
    LogLevel.WARNING: "\033[33m",   # yellow
    LogLevel.ERROR:   "\033[31m",   # red
}
_RESET = "\033[0m"


# ==============================================================================
# StructuredLogger
# ==============================================================================

class StructuredLogger:
    """
    Logger strutturato per una singola istanza del bot.

    Scrive messaggi in formato JSONL su file, con rotazione automatica
    al superamento di max_bytes. Opzionalmente stampa anche su console.

    Esempio di riga JSON prodotta:
        {
          "ts": "2026-04-10T08:30:00.123456+00:00",
          "level": "INFO",
          "instance": "FAU_00",
          "module": "raccolta",
          "msg": "Marcia inviata verso pomodoro",
          "coord": [540, 320],
          "score": 0.91
        }
    """

    def __init__(
        self,
        instance_name: str,
        log_dir: str | Path = "logs",
        min_level: LogLevel = LogLevel.DEBUG,
        max_bytes: int = 5 * 1024 * 1024,   # 5 MB
        console: bool = True,
        colors: bool = True,
    ):
        self.instance_name = instance_name
        self.log_dir       = Path(log_dir)
        self.min_level     = min_level
        self.max_bytes     = max_bytes
        self.console       = console
        self.colors        = colors

        self._lock = threading.Lock()
        self._file = None
        self._file_path: Path | None = None
        self._open_file()

    # ── File management ───────────────────────────────────────────────────────

    def _open_file(self) -> None:
        """Apre (o crea) il file di log corrente."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self.log_dir / f"{self.instance_name}.jsonl"
        self._file = open(self._file_path, "a", encoding="utf-8", buffering=1)

    def _rotate_if_needed(self) -> None:
        """Ruota il file se supera max_bytes."""
        if self._file_path is None or not self._file_path.exists():
            return
        if self._file_path.stat().st_size < self.max_bytes:
            return
        # Chiude il file corrente
        self._file.close()
        # Rinomina in .jsonl.1 (sovrascrive eventuale backup precedente)
        backup = self._file_path.with_suffix(".jsonl.1")
        self._file_path.replace(backup)
        # Riapre su file nuovo vuoto
        self._open_file()

    def close(self) -> None:
        """Chiude il file di log. Da chiamare alla fine del ciclo vita."""
        with self._lock:
            if self._file and not self._file.closed:
                self._file.close()

    # ── Core write ────────────────────────────────────────────────────────────

    def _write(
        self,
        level: LogLevel,
        module: str,
        message: str,
        **extra: Any,
    ) -> None:
        if level < self.min_level:
            return

        record: dict[str, Any] = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "level":    level.label(),
            "instance": self.instance_name,
            "module":   module,
            "msg":      message,
        }
        if extra:
            record.update(extra)

        line = json.dumps(record, ensure_ascii=False, default=str)

        with self._lock:
            self._rotate_if_needed()
            self._file.write(line + "\n")

            if self.console:
                self._print_console(level, record)

    def _print_console(self, level: LogLevel, record: dict) -> None:
        ts_short = record["ts"][11:23]   # HH:MM:SS.mmm
        prefix = f"[{ts_short}][{record['instance']:<12}][{record['module']:<16}]"
        msg = record["msg"]

        # Campi extra (escludi i fissi)
        extra_keys = {k for k in record if k not in ("ts", "level", "instance", "module", "msg")}
        extra_str = ""
        if extra_keys:
            parts = [f"{k}={record[k]!r}" for k in sorted(extra_keys)]
            extra_str = "  " + "  ".join(parts)

        line = f"{prefix} {msg}{extra_str}"

        if self.colors:
            color = _ANSI.get(level, "")
            print(f"{color}{line}{_RESET}", flush=True)
        else:
            print(line, flush=True)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def debug(self, module: str, message: str, **extra: Any) -> None:
        self._write(LogLevel.DEBUG, module, message, **extra)

    def info(self, module: str, message: str, **extra: Any) -> None:
        self._write(LogLevel.INFO, module, message, **extra)

    def warning(self, module: str, message: str, **extra: Any) -> None:
        self._write(LogLevel.WARNING, module, message, **extra)

    def error(self, module: str, message: str, **extra: Any) -> None:
        self._write(LogLevel.ERROR, module, message, **extra)

    def log(self, level: LogLevel, module: str, message: str, **extra: Any) -> None:
        """Versione generica con livello esplicito."""
        self._write(level, module, message, **extra)

    def __repr__(self) -> str:
        return (
            f"StructuredLogger(instance={self.instance_name!r}, "
            f"level={self.min_level.label()}, "
            f"file={self._file_path})"
        )


# ==============================================================================
# Registry globale — un logger per instance_name
# ==============================================================================

_registry: dict[str, StructuredLogger] = {}
_registry_lock = threading.Lock()


def get_logger(
    instance_name: str,
    log_dir: str | Path = "logs",
    min_level: LogLevel = LogLevel.DEBUG,
    console: bool = True,
    colors: bool = True,
) -> StructuredLogger:
    """
    Factory globale: ritorna sempre lo stesso logger per instance_name.
    Se non esiste ancora, lo crea con i parametri forniti.

    Uso tipico nei task:
        log = get_logger("FAU_00")
        log.info("boost", "Speed boost applicato", durata_h=8)
    """
    with _registry_lock:
        if instance_name not in _registry:
            _registry[instance_name] = StructuredLogger(
                instance_name=instance_name,
                log_dir=log_dir,
                min_level=min_level,
                console=console,
                colors=colors,
            )
        return _registry[instance_name]


def close_all_loggers() -> None:
    """Chiude tutti i logger aperti. Da chiamare allo shutdown del bot."""
    with _registry_lock:
        for logger in _registry.values():
            logger.close()
        _registry.clear()
