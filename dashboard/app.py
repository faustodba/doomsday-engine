# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/app.py
#
#  FastAPI application entry point.
#  Monta i router, serve /static, redirect / -> /ui.
#
#  Avvio: uvicorn dashboard.app:app --host 0.0.0.0 --port 8765
# ==============================================================================

from __future__ import annotations

import sys
from pathlib import Path

# Garantisce che il root del progetto sia in sys.path
# (necessario quando app.py e' avviato da dashboard/)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.routers import (
    api_status, api_stats,
    api_config_global, api_config_overrides, api_log,
)


# ==============================================================================
# Lifespan
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: verifica che i file critici esistano e siano leggibili.
    Non blocca l'avvio — logga warning se mancanti.
    Shutdown: nessuna operazione necessaria (tutto e' stateless).
    """
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
    yield
    print("[DASHBOARD] shutdown.")


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


# ==============================================================================
# Static files
# ==============================================================================

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

_TEMPLATES = Path(__file__).parent / "templates"
templates  = Jinja2Templates(directory=str(_TEMPLATES))


# ==============================================================================
# Root redirect + UI pages (Jinja2)
# ==============================================================================

@app.get("/", include_in_schema=False)
def root():
    """Redirect / -> /ui (la dashboard HTML)."""
    return RedirectResponse(url="/ui")


@app.get("/ui", include_in_schema=False)
def ui_index(request: Request):
    from dashboard.services.config_manager import get_global_config
    return templates.TemplateResponse(request, "index.html", {
        "cfg": get_global_config(),
    })


@app.get("/ui/instance/{nome}", include_in_schema=False)
def ui_instance(request: Request, nome: str):
    from dashboard.services.stats_reader import get_instance_stats
    from dashboard.services.log_reader import get_instance_log
    from dashboard.services.config_manager import get_instance, get_overrides
    return templates.TemplateResponse(request, "instance.html", {
        "stats":     get_instance_stats(nome),
        "log":       get_instance_log(nome, 100),
        "instance":  get_instance(nome),
        "overrides": get_overrides(),
    })


@app.get("/ui/config", include_in_schema=False)
def ui_config(request: Request):
    from dashboard.services.config_manager import (
        get_global_config, get_overrides, get_instances,
    )
    return templates.TemplateResponse(request, "config_overrides.html", {
        "overrides": get_overrides(),
        "instances": get_instances(),
        "gcfg":      get_global_config(),
    })


@app.get("/ui/config/global", include_in_schema=False)
def ui_config_global(request: Request):
    """Pagina edit global_config.json (require restart bot)."""
    from dashboard.services.config_manager import get_global_config
    return templates.TemplateResponse(request, "config_global.html", {
        "cfg": get_global_config(),
    })


# HTMX partial — card singola istanza (polling ogni 10s)
@app.get("/ui/partial/card/{nome}", include_in_schema=False)
def ui_partial_card(request: Request, nome: str):
    from dashboard.services.stats_reader import get_instance_stats
    return templates.TemplateResponse(request, "partials/card_istanza.html", {
        "s": get_instance_stats(nome),
    })


# HTMX partial — engine status bar (polling ogni 5s)
@app.get("/ui/partial/status", include_in_schema=False)
def ui_partial_status(request: Request):
    from dashboard.services.stats_reader import get_engine_status
    return templates.TemplateResponse(request, "partials/status_bar.html", {
        "engine": get_engine_status(),
    })


# HTMX partial — log viewer (polling ogni 15s)
@app.get("/ui/partial/log/{nome}", include_in_schema=False)
def ui_partial_log(request: Request, nome: str):
    from dashboard.services.log_reader import get_instance_log
    entries = get_instance_log(nome, 100)
    return templates.TemplateResponse(request, "partials/log_entries.html", {
        "log": entries,
    })


# HTMX partial — task-flags grid (refresh dopo toggle PATCH)
@app.get("/ui/partial/task-flags", include_in_schema=False)
def ui_partial_task_flags(request: Request):
    """
    Ritorna il div task-grid con lo stato attuale dei task flags.
    Chiamato dopo ogni PATCH /api/config/overrides/task/{name} per
    rigenerare il markup con valori freschi (evita drift JS/DOM).
    """
    from dashboard.services.config_manager import get_overrides
    return templates.TemplateResponse(request, "partials/task_flags.html", {
        "overrides": get_overrides(),
    })


# ==============================================================================
# HTMX partials — index.html (nuova dashboard unificata)
# ==============================================================================

@app.get("/ui/partial/status-inline", include_in_schema=False)
def partial_status_inline(request: Request):
    from dashboard.services.stats_reader import get_engine_status
    from fastapi.responses import HTMLResponse
    es = get_engine_status()
    uptime_h = es.uptime_s // 3600
    uptime_m = (es.uptime_s % 3600) // 60
    html = f'''
    <span class="dot {es.stato}"></span>
    <span class="stat-chip">stato <span>{es.stato}</span></span>
    <span class="stat-chip">ciclo <span>{es.ciclo}</span></span>
    <span class="stat-chip">uptime <span>{uptime_h}h {uptime_m}m</span></span>
    <span class="stat-chip">ts <span>{es.ts}</span></span>
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/summary", include_in_schema=False)
def partial_summary(request: Request):
    from dashboard.services.stats_reader import get_all_stats
    from fastapi.responses import HTMLResponse
    stats = get_all_stats()
    counts = {"running": 0, "waiting": 0, "done": 0, "error": 0, "idle": 0, "unknown": 0}
    for s in stats:
        counts[s.stato_live] = counts.get(s.stato_live, 0) + 1
    html = f'''
    <div class="sum-card"><div class="sum-num num-accent">{len(stats)}</div><div class="sum-lbl">totali</div></div>
    <div class="sum-card"><div class="sum-num num-green">{counts["running"]}</div><div class="sum-lbl">running</div></div>
    <div class="sum-card"><div class="sum-num num-yellow">{counts["waiting"]}</div><div class="sum-lbl">waiting</div></div>
    <div class="sum-card"><div class="sum-num num-blue">{counts["done"]}</div><div class="sum-lbl">done</div></div>
    <div class="sum-card"><div class="sum-num num-red">{counts["error"]}</div><div class="sum-lbl">error</div></div>
    <div class="sum-card"><div class="sum-num num-dim">{counts["idle"] + counts["unknown"]}</div><div class="sum-lbl">idle</div></div>
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/inst-grid", include_in_schema=False)
def partial_inst_grid(request: Request):
    from dashboard.services.stats_reader import get_all_stats, get_engine_status
    from fastapi.responses import HTMLResponse
    stats = get_all_stats()
    es = get_engine_status()
    rows = []
    for s in stats:
        ist_status = es.istanze.get(s.nome)
        ut = ist_status.ultimo_task if ist_status else None
        te = ut.nome if ut else '—'
        ts = ut.ts if ut else '—'
        msg = ut.msg if ut else '—'
        esito_css = 'esito-ok' if (ut and ut.esito == 'ok') else 'esito-err'
        rows.append(f'''
        <div class="inst-card {s.stato_live}">
          <div class="inst-head">
            <span class="inst-name">{s.nome}</span>
            <span class="badge {s.stato_live}">{s.stato_live}</span>
          </div>
          <div class="inst-row"><span>ultimo task</span>
            <span class="{esito_css}">{te}</span></div>
          <div class="inst-row"><span>ts</span><span>{ts}</span></div>
          <div class="inst-row"><span>msg</span>
            <span style="font-size:9px;max-width:140px;text-align:right;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{msg[:40]}</span></div>
        </div>''')
    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/task-flags-v2", include_in_schema=False)
def partial_task_flags_v2(request: Request):
    from dashboard.services.config_manager import get_overrides
    from fastapi.responses import HTMLResponse
    ov = get_overrides()
    flags = ov.get("globali", {}).get("task", {})
    rows = []
    for name, on in flags.items():
        css = "tog on" if on else "tog off"
        next_val = "false" if on else "true"
        rows.append(f'''<span class="{css}"
          hx-patch="/api/config/overrides/task/{name}"
          hx-vals='{{"abilitato":"{next_val}"}}'
          hx-swap="none"
          hx-on::after-request="location.reload()">
          <span class="tog-dot"></span>{name}</span>''')
    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/ist-table", include_in_schema=False)
def partial_ist_table(request: Request):
    from dashboard.services.stats_reader import get_all_stats
    from dashboard.services.config_manager import get_overrides
    from fastapi.responses import HTMLResponse
    stats = get_all_stats()
    ov = get_overrides()
    rows = []
    for s in stats:
        ist_ov = ov.get("istanze", {}).get(s.nome, {})
        on = ist_ov.get("abilitata", True)
        truppe = ist_ov.get("truppe", 0)
        tip = ist_ov.get("tipologia", "full")
        next_val = "false" if on else "true"
        tog_css = "tog on" if on else "tog off"
        rows.append(f'''<tr>
          <td style="color:var(--text);font-family:var(--sans);font-weight:700">{s.nome}</td>
          <td><span class="badge {s.stato_live}">{s.stato_live}</span></td>
          <td style="color:var(--text-dim)">{tip}</td>
          <td style="color:var(--text-dim)">{truppe:,}</td>
          <td><span class="{tog_css}"
            hx-patch="/api/config/overrides/istanze/{s.nome}"
            hx-vals='{{"abilitata":"{next_val}"}}'
            hx-swap="none"
            hx-on::after-request="location.reload()">
            <span class="tog-dot"></span>{"on" if on else "off"}</span></td>
        </tr>''')
    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/storico", include_in_schema=False)
def partial_storico(request: Request):
    from dashboard.services.stats_reader import get_storico
    from fastapi.responses import HTMLResponse
    entries = get_storico(30)
    rows = []
    for e in reversed(entries):
        css = "esito-ok" if e.esito == "ok" else "esito-err"
        rows.append(f'''<tr>
          <td>{e.ts}</td>
          <td style="color:var(--accent)">{e.istanza}</td>
          <td>{e.task}</td>
          <td class="{css}">{e.esito}</td>
          <td>{e.durata_s:.1f}s</td>
          <td style="color:var(--text-dim);font-size:10px">{e.msg[:60]}</td>
        </tr>''')
    return HTMLResponse(''.join(rows) or '<tr><td colspan="6" style="color:var(--text-dim);text-align:center">nessun evento</td></tr>')
