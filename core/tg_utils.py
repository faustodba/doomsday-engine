"""core/tg_utils.py — Utility condivise per il Telegram bot.

Contiene: path helpers, config helpers, patch functions, data readers,
          formatters, check processo bot/dashboard.
Importato da tg_handlers_*.py e telegram_bot.py.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# ─── Path helpers ─────────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _read_json_safe(p: Path) -> dict:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ─── Config helpers ───────────────────────────────────────────────────────────

def _tg_config() -> dict:
    """Ritorna config telegram da runtime_overrides (DYNAMIC, hot-reload)."""
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        ov = _read_json_safe(ov_path)
        return ov.get("globali", {}).get("notifications", {}).get("telegram", {})
    except Exception:
        return {}


def _tg_enabled() -> bool:
    """True se le notifiche proattive sono abilitate."""
    return bool(_tg_config().get("enabled", False))


def _patch_runtime(patch_fn) -> bool:
    """Legge runtime_overrides.json, applica patch_fn(ov: dict) e riscrive atomicamente."""
    try:
        ov_path = _root() / "config" / "runtime_overrides.json"
        try:
            ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}
        except Exception as read_exc:
            _log.warning("[TG-BOT] _patch_runtime: lettura fallita, abort: %s", read_exc)
            return False
        patch_fn(ov)
        tmp = ov_path.with_suffix(ov_path.suffix + ".tmp")
        tmp.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ov_path)
        return True
    except Exception as exc:
        _log.warning("[TG-BOT] _patch_runtime fallito: %s", exc)
        return False


def _set_messaggi_enabled(enabled: bool) -> bool:
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("notifications", {}).setdefault("telegram", {})["enabled"] = enabled
    return _patch_runtime(patch)


def _set_istanza_abilitata(nome: str, abilitata: bool) -> tuple[bool, str]:
    instances = _read_instances_cfg()
    nomi_map = {c["nome"].upper(): c["nome"] for c in instances}
    nome_canonico = nomi_map.get(nome.upper())
    if not nome_canonico:
        suggerito = ", ".join(sorted(nomi_map.values()))
        return False, f"istanza '{nome}' non trovata.\nDisponibili: {suggerito}"

    def patch(ov):
        ov.setdefault("istanze", {}).setdefault(nome_canonico, {})["abilitata"] = abilitata

    ok = _patch_runtime(patch)
    return ok, nome_canonico


def _set_task(nome: Optional[str], enabled: bool) -> tuple[bool, dict, dict]:
    before: dict = {}
    after:  dict = {}

    def patch(ov):
        task_dict = ov.setdefault("globali", {}).setdefault("task", {})
        before.update(task_dict)
        targets = [nome] if nome else list(task_dict)
        for k in targets:
            if k in task_dict:
                task_dict[k] = enabled
        after.update(task_dict)

    ok = _patch_runtime(patch)
    return ok, before, after


# ─── Rifornimento helpers ─────────────────────────────────────────────────────

_RIF_RISORSA_MAP: dict[str, str] = {
    "pomodoro": "campo",
    "campo":    "campo",
    "legno":    "legno",
    "acciaio":  "acciaio",
    "petrolio": "petrolio",
}
_RIF_RISORSE_VALIDE = ("pomodoro", "legno", "acciaio", "petrolio")


def _set_rif_risorsa(risorsa: str, abilitata: bool) -> tuple[bool, str]:
    nome_int = _RIF_RISORSA_MAP.get(risorsa.lower())
    if not nome_int:
        return False, f"risorsa '{risorsa}' non valida. Usa: {', '.join(_RIF_RISORSE_VALIDE)}"
    campo = f"{nome_int}_abilitato"
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento_comune", {})[campo] = abilitata
    ok = _patch_runtime(patch)
    return ok, campo


def _set_rif_modo(modo: str) -> tuple[bool, str]:
    modo = modo.lower()
    _validi = ("mappa", "membri", "entrambi", "nessuno")
    if modo not in _validi:
        return False, f"modo non valido. Usa: {', '.join(_validi)}"
    mappa_on  = modo in ("mappa",  "entrambi")
    membri_on = modo in ("membri", "entrambi")
    def patch(ov):
        rif = ov.setdefault("globali", {}).setdefault("rifornimento", {})
        rif["mappa_abilitata"]  = mappa_on
        rif["membri_abilitati"] = membri_on
    ok = _patch_runtime(patch)
    return ok, f"mappa={'on' if mappa_on else 'off'}  membri={'on' if membri_on else 'off'}"


def _set_rif_soglia(risorsa: str, valore_m: float) -> tuple[bool, str]:
    nome_int = _RIF_RISORSA_MAP.get(risorsa.lower())
    if not nome_int:
        return False, f"risorsa '{risorsa}' non valida. Usa: {', '.join(_RIF_RISORSE_VALIDE)}"
    campo = f"soglia_{nome_int}_m"
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento_comune", {})[campo] = valore_m
    ok = _patch_runtime(patch)
    return ok, campo


def _set_rif_provviste(valore: int) -> tuple[bool, str]:
    def patch(ov):
        ov.setdefault("globali", {}).setdefault("rifornimento", {})["provviste_max"] = valore
    ok = _patch_runtime(patch)
    return ok, f"provviste_max={valore}M"


def _reset_rif_stato(nome_ist: Optional[str]) -> tuple[int, int]:
    instances = _read_instances_cfg()
    tutti = [c["nome"] for c in instances if c["nome"] != "FauMorfeus"]
    if nome_ist:
        up = nome_ist.upper()
        if up not in {t.upper() for t in tutti}:
            return 0, 1
        targets = [up]
    else:
        targets = tutti

    today = datetime.now(timezone.utc).date().isoformat()
    n_ok = n_err = 0
    for ist in targets:
        p = _root() / "state" / f"{ist}.json"
        try:
            st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            rif = st.setdefault("rifornimento", {})
            rif["spedizioni_oggi"]    = 0
            rif["provviste_esaurite"] = False
            rif["data_riferimento"]   = today
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
            n_ok += 1
        except Exception as exc:
            _log.warning("[TG-BOT] reset rif stato %s fallito: %s", ist, exc)
            n_err += 1
    return n_ok, n_err


# ─── Notify config accessors ──────────────────────────────────────────────────

def _notify_cycle_every_n() -> int:
    return int(_tg_config().get("notify_cycle_every_n", 5))

def _notify_cascade() -> bool:
    return bool(_tg_config().get("notify_cascade", True))

def _notify_drl() -> bool:
    return bool(_tg_config().get("notify_drl", True))

def _notify_daily_report_flag() -> bool:
    return bool(_tg_config().get("notify_daily_report", True))


# ─── Data readers ─────────────────────────────────────────────────────────────

def _read_engine_status() -> dict:
    return _read_json_safe(_root() / "engine_status.json")

def _read_morfeus_state() -> dict:
    return _read_json_safe(_root() / "data" / "morfeus_state.json")

def _read_runtime_overrides() -> dict:
    return _read_json_safe(_root() / "config" / "runtime_overrides.json")

def _read_state(instance: str) -> dict:
    return _read_json_safe(_root() / "state" / f"{instance}.json")

def _read_cicli() -> list:
    d = _read_json_safe(_root() / "data" / "telemetry" / "cicli.json")
    return d.get("cicli", [])

def _read_instances_cfg() -> list:
    p = _root() / "config" / "instances.json"
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _read_last_metrics(instance: str) -> dict:
    p = _root() / "data" / "istanza_metrics.jsonl"
    last: dict = {}
    try:
        if p.exists():
            tag = f'"{instance}"'
            for line in p.read_text(encoding="utf-8").splitlines():
                if tag in line:
                    try:
                        last = json.loads(line)
                    except Exception:
                        pass
    except Exception:
        pass
    return last

def _read_all_last_metrics() -> dict[str, dict]:
    p = _root() / "data" / "istanza_metrics.jsonl"
    last: dict[str, dict] = {}
    try:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    nome = r.get("instance", "")
                    if nome:
                        last[nome] = r
                except Exception:
                    pass
    except Exception:
        pass
    return last

def _read_truppe_storico(instance: str) -> list:
    d = _read_json_safe(_root() / "data" / "storico_truppe.json")
    return d.get(instance, [])


# ─── Formatters ───────────────────────────────────────────────────────────────

def _fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _parse_dt(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _maintenance_info() -> Optional[dict]:
    try:
        from core.maintenance import get_maintenance_info
        return get_maintenance_info()
    except Exception:
        return None


def _morfeus_abilitata() -> bool:
    ov = _read_runtime_overrides()
    return ov.get("istanze", {}).get("FauMorfeus", {}).get("abilitata", True)


def _fmt_drl_line(prefix: str = "DRL FauMorfeus") -> str:
    morf    = _read_morfeus_state()
    drl     = morf.get("daily_recv_limit", -1)
    drl_max = morf.get("daily_recv_limit_max", -1)
    ts_drl  = morf.get("ts", "")
    if drl < 0:
        return f"{prefix}: non disponibile"
    drl_pct = int((drl / drl_max * 100)) if drl_max > 0 else 0
    icon = "🔴" if drl == 0 else ("🟡" if drl_pct < 20 else "🟢")
    ts_str = ""
    stale_note = ""
    if ts_drl:
        try:
            dt  = datetime.fromisoformat(ts_drl.replace("Z", "+00:00"))
            ago = int((datetime.now(timezone.utc) - dt).total_seconds())
            ts_str = f" ({_fmt_dur(ago)} fa)"
            if ago > 6 * 3600 and not _morfeus_abilitata():
                stale_note = " ⚠ stale — FauMorfeus disabilitata"
        except Exception:
            pass
    return f"{prefix}: {icon} {drl/1e6:.0f}M / {drl_max/1e6:.0f}M ({drl_pct}%){ts_str}{stale_note}"


# ─── System check helpers ─────────────────────────────────────────────────────

def _get_uptime_s() -> int:
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetTickCount64()) // 1000
    except Exception:
        return -1


def _check_dashboard_running() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8765/", timeout=2)
        return True
    except Exception:
        return False


def _check_bot_running() -> bool:
    """True se il processo main.py Python è in esecuzione.

    Metodi (priorità decrescente):
    1. bot.pid — PID scritto da main.py al boot, controllo alive via Get-Process
    2. Get-CimInstance su python.exe/*main.py* (fallback se pid file mancante)
    3. engine_status.json freschezza (< 30 min, fallback finale)
    """
    # ── 1. PID file ──────────────────────────────────────────────────────────
    pid_path = _root() / "data" / "bot.pid"
    try:
        if pid_path.exists():
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue) -ne $null"],
                capture_output=True, text=True, timeout=5,
            )
            if r.stdout.strip() == "True":
                return True
    except Exception:
        pass

    # ── 2. CimInstance fallback ───────────────────────────────────────────────
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
             "| Where-Object { $_.CommandLine -like '*main.py*' "
             "  -and $_.CommandLine -notlike '*-m uvicorn*' } "
             "| Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=10,
        )
        count = r.stdout.strip()
        if count.isdigit() and int(count) > 0:
            return True
    except Exception:
        pass

    # ── 3. engine_status.json freschezza (30 min) ────────────────────────────
    es = _read_engine_status()
    if not es:
        return False
    ts_raw = es.get("ts_update") or es.get("ts", "")
    if not ts_raw:
        return False
    try:
        dt  = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt).total_seconds() < 1800
    except Exception:
        return False
