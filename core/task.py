# ==============================================================================
#  DOOMSDAY ENGINE V6 - core/task.py
#
#  STANDARD ARCHITETTURALE (Step 25 — vincolante per tutti i task):
#    - run() SEMPRE sincrono: def run(self, ctx) -> TaskResult
#    - Attese SEMPRE con time.sleep() — mai asyncio.sleep()
#    - Logging SEMPRE con ctx.log_msg(msg) — mai ctx.log.info() né logging
#    - Thread per istanza (uno per MuMu) — non serve async
#    - Navigator SEMPRE sincrono: ctx.navigator.vai_in_home()
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
# TaskResult
# ==============================================================================

@dataclass(frozen=True)
class TaskResult:
    success: bool
    message: str  = ""
    data:    dict = field(default_factory=dict)
    skipped: bool = False

    @classmethod
    def ok(cls, message: str = "", **data) -> "TaskResult":
        return cls(success=True, message=message, data=dict(data))

    @classmethod
    def fail(cls, message: str = "", **data) -> "TaskResult":
        return cls(success=False, message=message, data=dict(data))

    @classmethod
    def skip(cls, message: str = "") -> "TaskResult":
        return cls(success=True, message=message, skipped=True)

    def __repr__(self) -> str:
        status = "SKIP" if self.skipped else ("OK" if self.success else "FAIL")
        return f"TaskResult({status}, {self.message!r})"


# ==============================================================================
# TaskContext
# ==============================================================================

@dataclass
class TaskContext:
    """
    Contesto condiviso passato ad ogni task.
    Logging: usare SEMPRE ctx.log_msg(msg) — mai accedere a ctx.log direttamente.
    """
    instance_name: str
    config:        "InstanceConfig"
    state:         "InstanceState"
    log:           "StructuredLogger"

    device:    "MuMuDevice | FakeDevice | None" = None
    matcher:   "TemplateMatcher | None"         = None
    navigator: "GameNavigator | None"           = None
    scheduler: "TaskScheduler | None"           = None
    extras:    dict[str, Any]                   = field(default_factory=dict)

    def log_msg(self, msg: str, *args, level: str = "info") -> None:
        """Metodo di logging unificato — usare SEMPRE questo nei task.
        Supporta log_msg(fmt, arg1, arg2) stile logging."""
        if self.log is None:
            return
        try:
            full_msg = (msg % args) if args else msg
            if level == "error":
                self.log.error("task", full_msg)
            else:
                self.log.info("task", full_msg)
        except Exception:
            pass

    def __repr__(self) -> str:
        return (
            f"TaskContext(instance={self.instance_name!r}, "
            f"device={'yes' if self.device else 'no'})"
        )


# ==============================================================================
# Task ABC
# ==============================================================================

class Task(ABC):
    """
    Interfaccia base per tutti i task. Regole vincolanti (Step 25):
      - run() SEMPRE def (sincrono) — mai async def
      - time.sleep() — mai asyncio.sleep()
      - ctx.log_msg() — mai ctx.log.info() né logging.getLogger()
      - ctx.navigator.vai_in_home() sincrono
    """

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def should_run(self, ctx: TaskContext) -> bool: ...

    @abstractmethod
    def run(self, ctx: TaskContext) -> TaskResult: ...

    def on_failure(self, ctx: TaskContext, result: TaskResult) -> None:
        ctx.log_msg(f"[{self.name()}] fallito: {result.message}", level="error")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name()!r})"
