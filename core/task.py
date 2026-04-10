# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/task.py
#
#  Interfaccia base per tutti i task del bot.
#
#  Classi:
#    TaskResult     — risultato dell'esecuzione di un task
#    TaskContext    — contesto condiviso passato ad ogni task
#    Task           — ABC che tutti i task devono implementare
#
#  Design:
#    - Task è una ABC con due metodi astratti: should_run() e run()
#    - TaskContext aggrega tutto ciò che un task può usare (device, matcher,
#      navigator, state, config, logger, scheduler)
#    - TaskResult è immutabile (frozen dataclass) con success, message, data
#    - on_failure() ha implementazione default (log errore) — override opzionale
#    - Nessun import circolare: task.py non importa moduli specifici di task
# ==============================================================================

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice
    from core.logger import StructuredLogger
    from core.navigator import GameNavigator
    from core.scheduler import TaskScheduler
    from core.state import InstanceState
    from config.config import InstanceConfig
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# TaskResult — risultato esecuzione
# ==============================================================================

@dataclass(frozen=True)
class TaskResult:
    """
    Risultato immutabile dell'esecuzione di un task.

    Attributi:
        success:  True se il task è completato senza errori critici
        message:  descrizione breve del risultato
        data:     dict opzionale con dati aggiuntivi (metriche, contatori, ecc.)
        skipped:  True se il task è stato saltato (precondizioni non soddisfatte)
    """
    success:  bool
    message:  str  = ""
    data:     dict = field(default_factory=dict)
    skipped:  bool = False

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def ok(cls, message: str = "", **data) -> "TaskResult":
        """Task completato con successo."""
        return cls(success=True, message=message, data=dict(data))

    @classmethod
    def fail(cls, message: str = "", **data) -> "TaskResult":
        """Task fallito."""
        return cls(success=False, message=message, data=dict(data))

    @classmethod
    def skip(cls, message: str = "") -> "TaskResult":
        """Task saltato (precondizioni non soddisfatte, non è un errore)."""
        return cls(success=True, message=message, skipped=True)

    def __repr__(self) -> str:
        status = "SKIP" if self.skipped else ("OK" if self.success else "FAIL")
        return f"TaskResult({status}, {self.message!r})"


# ==============================================================================
# TaskContext — contesto condiviso
# ==============================================================================

@dataclass
class TaskContext:
    """
    Contesto condiviso passato ad ogni task durante l'esecuzione.

    Aggrega tutti i servizi di cui un task può avere bisogno:
    device, matcher, navigator, state, config, logger, scheduler.

    I campi sono opzionali per permettere test parziali (es. un task
    che non usa il navigator non deve fornirlo nel test).
    """

    # Obbligatori
    instance_name: str
    config:        "InstanceConfig"
    state:         "InstanceState"
    log:           "StructuredLogger"

    # Opzionali (possono essere None nei test unitari)
    device:    "MuMuDevice | FakeDevice | None"  = None
    matcher:   "TemplateMatcher | None"          = None
    navigator: "GameNavigator | None"            = None
    scheduler: "TaskScheduler | None"            = None

    # Dati runtime extra (es. screenshot già acquisito, ecc.)
    extras:    dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"TaskContext(instance={self.instance_name!r}, "
            f"device={'yes' if self.device else 'no'}, "
            f"navigator={'yes' if self.navigator else 'no'})"
        )


# ==============================================================================
# Task — ABC base per tutti i task
# ==============================================================================

class Task(ABC):
    """
    Interfaccia base per tutti i task del bot.

    Ogni task concreto deve implementare:
        should_run(ctx) → bool    precondizioni (puro, no I/O)
        run(ctx)        → TaskResult   logica principale (async)

    Può opzionalmente fare override di:
        on_failure(ctx, result) → None   gestione fallimento

    Convenzione nomi modulo:
        Il nome del task è definito da name() e coincide con la chiave
        usata in DailyTasksState, TaskScheduler e InstanceConfig.task_abilitati.

    Esempio implementazione:
        class BoostTask(Task):
            def name(self) -> str:
                return "boost"

            def should_run(self, ctx: TaskContext) -> bool:
                return ctx.config.task_abilitato("boost")

            async def run(self, ctx: TaskContext) -> TaskResult:
                # ... logica boost ...
                return TaskResult.ok("Speed boost applicato")
    """

    @abstractmethod
    def name(self) -> str:
        """Nome canonico del task (deve corrispondere alla chiave in task_abilitati)."""
        ...

    @abstractmethod
    def should_run(self, ctx: TaskContext) -> bool:
        """
        Verifica le precondizioni senza eseguire il task.

        Chiamato prima di run() — deve essere puro (no I/O, no async).
        Tipicamente controlla: task abilitato in config, stato, ora del giorno.

        Returns:
            True se il task può essere eseguito ora.
        """
        ...

    @abstractmethod
    async def run(self, ctx: TaskContext) -> TaskResult:
        """
        Esegue la logica principale del task.

        Chiamato solo se should_run() ritorna True.
        Deve essere fault-tolerant: catturare eccezioni e ritornare
        TaskResult.fail() invece di propagare.

        Returns:
            TaskResult con esito dell'esecuzione.
        """
        ...

    def on_failure(self, ctx: TaskContext, result: TaskResult) -> None:
        """
        Chiamato quando run() ritorna TaskResult con success=False.
        Implementazione default: logga l'errore.
        Override per logica custom (es. reset stato, notifica).
        """
        if ctx.log:
            ctx.log.error(
                self.name(),
                f"Task fallito: {result.message}",
                **result.data,
            )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name()!r})"
