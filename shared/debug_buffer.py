"""
shared/debug_buffer.py — sistema di debug screenshot indipendente dal bot.

Architettura unificata per dump di screenshot a punti chiave durante l'esecuzione
di un task, con flush condizionale on fail/anomaly. Toggle hot-reload via config:
ogni task ha il proprio flag in `runtime_overrides.json::globali.debug_tasks.{task}`.

Uso tipico in un task:

    from shared.debug_buffer import DebugBuffer

    def run(self, ctx):
        debug = DebugBuffer.for_task(self.name(), ctx.instance_name)
        debug.snap("00_start", ctx.device.screenshot())
        # ... lavoro ...
        debug.snap("99_end", ctx.device.screenshot())
        ok = ...
        anomalia = ...
        debug.flush(success=ok, force=anomalia)
        return TaskResult(...)

Logica flush:
  - success=True  AND force=False → NO flush (clear buffer)
  - success=False (task tecnico fallito)   → flush
  - force=True    (anomalia task-specific) → flush

Storage: data/{task_name}_debug/{instance}_{ts}_{idx:02d}_{label}.png
Cleanup automatico: file >CLEANUP_DAYS giorni eliminati al boot del bot
                    (chiamare cleanup_old() da main.py o launcher).

Pattern config (runtime_overrides.json):
    "globali": {
        "debug_tasks": {
            "arena": false,
            "arena_mercato": false,
            "store": false,
            ...
        }
    }

Default: tutti False (no spreco disco). Hot-reload TTL 30s.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ── Config / cache ──────────────────────────────────────────────────────────

_CACHE: dict = {"flags": {}, "ts": 0.0}
_CACHE_TTL_S = 30.0
_CACHE_LOCK = threading.Lock()

CLEANUP_DAYS = 7   # file più vecchi di N giorni → eliminati da cleanup_old()


def _root() -> Path:
    """Root prod/dev (DOOMSDAY_ROOT env, fallback alla repo dev)."""
    env = os.environ.get("DOOMSDAY_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _read_json_safe(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_flags() -> dict[str, bool]:
    """
    Legge i flag debug per ogni task da runtime_overrides.json.
    Default: dict vuoto (nessun task in debug → tutti False).
    """
    ovr = _read_json_safe(_root() / "config" / "runtime_overrides.json") or {}
    debug_tasks = (ovr.get("globali") or {}).get("debug_tasks") or {}
    if not isinstance(debug_tasks, dict):
        return {}
    return {k: bool(v) for k, v in debug_tasks.items()}


def _refresh_if_stale() -> None:
    now = time.time()
    with _CACHE_LOCK:
        if now - _CACHE["ts"] >= _CACHE_TTL_S:
            _CACHE["flags"] = _compute_flags()
            _CACHE["ts"] = now


def invalidate_cache() -> None:
    """Forza ricalcolo al prossimo accesso (chiamato da PATCH endpoint)."""
    with _CACHE_LOCK:
        _CACHE["ts"] = 0.0


def is_debug_enabled(task_name: str) -> bool:
    """True se il task è abilitato per debug screenshot."""
    if not task_name:
        return False
    _refresh_if_stale()
    return bool(_CACHE["flags"].get(task_name, False))


def get_all_debug_status() -> dict[str, bool]:
    """Snapshot corrente dei flag debug (per dashboard listing)."""
    _refresh_if_stale()
    return dict(_CACHE["flags"])


def set_debug_enabled(task_name: str, enabled: bool) -> bool:
    """
    Modifica `globali.debug_tasks.{task_name}` in runtime_overrides.json
    e invalida la cache. Atomic write tmp+replace.

    Ritorna True se la scrittura ha avuto successo.
    """
    if not task_name:
        return False
    path = _root() / "config" / "runtime_overrides.json"
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        globali = d.setdefault("globali", {})
        debug_tasks = globali.setdefault("debug_tasks", {})
        debug_tasks[task_name] = bool(enabled)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        invalidate_cache()
        return True
    except Exception:
        return False


# ── Path helper ─────────────────────────────────────────────────────────────

def _debug_dir(task_name: str) -> Path:
    """Path data/{task}_debug/, creato se non esiste."""
    p = _root() / "data" / f"{task_name}_debug"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Buffer class ────────────────────────────────────────────────────────────

class DebugBuffer:
    """
    Buffer in-memory di screenshot per un task/istanza specifico.

    Costruzione tipica via factory `for_task()`. Se il task NON è enabled
    in config, ritorna un buffer "no-op" (snap silently scarta, flush no-op).

    Logica flush (chiamato a fine task):
      - success=True AND force=False → NO flush, clear buffer
      - success=False (task fail tecnico) → flush
      - force=True (anomalia task-specific) → flush sempre

    Tipico flow:
        debug = DebugBuffer.for_task("arena", "FAU_07")
        debug.snap("00_pre_battle", ctx.device.screenshot())
        # ... lavoro ...
        debug.snap("99_post_battle", ctx.device.screenshot())
        debug.flush(success=ok, force=False)
    """

    __slots__ = ("task_name", "instance_name", "_enabled", "_snapshots")

    def __init__(self, task_name: str, instance_name: str) -> None:
        self.task_name     = task_name
        self.instance_name = instance_name or "_unknown"
        self._enabled      = is_debug_enabled(task_name)
        self._snapshots: list = []   # [(label, frame_array)]

    @classmethod
    def for_task(cls, task_name: str, instance_name: str) -> "DebugBuffer":
        """Factory: ritorna un buffer enabled o no-op in base al config."""
        return cls(task_name, instance_name)

    @property
    def enabled(self) -> bool:
        """True se il debug è attivo per questo task (cached at construct)."""
        return self._enabled

    def snap(self, label: str, screen) -> None:
        """
        Aggiunge uno screenshot al buffer in-memory. No-op se disabled o screen None.

        `screen` deve essere il risultato di `ctx.device.screenshot()` o un
        oggetto compatibile con attributo `.frame` (numpy array BGR).
        """
        if not self._enabled or screen is None:
            return
        try:
            frame = getattr(screen, "frame", None)
            if frame is None:
                return
            self._snapshots.append((str(label), frame.copy()))
        except Exception:
            pass

    def snap_array(self, label: str, frame_array) -> None:
        """Variante per quando hai già un numpy array invece di screen object."""
        if not self._enabled or frame_array is None:
            return
        try:
            self._snapshots.append((str(label), frame_array.copy()))
        except Exception:
            pass

    def clear(self) -> None:
        """Scarta tutti gli snapshot accumulati senza flush."""
        self._snapshots.clear()

    def flush(self, success: bool = True, force: bool = False,
              log_fn=None) -> int:
        """
        Scrive snapshot su disco se condizioni soddisfatte. Buffer cleared dopo.

        Args:
            success: True se task tecnicamente OK, False se fallito
            force:   True per forzare flush (es. anomalia task-specific
                     anche se success=True). Default False.
            log_fn:  callable(str) opzionale per logging (es. ctx.log_msg)

        Logica flush:
          - not enabled → no-op
          - empty buffer → no-op
          - success=True AND force=False → clear (no flush, saving disk)
          - altrimenti → flush

        Ritorna numero di file scritti (0 se non flush).
        """
        if not self._enabled or not self._snapshots:
            self._snapshots.clear()
            return 0

        # Decisione flush
        should_flush = (not success) or force
        if not should_flush:
            self._snapshots.clear()
            return 0

        # Flush effettivo
        count = 0
        try:
            import cv2  # import locale per non rallentare boot bot se debug off
            ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            d = _debug_dir(self.task_name)
            for idx, (label, frame) in enumerate(self._snapshots):
                fname = f"{self.instance_name}_{ts_str}_{idx:02d}_{label}.png"
                cv2.imwrite(str(d / fname), frame)
                count += 1
            if log_fn is not None:
                log_fn(f"[DEBUG-{self.task_name}] flush {count} screenshot in {d}")
        except Exception as exc:
            if log_fn is not None:
                log_fn(f"[DEBUG-{self.task_name}] flush errore: {exc}")
        finally:
            self._snapshots.clear()
        return count


# ── Cleanup automatico ──────────────────────────────────────────────────────

def cleanup_old(days: int = CLEANUP_DAYS, log_fn=None) -> int:
    """
    Elimina file PNG >= `days` giorni in tutte le directory data/*_debug/.
    Da chiamare al boot del bot (best-effort, errori silenziati).

    Ritorna numero di file eliminati.
    """
    cutoff = time.time() - (days * 86400)
    data_dir = _root() / "data"
    if not data_dir.is_dir():
        return 0
    total_removed = 0
    for sub in data_dir.iterdir():
        if not sub.is_dir():
            continue
        if not sub.name.endswith("_debug"):
            continue
        for png in sub.glob("*.png"):
            try:
                if png.stat().st_mtime < cutoff:
                    png.unlink()
                    total_removed += 1
            except Exception:
                pass
    if log_fn is not None and total_removed > 0:
        log_fn(f"[DEBUG-CLEANUP] {total_removed} screenshot >{days}gg eliminati")
    return total_removed
