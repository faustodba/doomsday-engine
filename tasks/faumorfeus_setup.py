"""
tasks/faumorfeus_setup.py — FauMorfeusSetupTask V6
====================================================
Bundle di operazioni "come le istanze ordinarie" per l'istanza master
(FauMorfeus). Il master è tipologia="raccolta_only", quindi normalmente
`main.py::_thread_istanza` registra SOLO RaccoltaTask/RaccoltaChiusuraTask
(il filtro scarta ogni altra classe di task_setup.json) — grafica_hq,
pulizia_cache, boost e vip non girano MAI sul master.

Questo task riusa la STESSA logica delle istanze ordinarie, non una
riscrittura:
  - grafica_hq / pulizia_cache: chiama direttamente `esegui_grafica_hq()` /
    `esegui_pulizia_cache()` (le funzioni sotto ai rispettivi Task), NON i
    Task wrapper — `GraficaHqTask.run()`/`PuliziaCacheTask.run()` hanno uno
    skip esplicito `if tipologia == "raccolta_only": return` pensato apposta
    per escludere il master dal ciclo normale (docstring dei due file). Qui
    bypassiamo solo il wrapper, la logica sottostante è identica.
  - boost / vip: nessuno skip di tipologia nei rispettivi Task — riuso
    diretto di `BoostTask().should_run()+run()` e `VipTask().should_run()+run()`.

Scheduling: daily (config/task_setup.json, "schedule": "daily") — una volta
al giorno, al primo tick utile dopo il reset giornaliero, stesso meccanismo
già usato da VipTask/ZainoTask/MainMissionTask (core/scheduler.py).
should_run() ritorna True solo per l'istanza master (is_master_instance) —
sulle istanze ordinarie il task è comunque filtrato a monte in
main.py::_thread_istanza (tipologia != raccolta_only → non registrato per
loro), questo check è una seconda barriera difensiva.

Ogni sotto-step gira in modalità best-effort: il fallimento di uno non
blocca gli altri (stesso comportamento delle 4 istanze ordinarie, dove sono
4 entry orchestrator indipendenti). Fra uno step e l'altro viene richiamato
`ctx.navigator.vai_in_home()` esplicitamente — l'orchestrator lo farebbe
automaticamente PRIMA di ogni singolo task (gate HOME, core/orchestrator.py),
ma qui i 4 step sono dentro un unico run(), quindi il gate va replicato a
mano fra uno step e il successivo.
"""

from __future__ import annotations

from core.task import Task, TaskContext, TaskResult
from shared.instance_meta import is_master_instance


class FauMorfeusSetupTask(Task):
    """
    Task giornaliero esclusivo per l'istanza master: esegue in sequenza
    grafica_hq, pulizia_cache, boost, vip — le stesse operazioni delle
    istanze ordinarie, che il profilo raccolta_only del master normalmente
    esclude.
    """

    def name(self) -> str:
        return "faumorfeus_setup"

    def should_run(self, ctx: TaskContext) -> bool:
        if not is_master_instance(ctx.instance_name):
            return False
        if ctx.device is None:
            return False
        return True

    def _vai_in_home(self, ctx: TaskContext) -> None:
        if ctx.navigator is not None:
            try:
                ctx.navigator.vai_in_home()
            except Exception as exc:
                ctx.log_msg(f"[FAUMORFEUS-SETUP] vai_in_home errore (non bloccante): {exc}")

    def _task_abilitato(self, ctx: TaskContext, nome: str) -> bool:
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato(nome)
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        risultati: dict[str, str] = {}
        ok_tutti = True

        # 1. Grafica HQ — stessa logica di GraficaHqTask, bypassando lo skip
        # tipologia="raccolta_only" del wrapper (vedi docstring modulo).
        if not self._task_abilitato(ctx, "grafica_hq"):
            risultati["grafica_hq"] = "skip (task disabilitato)"
        else:
            self._vai_in_home(ctx)
            ctx.log_msg("[FAUMORFEUS-SETUP] grafica_hq: avvio")
            try:
                from core.settings_helper import esegui_grafica_hq
                ok = esegui_grafica_hq(ctx, log_fn=ctx.log_msg)
                risultati["grafica_hq"] = "ok" if ok else "fallito"
                ok_tutti = ok_tutti and ok
            except Exception as exc:
                ctx.log_msg(f"[FAUMORFEUS-SETUP] grafica_hq eccezione: {exc}", level="error")
                risultati["grafica_hq"] = f"eccezione: {exc}"
                ok_tutti = False

        # 2. Pulizia cache — stesso motivo del punto 1.
        if not self._task_abilitato(ctx, "pulizia_cache"):
            risultati["pulizia_cache"] = "skip (task disabilitato)"
        else:
            self._vai_in_home(ctx)
            ctx.log_msg("[FAUMORFEUS-SETUP] pulizia_cache: avvio")
            try:
                from core.settings_helper import esegui_pulizia_cache
                ok = esegui_pulizia_cache(ctx, log_fn=ctx.log_msg)
                risultati["pulizia_cache"] = "ok" if ok else "fallito"
                ok_tutti = ok_tutti and ok
            except Exception as exc:
                ctx.log_msg(f"[FAUMORFEUS-SETUP] pulizia_cache eccezione: {exc}", level="error")
                risultati["pulizia_cache"] = f"eccezione: {exc}"
                ok_tutti = False

        # 3. Boost — nessuno skip tipologia nel Task, riuso diretto di
        # should_run()+run() (should_run gestisce anche task_abilitato+BoostState).
        self._vai_in_home(ctx)
        ctx.log_msg("[FAUMORFEUS-SETUP] boost: verifica")
        try:
            from tasks.boost import BoostTask
            boost_task = BoostTask()
            if boost_task.should_run(ctx):
                res = boost_task.run(ctx)
                risultati["boost"] = "ok" if res.success else f"fallito: {res.message}"
                ok_tutti = ok_tutti and res.success
            else:
                risultati["boost"] = "skip (should_run=False)"
        except Exception as exc:
            ctx.log_msg(f"[FAUMORFEUS-SETUP] boost eccezione: {exc}", level="error")
            risultati["boost"] = f"eccezione: {exc}"
            ok_tutti = False

        # 4. VIP — nessuno skip tipologia nel Task, riuso diretto di
        # should_run()+run() (should_run gestisce anche task_abilitato+VipState).
        self._vai_in_home(ctx)
        ctx.log_msg("[FAUMORFEUS-SETUP] vip: verifica")
        try:
            from tasks.vip import VipTask
            vip_task = VipTask()
            if vip_task.should_run(ctx):
                res = vip_task.run(ctx)
                risultati["vip"] = "ok" if res.success else f"fallito: {res.message}"
                ok_tutti = ok_tutti and res.success
            else:
                risultati["vip"] = "skip (should_run=False)"
        except Exception as exc:
            ctx.log_msg(f"[FAUMORFEUS-SETUP] vip eccezione: {exc}", level="error")
            risultati["vip"] = f"eccezione: {exc}"
            ok_tutti = False

        msg = ", ".join(f"{k}={v}" for k, v in risultati.items())
        ctx.log_msg(f"[FAUMORFEUS-SETUP] completato: {msg}")
        return TaskResult(success=ok_tutti, message=msg, data=risultati)
