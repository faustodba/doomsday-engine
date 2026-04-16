# ==============================================================================
#  DOOMSDAY ENGINE V6 — core/orchestrator.py                        Step 22
#
#  Coordina l'esecuzione periodica dei Task su una singola istanza.
#
#  RESPONSABILITÀ:
#    • Registra i task con il loro schedule (periodic | daily)
#    • Decide quali task sono "dovuti" in base all'ora e all'ultimo run
#    • Esegue i task in ordine di priorità, avvolti in try/except
#    • Registra timestamp ultimo run e risultato per ogni task
#    • Espone lo stato corrente dell'istanza (task in corso, ultimo esito)
#
#  SCHEDULING:
#    periodic  → eseguito ogni `interval_hours` ore dall'ultimo run
#    daily     → eseguito una volta al giorno (reset alle 01:00 UTC)
#
#  CATENA DI COMANDO (in ordine):
#    1. e_dovuto()      → interval/daily scaduto? (scheduling temporale)
#    2. should_run()    → flag abilitazione + guard stato persistente
#    3. gate HOME       → navigator in HOME prima di ogni task
#    4. task.run()      → esecuzione effettiva
#
#  DESIGN:
#    - Nessuna dipendenza da config globale: tutto via ctx.config
#    - Nessun thread interno: l'orchestrator è chiamato da un loop esterno
#    - Testabile con FakeDevice + FakeMatcher + task stub
#    - Stato persistito in memoria (dict) — la persistenza su disco è
#      responsabilità del chiamante (es. orchestrator wrapper)
#
#  INTERFACCIA PRINCIPALE:
#    orc = Orchestrator(ctx)
#    orc.register(task, priority=10)
#    orc.tick()   → esegue i task dovuti, ritorna lista TaskResult
#
#  STATO:
#    orc.stato()  → dict {task_name: {"last_run": float, "last_result": ...}}
# ==============================================================================

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

from core.task import Task, TaskContext, TaskResult


def _tname(task: Task) -> str:
    """Ritorna il nome del task, gestendo sia @property che metodo callable."""
    n = task.name
    return n() if callable(n) else n


# ==============================================================================
# Struttura registrazione task
# ==============================================================================

@dataclass
class _TaskEntry:
    task: Task
    priority: int          # ordine esecuzione: più basso = prima
    last_run: float        # timestamp Unix ultimo run (0.0 = mai eseguito)
    last_result: Optional[TaskResult] = None
    enabled: bool = True


# ==============================================================================
# Helpers scheduling
# ==============================================================================

def _reset_daily_corrente() -> datetime:
    """
    Ritorna il datetime del reset giornaliero in vigore (01:00 UTC di oggi o ieri).
    Coerente con il pattern già usato in rifornimento_base.py V5.
    """
    now = datetime.now(timezone.utc)
    reset_oggi = now.replace(hour=1, minute=0, second=0, microsecond=0)
    return reset_oggi if now >= reset_oggi else reset_oggi - timedelta(days=1)


def _e_dovuto_periodic(entry: _TaskEntry) -> bool:
    """True se sono trascorse almeno interval_hours ore dall'ultimo run."""
    if entry.last_run == 0.0:
        return True
    elapsed_h = (time.time() - entry.last_run) / 3600.0
    return elapsed_h >= entry.task.interval_hours


def _e_dovuto_daily(entry: _TaskEntry) -> bool:
    """True se il task non è ancora stato eseguito nel ciclo giornaliero corrente."""
    if entry.last_run == 0.0:
        return True
    reset = _reset_daily_corrente()
    last_dt = datetime.fromtimestamp(entry.last_run, tz=timezone.utc)
    return last_dt < reset


def e_dovuto(entry: _TaskEntry) -> bool:
    """Dispatch schedule_type → logica corretta."""
    if not entry.enabled:
        return False
    if entry.task.schedule_type == "daily":
        return _e_dovuto_daily(entry)
    return _e_dovuto_periodic(entry)


# ==============================================================================
# Orchestrator
# ==============================================================================

class Orchestrator:
    """
    Coordina l'esecuzione periodica dei Task su una singola istanza.

    Esempio di utilizzo:
        orc = Orchestrator(ctx)
        orc.register(ZainoTask(),       priority=30)
        orc.register(RifornimentoTask(), priority=20)
        orc.register(RaccoltaTask(),    priority=10)
        results = orc.tick()
    """

    def __init__(self, ctx: TaskContext):
        self._ctx     = ctx
        self._entries: list[_TaskEntry] = []

    # ------------------------------------------------------------------
    # Registrazione
    # ------------------------------------------------------------------

    def register(self, task: Task, priority: int = 50,
                 enabled: bool = True) -> None:
        """
        Registra un task nell'orchestrator.

        priority  : ordine esecuzione — più basso = eseguito prima
        enabled   : False → task registrato ma mai eseguito
        """
        entry = _TaskEntry(
            task=task,
            priority=priority,
            last_run=0.0,
            enabled=enabled,
        )
        self._entries.append(entry)
        self._entries.sort(key=lambda e: e.priority)

    def enable(self, task_name: str) -> None:
        """Abilita un task registrato per nome."""
        for e in self._entries:
            if _tname(e.task) == task_name:
                e.enabled = True

    def disable(self, task_name: str) -> None:
        """Disabilita un task registrato per nome (non viene eseguito in tick)."""
        for e in self._entries:
            if _tname(e.task) == task_name:
                e.enabled = False

    def set_last_run(self, task_name: str, ts: float) -> None:
        """Imposta manualmente il timestamp dell'ultimo run (utile per i test)."""
        for e in self._entries:
            if _tname(e.task) == task_name:
                e.last_run = ts

    # ------------------------------------------------------------------
    # Tick principale
    # ------------------------------------------------------------------

    def tick(self) -> list[TaskResult]:
        """
        Esegue tutti i task dovuti (nell'ordine di priorità registrato).

        GATE HOME (Step 22 — fix RT):
          Prima di ogni task verifica che il navigator sia in HOME.
          Se il gate fallisce il task viene saltato (skip) senza aggiornare
          last_run, così verrà riprovato al tick successivo.
          I task che dichiarano requires_home = False saltano il gate.

        Ogni task viene avvolto in try/except: un errore non interrompe gli altri.
        Ritorna la lista dei TaskResult prodotti in questo tick.
        """
        results: list[TaskResult] = []

        for entry in self._entries:
            if not e_dovuto(entry):
                continue

            task_name = _tname(entry.task)

            # ── GATE SHOULD_RUN ───────────────────────────────────────────────
            # Flag abilitazione (global_config.json) + guard stato persistente
            # (BoostState, VipState, ArenaState, RifornimentoState, ecc.)
            # Se False → task saltato, last_run NON aggiornato → riprova al tick
            try:
                if hasattr(entry.task, "should_run"):
                    if not entry.task.should_run(self._ctx):
                        self._ctx.log_msg(
                            f"Orchestrator: [{task_name}] should_run=False → saltato"
                        )
                        continue
            except Exception as exc:
                self._ctx.log_msg(
                    f"Orchestrator: [{task_name}] should_run() eccezione: {exc} → saltato"
                )
                continue
            # ── fine GATE SHOULD_RUN ─────────────────────────────────────────

            # ── GATE HOME ────────────────────────────────────────────────────
            # Salta il gate se il task lo dichiara esplicitamente non necessario
            # oppure se il navigator non è disponibile (dry-run / test).
            richiede_home = getattr(entry.task, "requires_home", True)
            nav = self._ctx.navigator if hasattr(self._ctx, "navigator") else None

            if richiede_home and nav is not None:
                self._ctx.log_msg(
                    f"Orchestrator: [{task_name}] gate HOME pre-task"
                )
                try:
                    in_home = nav.vai_in_home()
                except Exception as exc:
                    in_home = False
                    self._ctx.log_msg(
                        f"Orchestrator: [{task_name}] gate HOME eccezione: {exc}"
                    )

                if not in_home:
                    self._ctx.log_msg(
                        f"Orchestrator: [{task_name}] gate HOME FALLITO "
                        f"— task SALTATO (last_run non aggiornato)"
                    )
                    # NON aggiorniamo last_run → il task verrà riprovato
                    results.append(TaskResult(
                        success=False,
                        message="gate HOME fallito — task saltato",
                        data={"gate_home": False},
                    ))
                    continue

                self._ctx.log_msg(
                    f"Orchestrator: [{task_name}] gate HOME OK"
                )
            # ── fine GATE HOME ───────────────────────────────────────────────

            self._ctx.log_msg(f"Orchestrator: avvio task '{task_name}'")

            try:
                result = entry.task.run(self._ctx)
            except Exception as exc:
                self._ctx.log_msg(f"Orchestrator: task '{task_name}' -- eccezione: {exc}")
                result = TaskResult(
                    success=False,
                    message=f"eccezione: {exc}",
                    data={},
                )

            entry.last_run    = time.time()
            entry.last_result = result
            results.append(result)

            self._ctx.log_msg(
                f"Orchestrator: task '{task_name}' completato "
                f"-- success={result.success} msg='{result.message}'"
            )

        return results

    # ------------------------------------------------------------------
    # Stato / introspezione
    # ------------------------------------------------------------------

    def stato(self) -> dict[str, dict]:
        """
        Ritorna lo stato corrente di tutti i task registrati.

        Formato:
          {
            "raccolta": {
              "priority":    10,
              "enabled":     True,
              "schedule":    "periodic",
              "interval_h":  4.0,
              "last_run":    1712345678.0,   # 0.0 se mai eseguito
              "dovuto":      True,
              "last_success": True,          # None se mai eseguito
              "last_message": "4 squadre",
            },
            ...
          }
        """
        out: dict[str, dict] = {}
        for entry in self._entries:
            lr = entry.last_result
            out[_tname(entry.task)] = {
                "priority":    entry.priority,
                "enabled":     entry.enabled,
                "schedule":    entry.task.schedule_type,
                "interval_h":  entry.task.interval_hours,
                "last_run":    entry.last_run,
                "dovuto":      e_dovuto(entry),
                "last_success": lr.success  if lr else None,
                "last_message": lr.message  if lr else None,
            }
        return out

    def task_names(self) -> list[str]:
        """Lista dei nomi dei task registrati, in ordine di priorità."""
        return [_tname(e.task) for e in self._entries]

    def n_dovuti(self) -> int:
        """Numero di task dovuti nel tick corrente."""
        return sum(1 for e in self._entries if e_dovuto(e))

    def __len__(self) -> int:
        return len(self._entries)
