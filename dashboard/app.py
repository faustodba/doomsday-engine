# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/app.py
#
#  FastAPI application entry point.
#  Monta i router, serve /static, redirect / -> /ui.
#
#  Avvio: uvicorn dashboard.app:app --host 0.0.0.0 --port 8765
# ==============================================================================

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.routers import (
    api_status, api_stats,
    api_config_global, api_config_overrides, api_log,
    api_debug,
)


# ==============================================================================
# Helpers
# ==============================================================================

def _fmt_m(v: int | float) -> str:
    """Formatta valore in M/K leggibile. 91699999 → '91.7M'. 0 → '—'"""
    v = float(v)
    if v == 0:
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(int(v))


def _env_label() -> dict:
    """
    Deriva ambiente (PROD/DEV) da DOOMSDAY_ROOT.
    Restituisce dict con label, css_class e is_prod per i template.
    """
    root = os.environ.get("DOOMSDAY_ROOT", "")
    is_prod = "prod" in root.lower()
    return {
        "env_label":   "PROD" if is_prod else "DEV",
        "env_css":     "env-prod" if is_prod else "env-dev",
        "env_is_prod": is_prod,
    }


# ==============================================================================
# Lifespan
# ==============================================================================

_predictor_recorder_task = None


async def _predictor_recorder_loop():
    """Background task: snapshot cycle predictor + evaluate completed cycles.

    Cadenza:
      - Snapshot OGNI 15 min (SNAPSHOT_INTERVAL_MIN)
      - PIÙ snapshot IMMEDIATO ad ogni nuovo ciclo bot rilevato (reset
        del timer 15min). Permette al drilldown di mostrare la stima
        del ciclo CORRENTE invece dell'ultimo snapshot del ciclo
        precedente (utile dopo restart o tick_sleep lungo).

    Implementazione: sleep granulare 30s; snapshot triggered se:
      - elapsed dall'ultimo snap >= SNAPSHOT_INTERVAL_MIN * 60 OR
      - cycle_numero del ciclo bot in corso != cycle_numero ultimo snap
    """
    import asyncio
    from datetime import datetime, timezone
    from core.cycle_duration_predictor import predict_cycle_from_config
    from core.cycle_predictor_recorder import (
        record_snapshot, evaluate_cycles, SNAPSHOT_INTERVAL_MIN,
        _read_cicli_in_corso, read_recent_snapshots,
    )
    print(f"[DASHBOARD] predictor recorder avviato (snapshot ogni {SNAPSHOT_INTERVAL_MIN}min + reset on new cycle)")
    POLL_GRANULAR_S = 30
    while True:
        try:
            # Detection nuovo ciclo bot
            ciclo_corrente = _read_cicli_in_corso()
            cycle_now = ciclo_corrente.get("numero") if ciclo_corrente else None
            last_snaps = read_recent_snapshots(1)
            last_snap = last_snaps[0] if last_snaps else None
            last_cycle_snap = last_snap.get("cycle_numero") if last_snap else None

            elapsed_s = float("inf")
            if last_snap and last_snap.get("ts"):
                try:
                    last_ts = datetime.fromisoformat(last_snap["ts"])
                    elapsed_s = (datetime.now(timezone.utc) - last_ts).total_seconds()
                except Exception:
                    pass

            is_new_cycle = (
                cycle_now is not None
                and last_cycle_snap is not None
                and int(cycle_now) != int(last_cycle_snap)
            )
            interval_due = elapsed_s >= SNAPSHOT_INTERVAL_MIN * 60

            should_snap = is_new_cycle or interval_due or last_snap is None

            if should_snap:
                res = predict_cycle_from_config(strict_schedule=True)
                if "error" not in res:
                    per_ist = res.get("per_istanza", {}) or {}
                    sched_dbg = res.get("schedule_debug", {}) or {}
                    input_context = {
                        "istanze_abilitate": list(per_ist.keys()),
                        "task_globali_abilitati": sorted({
                            t for tasks in (
                                (info.get("due", []) + info.get("skipped", []))
                                for info in sched_dbg.values()
                            )
                            for t in tasks
                        }),
                        "tasks_per_istanza_due": {
                            inst: info.get("due", []) for inst, info in sched_dbg.items()
                        },
                        "per_istanza_predicted_s": {
                            inst: round(p.get("T_s", 0), 1)
                            for inst, p in per_ist.items()
                        },
                        "tick_sleep_s": float(res.get("tick_sleep_s", 0)),
                    }
                    extra = {"trigger": "new_cycle"} if is_new_cycle else None
                    record_snapshot(
                        predicted_min=float(res.get("T_ciclo_min", 0)),
                        n_istanze=int(res.get("n_istanze", 0)),
                        confidence=str(res.get("confidence", "?")),
                        input_context=input_context,
                        extra=extra,
                    )
                    if is_new_cycle:
                        print(f"[DASHBOARD] new cycle #{cycle_now} → forced immediate snapshot (reset 15min timer)")
                n_eval = evaluate_cycles()
                if n_eval > 0:
                    print(f"[DASHBOARD] cycle accuracy evaluated: {n_eval} cicli")
        except Exception as exc:
            print(f"[DASHBOARD] predictor recorder errore: {exc}")
        await asyncio.sleep(POLL_GRANULAR_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from dashboard.services.config_manager import (
        get_global_config, get_overrides, get_instances,
    )
    gcfg  = get_global_config()
    ov    = get_overrides()
    insts = get_instances()
    print(f"[DASHBOARD] global_config: {len(gcfg)} sezioni")
    print(f"[DASHBOARD] overrides:     {len(ov.get('istanze', {}))} istanze")
    print(f"[DASHBOARD] instances:     {len(insts)} istanze")
    print(f"[DASHBOARD] API docs:      http://localhost:8765/docs")
    # Avvia background task predictor recorder
    global _predictor_recorder_task
    _predictor_recorder_task = asyncio.create_task(_predictor_recorder_loop())
    yield
    print("[DASHBOARD] shutdown.")
    if _predictor_recorder_task and not _predictor_recorder_task.done():
        _predictor_recorder_task.cancel()


# ==============================================================================
# App
# ==============================================================================

app = FastAPI(
    title       = "Doomsday Engine V6 — Dashboard",
    description = "Monitoring e configurazione del bot farm",
    version     = "6.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = None,
)


# ==============================================================================
# Router mount
# ==============================================================================

app.include_router(api_status.router)
app.include_router(api_stats.router)
app.include_router(api_config_global.router)
app.include_router(api_config_overrides.router)
app.include_router(api_log.router)
app.include_router(api_debug.router)   # WU115 — debug screenshot per task


# ==============================================================================
# Static + Templates
# ==============================================================================

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

_TEMPLATES = Path(__file__).parent / "templates"
templates  = Jinja2Templates(directory=str(_TEMPLATES))


# ==============================================================================
# Root redirect
# ==============================================================================

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")


# ==============================================================================
# Pagine UI Jinja2
# ==============================================================================

@app.get("/ui", include_in_schema=False)
def ui_index(request: Request):
    from dashboard.services.config_manager import get_merged_config, get_instances
    return templates.TemplateResponse(request, "index.html", {
        "active":  "home",
        "cfg":     get_merged_config(),
        "istanze": get_instances(),
        **_env_label(),
    })


@app.get("/ui/telemetria", include_in_schema=False)
def ui_telemetria(request: Request):
    """Pagina dedicata telemetria — pannelli analytics.

    Refactor 04/05: estratta da home (`/ui`) per alleggerire la dashboard.
    Storico eventi spostato a sua volta su `/ui/storico` (pagina separata).
    """
    from dashboard.services.config_manager import get_instances
    return templates.TemplateResponse(request, "telemetria.html", {
        "active":  "telemetria",
        "istanze": get_instances(),
        **_env_label(),
    })


@app.get("/ui/storico", include_in_schema=False)
def ui_storico(request: Request):
    """Pagina dedicata storico eventi — tabella filtrabile per istanza+task."""
    from dashboard.services.config_manager import get_instances
    return templates.TemplateResponse(request, "storico.html", {
        "active":  "storico",
        "istanze": get_instances(),
        **_env_label(),
    })


@app.get("/ui/predictor", include_in_schema=False)
def ui_predictor(request: Request):
    """Pagina dedicata predictor — cycle duration + skip squadre fuori."""
    return templates.TemplateResponse(request, "predictor.html", {
        "active": "predictor",
        **_env_label(),
    })


@app.get("/ui/mockup/telemetria", include_in_schema=False)
def ui_mockup_telemetria(request: Request):
    """
    Mockup statico — validation layout pannelli telemetria proposti.
    Dati hardcoded realistici (memoria notte 26/04 + sessione corrente).
    Da rimuovere dopo validazione utente.
    """
    html = _render_mockup_telemetria()
    return HTMLResponse(html)


def _render_mockup_telemetria() -> str:
    # Dati di esempio realistici da memoria progetto (notte 26/04 + sessione corrente)
    task_kpi = [
        # (nome,            esec, ok%,   avg,     last,    err)
        ("boost",            187,  98,  "42s",   "12:31", "—"),
        ("rifornimento",      92,  85,  "3m12s", "12:24", "OCR provviste fail ×3"),
        ("raccolta",         145,  71,  "8m40s", "12:33", "nessuna squadra ×12"),
        ("donazione",         45,  91,  "1m05s", "12:18", "—"),
        ("districtshowdown",   8,  50,  "12m00", "11:55", "early-exit ×2"),
        ("arena",             45,  93,  "1m20s", "12:19", "timeout 300s ×3"),
        ("zaino",             38, 100,  "55s",   "12:22", "—"),
        ("vip",               42, 100,  "18s",   "12:30", "—"),
    ]

    health = [
        ("warn", "Stab HOME timeout",        "18/23 boot (78%)",       "issue notte 26/04 #2"),
        ("warn", "ADB cascade abort",        "3 (FAU_02 ×2, FAU_04)",  "abort tick + reset emergenz."),
        ("warn", "ARENA recovery cascade",   "4 (FAU_05/07/07/09)",    "issue notte 26/04 #3"),
        ("warn", "Banner unmatched",         "14 tap X auto-fallback", "issue #54"),
        ("warn", "Boot foreground recov",    "2 (~90s/recovery)",      "WU60 — fix attivo"),
        ("ok",   "Spedizioni inviate",       "104/110 (94%)",          ""),
        ("ok",   "Cycle completati 24h",     "8 round (12 ist × 8)",   ""),
    ]

    ist_status = [
        # (nome, esito, durata, tasks_str, badge)
        ("FAU_00", "ok",     "12.4m",  "boost rif×2 racc×4",     ""),
        ("FAU_01", "ok",     "11.8m",  "rif×2 racc×5 don",       ""),
        ("FAU_02", "abort",  "09.2m",  "ADB cascade abort",      "ADB"),
        ("FAU_03", "live",   "08.5m",  "task=raccolta segh L7",  "▸"),
        ("FAU_04", "wait",   "—",      "in coda",                ""),
        ("FAU_05", "wait",   "—",      "in coda",                ""),
        ("FAU_06", "wait",   "—",      "in coda",                ""),
        ("FAU_07", "wait",   "—",      "in coda",                "DEF"),  # deficit
        ("FAU_08", "wait",   "—",      "in coda",                ""),
        ("FAU_09", "wait",   "—",      "in coda",                ""),
        ("FAU_10", "wait",   "—",      "in coda",                ""),
    ]

    trend = [
        # (label, sparkline ascii, attuale, delta)
        ("Spedizioni/gg",  "▂▃▄▆▇█▇▆", "104",   "↑13% vs avg"),
        ("Tassa media",    "▆▆▇▆▆▆▆▇", "23.0%", "stable"),
        ("Cycle time",     "▅▆▇█▇▆▅▅", "150m",  "avg 152m"),
        ("Anomalie/gg",    "▂▂▃▄█▆▃▂", "37",    "ARENA cascade ×4"),
    ]

    # ── HTML build ─────────────────────────────────────────────────────────
    def _ok_pill(pct):
        col = "var(--green)" if pct >= 90 else ("#fbbf24" if pct >= 70 else "var(--red,#f87171)")
        return f'<span style="color:{col};font-weight:600">{pct}%</span>'

    rows_kpi = "".join(
        f'<tr><td style="color:var(--accent)">{n}</td>'
        f'<td style="text-align:right">{e}</td>'
        f'<td style="text-align:right">{_ok_pill(p)}</td>'
        f'<td style="text-align:right;color:var(--text-dim)">{a}</td>'
        f'<td style="text-align:right;color:var(--text-dim)">{l}</td>'
        f'<td style="color:var(--text-dim);font-size:11px">{er}</td></tr>'
        for n, e, p, a, l, er in task_kpi
    )

    def _hbadge(kind):
        if kind == "ok":   return '<span style="color:var(--green);font-weight:600">✓</span>'
        return '<span style="color:#fbbf24;font-weight:600">⚠</span>'

    rows_health = "".join(
        f'<tr><td>{_hbadge(k)}</td>'
        f'<td style="color:var(--text)">{lbl}</td>'
        f'<td style="text-align:right;color:var(--accent);font-weight:600">{val}</td>'
        f'<td style="color:var(--text-dim);font-size:11px">{note}</td></tr>'
        for k, lbl, val, note in health
    )

    def _isth_badge(b):
        if b == "ADB": return '<span style="color:var(--red);font-size:10px;border:1px solid var(--red);padding:1px 5px;border-radius:3px">ADB</span>'
        if b == "DEF": return '<span style="color:#fbbf24;font-size:10px;border:1px solid #fbbf24;padding:1px 5px;border-radius:3px" title="netto deficit risorse">DEF</span>'
        if b == "▸":   return '<span style="color:var(--accent);font-weight:700">▸</span>'
        return ""

    def _isth_color(esito):
        return {
            "ok":    "var(--green)",
            "abort": "var(--red)",
            "live":  "var(--accent)",
            "wait":  "var(--text-dim)",
        }.get(esito, "var(--text)")

    rows_ist = "".join(
        f'<tr><td style="color:var(--accent);font-weight:600">{n}</td>'
        f'<td style="color:{_isth_color(es)}">{es}</td>'
        f'<td style="text-align:right">{d}</td>'
        f'<td style="color:var(--text-dim)">{t}</td>'
        f'<td style="text-align:center">{_isth_badge(b)}</td></tr>'
        for n, es, d, t, b in ist_status
    )

    rows_trend = "".join(
        f'<tr><td style="color:var(--text-dim)">{lbl}</td>'
        f'<td style="font-family:monospace;font-size:14px;color:var(--accent);letter-spacing:1px">{spark}</td>'
        f'<td style="text-align:right;color:var(--text);font-weight:600">{cur}</td>'
        f'<td style="color:var(--text-dim);font-size:11px">{delta}</td></tr>'
        for lbl, spark, cur, delta in trend
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <title>Mockup Telemetria — Doomsday V6</title>
  <link rel="stylesheet" href="/static/style.css">
  <style>
    .mock-banner {{
      background: #fbbf24; color: #000; padding: 8px 16px;
      text-align: center; font-weight: 600; letter-spacing: 1px;
    }}
    .mock-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
      padding: 16px; max-width: 1400px; margin: 0 auto;
    }}
    .mock-grid > .full {{ grid-column: 1 / -1; }}
    .mock-card {{
      background: var(--bg-2, #1a1a24);
      border: 0.5px solid var(--border);
      border-radius: 6px; padding: 14px;
    }}
    .mock-card h3 {{
      margin: 0 0 10px 0;
      font-size: 13px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--accent);
      border-bottom: 0.5px solid var(--border);
      padding-bottom: 6px;
    }}
    .mock-card table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .mock-card th {{
      text-align: left; color: var(--text-dim);
      font-weight: 400; font-size: 10px; text-transform: uppercase;
      letter-spacing: 1px; padding: 4px 6px; border-bottom: 0.5px solid var(--border);
    }}
    .mock-card td {{ padding: 4px 6px; border-bottom: 0.5px solid rgba(255,255,255,0.04); }}
    .mock-card tr:last-child td {{ border-bottom: none; }}
    .mock-card .footnote {{
      margin-top: 8px; color: var(--text-dim); font-size: 10px;
      font-style: italic;
    }}
  </style>
</head>
<body>
  <div class="mock-banner">⚠ MOCKUP STATICO — dati di esempio per validazione layout. URL: /ui/mockup/telemetria</div>

  <div class="mock-grid">

    <!-- 1. TELEMETRIA TASK ──────────────────────────────────────── -->
    <div class="mock-card full">
      <h3>📊 Telemetria task</h3>
      <table>
        <thead>
          <tr><th>task</th><th style="text-align:right">esec</th>
              <th style="text-align:right">ok%</th>
              <th style="text-align:right">avg durata</th>
              <th style="text-align:right">last run</th>
              <th>ultimo errore</th></tr>
        </thead>
        <tbody>{rows_kpi}</tbody>
      </table>
      <div class="footnote">
        sorgenti: <code>engine_status.istanze[].task_eseguiti</code> + scan rolling 24h <code>logs/FAU_*.jsonl</code> (pattern <code>Orchestrator: task '*' completato/failed</code>). Refresh 30s.
      </div>
    </div>

    <!-- 2. HEALTH 24h ────────────────────────────────────────────── -->
    <div class="mock-card">
      <h3>⚠️ Health 24h</h3>
      <table>
        <tbody>{rows_health}</tbody>
      </table>
      <div class="footnote">
        regex su 24h logs JSONL — pattern noti dalla memoria (notte 26/04, banner #54, WU60 foreground).
      </div>
    </div>

    <!-- 3. CICLO CORRENTE ───────────────────────────────────────── -->
    <div class="mock-card">
      <h3>🔄 Ciclo corrente</h3>
      <div style="display:flex;justify-content:space-between;margin-bottom:10px;font-size:12px">
        <div>
          <div style="color:var(--text-dim)">CICLO #14</div>
          <div style="color:var(--accent);font-size:18px;font-weight:600">23m 14s</div>
        </div>
        <div>
          <div style="color:var(--text-dim);text-align:right">prossima</div>
          <div style="color:var(--text);font-weight:600;text-align:right">FAU_04</div>
        </div>
        <div>
          <div style="color:var(--text-dim);text-align:right">ETA fine</div>
          <div style="color:var(--text);font-weight:600;text-align:right">~127m</div>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>ist</th><th>esito</th>
              <th style="text-align:right">durata</th>
              <th>task</th><th style="text-align:center"></th></tr>
        </thead>
        <tbody>{rows_ist}</tbody>
      </table>
      <div class="footnote">
        sorgenti: <code>engine_status.istanze[].ultimo_task</code> + <code>stato</code>. ETA = (12 - completate) × media ultimi 10.
      </div>
    </div>

    <!-- 4. TREND 7gg ─────────────────────────────────────────────── -->
    <div class="mock-card full">
      <h3>📈 Trend ultimi 7 giorni</h3>
      <table>
        <tbody>{rows_trend}</tbody>
      </table>
      <div class="footnote">
        sparkline ASCII (no librerie) da <code>data/storico_farm.json</code> (retention 90gg già esistente).
      </div>
    </div>

  </div>

  <div style="text-align:center;padding:20px;color:var(--text-dim);font-size:11px">
    <a href="/ui" style="color:var(--accent)">← back to dashboard</a>
    &nbsp;·&nbsp; pannelli aggiunti come HTMX partial sotto RISORSE FARM
  </div>
</body>
</html>"""


@app.get("/ui/instance/{nome}", include_in_schema=False)
def ui_instance(request: Request, nome: str):
    from dashboard.services.stats_reader import get_instance_stats
    from dashboard.services.log_reader import get_instance_log
    from dashboard.services.config_manager import get_instance, get_overrides
    return templates.TemplateResponse(request, "instance.html", {
        "active":    "instance",
        "stats":     get_instance_stats(nome),
        "log":       get_instance_log(nome, 100),
        "instance":  get_instance(nome),
        "overrides": get_overrides(),
        **_env_label(),
    })


@app.get("/ui/config", include_in_schema=False)
def ui_config(request: Request):
    """Redirect alla pagina global config — la pagina dedicata agli override
    runtime è stata rimossa (duplicava overview per task flags + istanze, e
    duplicava global config per le altre sezioni). WU98 02/05/2026."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui/config/global", status_code=302)


@app.get("/ui/config/global", include_in_schema=False)
def ui_config_global(request: Request):
    """Pagina config — legge global_config.json RAW (no round-trip via
    GlobalConfig dataclass che perde campi nuovi: rifugio, rifornimento
    unificato, auto_learn_banner, raccolta_ocr_debug, soglia_allocazione,
    e converte allocazione in frazioni 0-1)."""
    import json
    from dashboard.services.config_manager import (
        _GLOBAL_CONFIG_PATH, get_instances, get_overrides,
    )
    from shared.instance_meta import get_master_instances
    try:
        with open(_GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg_raw = json.load(f)
    except Exception:
        cfg_raw = {}
    return templates.TemplateResponse(request, "config_global.html", {
        "active":       "global",
        "cfg":          cfg_raw,
        "instances":    get_instances(),
        "overrides":    get_overrides(),
        "master_names": set(get_master_instances()),
        **_env_label(),
    })


# ==============================================================================
# HTMX partial — vecchia serie (mantenuti per retrocompat.)
# ==============================================================================

@app.get("/ui/partial/card/{nome}", include_in_schema=False)
def ui_partial_card(request: Request, nome: str):
    from dashboard.services.stats_reader import get_instance_stats
    return templates.TemplateResponse(request, "partials/card_istanza.html", {
        "s": get_instance_stats(nome),
    })


@app.get("/ui/partial/status", include_in_schema=False)
def ui_partial_status(request: Request):
    from dashboard.services.stats_reader import get_engine_status
    return templates.TemplateResponse(request, "partials/status_bar.html", {
        "engine": get_engine_status(),
    })


@app.get("/ui/partial/log/{nome}", include_in_schema=False)
def ui_partial_log(request: Request, nome: str):
    from dashboard.services.log_reader import get_instance_log
    return templates.TemplateResponse(request, "partials/log_entries.html", {
        "log": get_instance_log(nome, 100),
    })


@app.get("/ui/partial/task-flags", include_in_schema=False)
def ui_partial_task_flags(request: Request):
    from dashboard.services.config_manager import get_overrides
    return templates.TemplateResponse(request, "partials/task_flags.html", {
        "overrides": get_overrides(),
    })


# ==============================================================================
# HTMX partial — nuova serie (index.html V6)
# ==============================================================================

@app.get("/ui/partial/status-inline", include_in_schema=False)
def partial_status_inline(request: Request):
    from dashboard.services.stats_reader import get_engine_status
    es = get_engine_status()
    uptime_h  = es.uptime_s // 3600
    uptime_m  = (es.uptime_s % 3600) // 60
    stato_css = "running" if es.stato == "running" else "stopped"
    html = f'''
    <span class="dot {stato_css}"></span>
    <span class="cnt">{es.stato}</span>
    <span class="cnt amber">ciclo <b>{es.ciclo}</b></span>
    <span class="cnt">{uptime_h}h {uptime_m}m</span>
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/inst-grid", include_in_schema=False)
def partial_inst_grid(request: Request):
    from dashboard.services.stats_reader import get_engine_status
    from dashboard.services.config_manager import get_instances, get_overrides
    es    = get_engine_status()
    insts = get_instances()
    ov    = get_overrides()
    rows  = []

    for ist in insts:
        nome = ist.get("nome", "")
        if not nome:
            continue
        ist_ov     = ov.get("istanze", {}).get(nome, {})
        abilitata  = ist_ov.get("abilitata", ist.get("abilitata", True))
        ist_status = es.istanze.get(nome)

        if not abilitata:
            stato = "idle"
        elif ist_status:
            stato = ist_status.stato or "unknown"
        else:
            stato = "unknown"

        ut         = ist_status.ultimo_task if ist_status else None
        task_cor   = (ist_status.task_corrente if ist_status else None) or ""
        task_label = task_cor or (ut.nome if ut else "—")
        esito      = ut.esito if ut else ""
        esito_css  = "esito-ok" if esito == "ok" else ("esito-err" if esito == "err" else "")
        ts_label   = ut.ts if ut else "—"
        msg_label  = (ut.msg or "")[:35] if ut else "—"
        errori     = ist_status.errori if ist_status else 0
        errori_css = "color:var(--red)" if errori > 0 else "color:var(--text-dim)"

        rows.append(f'''<div class="ic {stato}">
          <div class="ic-head">
            <span class="ic-name">{nome}</span>
            <span class="badge {stato}">{stato}</span>
          </div>
          <div class="ic-row"><span>task</span>
            <span class="{esito_css}">{task_label}</span></div>
          <div class="ic-row"><span>ts</span>
            <span>{ts_label}</span></div>
          <div class="ic-row"><span>msg</span>
            <span style="font-size:9px;max-width:110px;text-align:right;
              overflow:hidden;white-space:nowrap;text-overflow:ellipsis">
              {msg_label}</span></div>
          <div class="ic-row"><span>errori</span>
            <span style="{errori_css}">{errori}</span></div>
        </div>''')

    return HTMLResponse(''.join(rows) or
        '<div class="ic idle"><div class="ic-head"><span class="ic-name">nessuna istanza</span></div></div>')


@app.get("/ui/partial/task-flags-v2", include_in_schema=False)
def partial_task_flags_v2(request: Request):
    from dashboard.services.config_manager import get_overrides
    ov    = get_overrides()
    flags = ov.get("globali", {}).get("task", {})

    COMPOUND = {
        "rifornimento": {
            "subtypes": ["mappa", "membri"],
            "active":   "mappa" if ov.get("globali", {}).get("rifornimento", {}).get("mappa_abilitata") else "membri",
        },
        "zaino": {
            "subtypes": ["bag", "svuota"],
            "active":   ov.get("globali", {}).get("zaino", {}).get("modalita", "bag"),
        },
    }

    # auto-WU24 (27/04): rifornimento+zaino accoppiati nella stessa riga
    # del grid 2-col (compound side-by-side, no più span 2 cols).
    # WU94 (02/05): raccolta ora controllabile via flag globale task.raccolta;
    # esposta in cima all'ORDER come task base.
    ORDER = [
        "raccolta", "rifornimento",
        "zaino", "vip",
        "boost", "truppe",
        "arena", "store",
        "alleanza", "donazione",
        "messaggi", "main_mission",
        "radar", "arena_mercato",
        "district_showdown",
    ]

    # auto-WU22 (27/04): rewrite as 2-col checkbox rows (style rifornimento .rr-cb)
    # auto-WU24 (27/04): max nome 15 char (abbrev solo district_showdown);
    # rifornimento+zaino side-by-side (no compound span 2 cols).
    ABBREV = {
        "district_showdown": "districtSD",  # 17 → 10
    }
    MAX_LEN = 15
    rows     = []
    rendered = set()

    for name in ORDER:
        if name in rendered:
            continue
        rendered.add(name)

        on      = flags.get(name, True)
        on_cls  = "on" if on else "off"
        checked = "checked" if on else ""
        # Abbreviazione solo se nome > MAX_LEN char
        display = ABBREV.get(name, name) if len(name) > MAX_LEN else name

        if name in COMPOUND:
            c    = COMPOUND[name]
            subs = []
            for s in c["subtypes"]:
                active_cls = "active" if s == c["active"] else ""
                subs.append(
                    f'<span class="task-sub {active_cls}" '
                    f'onclick="event.preventDefault();setModeRemote(\'{name}\',\'{s}\')">{s}</span>'
                )
            subs_html = '<span class="task-subs">' + "".join(subs) + '</span>'
            rows.append(f'''<label class="task-row {on_cls}" title="{name}">
              <input type="checkbox" class="task-cb" {checked}
                     onchange="toggleTaskFlag('{name}', this.checked)">
              <span class="task-name">{display}</span>
              {subs_html}
            </label>''')
        else:
            rows.append(f'''<label class="task-row {on_cls}" title="{name}">
              <input type="checkbox" class="task-cb" {checked}
                     onchange="toggleTaskFlag('{name}', this.checked)">
              <span class="task-name">{display}</span>
            </label>''')

    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/ist-table", include_in_schema=False)
def partial_ist_table(request: Request):
    from dashboard.services.config_manager import get_instances, get_overrides
    from dashboard.services.stats_reader import get_engine_status
    from shared.instance_meta import is_master_instance
    insts = get_instances()
    ov    = get_overrides()
    es    = get_engine_status()
    rows  = []

    for ist in insts:
        nome       = ist.get("nome", "")
        ist_ov     = ov.get("istanze", {}).get(nome, {})
        ist_status = es.istanze.get(nome)

        abilitata   = ist_ov.get("abilitata",    ist.get("abilitata",    True))
        truppe      = ist_ov.get("truppe",        ist.get("truppe",       0))
        tipologia   = ist_ov.get("tipologia",     ist.get("profilo",      "full"))
        fascia_raw  = ist_ov.get("fascia_oraria", ist.get("fascia_oraria", ""))
        max_squadre = ist.get("max_squadre", 4)
        livello     = ist.get("livello", 6)
        # WU50 — flag fuori territorio: override > instances.json (default)
        fuori_terr  = bool(ist_ov.get(
            "raccolta_fuori_territorio",
            ist.get("raccolta_fuori_territorio", False),
        ))
        stato       = ist_status.stato if ist_status else ("idle" if not abilitata else "unknown")
        # WU52 — quando istanza disabilitata, gli altri campi sono read-only
        disabled_attr = "disabled" if not abilitata else ""
        # WU101/WU121 — ★ marker accanto al nome se istanza master (hardcoded
        # in shared/instance_meta._HARDCODED_MASTERS, no UI toggle). Coerente
        # con card_istanza partial e altri panel.
        master_marker = ' <span title="istanza master (ricevente)" style="color:#ffc107;margin-right:2px">★</span>' if is_master_instance(nome) else ''

        # Badge "stato" sostituito da timestamp ultima esecuzione task se disponibile.
        # `ultimo_task.ts` è HH:MM:SS (no data). Aggiungo data odierna server-side
        # (engine_status viene aggiornato in continuo, ts si riferisce a oggi).
        # Fallback: se nessun ultimo_task → mostra stato badge.
        ut = ist_status.ultimo_task if ist_status else None
        ut_ts   = getattr(ut, "ts", None) if ut else None
        ut_nome = getattr(ut, "nome", None) if ut else None
        if ut_ts:
            from datetime import datetime as _dt
            today_dm = _dt.now().strftime("%d/%m")
            ut_lbl = ut_nome or "?"
            badge_html = (
                f'<span class="badge ts" style="margin-left:4px;color:var(--text-dim);'
                f'font-family:var(--font-mono);font-size:9px"'
                f' title="ultimo task: {ut_lbl}">'
                f'{today_dm} {ut_ts}</span>'
            )
        else:
            badge_html = f'<span class="badge {stato}" style="margin-left:4px">{stato}</span>'

        fascia_da = ""
        fascia_a  = ""
        if fascia_raw and "-" in str(fascia_raw):
            parts = str(fascia_raw).split("-")
            if len(parts) == 2:
                fascia_da = parts[0].strip()
                fascia_a  = parts[1].strip()

        nome_css = "" if abilitata else " off"
        checked  = "checked" if abilitata else ""

        rows.append(f'''<tr data-nome="{nome}" class="ist-row {'disabled' if not abilitata else ''}">
          <td><input type="checkbox" class="ist-cb" {checked}
                     style="accent-color:var(--accent);width:13px;height:13px;cursor:pointer"
                     onchange="onIstToggle(this)"></td>
          <td>
            <span class="ist-name-col{nome_css}">{master_marker}{nome}</span>
            {badge_html}
          </td>
          <td><input type="number" class="ist-truppe" value="{truppe}" {disabled_attr}
                     min="0" step="1000" style="width:62px"></td>
          <td><input type="number" class="ist-sq" value="{max_squadre}" {disabled_attr}
                     min="1" max="10" style="width:36px"></td>
          <td><select class="ist-prof" {disabled_attr}>
            <option value="full"          {"selected" if tipologia=="full"          else ""}>completo</option>
            <option value="raccolta_fast" {"selected" if tipologia=="raccolta_fast" else ""}>completo · fast</option>
            <option value="raccolta_only" {"selected" if tipologia=="raccolta_only" else ""}>solo raccolta</option>
          </select></td>
          <td><input type="number" class="ist-lv" value="{livello}" {disabled_attr}
                     min="1" max="10" style="width:36px"></td>
          <td><input type="checkbox" class="ist-fuori-terr" {"checked" if fuori_terr else ""} {disabled_attr}
                     title="modalità fuori territorio: raccolta su nodi fuori senza blacklist (WU50)"
                     style="accent-color:var(--accent);width:13px;height:13px;cursor:pointer"></td>
          <td><div class="fascia">
            <input type="time" class="ist-fascia-da" value="{fascia_da}" {disabled_attr}>
            <span class="fsep">—</span>
            <input type="time" class="ist-fascia-a" value="{fascia_a}" {disabled_attr}>
          </div></td>
        </tr>''')

    return HTMLResponse(''.join(rows) or
        '<tr><td colspan="8" style="color:var(--text-dim);font-size:9px;padding:8px">nessuna istanza</td></tr>')


@app.get("/ui/partial/storico", include_in_schema=False)
def partial_storico(
    request: Request,
    istanza: Optional[str] = None,
    task:    Optional[str] = None,
):
    from dashboard.services.stats_reader import get_storico
    entries = get_storico(50)

    if istanza:
        entries = [e for e in entries if e.istanza == istanza]
    if task:
        entries = [e for e in entries if e.task == task]

    rows = []
    for e in reversed(entries[-30:]):
        css = "esito-ok" if e.esito == "ok" else "esito-err"
        rows.append(f'''<tr>
          <td>{e.ts}</td>
          <td style="color:var(--accent)">{e.istanza}</td>
          <td>{e.task}</td>
          <td class="{css}">{e.esito}</td>
          <td>{e.durata_s:.1f}s</td>
          <td style="color:var(--text-dim);font-size:9px">{e.msg[:60]}</td>
        </tr>''')

    return HTMLResponse(''.join(rows) or
        '<tr><td colspan="6" style="color:var(--text-dim);text-align:center;padding:8px">nessun evento</td></tr>')


@app.get("/ui/partial/res-totali", include_in_schema=False)
def partial_res_totali(request: Request):
    """
    Pannello risorse farm — blocco superiore.
    Mostra: totale inviato oggi per risorsa (da dettaglio_oggi — immune OCR Issue #16)
            provviste residue totali + spedizioni oggi / quota per ciclo.
    """
    from dashboard.services.stats_reader import get_risorse_farm

    farm = get_risorse_farm()

    RISORSE = [
        ("pomodoro", "🍅"),
        ("legno",    "🪵"),
        ("acciaio",  "⚙"),
        ("petrolio", "🛢"),
    ]

    # Barre proporzionali al massimo valore
    valori  = [farm.inviato_per_risorsa.get(r, 0) for r, _ in RISORSE]
    max_val = max(valori) if any(v > 0 for v in valori) else 1

    rows_inviato = ""
    for risorsa, ico in RISORSE:
        qta = farm.inviato_per_risorsa.get(risorsa, 0)
        pct = int(qta / max_val * 100) if max_val > 0 else 0
        lbl = _fmt_m(qta)
        rows_inviato += f'''
        <div class="res-row">
          <span class="res-ico">{ico}</span>
          <span class="res-name">{risorsa}</span>
          <div class="res-bar-wrap">
            <div class="res-bar" style="width:{pct}%"></div>
          </div>
          <span class="res-val">{lbl}</span>
        </div>'''

    # Spedizioni: cumulativo giornaliero vs quota per-ciclo
    # Semantica: spedizioni_oggi può superare quota_max_per_ciclo (è multi-ciclo)
    # WU34: panel pulito a NETTO. Lordo OCR esposto solo in tooltip.
    prov_netta_lbl = _fmt_m(farm.provviste_residue_netta)
    prov_lordo_lbl = _fmt_m(farm.provviste_residue)

    # Dettaglio per istanza (compact) — provviste in NETTO
    _ZERO_INVIATO = {r: 0 for r in ("pomodoro", "legno", "petrolio", "acciaio")}

    detail_rows = ""
    for d in sorted(farm.istanze_detail, key=lambda x: x.nome):
        # Skip istanze senza mai spedizioni (es. raccolta_only come FauMorfeus)
        if d.inviato_oggi == _ZERO_INVIATO and d.spedizioni_oggi == 0:
            continue
        esaurita_css   = "color:var(--red)" if d.provviste_esaurite else "color:var(--text-dim)"
        prov_netta_ist = _fmt_m(d.provviste_residue_netta)
        prov_lordo_ist = _fmt_m(d.provviste_residue)
        tassa_pct      = d.tassa_pct_avg * 100
        tooltip        = f"lordo {prov_lordo_ist} · tassa {tassa_pct:.1f}%"
        inv_str        = " · ".join(
            f"{ico}{_fmt_m(d.inviato_oggi.get(r, 0))}"
            for r, ico in RISORSE
            if d.inviato_oggi.get(r, 0) > 0
        ) or "—"
        detail_rows += f'''
        <div class="res-row" style="font-size:9px">
          <span class="res-name" style="color:var(--accent);min-width:52px">{d.nome}</span>
          <span style="flex:1;color:var(--text-dim)">{inv_str}</span>
          <span style="{esaurita_css}" title="{tooltip}">{prov_netta_ist}</span>
        </div>'''

    # WU39 — Capienza giornaliera residua FauMorfeus (Daily Receiving Limit)
    morf = farm.morfeus
    if morf.daily_recv_limit < 0:
        morf_html = (
            '<div class="res-sub" style="display:flex;justify-content:space-between;align-items:center">'
            '<span>capienza morfeus</span>'
            '<span style="color:var(--text-dim)" title="OCR mai eseguito — attendere primo rifornimento">—</span>'
            '</div>'
        )
    else:
        recv_lbl = _fmt_m(morf.daily_recv_limit)
        if morf.daily_recv_limit == 0:
            recv_col = "var(--red,#f87171)"
            recv_warn = " ⚠ saturo"
        elif morf.daily_recv_limit < 5_000_000:
            recv_col = "#fbbf24"
            recv_warn = ""
        else:
            recv_col = "var(--accent)"
            recv_warn = ""
        # ts compatto HH:MM
        ts_short = morf.ts[11:16] if len(morf.ts) >= 16 else "—"
        morf_html = (
            f'<div class="res-sub" style="display:flex;justify-content:space-between;align-items:center" '
            f'title="aggiornato {morf.ts[:19]} da {morf.letto_da}">'
            f'<span>capienza morfeus</span>'
            f'<span style="color:{recv_col}">{recv_lbl}{recv_warn}'
            f'<span style="color:var(--text-dim);font-size:9px"> · {ts_short} {morf.letto_da}</span>'
            f'</span>'
            f'</div>'
        )

    html = f'''
    <div class="res-sub">inviato oggi — tutte le istanze</div>
    {rows_inviato}
    <div class="res-sub" style="margin-top:10px;display:flex;justify-content:space-between;align-items:center">
      <span>spedizioni oggi</span>
      <span style="color:var(--accent)">{farm.spedizioni_oggi}
        <span style="color:var(--text-dim);font-size:9px">· {farm.quota_max_per_ciclo}/ciclo</span>
      </span>
    </div>
    {morf_html}
    <div class="res-sub" style="display:flex;justify-content:space-between;align-items:center"
         title="lordo OCR: {prov_lordo_lbl}">
      <span>provviste residue (netto)</span>
      <span style="color:var(--accent)">{prov_netta_lbl}</span>
    </div>
    <div class="res-sub" style="margin-top:10px">dettaglio istanze (netto)</div>
    {detail_rows if detail_rows else
      '<div style="color:var(--text-dim);font-size:9px;padding:4px 0">nessun dato disponibile</div>'}
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/produzione-istanze", include_in_schema=False)
def partial_produzione_istanze(request: Request):
    """
    Auto-WU14 step3: cards produzione per istanza — compatta.
    Mostra sessione corrente + sessione precedente in grid 3-col.
    No scroll: tutte le istanze visibili.
    """
    from dashboard.services.stats_reader import get_produzione_istanze
    # Include master in fondo alla griglia: card con badge ★ + bordo dorato
    # (i dati aggregati continuano a escluderla, vedi get_risorse_farm)
    dati = get_produzione_istanze(include_master=True)
    if not dati:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px">'
            'nessuna istanza con dati produzione</div>'
        )

    RISORSE_ICO = [("pomodoro", "🍅"), ("legno", "🪵"),
                   ("acciaio", "⚙"),   ("petrolio", "🛢")]

    def _fmt_q(v):
        try:
            v = float(v)
        except Exception:
            return "—"
        if v == 0:
            return "0"
        sign = "-" if v < 0 else ""
        v = abs(v)
        if v >= 1_000_000:
            return f"{sign}{v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"{sign}{v/1_000:.0f}K"
        return f"{sign}{v:.0f}"

    # Master istanze in fondo alla griglia (priorità rendering ordinarie)
    dati = sorted(dati, key=lambda r: (bool(r.get("master", False)), r.get("nome", "")))

    cards_html = []
    for entry in dati:
        nome = entry.get("nome", "?")
        is_master = bool(entry.get("master", False))
        # auto-WU21 (27/04): istanze disabilitate continuano a comparire
        # con gli ultimi dati persistiti. Stile faded + badge DISABLED.
        is_abilitata = bool(entry.get("abilitata", False))
        corrente   = entry.get("corrente") or {}
        precedente = entry.get("precedente") or {}

        # auto-WU18: stato live + task corrente + errori + quota
        stato         = entry.get("stato", "unknown")
        task_corrente = entry.get("task_corrente") or None
        errori_live   = int(entry.get("errori_live", 0) or 0)
        quota_max     = int(entry.get("quota_max", 0) or 0)
        sped_oggi     = int(entry.get("spedizioni_oggi", 0) or 0)
        quota_esau    = bool(entry.get("quota_esaurita", False))
        quota_lbl     = f"{sped_oggi}/{quota_max}" if quota_max > 0 else "—"
        # auto-WU19: ultimo task (assorbe inst-grid card)
        ut_nome  = entry.get("ultimo_task_nome") or None
        ut_ts    = entry.get("ultimo_task_ts") or None
        ut_msg   = entry.get("ultimo_task_msg") or ""
        ut_esito = entry.get("ultimo_task_esito") or None
        # task da mostrare: priorità a task_corrente, fallback a ultimo task
        task_lbl = task_corrente if task_corrente else (ut_nome or "—")
        # auto-WU21: istanze disabilitate → stato visivo "disabled"
        # (override stato runtime, mostriamo sempre "DISABLED" badge)
        if not is_abilitata:
            stato = "disabled"
        # Stato pill colors
        STATO_COLOR = {
            "online":     "#4ade80",  # green
            "running":    "#4ade80",
            "idle":       "#94a3b8",  # gray
            "error":      "#f87171",  # red
            "disabled":   "#64748b",  # dim gray
            "unknown":    "#64748b",
        }
        stato_col = STATO_COLOR.get(stato, "#64748b")
        # Badge stato a destra (stile inst-grid IDLE/RUNNING)
        STATO_BADGE_BG = {
            "online":   "rgba(74,222,128,0.18)",
            "running":  "rgba(74,222,128,0.18)",
            "idle":     "rgba(148,163,184,0.15)",
            "error":    "rgba(248,113,113,0.20)",
            "disabled": "rgba(100,116,139,0.10)",
            "unknown":  "rgba(100,116,139,0.18)",
        }
        badge_bg = STATO_BADGE_BG.get(stato, "rgba(100,116,139,0.18)")
        # Card opacity ridotta per disabilitate (dati storici visibili)
        card_opacity = "0.55" if not is_abilitata else "1"

        # Sessione corrente
        ris_ini    = corrente.get("risorse_iniziali", {}) or {}
        rif_inv    = corrente.get("rifornimento_inviato", {}) or {}
        rif_tax    = corrente.get("rifornimento_tassa", {}) or {}
        zaino      = corrente.get("zaino_delta", {}) or {}
        truppe     = corrente.get("truppe_raccolta_inviate", 0)
        provv      = corrente.get("rifornimento_provviste_residue", -1)
        tasks_curr = corrente.get("tasks_count", {}) or {}
        ts_inizio  = corrente.get("ts_inizio", "")
        # auto-WU29 (27/04): avvio in orario LOCALE (era UTC), formato HH:MM
        # + live_dur_m calcolato da ts_inizio→ultimo_task.ts (= durata tick exec)
        avvio_lbl   = "—"
        live_dur_m  = 0  # durata tick exec (avvio → ultimo task)
        ts_inizio_local = None
        if ts_inizio:
            try:
                from datetime import datetime as _dt, time as _dtime
                t0 = _dt.fromisoformat(ts_inizio.replace("Z", "+00:00"))
                ts_inizio_local = t0.astimezone()
                avvio_lbl = ts_inizio_local.strftime("%H:%M")
                # live_dur = ultimo task ts (HH:MM:SS local) - ts_inizio_local
                if ut_ts and len(ut_ts) >= 8:
                    h, m, s = map(int, ut_ts[:8].split(":"))
                    today = ts_inizio_local.date()
                    ut_dt_local = _dt.combine(
                        today, _dtime(h, m, s),
                    ).astimezone(ts_inizio_local.tzinfo)
                    delta_s = (ut_dt_local - ts_inizio_local).total_seconds()
                    if delta_s > 0:
                        live_dur_m = int(delta_s // 60)
            except Exception:
                avvio_lbl = ts_inizio[11:16] if len(ts_inizio) >= 16 else "—"

        # Durata corrente: now - ts_inizio
        durata_curr_m = 0
        if ts_inizio:
            try:
                from datetime import datetime, timezone
                t0 = datetime.fromisoformat(ts_inizio)
                now = datetime.now(timezone.utc)
                durata_curr_m = int((now - t0).total_seconds() // 60)
            except Exception:
                durata_curr_m = 0

        # auto-WU27: provviste formattato in milioni (era integer raw)
        if provv == 0:
            provv_lbl = "esaurita"
        elif provv > 0:
            provv_lbl = _fmt_q(provv)
        else:
            provv_lbl = "—"

        # Sessione precedente
        prod_h_prec     = precedente.get("produzione_oraria") or {}
        ris_ini_prec    = precedente.get("risorse_iniziali") or {}
        ris_fin_prec    = precedente.get("risorse_finali") or {}
        rif_inv_prec    = precedente.get("rifornimento_inviato") or {}
        durata_s        = precedente.get("durata_sec") or 0
        durata_prec_m   = int(durata_s // 60) if durata_s else 0
        truppe_prec     = precedente.get("truppe_raccolta_inviate", 0)
        tasks_prec      = precedente.get("tasks_count", {}) or {}

        has_prec = bool(prod_h_prec)
        # Una riga per risorsa, 4 colonne: risorsa | corrente | precedente | prod/h
        rows = ""
        for r, ico in RISORSE_ICO:
            ini   = _fmt_q(ris_ini.get(r, 0))
            inv   = _fmt_q(rif_inv.get(r, 0))
            tax   = _fmt_q(rif_tax.get(r, 0))
            zd    = _fmt_q(zaino.get(r, 0))
            ini_p = _fmt_q(ris_ini_prec.get(r, 0))
            fin_p = _fmt_q(ris_fin_prec.get(r, 0))
            inv_p = _fmt_q(rif_inv_prec.get(r, 0))
            ph    = _fmt_q(prod_h_prec.get(r, 0)) if has_prec else "—"
            tooltip = (
                f"{r}: corrente ini(castle alla apertura sess)={ini} "
                f"inv(spedito a FauMorfeus durante sess)={inv} "
                f"tassa={tax} zaino={zd}"
                f" | precedente ini={ini_p} fin={fin_p} inv={inv_p}"
            )
            # auto-WU27 (27/04): label esplicite "ini" e "inv" invece di "+"
            # ambiguo. ini = valore castle al momento apri_sessione (snapshot
            # OCR top-bar). inv = quantità spedita a FauMorfeus in sessione.
            curr_cell = (
                f'<span title="{tooltip}">{ini}'
                f'<span style="color:var(--accent);font-size:10px"> ▸{inv}</span></span>'
            )
            prec_cell = (
                f'{ini_p}<span style="color:var(--text-dim);font-size:10px"> → {fin_p}</span>'
                if has_prec else '—'
            )
            ph_cell = (
                f'<span style="color:#7cf;font-weight:600">{ph}/h</span>'
                if has_prec else '<span style="color:var(--text-dim)">—/h</span>'
            )
            rows += (
                f'<tr title="{tooltip}">'
                f'<td style="padding:1px 4px">{ico}</td>'
                f'<td style="padding:1px 4px;text-align:right">{curr_cell}</td>'
                f'<td style="padding:1px 4px;text-align:right;color:var(--text-dim)">{prec_cell}</td>'
                f'<td style="padding:1px 4px;text-align:right">{ph_cell}</td>'
                f'</tr>'
            )

        # Compatta task count: "msg+aleanza+donaz+rifor+racc+ds" o lista nominata
        def _tasks_brief(tdict: dict) -> tuple[str, str]:
            """Ritorna (compact_text, tooltip_full) — compact ordina per priority."""
            if not tdict:
                return ("—", "nessuno")
            ABBREV = {
                "boost":"boost","vip":"vip","messaggi":"msg","alleanza":"alleanza",
                "store":"store","arena":"arena","arena_mercato":"arenaM",
                "zaino":"zaino","radar":"radar","radar_census":"radCens",
                "rifornimento":"rifor","donazione":"donaz",
                "main_mission":"mainM",
                "district_showdown":"DS","raccolta":"racc",
            }
            parts = []
            full  = []
            for k, v in tdict.items():
                lbl = ABBREV.get(k, k)
                parts.append(f"{lbl}({v})" if v > 1 else lbl)
                full.append(f"{k}={v}")
            return (" · ".join(parts), " | ".join(full))

        tasks_curr_short, tasks_curr_tip = _tasks_brief(tasks_curr)
        tasks_prec_short, tasks_prec_tip = _tasks_brief(tasks_prec)

        # auto-WU19: header completo (assorbe inst-grid).
        # auto-WU26 (27/04): nascondi task quando stato non live (idle/unknown/disabled);
        # aggiungi durata in header; promote truppe a "truppe:N" più evidente.
        err_color = "var(--red,#f87171)" if errori_live > 0 else "var(--text-dim)"
        is_live  = stato in ("online", "running")
        # task: solo se live, altrimenti "—"
        if is_live:
            task_col      = "var(--red,#f87171)" if ut_esito == "err" else "var(--accent)"
            task_show_lbl = task_lbl
        else:
            task_col      = "var(--text-dim)"
            task_show_lbl = "—"
        # auto-WU28+29: durata adattiva.
        # - LIVE: durata corrente cresce real-time (now - ts_inizio)
        # - IDLE/altro: live_dur_m = avvio → ultimo task (durata tick FROZEN)
        if is_live and durata_curr_m > 0:
            durata_show = f' · <b style="color:var(--text)">{durata_curr_m}m</b>'
        elif live_dur_m > 0:
            durata_show = f' · live <b style="color:var(--text)">{live_dur_m}m</b>'
        else:
            durata_show = ""
        header_status = (
            f'<div style="display:flex;justify-content:space-between;'
            f'gap:6px;font-size:11px;color:var(--text-dim);margin-bottom:2px">'
            f'<span>avvio <b style="color:var(--text)">{avvio_lbl}</b>{durata_show}</span>'
            f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
            f'text-align:center">task: <b style="color:{task_col}">{task_show_lbl}</b></span>'
            f'<span style="color:{err_color}">err:{errori_live}</span>'
            f'</div>'
        )
        # Riga ts + msg: solo se live (nascondi quando non live)
        if is_live and (ut_ts or ut_msg):
            ts_show  = ut_ts or "—"
            msg_show = ut_msg or "—"
            header_lastmsg = (
                f'<div style="display:flex;gap:6px;font-size:11px;color:var(--text-dim);'
                f'margin-bottom:3px">'
                f'<span>ts <b style="color:var(--text)">{ts_show}</b></span>'
                f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
                f'title="{msg_show}">msg: <i>{msg_show}</i></span>'
                f'</div>'
            )
        else:
            header_lastmsg = ""

        # auto-WU30 (27/04): corrente+precedente come 2 colonne verticali
        # con coppie label/value allineate. Più chiaro di line orizzontale
        # con info miste (raccolta+rifornimento+task).
        quota_flag = " 🔴" if quota_esau else ""
        truppe_col = "#7cf" if truppe > 0 else "var(--text-dim)"

        def _kv(label: str, value: str, val_color: str = "var(--text)") -> str:
            return (
                f'<div style="display:flex;justify-content:space-between;gap:4px">'
                f'<span style="color:var(--text-dim)">{label}</span>'
                f'<span style="color:{val_color};overflow:hidden;'
                f'text-overflow:ellipsis;white-space:nowrap;max-width:65%" '
                f'title="{value}">{value}</span></div>'
            )

        # auto-WU31+32+34: corrente block con stats giornaliere rifornimento.
        # spediz = daily count.
        # inviato netto = qty arrivata a FauMorfeus (sum inviato_oggi).
        # inviato lordo = qty uscita dal castello (sum inviato_lordo_oggi).
        # tassa = inviato_lordo - inviato_netto (sum tassa_oggi).
        # provv. lorde = OCR gioco (saldo capacità output).
        # provv. nette = stima = lorde × (1 - tassa_pct_avg).
        inviato_totale = int(entry.get("inviato_totale", 0) or 0)
        inviato_lordo  = int(entry.get("inviato_lordo_totale", 0) or 0)
        tassa_tot      = int(entry.get("tassa_totale", 0) or 0)
        tassa_pct_avg  = float(entry.get("tassa_pct_avg", 0.23) or 0.23)
        provviste_res  = int(entry.get("provviste_residue", -1) or -1)
        provv_res_net  = int(entry.get("provviste_residue_netta", -1) or -1)
        provviste_esau_state = bool(entry.get("provviste_esaurite", False))
        # Format
        netto_lbl  = _fmt_q(inviato_totale) if inviato_totale > 0 else "0"
        lordo_lbl  = _fmt_q(inviato_lordo)  if inviato_lordo  > 0 else "0"
        tassa_lbl  = _fmt_q(tassa_tot)      if tassa_tot      > 0 else "0"
        if provviste_esau_state or provviste_res == 0:
            provv_lordo_lbl = "esaurita"
            provv_lordo_col = "var(--red,#f87171)"
            provv_netto_lbl = "—"
            provv_netto_col = "var(--text-dim)"
        elif provviste_res > 0:
            provv_lordo_lbl = _fmt_q(provviste_res)
            provv_lordo_col = "var(--text)"
            provv_netto_lbl = _fmt_q(provv_res_net) if provv_res_net > 0 else "—"
            provv_netto_col = "var(--text-dim)"
        else:
            provv_lordo_lbl = "—"
            provv_lordo_col = "var(--text-dim)"
            provv_netto_lbl = "—"
            provv_netto_col = "var(--text-dim)"

        # auto-WU34 (27/04): blocco rifornimento giornaliero esteso con
        # netto/lordo/tassa + provv. lorde/nette per chiarezza semantica.
        corr_kvs = [
            _kv("spediz",       str(sped_oggi)),
            _kv("inv. netto",   netto_lbl,  "#7cf" if inviato_totale > 0 else "var(--text)"),
            _kv("inv. lordo",   lordo_lbl,  "var(--text)"),
            _kv("tassa",        tassa_lbl,  "var(--red,#f87171)" if tassa_tot > 0 else "var(--text-dim)"),
            _kv("provv. lorde", provv_lordo_lbl, provv_lordo_col),
            _kv("provv. nette", provv_netto_lbl, provv_netto_col),
        ]
        sess_block = (
            f'<div style="font-size:11px;color:var(--text-dim);'
            f'margin-top:5px;flex:1;min-width:0" '
            f'title="tassa media: {tassa_pct_avg*100:.1f}%">'
            f'<div style="color:var(--accent);font-weight:600;text-align:center;'
            f'margin-bottom:2px;border-bottom:0.5px solid rgba(255,255,255,0.06);'
            f'padding-bottom:1px">rifornimento giornaliero</div>'
            f'{"".join(corr_kvs)}</div>'
        )

        # WU86 — ultimi 5 cicli istanza (avvio → chiusura, durata)
        ultimi_cicli = []
        try:
            from dashboard.services.telemetry_reader import get_ultimi_cicli_istanza
            ultimi_cicli = get_ultimi_cicli_istanza(nome, n=5)
        except Exception:
            pass

        if ultimi_cicli:
            rows_cicli = []
            for c in ultimi_cicli:
                dur_s = int(c.get("durata_s", 0))
                dur_lbl = f'{dur_s//60}m{dur_s%60:02d}s'
                rows_cicli.append(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'gap:6px;font-size:11px;line-height:1.5">'
                    f'<span style="color:var(--text-dim)">'
                    f'{c["avvio_lbl"]}→{c["fine_lbl"]}</span>'
                    f'<span style="color:var(--text)">{dur_lbl}</span></div>'
                )
            cicli_block = (
                '<div style="font-size:11px;color:var(--text-dim);'
                'margin-top:5px;flex:1;min-width:0">'
                '<div style="color:var(--accent);font-weight:600;text-align:center;'
                'margin-bottom:2px;border-bottom:0.5px solid rgba(255,255,255,0.06);'
                'padding-bottom:1px">ultimi 5 cicli</div>'
                + "".join(rows_cicli) + '</div>'
            )
        else:
            cicli_block = ''

        # Container flex side-by-side: rifornimento (sx) + ultimi cicli (dx)
        bottom_block = (
            '<div style="display:flex;gap:10px;align-items:flex-start">'
            + sess_block + cicli_block +
            '</div>'
        )

        # WU66 — riga truppe (Layout A): total oggi + Δ7gg + sparkline 7 giorni
        from dashboard.services.stats_reader import get_truppe_istanza
        try:
            tr = get_truppe_istanza(nome)
        except Exception:
            tr = {"oggi": None, "sette_gg_fa": None, "delta": None,
                  "delta_pct": None, "serie_7d": [None]*7}

        oggi_v   = tr.get("oggi")
        delta_v  = tr.get("delta")
        delta_p  = tr.get("delta_pct")
        serie_v  = tr.get("serie_7d") or []

        # Format oggi
        if oggi_v is None:
            oggi_lbl = "—"
            oggi_col = "var(--text-dim)"
        else:
            oggi_lbl = f"{oggi_v:,}"
            oggi_col = "var(--text)"

        # Format delta + arrow + colore
        if delta_v is None:
            delta_lbl = "Δ7gg —"
            delta_col = "var(--text-dim)"
        elif delta_v > 0:
            delta_lbl = f"Δ7gg +{delta_v:,} ▲{delta_p:.1f}%"
            delta_col = "#4ade80"  # green
        elif delta_v < 0:
            delta_lbl = f"Δ7gg {delta_v:,} ▼{abs(delta_p):.1f}%"
            delta_col = "#f87171"  # red
        else:
            delta_lbl = f"Δ7gg 0"
            delta_col = "var(--text-dim)"

        # Sparkline ASCII: 7 char (gg-6 .. oggi). None → '·' (dato mancante)
        chars = "▁▂▃▄▅▆▇█"
        valid_vals = [v for v in serie_v if v is not None]
        if valid_vals:
            mn, mx = min(valid_vals), max(valid_vals)
            rng = (mx - mn) or 1
            spark = "".join(
                chars[min(7, int((v - mn) / rng * 7))] if v is not None else "·"
                for v in serie_v
            )
            # tooltip con valori esatti
            from datetime import date, timedelta
            today_d = date.today()
            spark_tip = " · ".join(
                f"{(today_d - timedelta(days=6-i)).strftime('%d/%m')}: "
                f"{(v if v is not None else '—')}"
                for i, v in enumerate(serie_v)
            )
        else:
            spark = "·" * 7
            spark_tip = "nessun dato 7gg"

        truppe_block = (
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;gap:6px;margin-top:5px;padding-top:4px;'
            f'border-top:0.5px solid rgba(255,255,255,0.06);font-size:11px">'
            f'<span style="color:var(--text-dim)">🪖 truppe: '
            f'<b style="color:{oggi_col}">{oggi_lbl}</b></span>'
            f'<span style="color:{delta_col};font-size:10px">{delta_lbl}</span>'
            f'<span style="font-family:monospace;font-size:13px;color:var(--accent);'
            f'letter-spacing:1px" title="{spark_tip}">{spark}</span>'
            f'</div>'
        )

        master_border = "border:1.5px solid #f5c542;" if is_master else "border:1px solid var(--border);"
        master_star = '<span title="master — rifugio destinatario" style="color:#f5c542;font-weight:700;margin-right:2px">★</span>' if is_master else ""
        master_pill = '<span style="background:rgba(245,197,66,0.15);color:#f5c542;font-size:9px;font-weight:600;padding:1px 5px;border-radius:3px;letter-spacing:0.5px;margin-left:4px">MASTER</span>' if is_master else ""
        cards_html.append(f'''
        <div class="prod-card" style="background:var(--bg-card);{master_border}
             border-radius:5px;padding:8px 10px;font-size:12px;opacity:{card_opacity}">
          <div style="display:flex;justify-content:space-between;align-items:center;
               margin-bottom:4px;font-weight:600;font-size:14px">
            <span style="display:flex;align-items:center;gap:6px">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;
                background:{stato_col}"></span>
              {master_star}{nome}{master_pill}
              <span style="background:{badge_bg};color:{stato_col};font-size:10px;
                font-weight:600;padding:1px 6px;border-radius:3px;text-transform:uppercase;
                letter-spacing:0.5px">{stato}</span>
            </span>
            <span style="color:var(--text-dim);font-weight:normal;font-size:10px"></span>
          </div>
          {header_status}
          {header_lastmsg}
          {truppe_block}
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr style="color:var(--text-dim);font-size:11px">
              <th style="text-align:left">risorsa</th>
              <th style="text-align:right">corrente</th>
              <th style="text-align:right">precedente</th>
              <th style="text-align:right">prod/h</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {bottom_block}
        </div>
        ''')

    if not cards_html:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px">'
            'nessuna istanza abilitata con dati produzione</div>'
        )

    return HTMLResponse(
        '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));'
        'gap:6px">' + "".join(cards_html) + '</div>'
    )


@app.get("/ui/partial/cycle-prediction", include_in_schema=False)
def partial_cycle_prediction(request: Request):
    """
    WU-CycleDur (04/05) — pannello stima durata ciclo bot.

    Mostra: T_ciclo_atteso (min), breakdown per istanza, schedule debug
    (quali task girano per ogni istanza al prossimo tick).

    Source: `core.cycle_duration_predictor.predict_cycle_from_config(strict=True)`.
    Refresh ogni 60s (rolling stats TTL 30min, schedule cambia ogni minuto).
    """
    try:
        from core.cycle_duration_predictor import predict_cycle_from_config
        res     = predict_cycle_from_config(strict_schedule=True, percentile="median")
        res_p75 = predict_cycle_from_config(strict_schedule=True, percentile="p75")
    except Exception as exc:
        return HTMLResponse(
            f'<div style="color:var(--text-dim);text-align:center;padding:8px">'
            f'errore caricamento: {exc}</div>'
        )
    if "error" in res:
        return HTMLResponse(
            f'<div style="color:var(--text-dim);text-align:center;padding:8px">'
            f'{res["error"]}</div>'
        )

    t_min = res.get("T_ciclo_min", 0)
    t_s   = res.get("T_ciclo_s", 0)
    n_ist = res.get("n_istanze", 0)
    conf  = res.get("confidence", "?")
    tick  = res.get("tick_sleep_s", 0)
    per_ist = res.get("per_istanza", {})
    sched_dbg = res.get("schedule_debug", {})

    # P75 (stima conservativa): solo top number, no breakdown duplicato
    t_min_p75 = res_p75.get("T_ciclo_min", 0)
    per_ist_p75 = res_p75.get("per_istanza", {})

    # WU122-OptC: wait inter-task aggregato (somma per istanze) + source
    total_wait_s = sum(p.get("wait_inter_task_s", 0) for p in per_ist.values())
    wait_sources = [p.get("wait_inter_task_src", "?") for p in per_ist.values()]
    n_rolling  = sum(1 for s in wait_sources if s == "rolling")
    n_fallback = sum(1 for s in wait_sources if s == "fallback")

    conf_color = {"alta": "#4caf50", "media": "#ff9800", "bassa": "#f44336"}.get(conf, "var(--text-dim)")

    # Header — p75 prominente (stima realistica, cattura cicli pieni)
    # median resta visibile come confronto. Validazione 05/05 con
    # cycle_accuracy.jsonl: median sotto-stima cicli pieni del 25-43%,
    # p75 li cattura entro 5-15%.
    wait_label = (
        f'wait inter-task: <b>{total_wait_s:.0f}s</b> '
        f'(<span style="color:#4caf50">{n_rolling}</span> rolling, '
        f'<span style="color:#ff9800">{n_fallback}</span> fallback)'
    )
    head = (
        f'<div style="display:flex;align-items:baseline;gap:24px;margin-bottom:10px;flex-wrap:wrap">'
        f'<div title="stima realistica p75 ultimi 20 record per task — cattura cicli con lavoro pieno (validato cycle_accuracy.jsonl: errore 5-15% sui cicli reali)">'
        f'<span style="font-size:22px;font-weight:700;color:var(--accent)">{t_min_p75:.1f}</span>'
        f'<span style="font-size:11px;color:var(--text-dim);margin-left:4px">min · realistica (p75)</span></div>'
        f'<div title="stima centrale median — sotto-stima cicli pieni del 25-43% (riferimento)">'
        f'<span style="font-size:16px;font-weight:500;color:var(--text-dim)">{t_min:.1f}</span>'
        f'<span style="font-size:11px;color:var(--text-dim);margin-left:4px">min · centrale (median)</span></div>'
        f'<div style="color:var(--text-dim);font-size:11px">'
        f'{n_ist} istanze · sleep {tick:.0f}s · confidence '
        f'<span style="color:{conf_color};font-weight:600">{conf}</span></div>'
        f'<div style="color:var(--text-dim);font-size:10px">{wait_label}</div></div>'
    )

    # Tabella per istanza (sorted by T_s desc)
    sorted_inst = sorted(per_ist.items(), key=lambda kv: -kv[1].get("T_s", 0))
    rows = []
    for inst, p in sorted_inst:
        t_inst_s = p.get("T_s", 0)
        t_p75_s  = (per_ist_p75.get(inst) or {}).get("T_s", 0)
        boot_s   = p.get("boot_home_s", 0)
        c_inst   = p.get("confidence", "?")
        c_color  = {"alta": "#4caf50", "media": "#ff9800", "bassa": "#f44336"}.get(c_inst, "var(--text-dim)")
        # Schedule debug per istanza
        dbg = sched_dbg.get(inst, {})
        n_due  = len(dbg.get("due", []))
        n_skip = len(dbg.get("skipped", []))
        due_str  = ", ".join(dbg.get("due", []))
        skip_str = ", ".join(dbg.get("skipped", []))
        rows.append(
            f'<tr>'
            f'<td style="font-weight:600">{inst}</td>'
            f'<td style="text-align:right;font-family:monospace">{t_inst_s/60:.1f}m</td>'
            f'<td style="text-align:right;font-family:monospace;color:var(--text-dim);font-size:10px">{t_p75_s/60:.1f}m</td>'
            f'<td style="text-align:right;color:var(--text-dim);font-size:10px">{boot_s:.0f}s</td>'
            f'<td style="text-align:center"><span style="color:#4caf50;font-weight:600">{n_due}</span>'
            f'<span style="color:var(--text-dim)">/{n_due+n_skip}</span></td>'
            f'<td style="color:var(--text-dim);font-size:10px" title="DUE: {due_str} || SKIP: {skip_str}">'
            f'{due_str[:60]}{"…" if len(due_str)>60 else ""}</td>'
            f'<td style="color:{c_color};font-size:10px;text-align:right">{c_inst}</td>'
            f'</tr>'
        )

    table = (
        '<table class="tel-table"><thead><tr>'
        '<th>istanza</th>'
        '<th style="text-align:right" title="median ultimi 20 record">T</th>'
        '<th style="text-align:right" title="p75 ultimi 20 record (conservativa)">T p75</th>'
        '<th style="text-align:right">boot</th>'
        '<th style="text-align:center">due/tot</th>'
        '<th>task pianificati</th>'
        '<th style="text-align:right">conf</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )

    return HTMLResponse(head + table)


@app.get("/ui/partial/cycle-snapshot-detail", include_in_schema=False)
def partial_cycle_snapshot_detail(request: Request):
    """
    WU-CycleAccuracy — drilldown del ciclo corrente o specificato:
    mostra input_context (istanze abilitate, task abilitati globali, task per
    istanza, breakdown T_s) + what-if (T_ciclo se skippo singola istanza).

    Query: ?cycle=N (default: ultimo snapshot disponibile).
    """
    from core.cycle_predictor_recorder import (
        get_snapshot_for_cycle, read_recent_snapshots,
        get_all_snapshots_for_cycle,
    )
    cycle_str = request.query_params.get("cycle", "")
    snap = None
    if cycle_str:
        try:
            # Per ciclo specifico: usa il PRIMO snapshot (pred originale a
            # inizio ciclo, prima che le istanze modifichino last_run).
            # 05/05: fix bug 'truppe/alleanza falsi extra' — il pred fluido
            # post-esecuzioni dimenticava task con interval scaduto al momento
            # dell'esecuzione ma con last_run recente al momento dello snap.
            snaps_cycle = get_all_snapshots_for_cycle(int(cycle_str))
            if snaps_cycle:
                snap = snaps_cycle[0]   # ordinati asc per elapsed_min
        except Exception:
            pass
    if snap is None:
        # Default: snapshot più recente del CICLO IN CORSO (no completato).
        # Per cicli completati usa il primo del ciclo.
        recent = read_recent_snapshots(1)
        if recent:
            cur_cycle = recent[0].get("cycle_numero")
            if cur_cycle is not None:
                snaps_cycle = get_all_snapshots_for_cycle(int(cur_cycle))
                if snaps_cycle:
                    snap = snaps_cycle[0]   # PRIMO snap del ciclo (pred originale)
        if snap is None:
            snap = recent[0] if recent else None
    if snap is None:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px;font-size:11px">'
            'nessuno snapshot disponibile</div>'
        )

    cn          = snap.get("cycle_numero", "?")
    elapsed_min = snap.get("elapsed_min", 0)
    pred        = snap.get("predicted_min", 0)
    # Conversione UTC → locale per visualizzazione coerente
    ts_iso = snap.get("ts", "")
    try:
        from datetime import datetime as _dt
        ts = _dt.fromisoformat(ts_iso).astimezone().strftime("%d/%m %H:%M:%S")
    except Exception:
        ts = ts_iso[:19]
    ic          = snap.get("input_context", {}) or {}
    istanze_ab  = ic.get("istanze_abilitate", []) or []
    task_glob   = ic.get("task_globali_abilitati", []) or []
    task_per    = ic.get("tasks_per_istanza_due", {}) or {}
    per_ist     = ic.get("per_istanza_predicted_s", {}) or {}
    tick_sleep  = ic.get("tick_sleep_s", 0)

    # 05/05: task EFFETTIVAMENTE eseguiti nel CICLO CORRENTE per istanza.
    # Filtro temporale: prende solo record con ts >= start_ts del ciclo
    # corrente (da data/telemetry/cicli.json). Se l'istanza non ha ancora
    # girato → exec vuoto (NO record del ciclo precedente leakato).
    #
    # Caso resume del ciclo (interruzione + ripresa stesso cycle_numero):
    # cicli.start_ts invariato → record delle istanze già girate ancora
    # validi (ts > start_ts) → mostrati correttamente.
    #
    # Caso nuovo ciclo: cycle_numero diverso, start_ts diverso → record
    # del ciclo precedente con ts < new_start_ts vengono filtrati out.
    import json as _json
    from pathlib import Path as _P
    from datetime import datetime as _dt
    eseguiti_per_inst: dict[str, list[str]] = {}
    eseguiti_ts_per_inst: dict[str, str] = {}

    # Determina start_ts del ciclo corrispondente allo snapshot. Il
    # snapshot ha cycle_numero; cerchiamo il ciclo con quel numero in
    # cicli.json e usiamo il suo start_ts come baseline temporale.
    cycle_start_ts: str = ""
    cycle_start_dt: _dt | None = None
    try:
        cicli_path = _P("C:/doomsday-engine-prod") / "data" / "telemetry" / "cicli.json"
        if cicli_path.exists():
            cicli_data = _json.loads(cicli_path.read_text(encoding="utf-8"))
            cicli_list = cicli_data.get("cicli", []) if isinstance(cicli_data, dict) else cicli_data
            for c in cicli_list:
                if c.get("numero") == cn:
                    cycle_start_ts = c.get("start_ts", "")
                    try:
                        cycle_start_dt = _dt.fromisoformat(cycle_start_ts)
                    except Exception:
                        pass
                    break
    except Exception:
        pass

    metrics_path = _P("C:/doomsday-engine-prod") / "data" / "istanza_metrics.jsonl"
    # NEW 05/05: record_per_inst = record completo per breakdown side-by-side
    # (boot_home_s, task_durations_s, wait_inter_task_s, tick_total_s)
    tick_total_per_inst: dict[str, float] = {}
    record_per_inst: dict[str, dict] = {}
    try:
        if metrics_path.exists():
            with metrics_path.open(encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = _json.loads(line)
                except Exception:
                    continue
                inst = r.get("instance")
                if not inst or inst in eseguiti_per_inst:
                    continue
                # Filtro temporale: solo record del ciclo corrente
                if cycle_start_dt is not None:
                    try:
                        rec_dt = _dt.fromisoformat(r.get("ts", ""))
                        if rec_dt < cycle_start_dt:
                            eseguiti_per_inst[inst] = []
                            eseguiti_ts_per_inst[inst] = ""
                            tick_total_per_inst[inst] = 0.0
                            record_per_inst[inst] = {}
                            continue
                    except Exception:
                        pass
                durs = r.get("task_durations_s") or {}
                tasks_done = sorted(durs.keys(), key=lambda k: -float(durs.get(k, 0)))
                eseguiti_per_inst[inst] = tasks_done
                eseguiti_ts_per_inst[inst] = r.get("ts", "")
                tick_total_per_inst[inst] = float(r.get("tick_total_s", 0) or 0)
                record_per_inst[inst] = r
                if len(eseguiti_per_inst) >= len(istanze_ab):
                    break
    except Exception:
        pass

    # Label timestamp locale per ogni istanza con record valido
    eseguiti_ts_local: dict[str, str] = {}
    for inst, ts_str in eseguiti_ts_per_inst.items():
        try:
            if ts_str:
                eseguiti_ts_local[inst] = _dt.fromisoformat(ts_str).astimezone().strftime("%H:%M %d/%m")
            else:
                eseguiti_ts_local[inst] = ""
        except Exception:
            eseguiti_ts_local[inst] = ""

    # Header info ciclo
    header = (
        f'<div style="display:flex;gap:16px;font-size:11px;margin-bottom:10px">'
        f'<div><span style="color:var(--text-dim)">ciclo</span> '
        f'<b style="color:var(--accent)">#{cn}</b></div>'
        f'<div><span style="color:var(--text-dim)">snapshot @</span> '
        f'<b>{elapsed_min:.0f}min</b></div>'
        f'<div><span style="color:var(--text-dim)">predicted</span> '
        f'<b>{pred:.1f}min</b></div>'
        f'<div><span style="color:var(--text-dim)">istanze</span> '
        f'<b>{len(istanze_ab)}</b></div>'
        f'<div><span style="color:var(--text-dim)">tick_sleep</span> '
        f'<b>{tick_sleep:.0f}s</b></div>'
        f'<div style="color:var(--text-dim);margin-left:auto">{ts}</div>'
        f'</div>'
    )

    # Task globali abilitati
    tasks_section = (
        f'<div style="margin-bottom:10px">'
        f'<div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">'
        f'task globali abilitati ({len(task_glob)})</div>'
        f'<div style="font-family:monospace;font-size:10px;color:var(--text)">'
        f'{", ".join(task_glob) or "<i style=\"color:var(--text-dim)\">nessuno</i>"}'
        f'</div></div>'
    )

    # 05/05: per ogni istanza calcola il breakdown della stima (boot_home +
    # task individuali + wait inter-task). Permette espandere la riga e vedere
    # COME è composto il T_s. Necessario per analizzare scostamenti predictor.
    from core.cycle_duration_predictor import predict_istanza_duration
    breakdown_per_inst: dict[str, dict] = {}
    for inst in istanze_ab:
        try:
            due = task_per.get(inst, [])
            pred_data = predict_istanza_duration(inst, due, percentile="median")
            breakdown_per_inst[inst] = pred_data
        except Exception:
            breakdown_per_inst[inst] = {}

    # Tabella per istanza con what-if + confronto eseguiti
    rows = []
    for inst in sorted(istanze_ab):
        t_s = per_ist.get(inst, 0)
        due_tasks = task_per.get(inst, [])
        eseguiti = eseguiti_per_inst.get(inst, [])
        # 05/05: distinzione "istanza non ancora girata" vs "girata":
        # se exec è vuoto → tutti i task pianificati senza barratura
        # (è solo previsione, non c'è ancora confronto possibile).
        # Solo per istanze già girate calcoliamo missing/extra/diff.
        is_done = bool(eseguiti)
        due_set = set(due_tasks)
        ese_set = set(eseguiti)
        if is_done:
            extra   = ese_set - due_set   # eseguiti senza essere pianificati
            missing = due_set - ese_set   # pianificati ma non eseguiti
        else:
            extra   = set()
            missing = set()
        # Render eseguiti con highlight: rosso = extra (non previsti)
        eseguiti_render = []
        for t in eseguiti:
            if t in extra:
                eseguiti_render.append(f'<span style="color:#f44336" title="non pianificato">{t}</span>')
            else:
                eseguiti_render.append(t)
        # Render pianificati: barrato SOLO se istanza ha già girato e task missing
        due_render = []
        for t in due_tasks:
            if is_done and t in missing:
                due_render.append(f'<span style="color:#ff9800;text-decoration:line-through" title="pianificato ma non eseguito">{t}</span>')
            else:
                due_render.append(t)
        # What-if: T_ciclo SE skippo questa istanza
        t_ciclo_s = sum(per_ist.values()) + tick_sleep
        t_skip_s  = t_ciclo_s - t_s
        savings   = t_s
        savings_pct = 100 * t_s / t_ciclo_s if t_ciclo_s > 0 else 0
        # Indicatore differenza solo per istanze già girate
        n_diff = len(extra) + len(missing) if is_done else 0
        diff_marker = (
            f' <span style="color:#f44336;font-weight:600" title="{n_diff} task discordanti">⚠{n_diff}</span>'
            if n_diff > 0 else ''
        )
        # T_s reale (ciclo corrente) — solo se istanza ha già girato.
        # Definito qui (prima del bd_rows) per essere accessibile sia nel
        # breakdown expand che nella cella main.
        t_real = tick_total_per_inst.get(inst, 0)
        # Riga main + riga expand (breakdown stima): toggle via onclick JS
        row_id = f"snap-detail-{inst}"
        bd = breakdown_per_inst.get(inst, {})
        boot_s = bd.get("boot_home_s", 0)
        tasks_bd = bd.get("tasks", {}) or {}
        wait_s = bd.get("wait_inter_task_s", 0)
        wait_src = bd.get("wait_inter_task_src", "?")
        # NEW 05/05: breakdown side-by-side pred | real per ogni componente.
        # Permette analisi puntuale dove il predictor sotto/sovra-stima
        # (boot_home, task individuali, wait_inter_task) per migliorare modello.
        rec = record_per_inst.get(inst, {}) or {}
        boot_real = float(rec.get("boot_home_s", 0) or 0)
        durs_real = rec.get("task_durations_s") or {}
        wait_real = float(rec.get("wait_inter_task_s", 0) or 0)

        def _row_compare(label: str, pred_val: float, real_val: float, has_real: bool) -> str:
            """Render riga breakdown con pred | real | Δ%."""
            if has_real and real_val > 0:
                err_pct = abs(real_val - pred_val) / pred_val * 100 if pred_val > 0 else 0
                color = "#4caf50" if err_pct < 10 else ("#fbbf24" if err_pct < 25 else "#f44336")
                sign = "+" if real_val >= pred_val else "-"
                real_html = (
                    f'<span style="color:{color};margin-left:8px">'
                    f'real {real_val:.1f}s '
                    f'<span style="font-size:9px">(Δ {sign}{err_pct:.0f}%)</span>'
                    f'</span>'
                )
            else:
                real_html = '<span style="color:var(--text-dim);margin-left:8px">real —</span>'
            return (
                f'<div style="display:flex;justify-content:space-between;font-family:monospace;font-size:10px;padding:1px 0">'
                f'<span style="color:var(--text-dim)">{label}</span>'
                f'<span style="color:var(--text)">pred {pred_val:.1f}s{real_html}</span>'
                f'</div>'
            )

        bd_rows = []
        bd_rows.append(_row_compare("└─ boot_home (avvio→pronto)", boot_s, boot_real, is_done))
        for tname, tval in sorted(tasks_bd.items(), key=lambda kv: -kv[1]):
            real_t = float(durs_real.get(tname, 0) or 0)
            bd_rows.append(_row_compare(f"└─ task: {tname}", tval, real_t, is_done))
        bd_rows.append(_row_compare(f"└─ wait inter-task ({wait_src})", wait_s, wait_real, is_done))
        bd_rows.append(
            f'<div style="display:flex;justify-content:space-between;font-family:monospace;font-size:11px;padding:3px 0;border-top:1px solid var(--border);margin-top:3px">'
            f'<span style="color:var(--accent);font-weight:600">TOT predicted</span>'
            f'<span style="color:var(--accent);font-weight:600">{t_s:.1f}s = {t_s/60:.1f}min</span></div>'
        )
        # Reale (se eseguito) — confronto con predicted
        if is_done and t_real > 0:
            err_real_pct = abs(t_real - t_s) / t_s * 100 if t_s > 0 else 0
            real_color = "#4caf50" if err_real_pct < 10 else ("#fbbf24" if err_real_pct < 25 else "#f44336")
            sign = "+" if t_real >= t_s else "-"
            bd_rows.append(
                f'<div style="display:flex;justify-content:space-between;font-family:monospace;font-size:11px;padding:3px 0">'
                f'<span style="color:{real_color};font-weight:600">TOT REALE (ciclo corrente)</span>'
                f'<span style="color:{real_color};font-weight:600">{t_real:.1f}s = {t_real/60:.1f}min '
                f'<span style="font-size:9px">(Δ {sign}{err_real_pct:.0f}%)</span></span></div>'
            )
        # Stringa T_s reale per cella main (t_real già calcolato sopra)
        if is_done and t_real > 0:
            err_real_pct = abs(t_real - t_s) / t_s * 100 if t_s > 0 else 0
            real_color = "#4caf50" if err_real_pct < 10 else ("#fbbf24" if err_real_pct < 25 else "#f44336")
            sign = "+" if t_real >= t_s else "-"
            real_str = (
                f' <span style="color:var(--text-dim)">/</span> '
                f'<span style="color:{real_color}" title="T_s reale = tick_total_s del record ciclo corrente. Δ rispetto pred">'
                f'{t_real/60:.1f}m'
                f'<span style="font-size:9px;color:{real_color};margin-left:2px">'
                f'({sign}{err_real_pct:.0f}%)</span>'
                f'</span>'
            )
        else:
            real_str = ' <span style="color:var(--text-dim)">/ —</span>'
        rows.append(
            f'<tr style="cursor:pointer" onclick="(function(r){{var d=document.getElementById(\'{row_id}\');d.style.display=d.style.display===\'none\'?\'\':\'none\';}})(this)" title="click per espandere/comprimere il breakdown">'
            f'<td style="font-weight:600">▸ {inst}</td>'
            f'<td style="text-align:right;font-family:monospace;white-space:nowrap" title="T_s predicted / reale (se eseguito). Δ% in colore">'
            f'{t_s/60:.1f}m{real_str}</td>'
            f'<td style="text-align:center">'
            f'<span style="color:#4caf50">{len(due_tasks)}</span>'
            f'<span style="color:var(--text-dim)"> / </span>'
            f'<span style="color:var(--accent)">{len(eseguiti)}</span>'
            f'{diff_marker}</td>'
            f'<td style="color:var(--text-dim);font-size:10px;font-family:monospace">'
            f'{", ".join(due_render) or "<i>—</i>"}</td>'
            f'<td style="color:var(--text-dim);font-size:10px;font-family:monospace">'
            + (
                f'{", ".join(eseguiti_render)}'
                f'<div style="font-size:9px;color:var(--text-dim);margin-top:2px">'
                f'@ {eseguiti_ts_local.get(inst) or ""}</div>'
                if eseguiti_per_inst.get(inst) else
                '<i style="color:var(--text-dim)">non ancora girata in questo ciclo</i>'
            )
            + '</td>'
            f'<td style="text-align:right;color:var(--accent);font-family:monospace">'
            f'{t_skip_s/60:.1f}m</td>'
            f'<td style="text-align:right;color:#ff9800;font-size:10px">'
            f'-{savings/60:.1f}m ({savings_pct:.0f}%)</td>'
            f'</tr>'
            f'<tr id="{row_id}" style="display:none;background:rgba(255,255,255,0.03)">'
            f'<td colspan="7" style="padding:6px 12px">'
            f'<div style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">'
            f'breakdown stima {inst}</div>'
            + "".join(bd_rows) +
            f'</td></tr>'
        )

    tot_pred = sum(per_ist.values()) + tick_sleep
    table = (
        '<table class="tel-table"><thead><tr>'
        '<th title="click su una riga per espandere il breakdown">istanza</th>'
        '<th style="text-align:right" title="T_s predicted / reale (se istanza ha già girato nel ciclo). Δ% colorato: verde<10%, giallo<25%, rosso>25%">T_s pred/real</th>'
        '<th style="text-align:center" title="N pianificati / N eseguiti (ultimo ciclo)">N pred/exec</th>'
        '<th>task pianificati</th>'
        '<th title="task effettivamente eseguiti nell&#39;ultimo ciclo (data/istanza_metrics.jsonl)">task eseguiti (ultimo)</th>'
        '<th style="text-align:right" title="T_ciclo se skippo questa istanza">'
        'T_ciclo skip</th>'
        '<th style="text-align:right">saving</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'<tfoot><tr style="border-top:1px solid var(--border)">'
        f'<td colspan="2" style="font-weight:600">TOTALE</td>'
        f'<td colspan="3" style="text-align:right;color:var(--text-dim);font-size:10px">'
        f'+ tick_sleep {tick_sleep:.0f}s</td>'
        f'<td style="text-align:right;font-family:monospace;font-weight:600;color:var(--accent)">'
        f'{tot_pred/60:.1f}m</td>'
        f'<td></td></tr></tfoot></table>'
        '<div style="margin-top:6px;font-size:10px;color:var(--text-dim)">'
        '<b>legenda</b>: '
        '<span style="color:#f44336">rosso</span> = eseguito ma non pianificato · '
        '<span style="color:#ff9800;text-decoration:line-through">arancione barrato</span> = pianificato ma non eseguito · '
        '<i>non ancora girata</i> = istanza non ha ancora eseguito nel ciclo corrente (record filtrati per cicli.start_ts) · '
        'normale = match. ⚠N = task discordanti. '
        '<b>Click sulla riga</b> per espandere il breakdown della stima '
        '(boot_home + ogni task + wait inter-task).'
        '</div>'
    )

    return HTMLResponse(header + tasks_section + table)


@app.get("/ui/partial/cycle-accuracy", include_in_schema=False)
def partial_cycle_accuracy(request: Request):
    """
    WU-CycleAccuracy — accuracy storica del cycle predictor per ciclo.

    Mostra ultimi N=10 cicli completati con: actual_min, snapshots presi durante
    il ciclo (elapsed_min, predicted_min, error_pct).
    """
    from core.cycle_predictor_recorder import (
        read_recent_accuracy, _read_cicli_in_corso, get_all_snapshots_for_cycle,
    )
    from datetime import datetime as _dt, timezone as _tz
    rows = read_recent_accuracy(n_cycles=10)

    # 05/05: aggiungi ciclo CORRENTE in cima (in_corso, no actual_min finale)
    # con elapsed parziale + snapshot già fatti. Confronto pred-vs-elapsed
    # solo informativo (errore vero noto solo a fine ciclo).
    in_corso_row_html = ""
    try:
        ciclo_now = _read_cicli_in_corso()
        if ciclo_now:
            cn_now = ciclo_now.get("numero")
            start_ts = ciclo_now.get("start_ts", "")
            try:
                start_dt = _dt.fromisoformat(start_ts)
                elapsed_min = (_dt.now(_tz.utc) - start_dt).total_seconds() / 60.0
            except Exception:
                elapsed_min = 0.0
            snaps_now = get_all_snapshots_for_cycle(int(cn_now)) if cn_now else []
            n_snaps_now = len(snaps_now)
            # Errore parziale: |predicted - elapsed| / elapsed × 100
            # NB: solo informativo — actual finale può essere maggiore
            errs_partial = []
            for s in snaps_now:
                pred = float(s.get("predicted_min", 0))
                if elapsed_min > 0:
                    err_p = abs(pred - elapsed_min) / elapsed_min * 100
                    errs_partial.append(err_p)
            if errs_partial:
                avg_err = sum(errs_partial) / len(errs_partial)
                err_color = "#4caf50" if avg_err < 10 else ("#ff9800" if avg_err < 25 else "#f44336")
                err_summary = f"vs elapsed: avg {avg_err:.1f}%"
            else:
                avg_err = 0.0
                err_color = "var(--text-dim)"
                err_summary = "no snapshots ancora"
            snaps_str = " · ".join(
                f'+{s.get("elapsed_min",0):.0f}m={s.get("predicted_min",0):.0f}m'
                for s in snaps_now[:5]
            )
            initial_pred_now = (
                sorted(snaps_now, key=lambda s: s.get('elapsed_min', 0))[0].get('predicted_min', 0)
                if snaps_now else 0
            )
            in_corso_row_html = (
                f'<tr style="background:rgba(76,175,80,0.06)">'
                f'<td style="font-weight:600;color:#4caf50">#{cn_now} ▶</td>'
                f'<td style="text-align:right;font-family:monospace;color:var(--text-dim)" title="elapsed dal start_ts del ciclo (in corso, actual finale TBD)">{elapsed_min:.1f}m...</td>'
                f'<td style="text-align:right;font-family:monospace;color:#4caf50" title="stima iniziale (primo snapshot del ciclo)">{initial_pred_now:.1f}m</td>'
                f'<td style="text-align:center;font-size:10px">{n_snaps_now}</td>'
                f'<td style="color:{err_color};font-weight:500" title="error_pct calcolato vs elapsed corrente — solo informativo, actual finale può essere maggiore">{err_summary}</td>'
                f'<td style="color:var(--text-dim);font-size:10px;font-family:monospace">{snaps_str}</td>'
                f'</tr>'
            )
    except Exception:
        pass

    if not rows and not in_corso_row_html:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px;font-size:11px">'
            'nessun ciclo valutato — il primo snapshot è preso ad avvio dashboard,<br>'
            'i cicli iniziati dopo accumulo dati avranno errori_pct calcolati'
            '</div>'
        )

    body = []
    if in_corso_row_html:
        body.append(in_corso_row_html)
    for r in rows:
        cn = r.get("cycle_numero", "?")
        actual = r.get("actual_min", 0)
        snaps = r.get("snapshots", []) or []
        n_snaps = len(snaps)
        # 05/05: STIMA INIZIALE = predicted del PRIMO snapshot del ciclo
        # (recorder ora forza snap immediato all'avvio nuovo ciclo).
        # È la stima "lock-in" che il predictor aveva a inizio ciclo,
        # prima che le esecuzioni modifichino last_run.
        # ordering: snapshots ordinati per elapsed_min asc nel record accuracy
        sorted_snaps = sorted(snaps, key=lambda s: s.get("elapsed_min", 0))
        initial_pred = sorted_snaps[0].get("predicted_min", 0) if sorted_snaps else 0
        initial_err = sorted_snaps[0].get("error_pct", 0) if sorted_snaps else 0
        initial_color = "#4caf50" if initial_err < 10 else ("#ff9800" if initial_err < 25 else "#f44336")
        # Calcola errore medio se ci sono snapshots
        if n_snaps > 0:
            avg_err = sum(s.get("error_pct", 0) for s in snaps) / n_snaps
            min_err = min(s.get("error_pct", 0) for s in snaps)
            max_err = max(s.get("error_pct", 0) for s in snaps)
            err_summary = f"avg {avg_err:.1f}% (min {min_err:.1f} max {max_err:.1f})"
            err_color = "#4caf50" if avg_err < 10 else ("#ff9800" if avg_err < 25 else "#f44336")
        else:
            err_summary = "no snapshots"
            err_color = "var(--text-dim)"
        # Lista snapshots compatta
        snaps_str = " · ".join(
            f'+{s.get("elapsed_min",0):.0f}m={s.get("predicted_min",0):.0f}m({s.get("error_pct",0):.0f}%)'
            for s in snaps[:5]
        )
        body.append(
            f'<tr>'
            f'<td style="font-weight:600;color:var(--accent)">#{cn}</td>'
            f'<td style="text-align:right;font-family:monospace">{actual:.1f}m</td>'
            f'<td style="text-align:right;font-family:monospace;color:{initial_color}" title="stima iniziale (primo snapshot del ciclo) — predicted={initial_pred:.1f}min vs actual={actual:.1f}min, err={initial_err:.1f}%">{initial_pred:.1f}m</td>'
            f'<td style="text-align:center;font-size:10px">{n_snaps}</td>'
            f'<td style="color:{err_color};font-weight:500">{err_summary}</td>'
            f'<td style="color:var(--text-dim);font-size:10px;font-family:monospace">{snaps_str}</td>'
            f'</tr>'
        )
    return HTMLResponse(
        '<table class="tel-table"><thead><tr>'
        '<th>ciclo</th>'
        '<th style="text-align:right">actual</th>'
        '<th style="text-align:right" title="stima iniziale = predicted del primo snapshot del ciclo (lock-in a inizio ciclo)">stima iniziale</th>'
        '<th style="text-align:center">N snap</th>'
        '<th>errore medio</th>'
        '<th>snapshots (elapsed=predicted/err%)</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


@app.get("/ui/partial/predictor-decisions", include_in_schema=False)
def partial_predictor_decisions(request: Request):
    """
    WU89-Step4 — pannello live decisioni Skip Predictor.

    Mostra ultime 30 decisioni in ordine cronologico inverso (più recenti
    prime), con colori per outcome (skip live applied=rosso, shadow=arancione,
    proceed=grigio). Aggiorna ogni 15s via HTMX.

    Source: `data/predictor_decisions.jsonl` (scritto da main.py al passaggio
    del hook in _thread_istanza).
    """
    from dashboard.services.stats_reader import get_predictor_decisions
    rows = get_predictor_decisions(n=30)
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px;font-size:11px">'
            'nessuna decisione registrata.<br>'
            '<span style="color:var(--text-dim);font-size:10px">'
            'attiva il predictor in <code>home → sistema → predictor</code> '
            'e attendi il primo tick istanza dopo il prossimo restart bot</span></div>'
        )
    body = []
    for r in rows:
        ts    = r.get("ts_local", "?")
        inst  = r.get("instance", "?")
        mode  = r.get("mode", "?")
        skip  = bool(r.get("should_skip"))
        reas  = r.get("reason", "?")
        score = float(r.get("score", 0))
        appl  = bool(r.get("applied"))
        gr    = r.get("guardrail")
        sig   = r.get("signals") or {}
        gp    = bool(r.get("growth_phase"))

        # Color coding
        if appl:
            row_color = "#f44336"   # rosso: skip applicato live
            badge = "SKIP LIVE"
        elif skip and mode == "SHADOW":
            row_color = "#ff9800"   # arancione: skip shadow (no apply)
            badge = "SKIP SHADOW"
        elif gr:
            row_color = "#9c27b0"   # viola: guardrail block
            badge = f"GR-{gr}"
        else:
            row_color = "var(--text-dim)"
            badge = "PROCEED"
        # Saving estimato (solo per skip o guardrail su skip predetto)
        saving_min  = sig.get("saving_estimato_min")
        saving_boot = sig.get("saving_boot_home_s")
        saving_task = sig.get("saving_tasks_s")
        if saving_min is not None and (skip or gr):
            saving_str = (
                f'<b style="color:var(--text)">{saving_min:.1f}min</b>'
                f'<span style="color:var(--text-dim);font-size:9px"> '
                f'(boot {saving_boot:.0f}s + task {saving_task:.0f}s)</span>'
            )
        else:
            saving_str = '<span style="color:var(--text-dim);font-size:9px">—</span>'
        # Signals compact (escluse keys saving — già in colonna dedicata)
        SAVING_KEYS = {"saving_estimato_s", "saving_estimato_min",
                       "saving_boot_home_s", "saving_tasks_s"}
        sig_short = {k: v for k, v in sig.items() if k not in SAVING_KEYS}
        sig_str = " ".join(f"{k}={v}" for k, v in list(sig_short.items())[:5])
        if len(sig_str) > 80:
            sig_str = sig_str[:77] + "..."
        gp_marker = ' <span style="color:#4caf50;font-size:9px">GROWTH</span>' if gp else ""
        body.append(
            f'<tr>'
            f'<td style="color:var(--text-dim);font-size:10px;white-space:nowrap">{ts}</td>'
            f'<td style="font-weight:600">{inst}</td>'
            f'<td style="color:{row_color};font-weight:600;font-size:10px">{badge}</td>'
            f'<td style="color:var(--accent);font-size:10px">{reas}</td>'
            f'<td style="text-align:right;font-family:monospace;font-size:10px">{score:.2f}</td>'
            f'<td style="font-size:10px;text-align:right;white-space:nowrap">{saving_str}</td>'
            f'<td style="color:var(--text-dim);font-size:9px;font-family:monospace">{sig_str}{gp_marker}</td>'
            f'</tr>'
        )
    return HTMLResponse(
        '<div style="color:var(--text-dim);font-size:10px;padding:4px 8px;'
        'background:rgba(255,255,255,0.02);border-left:2px solid var(--accent);'
        'margin-bottom:6px">'
        '<b style="color:var(--text)">ℹ semantica:</b> il timestamp è il momento '
        'della <b>decisione predictor</b> (inizio thread istanza), <i>prima</i> del '
        'boot MuMu+attendi_home (~6-9 min). Le azioni effettive su quella istanza '
        'appaiono nei log task ~6-9 min dopo la decisione, salvo SKIP-LIVE applicato '
        '(early return, no boot).'
        '</div>'
        '<table class="tel-table"><thead><tr>'
        '<th>decisione</th><th>ist</th><th>esito</th><th>regola</th>'
        '<th style="text-align:right">score</th>'
        '<th style="text-align:right">saving</th>'
        '<th>signals</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


@app.get("/ui/partial/predictor-distribuzione", include_in_schema=False)
def partial_predictor_distribuzione(request: Request):
    """
    Distribuzione empirica slot-pieni-al-ritorno per istanza.

    Per ogni istanza, valuta ultime 30 transizioni (record, record+1) di
    `data/istanza_metrics.jsonl`:
      - n_post_pieni: tick chiusi con slot saturi
      - P(squadre_fuori): P(slot ancora pieni al tick successivo | post_pieni)
      - Δt p25/p50/p75: tempo trascorso fra tick consecutivi (solo post_pieni)

    Senza modello empirico T_marcia: lookup diretto sullo storico osservato.
    Per validare/correlare con il modello puntuale di skip_predictor.

    Refresh 60s via HTMX. Restart dashboard richiesto al primo deploy.
    """
    from dashboard.services.stats_reader import get_distribuzione_slot_per_istanza
    rows = get_distribuzione_slot_per_istanza(window_records=30)
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px;font-size:11px">'
            'nessun dato disponibile.<br>'
            '<span style="font-size:10px">richiede record in <code>data/istanza_metrics.jsonl</code></span>'
            '</div>'
        )

    body = []
    for r in rows:
        inst   = r["istanza"]
        ntrans = r["n_transizioni"]
        npost  = r["n_post_pieni"]
        p_sf   = r["P_squadre_fuori"]
        p25    = r["delta_t_min_p25"]
        p50    = r["delta_t_min_p50"]
        p75    = r["delta_t_min_p75"]

        # Color coding P_squadre_fuori
        if p_sf is None:
            p_str   = '<span style="color:var(--text-dim);font-size:10px">n/a</span>'
            verdict = '<span style="color:var(--text-dim);font-size:10px">campione&lt;5</span>'
        else:
            pct = p_sf * 100
            if pct >= 70:
                pcol = "#f44336"   # rosso: skip frequente raccomandato
                verdict = '<span style="color:#f44336;font-size:10px">SKIP frequente</span>'
            elif pct >= 30:
                pcol = "#ff9800"   # arancione: caso limite
                verdict = '<span style="color:#ff9800;font-size:10px">borderline</span>'
            else:
                pcol = "#4caf50"   # verde: NO skip raccomandato
                verdict = '<span style="color:#4caf50;font-size:10px">NO skip</span>'
            p_str = f'<b style="color:{pcol}">{pct:.0f}%</b>'

        # Tabellina ultime 5 (inline su singola cella)
        ult_html = []
        for u in r["ultime"]:
            esito = u["esito"]
            if "fuori" in esito:
                ecol = "#f44336"
            elif "rientrate" in esito:
                ecol = "#4caf50"
            else:
                ecol = "var(--text-dim)"
            ult_html.append(
                f'<div style="font-size:9px;color:var(--text-dim);white-space:nowrap">'
                f'{u["ts_local"]} Δ{u["delta_t_min"]:.0f}min '
                f'<span style="color:var(--text)">{u["post"]}/{u["totali"]}→{u["pre"]}/{u["totali"]}</span> '
                f'<span style="color:{ecol}">{esito}</span>'
                f'</div>'
            )

        body.append(
            f'<tr>'
            f'<td style="font-weight:600">{inst}</td>'
            f'<td style="text-align:right;font-size:10px">{ntrans}</td>'
            f'<td style="text-align:right;font-size:10px">{npost}</td>'
            f'<td style="text-align:right">{p_str}</td>'
            f'<td style="text-align:right;font-size:10px">{p25:.0f}</td>'
            f'<td style="text-align:right;font-size:10px">{p50:.0f}</td>'
            f'<td style="text-align:right;font-size:10px">{p75:.0f}</td>'
            f'<td>{verdict}</td>'
            f'<td style="line-height:1.2">{"".join(ult_html)}</td>'
            f'</tr>'
        )

    return HTMLResponse(
        '<table class="tel-table"><thead><tr>'
        '<th>istanza</th>'
        '<th style="text-align:right">n.trans</th>'
        '<th style="text-align:right">n.saturi</th>'
        '<th style="text-align:right">P sq fuori</th>'
        '<th style="text-align:right" colspan="3">Δt p25/p50/p75 (min)</th>'
        '<th>raccom.</th>'
        '<th>ultime 5 transizioni</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


@app.get("/ui/partial/copertura-cicli", include_in_schema=False)
def partial_copertura_cicli(request: Request):
    """
    WU118 (04/05) — pannello copertura squadre ultimi 5 cicli per istanza.

    Per ogni istanza non-master mostra:
      - Lista ultimi 5 cicli (cycle_id, ts) con n_satura/n_invii e per-tipo
      - Totali aggregati nei 5 cicli per tipo (pomodoro/legno/acciaio/petrolio)

    Ordine tipi UI: pomodoro, legno, acciaio, petrolio (fisso).
    Soglia "satura": load_squadra >= cap_nodo × 0.95 (margine OCR noise).

    Dati: data/istanza_metrics.jsonl (post-WU116 hanno load_squadra).
    Pre-WU116: invii con load=-1 contati come "?" (no OCR).
    """
    from dashboard.services.stats_reader import (
        get_copertura_ultimi_cicli, _LABEL_ORDINE, _LABEL_ICONA,
    )
    data = get_copertura_ultimi_cicli(n_cicli=5)
    if not data:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px">'
            'nessun dato copertura — record disponibili dopo prossimo restart '
            'bot (WU116 hook in raccolta.py)</div>'
        )
    return templates.TemplateResponse(
        request,
        "partials/copertura_cicli.html",
        {
            "data":         data,
            "label_ordine": _LABEL_ORDINE,
            "label_icona":  _LABEL_ICONA,
        },
    )


@app.get("/ui/partial/truppe-storico", include_in_schema=False)
def partial_truppe_storico(request: Request):
    """
    WU66 (Layout B) — pannello storico truppe 8 giorni con tabella comparata.

    Mostra per ogni istanza:
      - Total Squads oggi (UTC)
      - Total Squads 7 giorni fa
      - Δ assoluto + Δ% + sparkline 8gg
      - Riga TOTALE in fondo
    Ordinamento: delta_pct desc (chi cresce di più sopra), None in fondo.
    """
    from dashboard.services.stats_reader import get_truppe_storico_aggregato
    from datetime import date, timedelta

    data = get_truppe_storico_aggregato(days=8)
    per_istanza = data.get("per_istanza") or []
    totale      = data.get("totale") or {}
    days        = int(data.get("days", 8))

    if not per_istanza:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:12px">'
            'nessun dato truppe — il primo snapshot è scritto al prossimo settings '
            'di ogni istanza (1x/giorno UTC)</div>'
        )

    chars = "▁▂▃▄▅▆▇█"

    def _spark(serie: list, mn: Optional[int], rng: int) -> str:
        out = []
        for v in serie:
            if v is None:
                out.append("·")
            else:
                pct = (v - mn) / rng if rng else 0
                out.append(chars[min(7, max(0, int(pct * 7)))])
        return "".join(out)

    def _fmt(n) -> str:
        return f"{n:,}" if n is not None else "—"

    def _delta_cell(d, p) -> tuple[str, str]:
        if d is None:
            return ("—", "var(--text-dim)")
        if d > 0:
            return (f"+{d:,} ▲{p:.1f}%", "#4ade80")
        if d < 0:
            return (f"{d:,} ▼{abs(p):.1f}%", "#f87171")
        return ("0", "var(--text-dim)")

    today_d = date.today()
    date_labels = [
        (today_d - timedelta(days=days - 1 - i)).strftime("%d/%m")
        for i in range(days)
    ]

    # Per normalizzare lo spark globalmente (stesso scale per tutte)
    all_vals = [v for r in per_istanza for v in (r["serie"] or []) if v is not None]
    g_mn = min(all_vals) if all_vals else 0
    g_mx = max(all_vals) if all_vals else 1
    g_rng = (g_mx - g_mn) or 1

    rows = []
    for r in per_istanza:
        nome  = r["nome"]
        oggi  = r["oggi"]
        sette = r["sette_gg_fa"]
        d, p  = r["delta"], r["delta_pct"]
        serie = r["serie"] or [None] * days
        delta_lbl, delta_col = _delta_cell(d, p)
        # spark normalizzato sui valori dell'istanza (più informativo che globale)
        ivals = [v for v in serie if v is not None]
        if ivals:
            i_mn, i_mx = min(ivals), max(ivals)
            i_rng = (i_mx - i_mn) or 1
            spark = _spark(serie, i_mn, i_rng)
        else:
            spark = "·" * days
        spark_tip = " · ".join(
            f"{date_labels[i]}: {(v if v is not None else '—')}"
            for i, v in enumerate(serie)
        )
        rows.append(
            f'<tr style="border-bottom:0.5px solid rgba(255,255,255,0.04)">'
            f'<td style="padding:3px 8px;font-weight:600">{nome}</td>'
            f'<td style="padding:3px 8px;text-align:right">{_fmt(oggi)}</td>'
            f'<td style="padding:3px 8px;text-align:right;color:var(--text-dim)">{_fmt(sette)}</td>'
            f'<td style="padding:3px 8px;text-align:right;color:{delta_col}">{delta_lbl}</td>'
            f'<td style="padding:3px 8px;font-family:monospace;font-size:14px;'
            f'color:var(--accent);letter-spacing:1px" title="{spark_tip}">{spark}</td>'
            f'</tr>'
        )

    # Riga TOTALE
    t_oggi  = totale.get("oggi")
    t_sette = totale.get("sette_gg_fa")
    t_d, t_p = totale.get("delta"), totale.get("delta_pct")
    t_serie = totale.get("serie") or [None] * days
    t_delta_lbl, t_delta_col = _delta_cell(t_d, t_p)
    tvals = [v for v in t_serie if v is not None]
    if tvals:
        t_mn, t_mx = min(tvals), max(tvals)
        t_rng = (t_mx - t_mn) or 1
        t_spark = _spark(t_serie, t_mn, t_rng)
    else:
        t_spark = "·" * days
    t_spark_tip = " · ".join(
        f"{date_labels[i]}: {(v if v is not None else '—')}"
        for i, v in enumerate(t_serie)
    )

    tot_row = (
        f'<tr style="border-top:1.5px solid var(--border);'
        f'background:rgba(255,255,255,0.02)">'
        f'<td style="padding:5px 8px;font-weight:700;color:var(--accent)">TOTALE</td>'
        f'<td style="padding:5px 8px;text-align:right;font-weight:700">{_fmt(t_oggi)}</td>'
        f'<td style="padding:5px 8px;text-align:right;color:var(--text-dim)">{_fmt(t_sette)}</td>'
        f'<td style="padding:5px 8px;text-align:right;font-weight:700;color:{t_delta_col}">{t_delta_lbl}</td>'
        f'<td style="padding:5px 8px;font-family:monospace;font-size:14px;'
        f'color:var(--accent);letter-spacing:1px" title="{t_spark_tip}">{t_spark}</td>'
        f'</tr>'
    )

    # Riga MASTER (FauMorfeus o altre istanze master) — fuori dal totale
    master_row_html = ""
    m = data.get("master")
    if m:
        m_d, m_p = m.get("delta"), m.get("delta_pct")
        m_serie = m.get("serie") or [None] * days
        m_delta_lbl, m_delta_col = _delta_cell(m_d, m_p)
        mvals = [v for v in m_serie if v is not None]
        if mvals:
            m_mn, m_mx = min(mvals), max(mvals)
            m_rng = (m_mx - m_mn) or 1
            m_spark = _spark(m_serie, m_mn, m_rng)
        else:
            m_spark = "·" * days
        m_spark_tip = " · ".join(
            f"{date_labels[i]}: {(v if v is not None else '—')}"
            for i, v in enumerate(m_serie)
        )
        master_row_html = (
            f'<tr style="border-top:0.5px dashed var(--border);'
            f'background:rgba(245,197,66,0.04)">'
            f'<td style="padding:5px 8px;font-weight:600;color:#f5c542">'
            f'<span title="master — rifugio destinatario">★</span> {m["nome"]}</td>'
            f'<td style="padding:5px 8px;text-align:right">{_fmt(m.get("oggi"))}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:var(--text-dim)">{_fmt(m.get("sette_gg_fa"))}</td>'
            f'<td style="padding:5px 8px;text-align:right;color:{m_delta_col}">{m_delta_lbl}</td>'
            f'<td style="padding:5px 8px;font-family:monospace;font-size:14px;'
            f'color:#f5c542;letter-spacing:1px" title="{m_spark_tip}">{m_spark}</td>'
            f'</tr>'
        )

    header = (
        f'<thead><tr style="color:var(--text-dim);font-size:11px;'
        f'border-bottom:1px solid var(--border)">'
        f'<th style="text-align:left;padding:4px 8px">istanza</th>'
        f'<th style="text-align:right;padding:4px 8px">oggi</th>'
        f'<th style="text-align:right;padding:4px 8px">7 gg fa</th>'
        f'<th style="text-align:right;padding:4px 8px">Δ (Δ%)</th>'
        f'<th style="text-align:left;padding:4px 8px" '
        f'title="ultimi {days} giorni: {" · ".join(date_labels)}">'
        f'trend ({days}gg)</th>'
        f'</tr></thead>'
    )

    return HTMLResponse(
        f'<table style="width:100%;border-collapse:collapse;font-size:12px">'
        f'{header}<tbody>{"".join(rows)}{tot_row}{master_row_html}</tbody></table>'
    )


@app.get("/ui/partial/debug-tasks", include_in_schema=False)
def partial_debug_tasks(request: Request):
    """
    WU115 — pannello debug screenshot per task (hot-reload via config).

    Mostra toggle pill per ogni task noto, click invia PATCH a
    /api/debug-tasks/{task}/{enable|disable} e re-renderizza il partial.
    HTMX refresh ogni 30s (sync con cache TTL shared/debug_buffer).
    """
    from shared.debug_buffer import get_all_debug_status

    # Lista task noti (deve corrispondere a _KNOWN_TASKS in api_debug.py)
    known_tasks = ["arena", "arena_mercato", "store", "vip", "messaggi", "boost",
                   "alleanza", "donazione", "radar", "radar_census",
                   "truppe", "zaino", "main_mission",
                   "raccolta", "raccolta_chiusura", "rifornimento",
                   "district_showdown"]
    raw_status = get_all_debug_status()
    status: dict[str, bool] = {}
    for t in known_tasks:
        status[t] = bool(raw_status.get(t, False))
    # Aggiungi eventuali task in config NON in known (per visibilità)
    for t, v in raw_status.items():
        if t not in status:
            status[t] = bool(v)

    active_count = sum(1 for v in status.values() if v)

    pills = []
    for task in sorted(status.keys()):
        on = status[task]
        action = "disable" if on else "enable"
        bg = "#f5c542" if on else "rgba(255,255,255,0.08)"
        fg = "#0f0f0f" if on else "var(--text)"
        border = "1.5px solid #f5c542" if on else "1px solid var(--border)"
        label = f"🐛 {task}"
        # NB: usiamo /ui/debug-tasks/... che ritorna HTML del partial
        # (l'API JSON sta su /api/debug-tasks/... per consumer programmatici)
        pills.append(
            f'<button hx-patch="/ui/debug-tasks/{task}/{action}" '
            f'hx-target="#debug-tasks-panel" hx-swap="innerHTML" '
            f'hx-trigger="click" '
            f'style="background:{bg};color:{fg};border:{border};'
            f'border-radius:14px;padding:4px 12px;font-size:11px;'
            f'font-weight:{600 if on else 400};cursor:pointer;'
            f'margin:2px 4px 2px 0;letter-spacing:0.3px" '
            f'title="click per {action}">'
            f'{label}</button>'
        )

    summary = (
        f'<div style="color:var(--text-dim);font-size:10px;padding:4px 0">'
        f'{active_count} task con debug attivo · click pill per toggle'
        f'</div>'
    )
    pills_html = (
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;'
        f'padding:4px 0">{"".join(pills)}</div>'
    )

    return HTMLResponse(f'{summary}{pills_html}')


# UI wrapper: PATCH che ritorna HTML del partial (per HTMX swap automatico).
# Path separato da /api/debug-tasks (JSON) per evitare conflitto router.
@app.api_route("/ui/debug-tasks/{task_name}/{action}", methods=["PATCH"],
               include_in_schema=False)
def _ui_patch_debug_task(task_name: str, action: str, request: Request):
    """HTMX wrapper: applica toggle e ritorna partial HTML aggiornato."""
    from dashboard.routers.api_debug import patch_debug_task
    try:
        patch_debug_task(task_name, action)
    except Exception:
        pass
    return partial_debug_tasks(request)


@app.get("/ui/partial/learned-banners", include_in_schema=False)
def partial_learned_banners(request: Request):
    """
    WU93 — pannello banner appresi automaticamente dal BannerLearner.
    Mostra:
      - Toggle ON/OFF globale del learner (`globali.auto_learn_banner`)
      - Tabella entry appresi con metadati + actions (disable/enable/delete).
    """
    from shared.learned_banners import load_all
    from dashboard.services.config_manager import get_overrides

    # Leggi stato learner globale
    try:
        ov = get_overrides() or {}
        learner_enabled = bool(ov.get("globali", {}).get("auto_learn_banner", True))
    except Exception:
        learner_enabled = True

    learner_color = "#4ade80" if learner_enabled else "#f87171"
    learner_lbl = "ATTIVO" if learner_enabled else "DISATTIVO"
    toggle_action = "disable" if learner_enabled else "enable"
    toggle_lbl = "Disattiva learner" if learner_enabled else "Attiva learner"

    toggle_row = (
        f'<div style="display:flex;align-items:center;gap:12px;'
        f'padding:8px 12px;margin-bottom:8px;background:rgba(255,255,255,0.02);'
        f'border:1px solid var(--border);border-radius:4px">'
        f'<span style="font-size:11px;color:var(--text-dim)">processo learner:</span>'
        f'<span style="color:{learner_color};font-weight:700;font-size:12px">{learner_lbl}</span>'
        f'<button hx-post="/api/banner-learner/{toggle_action}" '
        f'hx-target="#learned-banners-panel" hx-swap="innerHTML" '
        f'style="margin-left:auto;padding:4px 12px;font-size:11px;'
        f'background:var(--bg-light);border:1px solid var(--border);'
        f'color:var(--text);border-radius:3px;cursor:pointer">{toggle_lbl}</button>'
        f'</div>'
    )

    banners = load_all()
    if not banners:
        return HTMLResponse(
            toggle_row +
            '<div style="color:var(--text-dim);text-align:center;padding:12px">'
            'nessun banner appreso (verranno aggiunti automaticamente quando il '
            'bot incontra un popup non catalogato e riesce a chiuderlo)</div>'
        )

    rows = []
    for b in sorted(banners, key=lambda x: x.created_at, reverse=True):
        succ_rate = (
            f"{100*b.success_count/b.hit_count:.0f}%"
            if b.hit_count > 0 else "—"
        )
        last = (b.last_used or b.created_at)[:16].replace("T", " ")
        status_color = "#4ade80" if b.enabled else "#f87171"
        status_lbl = "ON" if b.enabled else "OFF"
        toggle_action = "disable" if b.enabled else "enable"
        toggle_lbl = "Disabilita" if b.enabled else "Abilita"
        rows.append(
            f'<tr style="border-bottom:0.5px solid rgba(255,255,255,0.04)">'
            f'<td style="padding:4px 8px;font-family:monospace;font-size:11px">{b.name}</td>'
            f'<td style="padding:4px 8px;text-align:center">'
            f'<img src="/learned-template/{b.name}/x" '
            f'style="height:32px;border:1px solid var(--border);border-radius:3px" '
            f'title="X tag" /></td>'
            f'<td style="padding:4px 8px;text-align:center">{b.x_coords[0]},{b.x_coords[1]}</td>'
            f'<td style="padding:4px 8px;text-align:right">{b.hit_count}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:{"#4ade80" if b.success_count >= b.fail_count else "#f87171"}">{succ_rate}</td>'
            f'<td style="padding:4px 8px;text-align:right">{b.fail_streak}</td>'
            f'<td style="padding:4px 8px;font-size:11px;color:var(--text-dim)">{last}</td>'
            f'<td style="padding:4px 8px;text-align:center;color:{status_color};font-weight:700">{status_lbl}</td>'
            f'<td style="padding:4px 8px;text-align:center">'
            f'<button hx-post="/api/learned-banners/{b.name}/{toggle_action}" '
            f'hx-target="#learned-banners-panel" hx-swap="innerHTML" '
            f'style="padding:2px 8px;font-size:11px;background:var(--bg-light);'
            f'border:1px solid var(--border);color:var(--text);border-radius:3px;'
            f'cursor:pointer;margin-right:4px">{toggle_lbl}</button>'
            f'<button hx-post="/api/learned-banners/{b.name}/delete" '
            f'hx-target="#learned-banners-panel" hx-swap="innerHTML" '
            f'hx-confirm="Eliminare definitivamente {b.name}?" '
            f'style="padding:2px 8px;font-size:11px;background:rgba(248,113,113,0.1);'
            f'border:1px solid #f87171;color:#f87171;border-radius:3px;cursor:pointer">'
            f'Elimina</button></td>'
            f'</tr>'
        )

    header = (
        '<thead><tr style="color:var(--text-dim);font-size:11px;'
        'border-bottom:1px solid var(--border)">'
        '<th style="text-align:left;padding:4px 8px">name</th>'
        '<th style="text-align:center;padding:4px 8px">X</th>'
        '<th style="text-align:center;padding:4px 8px">coord</th>'
        '<th style="text-align:right;padding:4px 8px">hits</th>'
        '<th style="text-align:right;padding:4px 8px">succ%</th>'
        '<th style="text-align:right;padding:4px 8px">fail streak</th>'
        '<th style="text-align:left;padding:4px 8px">last used</th>'
        '<th style="text-align:center;padding:4px 8px">stato</th>'
        '<th style="text-align:center;padding:4px 8px">azioni</th>'
        '</tr></thead>'
    )

    return HTMLResponse(
        toggle_row +
        f'<table style="width:100%;border-collapse:collapse;font-size:12px">'
        f'{header}<tbody>{"".join(rows)}</tbody></table>'
    )


@app.post("/api/banner-learner/{action}", include_in_schema=False)
def api_banner_learner_toggle(action: str):
    """Toggle ON/OFF globale del BannerLearner. Persiste in
    runtime_overrides.json globali.auto_learn_banner."""
    from dashboard.services.config_manager import get_overrides, save_overrides
    if action not in ("enable", "disable"):
        return HTMLResponse(f"action sconosciuta: {action}", status_code=400)
    enabled = (action == "enable")
    try:
        ov = get_overrides() or {}
        if "globali" not in ov:
            ov["globali"] = {}
        ov["globali"]["auto_learn_banner"] = enabled
        save_overrides(ov)
    except Exception as exc:
        return HTMLResponse(f"errore: {exc}", status_code=500)
    return partial_learned_banners(None)


@app.get("/learned-template/{name}/{kind}", include_in_schema=False)
def learned_template_image(name: str, kind: str):
    """Serve i PNG dei template learned per anteprima dashboard."""
    from shared.learned_banners import load_all, _resolve_root
    from fastapi.responses import FileResponse
    if kind not in ("x", "title"):
        return HTMLResponse("kind non valido", status_code=400)
    for b in load_all():
        if b.name == name:
            path = _resolve_root() / (b.x_path if kind == "x" else b.title_path)
            if path.exists():
                return FileResponse(str(path), media_type="image/png")
            return HTMLResponse("template mancante", status_code=404)
    return HTMLResponse("banner non trovato", status_code=404)


@app.post("/api/learned-banners/{name}/{action}", include_in_schema=False)
def api_learned_banner_action(name: str, action: str):
    """Disable / enable / delete di un learned banner. Ritorna il pannello aggiornato."""
    from shared.learned_banners import set_enabled, delete as delete_learned
    if action == "disable":
        set_enabled(name, False)
    elif action == "enable":
        set_enabled(name, True)
    elif action == "delete":
        delete_learned(name)
    else:
        return HTMLResponse(f"action sconosciuta: {action}", status_code=400)
    # Restituisce il pannello aggiornato per HTMX swap
    return partial_learned_banners(None)


@app.get("/ui/partial/res-oraria", include_in_schema=False)
def partial_res_oraria(request: Request):
    """
    Pannello risorse farm — blocco produzione/ora.
    Somma metrics.*_per_ora da tutti gli state/FAU_XX.json.
    Valori 0.0 normali se bot appena ripartito (metrics aggiornati da raccolta.py).
    """
    from dashboard.services.stats_reader import get_risorse_farm

    farm = get_risorse_farm()
    prod = farm.produzione_per_ora

    RISORSE = [
        ("pomodoro", "🍅"),
        ("legno",    "🪵"),
        ("acciaio",  "⚙"),
        ("petrolio", "🛢"),
    ]

    ha_dati = any(prod.get(r, 0.0) > 0 for r, _ in RISORSE)

    if not ha_dati:
        corpo = '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:6px">in attesa del primo ciclo raccolta</td></tr>'
    else:
        max_val   = max(prod.get(r, 0.0) for r, _ in RISORSE) or 1.0
        riga_vals = ""
        for risorsa, ico in RISORSE:
            v   = prod.get(risorsa, 0.0)
            pct = int(v / max_val * 100)
            lbl = _fmt_m(v)
            riga_vals += (
                f'<td title="{risorsa}: {lbl}/h">'
                f'<div style="display:flex;flex-direction:column;align-items:center;gap:2px">'
                f'<div style="width:{max(pct,2)}%;height:4px;background:var(--accent);'
                f'border-radius:2px;min-width:2px"></div>'
                f'<span>{lbl}</span></div></td>'
            )
        corpo = f'<tr><td style="color:var(--text-dim)">farm</td>{riga_vals}</tr>'

    # WU56 — Storico aggregator (default 12h per stare in larghezza sidebar)
    from dashboard.services.stats_reader import get_produzione_storico_24h
    storico  = get_produzione_storico_24h(hours=12)
    samples  = storico.get("samples", 0)
    window_h = storico.get("window_h", 12)

    # Sparkline ASCII per ogni risorsa
    def _spark(vals):
        if not vals:
            return ""
        chars = "▁▂▃▄▅▆▇█"
        mx = max(vals) or 1
        return "".join(chars[min(7, int(v / mx * 7))] for v in vals)

    # Layout 2-righe per risorsa (sparkline sopra full-width, valori sotto)
    # Evita overflow su sidebar stretta (260px).
    storico_rows = ""
    if samples > 0:
        for risorsa, ico in RISORSE:
            serie = storico["serie"].get(risorsa, [])
            media = storico["media_24h"].get(risorsa, 0)
            mn    = storico["min_24h"].get(risorsa,   0)
            mx    = storico["max_24h"].get(risorsa,   0)
            spark = _spark(serie)
            storico_rows += (
                f'<div style="margin-bottom:8px;border-bottom:0.5px solid var(--border);'
                f'padding-bottom:5px">'
                # Riga 1: icona + sparkline grande
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">'
                f'<span style="font-size:14px;width:18px">{ico}</span>'
                f'<span style="font-family:monospace;font-size:14px;color:var(--accent);'
                f'letter-spacing:1px" title="ultime {window_h} ore">{spark}</span>'
                f'</div>'
                # Riga 2: valori avg/min/max compatti
                f'<div style="display:flex;justify-content:space-between;'
                f'font-size:10px;padding-left:24px">'
                f'<span style="color:var(--text-dim)">avg <b style="color:var(--text)">{_fmt_m(media)}</b></span>'
                f'<span style="color:var(--text-dim)">min <b style="color:var(--text)">{_fmt_m(mn)}</b></span>'
                f'<span style="color:var(--text-dim)">max <b style="color:var(--accent)">{_fmt_m(mx)}</b></span>'
                f'</div>'
                f'</div>'
            )

    html = f'''
    <div class="res-sub">produzione/ora — farm aggregata</div>
    <table class="ora-tbl">
      <thead>
        <tr>
          <th></th>
          {''.join(f'<th>{ico}</th>' for _, ico in RISORSE)}
        </tr>
      </thead>
      <tbody>{corpo}</tbody>
    </table>

    <details style="margin-top:8px" {("open" if samples > 0 else "")}>
      <summary style="cursor:pointer;font-size:11px;color:var(--text-dim);
                       letter-spacing:1px;text-transform:uppercase">
        📊 storico {window_h}h ({samples} sessioni)
      </summary>
      <div style="margin-top:6px">
      {(storico_rows
        if samples > 0 else
        '<div style="color:var(--text-dim);font-size:11px;padding:6px 0">'
        'nessun dato (serve ≥1 sessione completata con durata ≥5min)</div>')}
      </div>
    </details>

    <div style="color:var(--text-dim);font-size:9px;margin-top:6px;text-align:center;
                line-height:1.3">
      farm: ultima sessione · storico: ultime {window_h}h
    </div>
    '''
    return HTMLResponse(html)


# ==============================================================================
# Telemetria — 4 partial HTMX (WU37 — Issue #53 MVP)
# ==============================================================================

def _fmt_dur(s: float) -> str:
    if s <= 0:
        return "—"
    if s < 60:
        return f"{s:.0f}s"
    m = s / 60
    if m < 60:
        return f"{int(m)}m{int(s % 60):02d}s"
    h = m / 60
    return f"{int(h)}h{int(m % 60):02d}m"


@app.get("/ui/partial/telemetria-task", include_in_schema=False)
def partial_telemetria_task(request: Request):
    from dashboard.services.telemetry_reader import get_task_kpi_24h
    rows = get_task_kpi_24h()
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px">'
            'nessun task eseguito nelle ultime 24h</div>'
        )
    body = []
    for k in rows:
        col = "var(--green)" if k.ok_pct >= 90 else ("#fbbf24" if k.ok_pct >= 70 else "var(--red,#f87171)")
        err = k.last_err if k.last_err and k.last_err != "—" else "—"
        body.append(
            f'<tr><td style="color:var(--accent)">{k.nome}</td>'
            f'<td style="text-align:right">{k.esec_24h}</td>'
            f'<td style="text-align:right;color:{col};font-weight:600">{k.ok_pct}%</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{_fmt_dur(k.avg_dur_s)}</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{k.last_ts or "—"}</td>'
            f'<td style="color:var(--text-dim);font-size:11px">{err}</td></tr>'
        )
    html = (
        '<table class="tel-table">'
        '<thead><tr>'
        '<th>task</th>'
        '<th style="text-align:right">esec</th>'
        '<th style="text-align:right">ok%</th>'
        '<th style="text-align:right">avg dur</th>'
        '<th style="text-align:right">last</th>'
        '<th>ultimo errore</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )
    return HTMLResponse(html)


@app.get("/ui/partial/telemetria-health", include_in_schema=False)
def partial_telemetria_health(request: Request):
    from dashboard.services.telemetry_reader import get_health_24h
    rows = get_health_24h()
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--green);text-align:center;padding:8px">'
            '✓ nessuna anomalia rilevata 24h</div>'
        )
    body = []
    for h in rows:
        if h.kind == "ok":
            badge = '<span style="color:var(--green);font-weight:600">✓</span>'
            val_col = "var(--green)"
        elif h.kind == "err":
            badge = '<span style="color:var(--red);font-weight:700">✗</span>'
            val_col = "var(--red)"
        else:
            badge = '<span style="color:#fbbf24;font-weight:600">⚠</span>'
            val_col = "var(--accent)"
        body.append(
            f'<tr><td style="width:18px">{badge}</td>'
            f'<td>{h.label}</td>'
            f'<td style="text-align:right;color:{val_col};font-weight:600">{h.value}</td>'
            f'<td style="color:var(--text-dim);font-size:11px">{h.note}</td></tr>'
        )
    return HTMLResponse(f'<table class="tel-table"><tbody>{"".join(body)}</tbody></table>')


@app.get("/ui/partial/telemetria-ciclo", include_in_schema=False)
def partial_telemetria_ciclo(request: Request):
    from dashboard.services.telemetry_reader import get_ciclo_status
    cs = get_ciclo_status()

    def _isth_badge(b):
        if b == "ADB": return '<span style="color:var(--red);font-size:10px;border:1px solid var(--red);padding:1px 5px;border-radius:3px">ADB</span>'
        if b == "DEF": return '<span style="color:#fbbf24;font-size:10px;border:1px solid #fbbf24;padding:1px 5px;border-radius:3px">DEF</span>'
        if b == "▸":   return '<span style="color:var(--accent);font-weight:700">▸</span>'
        return ""

    def _isth_color(esito):
        return {"ok":"var(--green)","abort":"var(--red)","live":"var(--accent)","wait":"var(--text-dim)"}.get(esito,"var(--text)")

    def _hms(s: int) -> str:
        if s <= 0:
            return "—"
        m = s // 60
        if m < 60:
            return f"{m}m {s % 60}s"
        return f"{m // 60}h {m % 60:02d}m"

    rows = "".join(
        f'<tr><td style="color:var(--accent);font-weight:600">{r.nome}</td>'
        f'<td style="color:{_isth_color(r.esito)}">{r.esito}</td>'
        f'<td style="text-align:right">{r.durata}</td>'
        f'<td style="color:var(--text-dim)">{r.tasks}</td>'
        f'<td style="text-align:center">{_isth_badge(r.badge)}</td></tr>'
        for r in cs.istanze
    )

    html = f'''
    <div style="display:flex;justify-content:space-between;margin-bottom:10px;font-size:12px">
      <div>
        <div style="color:var(--text-dim)">CICLO #{cs.numero}</div>
        <div style="color:var(--accent);font-size:18px;font-weight:600">{_hms(cs.in_corso_da_s)}</div>
      </div>
      <div>
        <div style="color:var(--text-dim);text-align:right">prossima</div>
        <div style="color:var(--text);font-weight:600;text-align:right">{cs.prossima}</div>
      </div>
      <div>
        <div style="color:var(--text-dim);text-align:right">ETA fine</div>
        <div style="color:var(--text);font-weight:600;text-align:right">~{_hms(cs.eta_fine_s)}</div>
      </div>
    </div>
    <table class="tel-table">
      <thead><tr>
        <th>ist</th><th>esito</th>
        <th style="text-align:right">durata</th>
        <th>task</th><th></th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/telemetria-trend", include_in_schema=False)
def partial_telemetria_trend(request: Request):
    from dashboard.services.telemetry_reader import get_trend_7gg
    rows = get_trend_7gg()
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px">'
            'nessun dato storico (data/storico_farm.json vuoto)</div>'
        )
    body = "".join(
        f'<tr><td style="color:var(--text-dim)">{t.label}</td>'
        f'<td style="font-family:monospace;font-size:14px;color:var(--accent);letter-spacing:1px">{t.sparkline}</td>'
        f'<td style="text-align:right;color:var(--text);font-weight:600">{t.current}</td>'
        f'<td style="color:var(--text-dim);font-size:11px">{t.delta}</td></tr>'
        for t in rows
    )
    return HTMLResponse(f'<table class="tel-table"><tbody>{body}</tbody></table>')


@app.get("/ui/partial/telemetria-storico-cicli", include_in_schema=False)
def partial_telemetria_storico_cicli(request: Request):
    """
    WU46 — pannello storico cicli con durate.
    Source: data/telemetry/cicli.json (auto-backfill da bot.log al primo accesso).
    """
    from dashboard.services.telemetry_reader import get_storico_cicli
    rows = get_storico_cicli(15)
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px">'
            'nessun ciclo registrato</div>'
        )

    def _fmt_min(s: int) -> str:
        if s <= 0:
            return "—"
        m = s // 60
        if m < 60:
            return f"{m}m"
        return f"{m // 60}h{m % 60:02d}m"

    body = []
    for c in rows:
        if c.aborted:
            esito_badge = '<span style="color:var(--text-dim);font-weight:600" title="ciclo interrotto da restart bot">⊘</span>'
            esito_col   = "var(--text-dim)"
            dur_lbl     = _fmt_min(c.durata_s) if c.durata_s > 0 else "abort"
        elif c.completato:
            esito_badge = '<span style="color:var(--green);font-weight:600">✓</span>'
            esito_col   = "var(--green)"
            dur_lbl     = _fmt_min(c.durata_s)
        else:
            esito_badge = '<span style="color:var(--accent);font-weight:700">▸</span>'
            esito_col   = "var(--accent)"
            dur_lbl     = "in corso"
        run_tag = (f'<span style="color:var(--text-dim);font-size:9px;margin-left:4px" '
                   f'title="run_local={c.run_local}">·{c.run_local}</span>') if c.run_local else ''
        data_lbl = c.start_date or "—"
        body.append(
            f'<tr><td style="width:18px">{esito_badge}</td>'
            f'<td style="color:var(--accent);font-weight:600">CICLO {c.numero}{run_tag}</td>'
            f'<td style="color:var(--text-dim);font-size:11px;white-space:nowrap">{data_lbl}</td>'
            f'<td style="color:var(--text-dim);font-size:11px">{c.start_hhmm} → {c.end_hhmm}</td>'
            f'<td style="text-align:right;color:{esito_col};font-weight:600">{dur_lbl}</td>'
            f'<td style="text-align:right;color:var(--text-dim);font-size:11px">{c.n_istanze} ist</td></tr>'
        )
    return HTMLResponse(
        '<table class="tel-table"><thead><tr>'
        '<th></th><th>ciclo</th><th>data</th><th>finestra</th>'
        '<th style="text-align:right">durata</th>'
        '<th style="text-align:right">istanze</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


@app.get("/ui/partial/telemetria-tempi-medi", include_in_schema=False)
def partial_telemetria_tempi_medi(request: Request):
    """
    WU49 — Report tempi medi task con filtro outlier IQR (consistenti).
    Esclude district_showdown + radar_census. Min sample 5 esecuzioni.
    """
    from dashboard.services.telemetry_reader import get_task_durations_report
    rows = get_task_durations_report(days=7)
    if not rows:
        return HTMLResponse(
            '<div style="color:var(--text-dim);text-align:center;padding:8px">'
            'nessun dato — telemetria attiva ma serve almeno 5 esecuzioni per task</div>'
        )

    def _fmt(s: float) -> str:
        if s < 60:
            return f"{s:.1f}s"
        return f"{s/60:.1f}m"

    cons_badge = {
        "high": ('<span style="color:var(--green);font-weight:600" title="cv<0.3 — tempi molto consistenti">●●●</span>', "var(--green)"),
        "med":  ('<span style="color:#fbbf24;font-weight:600" title="cv 0.3-0.7 — variabilità media">●●○</span>', "#fbbf24"),
        "low":  ('<span style="color:var(--red);font-weight:600" title="cv>0.7 — alta varianza, tempi inconsistenti">●○○</span>', "var(--red)"),
        "n/a":  ('<span style="color:var(--text-dim)" title="campione troppo piccolo">○○○</span>', "var(--text-dim)"),
    }

    body = []
    for r in rows:
        badge, mean_col = cons_badge.get(r.consistenza, cons_badge["n/a"])
        excl_lbl = (f'<span style="color:var(--text-dim);font-size:9px"> '
                    f'(-{r.excluded})</span>') if r.excluded > 0 else ''
        body.append(
            f'<tr>'
            f'<td style="color:var(--accent)">{r.task}</td>'
            f'<td style="text-align:right">{r.count}{excl_lbl}</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{_fmt(r.min_s)}</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{_fmt(r.median_s)}</td>'
            f'<td style="text-align:right;color:{mean_col};font-weight:600">{_fmt(r.mean_s)}</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{_fmt(r.p95_s)}</td>'
            f'<td style="text-align:right;color:var(--text-dim)">{_fmt(r.max_s)}</td>'
            f'<td style="text-align:right;color:var(--text-dim);font-size:11px">{r.cv:.2f}</td>'
            f'<td style="text-align:center">{badge}</td>'
            f'</tr>'
        )
    return HTMLResponse(
        '<table class="tel-table"><thead><tr>'
        '<th>task</th>'
        '<th style="text-align:right">n</th>'
        '<th style="text-align:right">min</th>'
        '<th style="text-align:right">mediana</th>'
        '<th style="text-align:right">media</th>'
        '<th style="text-align:right">p95</th>'
        '<th style="text-align:right">max</th>'
        '<th style="text-align:right" title="coefficient of variation">cv</th>'
        '<th style="text-align:center" title="consistenza">●</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


# ==============================================================================
# WU51 — Modalità manutenzione (file flag + endpoint dashboard)
# ==============================================================================

from fastapi import HTTPException
from pydantic import BaseModel as _BaseModel


class _MaintenanceReq(_BaseModel):
    motivo: str = ""


@app.get("/api/maintenance/status", include_in_schema=False)
def api_maintenance_status():
    """Stato corrente modalità manutenzione."""
    from core.maintenance import is_maintenance_active, get_maintenance_info
    info = get_maintenance_info()
    return {
        "active":   is_maintenance_active(),
        "info":     info,
    }


@app.post("/api/maintenance/start", include_in_schema=False)
def api_maintenance_start(req: _MaintenanceReq):
    """
    Attiva modalità manutenzione (crea data/maintenance.flag).
    Il bot pausa tra le istanze al prossimo controllo (~entro 5s).
    Mai interrompe un tick istanza in corso.
    """
    from core.maintenance import enable_maintenance, get_maintenance_info
    if not enable_maintenance(motivo=req.motivo, set_da="dashboard"):
        raise HTTPException(500, "scrittura flag fallita")
    return {"active": True, "info": get_maintenance_info()}


@app.post("/api/maintenance/stop", include_in_schema=False)
def api_maintenance_stop():
    """Disattiva modalità manutenzione (rimuove file flag). Bot riprende."""
    from core.maintenance import disable_maintenance
    ok = disable_maintenance()
    if not ok:
        raise HTTPException(500, "rimozione flag fallita")
    return {"active": False}


@app.post("/api/raccolta-ocr-debug/{mode}", include_in_schema=False)
def api_raccolta_ocr_debug(mode: str):
    """
    WU55 — Toggle data collection OCR slot HOME vs MAPPA.
    Modifica `runtime_overrides.json.globali.raccolta_ocr_debug`.

    mode: 'on' | 'off'
    """
    if mode not in ("on", "off"):
        raise HTTPException(400, "mode deve essere 'on' o 'off'")
    from dashboard.services.config_manager import get_overrides, save_overrides
    ov = get_overrides()
    if "globali" not in ov:
        ov["globali"] = {}
    ov["globali"]["raccolta_ocr_debug"] = (mode == "on")
    save_overrides(ov)
    return {"ok": True, "raccolta_ocr_debug": mode == "on"}


@app.get("/api/raccolta-ocr-debug/status", include_in_schema=False)
def api_raccolta_ocr_debug_status():
    """Stato corrente flag + count pair raccolti."""
    from dashboard.services.config_manager import get_overrides
    try:
        from shared.ocr_dataset import list_pairs
        pairs = list_pairs()
        n_complete = sum(1 for p in pairs if p["complete"])
    except Exception:
        pairs = []
        n_complete = 0
    ov = get_overrides()
    active = bool(ov.get("globali", {}).get("raccolta_ocr_debug", False))
    return {
        "active":           active,
        "pair_count":       len(pairs),
        "pair_complete":    n_complete,
        "pair_incomplete":  len(pairs) - n_complete,
    }


@app.get("/ui/partial/maintenance-banner", include_in_schema=False)
def partial_maintenance_banner(request: Request):
    """
    Banner stato manutenzione + pulsanti start/stop. Renderizzato in topbar.
    """
    from core.maintenance import is_maintenance_active, get_maintenance_info
    active = is_maintenance_active()
    info   = get_maintenance_info() or {}

    if active:
        motivo = info.get("motivo", "")
        ts     = info.get("ts_attivato", "")[:19].replace("T", " ")
        # WU54 — auto-resume ts (gioco in manutenzione)
        ar_ts  = info.get("auto_resume_ts", "")
        ar_lbl = ""
        if ar_ts:
            try:
                from datetime import datetime, timezone
                ar_dt = datetime.fromisoformat(ar_ts)
                delta = (ar_dt - datetime.now(timezone.utc)).total_seconds()
                if delta > 0:
                    m, s = int(delta // 60), int(delta % 60)
                    ar_lbl = f' <span style="color:#fbbf24">· auto-resume ~{m}m{s:02d}s</span>'
                else:
                    ar_lbl = ' <span style="color:var(--green)">· auto-resume scaduto</span>'
            except Exception:
                pass
        body = f'''
        <div style="background:rgba(248,113,113,0.15);border:1px solid var(--red);
                    color:var(--red);padding:6px 12px;border-radius:4px;
                    display:flex;align-items:center;gap:10px;font-size:12px">
          <span style="font-weight:600">🔧 MANUTENZIONE ATTIVA</span>
          <span style="color:var(--text-dim)">attivata {ts}{(" — " + motivo) if motivo else ""}{ar_lbl}</span>
          <button onclick="maintenanceToggle(false)" class="btn btn-primary"
                  style="margin-left:auto;padding:3px 10px;font-size:11px">▶ riprendi bot</button>
        </div>
        '''
    else:
        body = f'''
        <div style="display:flex;align-items:center;gap:8px;font-size:11px">
          <span style="color:var(--text-dim)">bot attivo</span>
          <button onclick="maintenanceToggle(true)" class="btn"
                  style="padding:3px 10px;font-size:11px;background:transparent;
                         color:var(--text-dim);border:1px solid var(--border);cursor:pointer">
            🔧 manutenzione
          </button>
        </div>
        '''
    return HTMLResponse(body)
