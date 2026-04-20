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
def ui_overview(request: Request):
    from dashboard.services.stats_reader import get_all_stats, get_engine_status
    from dashboard.services.config_manager import get_overrides
    return templates.TemplateResponse(request, "overview.html", {
        "stats":     get_all_stats(),
        "engine":    get_engine_status(),
        "overrides": get_overrides(),
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
