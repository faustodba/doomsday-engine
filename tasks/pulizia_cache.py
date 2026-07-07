"""
tasks/pulizia_cache.py — PuliziaCacheTask V6
==============================================
Pulizia cache giornaliera del client gioco (Avatar → Settings → Help →
Clear cache → CLOSE), 1×/die per istanza via `data/cache_state.json`.

WU195 (07/07/2026) — estratto da `core/settings_helper.py::
imposta_settings_lightweight()` (prima chiamato incondizionatamente da
`core/launcher.py` ad ogni avvio istanza, insieme alla grafica HIGH) per
diventare un task orchestrator indipendente, abilitabile/disabilitabile
da dashboard separatamente dalla grafica (vedi `tasks/grafica_hq.py`).

Scheduling: always (analogo a RaccoltaTask/RifornimentoTask)
  - e_dovuto() → True sempre — il gate reale "già pulita oggi?" è interno
    a `esegui_pulizia_cache()` (via `data/cache_state.json`), che esce
    subito senza navigare se non serve.
  - Flag abilitato: globali.task.pulizia_cache (runtime_overrides.json)

Priority: 2 (gira per secondo nel ciclo, subito dopo GraficaHqTask —
replica il fatto che prima girava durante il boot, ancora prima
dell'orchestrator).
"""

from __future__ import annotations

from core.task import Task as BaseTask, TaskContext, TaskResult
from core.settings_helper import esegui_pulizia_cache


class PuliziaCacheTask(BaseTask):
    """
    Pulizia cache giornaliera del client gioco.
    Skip esplicito per istanze tipologia="raccolta_only" (es. FauMorfeus
    master), che storicamente non ricevevano questa fase.
    """

    def name(self) -> str:
        return "pulizia_cache"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("pulizia_cache")
        return True

    def e_dovuto(self, ctx: TaskContext) -> bool:  # noqa: ARG002
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        tipologia = (
            getattr(ctx.config, "tipologia", None)
            or getattr(ctx.config, "profilo", None)
            or "full"
        )
        if str(tipologia) == "raccolta_only":
            ctx.log_msg("[PULIZIA-CACHE] tipologia=raccolta_only — skip")
            return TaskResult(success=True, skipped=True)

        ctx.log_msg("[PULIZIA-CACHE] avvio")
        ok = esegui_pulizia_cache(ctx, log_fn=ctx.log_msg)
        if ok:
            ctx.log_msg("[PULIZIA-CACHE] completato")
            return TaskResult(success=True, message="pulizia cache eseguita/già fatta oggi")
        ctx.log_msg("[PULIZIA-CACHE] fallito")
        return TaskResult(success=False, message="sequenza fallita")
