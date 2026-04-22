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
)


# ==============================================================================
# Lifespan
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
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
        "active":   "home",
        "cfg":      get_merged_config(),
        "istanze":  get_instances(),
    })


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
    })


@app.get("/ui/config", include_in_schema=False)
def ui_config(request: Request):
    from dashboard.services.config_manager import (
        get_global_config, get_overrides, get_instances,
    )
    return templates.TemplateResponse(request, "config_overrides.html", {
        "active":    "config",
        "overrides": get_overrides(),
        "instances": get_instances(),
        "gcfg":      get_global_config(),
    })


@app.get("/ui/config/global", include_in_schema=False)
def ui_config_global(request: Request):
    from dashboard.services.config_manager import get_global_config
    return templates.TemplateResponse(request, "config_global.html", {
        "active": "global",
        "cfg":    get_global_config(),
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
    uptime_h = es.uptime_s // 3600
    uptime_m = (es.uptime_s % 3600) // 60
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
    es      = get_engine_status()
    insts   = get_instances()
    ov      = get_overrides()
    rows    = []
    n_run   = 0
    n_err   = 0

    for ist in insts:
        nome      = ist.get("nome", "")
        ist_status = es.istanze.get(nome)
        ist_ov    = ov.get("istanze", {}).get(nome, {})
        abilitata = ist_ov.get("abilitata", ist.get("abilitata", True))

        if not abilitata:
            stato = "idle"
        elif ist_status:
            stato = ist_status.stato
        else:
            stato = "unknown"

        if stato == "running": n_run += 1
        if stato == "error":   n_err += 1

        ut         = ist_status.ultimo_task if ist_status else None
        task_cor   = ist_status.task_corrente if ist_status else None
        task_label = task_cor or (ut.nome if ut else "—")
        slot_label = "—"
        if ist_status and ist_status.task_eseguiti:
            pass  # slot da OCR non disponibile in status

        rows.append(f'''<div class="ic {stato}">
          <div class="ic-head">
            <span class="ic-name">{nome}</span>
            <span class="badge {stato}">{stato}</span>
          </div>
          <div class="ic-row"><span>task</span><span>{task_label}</span></div>
          <div class="ic-row"><span>ts</span><span>{ut.ts if ut else "—"}</span></div>
        </div>''')

    # Inietta contatori nel topbar via OOB swap (opzionale — aggiornato inline)
    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/task-flags-v2", include_in_schema=False)
def partial_task_flags_v2(request: Request):
    from dashboard.services.config_manager import get_overrides
    ov    = get_overrides()
    flags = ov.get("globali", {}).get("task", {})

    # Task con sottotipo (compound pill)
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

    # Ordine visualizzazione
    ORDER = [
        "raccolta", "rifornimento", "vip", "boost", "arena", "store",
        "alleanza", "messaggi", "radar", "zaino", "arena_mercato",
    ]

    rows = []
    rendered = set()

    for name in ORDER:
        if name in rendered:
            continue
        rendered.add(name)

        # raccolta — sempre on, non togglabile
        if name == "raccolta":
            rows.append('<span class="tog on"><span class="tog-dot"></span>raccolta</span>')
            continue

        on       = flags.get(name, True)
        on_css   = "on" if on else "off"
        next_val = "false" if on else "true"

        if name in COMPOUND:
            c       = COMPOUND[name]
            subs_html = ""
            for s in c["subtypes"]:
                active_css = " active" if s == c["active"] else ""
                # click sottotipo → patch modalità
                if name == "rifornimento":
                    patch_url  = f"/api/config/rifornimento-mode/{s}"
                else:
                    patch_url  = f"/api/config/zaino-mode/{s}"
                subs_html += f'<span class="sub{active_css}" onclick="setModeRemote(\'{name}\',\'{s}\')">{s}</span>'

            rows.append(f'''<span class="tog-c {on_css}">
              <span class="tog-main"
                hx-patch="/api/config/overrides/task/{name}"
                hx-vals='{{"abilitato":"{next_val}"}}'
                hx-swap="none"
                hx-on::after-request="htmx.ajax('GET','/ui/partial/task-flags-v2',{{target:'#task-flags',swap:'innerHTML'}})">
                <span class="tog-dot" style="width:5px;height:5px;border-radius:50%;background:currentColor;flex-shrink:0"></span>{name}
              </span>
              <span class="tog-vsep"></span>
              <span class="subs">{subs_html}</span>
            </span>''')
        else:
            rows.append(f'''<span class="tog {on_css}"
              hx-patch="/api/config/overrides/task/{name}"
              hx-vals='{{"abilitato":"{next_val}"}}'
              hx-swap="none"
              hx-on::after-request="htmx.ajax('GET','/ui/partial/task-flags-v2',{{target:'#task-flags',swap:'innerHTML'}})">
              <span class="tog-dot"></span>{name}
            </span>''')

    return HTMLResponse(''.join(rows))


@app.get("/ui/partial/ist-table", include_in_schema=False)
def partial_ist_table(request: Request):
    from dashboard.services.config_manager import get_instances, get_overrides
    from dashboard.services.stats_reader import get_engine_status
    insts  = get_instances()
    ov     = get_overrides()
    es     = get_engine_status()
    rows   = []

    for ist in insts:
        nome      = ist.get("nome", "")
        ist_ov    = ov.get("istanze", {}).get(nome, {})
        ist_status = es.istanze.get(nome)

        abilitata   = ist_ov.get("abilitata",   ist.get("abilitata",   True))
        truppe      = ist_ov.get("truppe",       ist.get("truppe",      0))
        tipologia   = ist_ov.get("tipologia",    ist.get("profilo",     "full"))
        fascia_raw  = ist_ov.get("fascia_oraria", ist.get("fascia_oraria", ""))
        max_squadre = ist.get("max_squadre", 4)
        livello     = ist.get("livello", 6)
        stato       = ist_status.stato if ist_status else ("idle" if not abilitata else "unknown")

        # Parse fascia "HH:MM-HH:MM"
        fascia_da = ""
        fascia_a  = ""
        if fascia_raw and "-" in str(fascia_raw):
            parts = str(fascia_raw).split("-")
            if len(parts) == 2:
                fascia_da = parts[0].strip()
                fascia_a  = parts[1].strip()

        nome_css = "" if abilitata else " off"
        checked  = "checked" if abilitata else ""

        rows.append(f'''<tr data-nome="{nome}">
          <td><input type="checkbox" class="ist-cb" {checked}
                     style="accent-color:var(--accent);width:13px;height:13px;cursor:pointer"
                     onchange="document.querySelector('[data-nome=\\"{nome}\\"] .ist-name-col').classList.toggle('off',!this.checked)"></td>
          <td>
            <span class="ist-name-col{nome_css}">{nome}</span>
            <span class="badge {stato}" style="margin-left:4px">{stato}</span>
          </td>
          <td><input type="number" class="ist-truppe" value="{truppe}"
                     min="0" step="1000" style="width:62px"></td>
          <td><input type="number" class="ist-sq" value="{max_squadre}"
                     min="1" max="10" style="width:36px"></td>
          <td><select class="ist-prof">
            <option value="full"          {"selected" if tipologia=="full"          else ""}>full</option>
            <option value="raccolta_only" {"selected" if tipologia=="raccolta_only" else ""}>raccolta</option>
          </select></td>
          <td><input type="number" class="ist-lv" value="{livello}"
                     min="1" max="10" style="width:36px"></td>
          <td><div class="fascia">
            <input type="time" class="ist-fascia-da" value="{fascia_da}">
            <span class="fsep">—</span>
            <input type="time" class="ist-fascia-a" value="{fascia_a}">
          </div></td>
        </tr>''')

    return HTMLResponse(''.join(rows) or
        '<tr><td colspan="7" style="color:var(--text-dim);font-size:9px;padding:8px">nessuna istanza</td></tr>')


@app.get("/ui/partial/storico", include_in_schema=False)
def partial_storico(
    request: Request,
    istanza: Optional[str] = None,
    task:    Optional[str] = None,
):
    from dashboard.services.stats_reader import get_storico
    entries = get_storico(50)

    # Filtro per istanza e task
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
    """Placeholder — dati reali da implementare con stats_reader."""
    html = '''
    <div class="res-sub">totale raccolto (ultime 5h)</div>
    <div class="res-row"><span class="res-ico">🍅</span><span class="res-name">campo</span>
      <div class="res-bar-wrap"><div class="res-bar" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">🪵</span><span class="res-name">legno</span>
      <div class="res-bar-wrap"><div class="res-bar" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">🛢</span><span class="res-name">petrolio</span>
      <div class="res-bar-wrap"><div class="res-bar" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">⚙</span><span class="res-name">acciaio</span>
      <div class="res-bar-wrap"><div class="res-bar" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-sub" style="margin-top:10px">nodi in campo ora</div>
    <div class="res-row"><span class="res-ico">🍅</span><span class="res-name">campo</span>
      <div class="res-bar-wrap"><div class="res-bar green" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">🪵</span><span class="res-name">legno</span>
      <div class="res-bar-wrap"><div class="res-bar green" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">🛢</span><span class="res-name">petrolio</span>
      <div class="res-bar-wrap"><div class="res-bar green" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="res-row"><span class="res-ico">⚙</span><span class="res-name">acciaio</span>
      <div class="res-bar-wrap"><div class="res-bar green" style="width:0%"></div></div>
      <span class="res-val">—</span></div>
    <div class="diamond-row">
      <span class="res-ico">💎</span>
      <span class="res-name" style="color:var(--text-dim)">diamanti</span>
      <span class="diamond-val">—</span>
    </div>
    '''
    return HTMLResponse(html)


@app.get("/ui/partial/res-oraria", include_in_schema=False)
def partial_res_oraria(request: Request):
    """Placeholder — dati reali da implementare con stats_reader."""
    html = '''
    <div class="res-sub">produzione/ora (ultime 5h)</div>
    <table class="ora-tbl">
      <thead><tr><th>ora</th><th>🍅</th><th>🪵</th><th>🛢</th><th>⚙</th></tr></thead>
      <tbody>
        <tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:6px">dati non disponibili</td></tr>
      </tbody>
    </table>
    '''
    return HTMLResponse(html)
