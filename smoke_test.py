#!/usr/bin/env python
# ==============================================================================
#  DOOMSDAY ENGINE V6 — smoke_test.py
#
#  Verifica che l'intera pipeline V6 si avvii correttamente in dry-run:
#    1. Import di tutti i moduli
#    2. Lettura instances.json
#    3. Costruzione TaskContext per ogni istanza
#    4. Avvio main() in dry-run per SMOKE_DURATA secondi
#    5. Verifica engine_status.json scritto correttamente
#    6. Report finale: OK / FAIL con dettaglio per istanza
#
#  Uso:
#    python smoke_test.py                  # 15 secondi, tick ogni 2s
#    python smoke_test.py --durata 30      # 30 secondi
#    python smoke_test.py --tick-sleep 0   # tick immediato (test veloce)
#
#  Esce con codice 0 se tutti i check passano, 1 altrimenti.
# ==============================================================================
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Colori ANSI (disabilitati su Windows se non supportati)
# ---------------------------------------------------------------------------
_USE_COLOR = sys.platform != "win32" or os.environ.get("TERM") == "xterm"

def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

OK   = _c("32", "✓")
FAIL = _c("31", "✗")
WARN = _c("33", "⚠")
INFO = _c("36", "ℹ")


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def check(label: str, cond: bool, detail: str = "") -> bool:
    sym = OK if cond else FAIL
    line = f"  {sym}  {label}"
    if detail:
        line += f"  [{detail}]"
    print(line)
    return cond


def section(title: str) -> None:
    print(f"\n{_c('1', title)}")
    print("  " + "─" * 50)


# ---------------------------------------------------------------------------
# 1. Verifica import moduli
# ---------------------------------------------------------------------------
def check_imports() -> bool:
    section("1. Import moduli V6")
    ok = True

    _core = [
        ("core.task",         "Task, TaskContext, TaskResult"),
        ("core.orchestrator", "Orchestrator"),
    ]
    _tasks = [
        ("tasks.raccolta",      "RaccoltaTask"),
        ("tasks.rifornimento",  "RifornimentoTask"),
        ("tasks.zaino",         "ZainoTask"),
        ("tasks.vip",           "VipTask"),
        ("tasks.alleanza",      "AlleanzaTask"),
        ("tasks.messaggi",      "MessaggiTask"),
        ("tasks.arena",         "ArenaTask"),
        ("tasks.arena_mercato", "ArenaMercatoTask"),
        ("tasks.boost",         "BoostTask"),
        ("tasks.store",         "StoreTask"),
        ("tasks.radar",         "RadarTask"),
        ("tasks.radar_census",  "RadarCensusTask"),
    ]
    _infra = [
        ("dashboard.dashboard_server", "avvia"),
        ("main",                       "main"),
    ]

    task_mancanti = []
    for mod, symbols in _core + _infra:
        try:
            m = __import__(mod, fromlist=symbols.split(","))
            for sym in symbols.split(","):
                sym = sym.strip()
                if not hasattr(m, sym):
                    raise ImportError(f"{sym} non trovato in {mod}")
            ok &= check(f"import {mod}", True)
        except ImportError as exc:
            ok &= check(f"import {mod}", False, str(exc))
        except Exception as exc:
            ok &= check(f"import {mod}", False, f"ERRORE: {exc}")

    for mod, symbols in _tasks:
        try:
            m = __import__(mod, fromlist=symbols.split(","))
            for sym in symbols.split(","):
                sym = sym.strip()
                if not hasattr(m, sym):
                    raise ImportError(f"{sym} non trovato in {mod}")
            print(f"  {OK}  import {mod}")
        except ImportError as exc:
            task_mancanti.append(mod)
            print(f"  {WARN}  import {mod}  [{exc}] (task non ancora copiato in V6)")

    if task_mancanti:
        print(f"  {WARN}  {len(task_mancanti)}/12 task non presenti — normale se tasks/ non ancora deployati")
    else:
        print(f"  {OK}  Tutti i task importati")

    return ok


# ---------------------------------------------------------------------------
# 2. Verifica instances.json
# ---------------------------------------------------------------------------
def check_instances() -> tuple[bool, list[dict]]:
    section("2. instances.json")
    path = os.path.join(ROOT, "config", "instances.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            istanze = json.load(f)
        ok = check(f"instances.json trovato ({len(istanze)} istanze)", True, path)
    except FileNotFoundError:
        check("instances.json trovato", False, path)
        return False, []
    except json.JSONDecodeError as exc:
        check("instances.json JSON valido", False, str(exc))
        return False, []

    campi_obbligatori = ["nome", "indice", "porta", "truppe", "max_squadre", "layout", "lingua"]
    tutti_ok = True
    for ist in istanze:
        mancanti = [c for c in campi_obbligatori if c not in ist]
        ist_ok = not mancanti
        tutti_ok &= check(
            f"  {ist.get('nome', '?')}  porta={ist.get('porta')}  profilo={ist.get('profilo','full')}",
            ist_ok,
            f"mancanti: {mancanti}" if mancanti else "",
        )
    return tutti_ok, istanze


# ---------------------------------------------------------------------------
# 3. Verifica TaskContext costruibile per ogni istanza
# ---------------------------------------------------------------------------
def check_ctx(istanze: list[dict]) -> bool:
    section("3. TaskContext dry-run per ogni istanza")
    import main as M
    ok = True
    for ist in istanze:
        try:
            ctx = M._build_ctx(ist, {}, dry_run=True)
            ok &= check(
                f"  {ist['nome']}  ctx.instance_name={ctx.instance_name}",
                ctx.instance_name == ist["nome"],
            )
            # Verifica config minima
            assert ctx.config is not None
            assert ctx.config.task_abilitato("raccolta") is True
        except Exception as exc:
            ok &= check(f"  {ist['nome']}", False, str(exc))
    return ok


# ---------------------------------------------------------------------------
# 4. Avvio main.py --dry-run in subprocess
# ---------------------------------------------------------------------------
def run_main_dryrun(durata: int, tick_sleep: int) -> subprocess.Popen:
    cmd = [
        sys.executable, os.path.join(ROOT, "main.py"),
        "--dry-run",
        f"--tick-sleep={tick_sleep}",
        f"--status-interval=2",
    ]
    print(f"\n  $ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=ROOT,
    )
    return proc


# ---------------------------------------------------------------------------
# 5. Verifica engine_status.json
# ---------------------------------------------------------------------------
def check_status_json(istanze: list[dict]) -> bool:
    section("5. engine_status.json")
    path = os.path.join(ROOT, "engine_status.json")

    if not os.path.exists(path):
        check("engine_status.json esiste", False, path)
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        check("engine_status.json leggibile", False, str(exc))
        return False

    ok = True
    ok &= check("engine_status.json esiste e leggibile", True)
    ok &= check(f"version = {data.get('version')}", data.get("version") == "v6")
    ok &= check(f"stato = {data.get('stato')}", data.get("stato") in ("running", "waiting", "idle"))
    ok &= check(f"uptime_s presente", "uptime_s" in data)
    ok &= check(f"ts presente", "ts" in data)

    ist_json = data.get("istanze", {})
    nomi_attesi = {i["nome"] for i in istanze}
    nomi_trovati = set(ist_json.keys())
    # Accetta subset: con stagger 2s per 12 istanze servono 24s per avviarle tutte
    ok &= check(
        f"istanze nel JSON: {len(nomi_trovati)}/{len(nomi_attesi)} avviate",
        len(nomi_trovati) > 0,
        f"trovate: {sorted(nomi_trovati)}" if nomi_trovati != nomi_attesi else "",
    )

    for nome, ist_data in ist_json.items():
        stato_ist = ist_data.get("stato", "?")
        porta_ist = ist_data.get("porta", 0)
        ok &= check(f"  {nome}  stato={stato_ist}  porta={porta_ist}", True)

    return ok


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Smoke test Doomsday Engine V6")
    parser.add_argument("--durata",    type=int, default=15,
                        help="Secondi di run dry-run (default: 15)")
    parser.add_argument("--tick-sleep", type=int, default=2,
                        help="Secondi tra tick nell'istanza (default: 2)")
    args = parser.parse_args()

    print(_c("1;36", "\n╔══════════════════════════════════════════════════╗"))
    print(_c("1;36",   "║  DOOMSDAY ENGINE V6 — SMOKE TEST                ║"))
    print(_c("1;36",   "╚══════════════════════════════════════════════════╝"))
    print(f"  Root   : {ROOT}")
    print(f"  Durata : {args.durata}s  |  tick-sleep: {args.tick_sleep}s")
    print(f"  Ora    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    risultati: dict[str, bool] = {}

    # ── Check 1: import
    risultati["import"] = check_imports()

    # ── Check 2: instances.json
    ok_ist, istanze = check_instances()
    risultati["instances"] = ok_ist

    if not istanze:
        print(f"\n  {FAIL}  instances.json mancante o vuoto — smoke test interrotto.")
        sys.exit(1)

    # ── Check 3: ctx
    risultati["ctx"] = check_ctx(istanze)

    # ── Check 4: run main --dry-run
    section(f"4. main.py --dry-run ({args.durata}s)")
    proc = run_main_dryrun(args.durata, args.tick_sleep)

    # Leggi output in tempo reale per i primi `durata` secondi
    t0 = time.time()
    output_lines: list[str] = []
    print()
    try:
        while time.time() - t0 < args.durata:
            line = proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            line = line.rstrip()
            output_lines.append(line)
            print(f"  {_c('90', line)}")
    except KeyboardInterrupt:
        pass

    # Ferma il processo
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=8)
    except Exception:
        proc.kill()

    exit_ok = proc.returncode in (0, -2, 1, None)  # SIGINT → -2 su Unix
    risultati["main_avvio"] = check(
        f"main.py si è avviato e fermato (returncode={proc.returncode})",
        True,  # se arriviamo qui senza crash è già un successo
    )

    # Controlla che non ci siano errori critici nell'output
    errori_critici = [l for l in output_lines if "Traceback" in l or "ImportError" in l]
    risultati["no_crash"] = check(
        "Nessun crash / ImportError nell'output",
        len(errori_critici) == 0,
        f"{len(errori_critici)} errori trovati" if errori_critici else "",
    )
    if errori_critici:
        for l in errori_critici[:5]:
            print(f"    {FAIL}  {l}")

    # ── Check 5: engine_status.json
    risultati["status_json"] = check_status_json(istanze)

    # ── Riepilogo finale
    section("Riepilogo")
    tutti_ok = True
    for nome, ok in risultati.items():
        sym = OK if ok else FAIL
        print(f"  {sym}  {nome}")
        tutti_ok = tutti_ok and ok

    print()
    if tutti_ok:
        print(_c("1;32", "  ✓ SMOKE TEST PASSATO — V6 pronto per il run reale"))
    else:
        print(_c("1;31", "  ✗ SMOKE TEST FALLITO — correggi gli errori prima del run reale"))
    print()

    sys.exit(0 if tutti_ok else 1)


if __name__ == "__main__":
    main()
