# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/scheduler.py
#
#  Scheduler per i task periodici dell'istanza.
#
#  Classi:
#    TaskEntry      — registrazione di un task con il suo stato temporale
#    TaskScheduler  — decide quali task eseguire e in che ordine
#
#  Design:
#    - Due categorie di task:
#        daily:    eseguiti una volta al giorno (usa DailyTasksState)
#        periodic: eseguiti ogni N ore (usa timestamp ultimo completamento)
#    - should_run() è puro (no I/O, no async) — testabile senza device
#    - Il bot chiama next_tasks() per ottenere la lista ordinata di task pronti
#    - La fascia_oraria dell'istanza è rispettata: fuori fascia nessun task
#    - Nessuna dipendenza da device.py, navigator.py, template_matcher.py
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


# ==============================================================================
# Helpers tempo
# ==============================================================================

def _now_ts() -> float:
    """Timestamp UTC corrente in secondi (monotonic per intervalli)."""
    return time.monotonic()


def _utc_hour() -> int:
    """Ora UTC corrente (0-23)."""
    return datetime.now(timezone.utc).hour


# ==============================================================================
# TaskEntry — registrazione di un task nello scheduler
# ==============================================================================

@dataclass
class TaskEntry:
    """
    Descrive un task registrato nello scheduler.

    Attributi:
        name:          nome canonico del task (es. "boost", "raccolta")
        kind:          "daily" | "periodic"
        interval_secs: per periodic — secondi tra esecuzioni (0 = sempre pronto)
        priority:      ordine di esecuzione (più basso = prima)
        last_run_ts:   timestamp monotonic ultima esecuzione (None = mai)
        enabled:       se False il task non viene mai schedulato
    """
    name:           str
    kind:           str                   # "daily" | "periodic"
    interval_secs:  float = 0.0           # usato solo per periodic
    priority:       int   = 50
    last_run_ts:    float | None = None
    enabled:        bool  = True

    def elapsed_secs(self) -> float:
        """Secondi trascorsi dall'ultima esecuzione (inf se mai eseguito)."""
        if self.last_run_ts is None:
            return float("inf")
        return _now_ts() - self.last_run_ts

    def mark_done(self) -> None:
        """Aggiorna il timestamp all'esecuzione appena completata."""
        self.last_run_ts = _now_ts()

    def __repr__(self) -> str:
        elapsed = f"{self.elapsed_secs():.0f}s" if self.last_run_ts else "mai"
        return (
            f"TaskEntry({self.name!r}, kind={self.kind}, "
            f"elapsed={elapsed}, enabled={self.enabled})"
        )


# ==============================================================================
# TaskScheduler
# ==============================================================================

class TaskScheduler:
    """
    Decide quali task sono pronti per l'esecuzione e in che ordine.

    Uso tipico:
        scheduler = TaskScheduler(config, state)
        scheduler.register("boost",    kind="daily",    priority=10)
        scheduler.register("raccolta", kind="periodic", interval_h=0.5, priority=20)

        # Nel loop principale:
        tasks = scheduler.next_tasks(daily_completed=state.daily_tasks.completati)
        for task_name in tasks:
            await run_task(task_name)
            scheduler.mark_done(task_name)
    """

    def __init__(
        self,
        fascia_oraria: tuple[int, int] | None = None,
    ):
        """
        Args:
            fascia_oraria: (ora_inizio, ora_fine) UTC — task eseguiti solo
                           in questo intervallo. None = sempre attivo.
        """
        self._fascia   = fascia_oraria
        self._entries: dict[str, TaskEntry] = {}

    # ── Registrazione ─────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        kind: str,
        interval_h: float = 0.0,
        priority: int = 50,
        enabled: bool = True,
    ) -> None:
        """
        Registra un task nello scheduler.

        Args:
            name:       nome canonico (es. "boost")
            kind:       "daily" | "periodic"
            interval_h: per periodic — ore tra esecuzioni (es. 4.0 = ogni 4h)
            priority:   ordine esecuzione (più basso = prima)
            enabled:    se False non viene mai schedulato
        """
        if kind not in ("daily", "periodic"):
            raise ValueError(f"kind deve essere 'daily' o 'periodic', ricevuto: {kind!r}")

        self._entries[name] = TaskEntry(
            name=name,
            kind=kind,
            interval_secs=interval_h * 3600,
            priority=priority,
            enabled=enabled,
        )

    def register_many(self, tasks: list[dict]) -> None:
        """
        Registra più task da una lista di dict.

        Ogni dict deve avere almeno: name, kind.
        Opzionali: interval_h, priority, enabled.
        """
        for t in tasks:
            self.register(
                name=t["name"],
                kind=t["kind"],
                interval_h=t.get("interval_h", 0.0),
                priority=t.get("priority", 50),
                enabled=t.get("enabled", True),
            )

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Abilita/disabilita un task già registrato."""
        if name in self._entries:
            self._entries[name].enabled = enabled

    # ── Logica di scheduling ──────────────────────────────────────────────────

    def in_fascia(self, utc_hour: int | None = None) -> bool:
        """
        True se l'ora corrente è nella fascia oraria configurata.
        Se fascia_oraria è None, ritorna sempre True.

        Args:
            utc_hour: ora UTC da usare (None = usa ora corrente)
        """
        if self._fascia is None:
            return True
        h = utc_hour if utc_hour is not None else _utc_hour()
        start, end = self._fascia
        if start <= end:
            return start <= h < end
        else:
            # Fascia a cavallo della mezzanotte (es. 22-6)
            return h >= start or h < end

    def should_run(
        self,
        name: str,
        daily_completed: dict[str, bool] | None = None,
        utc_hour: int | None = None,
    ) -> bool:
        """
        Determina se un task specifico è pronto per l'esecuzione.

        Args:
            name:            nome del task
            daily_completed: dict {task: bool} dallo stato giornaliero
            utc_hour:        ora UTC override (per test)

        Returns:
            True se il task deve essere eseguito ora.
        """
        entry = self._entries.get(name)
        if entry is None or not entry.enabled:
            return False

        if not self.in_fascia(utc_hour):
            return False

        if entry.kind == "daily":
            completed = (daily_completed or {}).get(name, False)
            return not completed

        if entry.kind == "periodic":
            return entry.elapsed_secs() >= entry.interval_secs

        return False

    def next_tasks(
        self,
        daily_completed: dict[str, bool] | None = None,
        utc_hour: int | None = None,
    ) -> list[str]:
        """
        Ritorna la lista ordinata per priority dei task pronti.

        Args:
            daily_completed: dict {task: bool} — stati daily tasks
            utc_hour:        ora UTC override (per test)

        Returns:
            Lista di nomi task pronti, ordinata per priority crescente.
        """
        ready = [
            entry for entry in self._entries.values()
            if self.should_run(entry.name, daily_completed, utc_hour)
        ]
        ready.sort(key=lambda e: e.priority)
        return [e.name for e in ready]

    # ── Aggiornamento stato ───────────────────────────────────────────────────

    def mark_done(self, name: str) -> None:
        """
        Segna un task come completato (aggiorna timestamp).
        Per i daily task, la logica di completamento è in DailyTasksState —
        qui aggiorniamo solo il timestamp per i periodic.
        """
        entry = self._entries.get(name)
        if entry:
            entry.mark_done()

    def mark_all_done(self, names: list[str]) -> None:
        """Segna più task come completati."""
        for name in names:
            self.mark_done(name)

    # ── Ispezione ─────────────────────────────────────────────────────────────

    def entries(self) -> list[TaskEntry]:
        """Lista di tutti i TaskEntry registrati."""
        return list(self._entries.values())

    def entry(self, name: str) -> TaskEntry | None:
        """Ritorna il TaskEntry per nome, o None se non esiste."""
        return self._entries.get(name)

    def registered_names(self) -> list[str]:
        """Lista dei nomi di task registrati."""
        return list(self._entries.keys())

    def __repr__(self) -> str:
        return (
            f"TaskScheduler(tasks={len(self._entries)}, "
            f"fascia={self._fascia})"
        )
