"""
tasks/grafica_hq.py — GraficaHqTask V6
=======================================
Imposta Graphics Quality HIGH + Frame Rate MID + Optimize Mode HIGH nel
client gioco (driver Vulkan→DirectX, Issue #88, WU78-rev).

WU195 (07/07/2026) — estratto da `core/settings_helper.py::
imposta_settings_lightweight()` (prima chiamato incondizionatamente da
`core/launcher.py` ad ogni avvio istanza) per diventare un task
orchestrator indipendente, abilitabile/disabilitabile da dashboard
separatamente dalla pulizia cache (vedi `tasks/pulizia_cache.py`).

Scheduling: always (analogo a RaccoltaTask/RifornimentoTask)
  - e_dovuto() → True sempre — replica il comportamento storico "ad ogni
    avvio istanza". I 3 tap sono tutti idempotenti (nessun danno a
    ripeterli ogni ciclo).
  - Flag abilitato: globali.task.grafica_hq (runtime_overrides.json)

Priority: 1 (gira per primo nel ciclo, prima di qualunque altro task —
replica il fatto che prima girava durante il boot, ancora prima
dell'orchestrator).
"""

from __future__ import annotations

from core.task import Task as BaseTask, TaskContext, TaskResult
from core.settings_helper import esegui_grafica_hq


class GraficaHqTask(BaseTask):
    """
    Imposta i settings grafici HIGH del client gioco.
    Skip esplicito per istanze tipologia="raccolta_only" (es. FauMorfeus
    master), che storicamente non ricevevano questa fase.
    """

    def name(self) -> str:
        return "grafica_hq"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("grafica_hq")
        return True

    def e_dovuto(self, ctx: TaskContext) -> bool:  # noqa: ARG002
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        tipologia = (
            getattr(ctx.config, "tipologia", None)
            or getattr(ctx.config, "profilo", None)
            or "full"
        )
        # WU-MasterTasks (17/07) — skip raccolta_only ora whitelist-aware:
        # il master salta grafica_hq SOLO se non l'ha selezionato nella sua
        # master_task_whitelist. Se selezionato, main.py lo registra e qui
        # deve girare (prima veniva sempre saltato per il master).
        _wl = getattr(ctx.config, "MASTER_TASK_WHITELIST", []) or []
        if str(tipologia) == "raccolta_only" and "grafica_hq" not in _wl:
            ctx.log_msg("[GRAFICA-HQ] tipologia=raccolta_only, non in whitelist master — skip")
            return TaskResult(success=True, skipped=True)

        ctx.log_msg("[GRAFICA-HQ] avvio")
        ok = esegui_grafica_hq(ctx, log_fn=ctx.log_msg)
        if ok:
            ctx.log_msg("[GRAFICA-HQ] completato")
            return TaskResult(success=True, message="grafica HIGH impostata")
        ctx.log_msg("[GRAFICA-HQ] fallito")
        return TaskResult(success=False, message="sequenza fallita")
