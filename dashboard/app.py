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
        "active":  "home",
        "cfg":     get_merged_config(),
        "istanze": get_instances(),
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
    from dashboard.services.config_manager import (
        get_global_config, get_overrides, get_instances,
    )
    return templates.TemplateResponse(request, "config_overrides.html", {
        "active":    "config",
        "overrides": get_overrides(),
        "instances": get_instances(),
        "gcfg":      get_global_config(),
        **_env_label(),
    })


@app.get("/ui/config/global", include_in_schema=False)
def ui_config_global(request: Request):
    from dashboard.services.config_manager import get_global_config
    return templates.TemplateResponse(request, "config_global.html", {
        "active": "global",
        "cfg":    get_global_config(),
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

    # raccolta esclusa: è sempre attiva, non controllabile da UI.
    # auto-WU24 (27/04): rifornimento+zaino accoppiati nella stessa riga
    # del grid 2-col (compound side-by-side, no più span 2 cols).
    ORDER = [
        "rifornimento", "zaino",
        "vip", "boost",
        "arena", "store",
        "alleanza", "donazione",
        "messaggi", "radar",
        "arena_mercato", "district_showdown",
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
            <span class="ist-name-col{nome_css}">{nome}</span>
            <span class="badge {stato}" style="margin-left:4px">{stato}</span>
          </td>
          <td><input type="number" class="ist-truppe" value="{truppe}" {disabled_attr}
                     min="0" step="1000" style="width:62px"></td>
          <td><input type="number" class="ist-sq" value="{max_squadre}" {disabled_attr}
                     min="1" max="10" style="width:36px"></td>
          <td><select class="ist-prof" {disabled_attr}>
            <option value="full"          {"selected" if tipologia=="full"          else ""}>full</option>
            <option value="raccolta_only" {"selected" if tipologia=="raccolta_only" else ""}>raccolta</option>
            <option value="raccolta_fast" {"selected" if tipologia=="raccolta_fast" else ""}>raccolta fast</option>
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
    dati = get_produzione_istanze()
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

    cards_html = []
    for entry in dati:
        nome = entry.get("nome", "?")
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
            f'margin-top:5px;max-width:60%" '
            f'title="tassa media: {tassa_pct_avg*100:.1f}%">'
            f'<div style="color:var(--accent);font-weight:600;text-align:center;'
            f'margin-bottom:2px;border-bottom:0.5px solid rgba(255,255,255,0.06);'
            f'padding-bottom:1px">rifornimento giornaliero</div>'
            f'{"".join(corr_kvs)}</div>'
        )

        cards_html.append(f'''
        <div class="prod-card" style="background:var(--bg-card);border:1px solid var(--border);
             border-radius:5px;padding:8px 10px;font-size:12px;opacity:{card_opacity}">
          <div style="display:flex;justify-content:space-between;align-items:center;
               margin-bottom:4px;font-weight:600;font-size:14px">
            <span style="display:flex;align-items:center;gap:6px">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;
                background:{stato_col}"></span>
              {nome}
              <span style="background:{badge_bg};color:{stato_col};font-size:10px;
                font-weight:600;padding:1px 6px;border-radius:3px;text-transform:uppercase;
                letter-spacing:0.5px">{stato}</span>
            </span>
            <span style="color:var(--text-dim);font-weight:normal;font-size:10px"></span>
          </div>
          {header_status}
          {header_lastmsg}
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr style="color:var(--text-dim);font-size:11px">
              <th style="text-align:left">risorsa</th>
              <th style="text-align:right">corrente</th>
              <th style="text-align:right">precedente</th>
              <th style="text-align:right">prod/h</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {sess_block}
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
        body.append(
            f'<tr><td style="width:18px">{esito_badge}</td>'
            f'<td style="color:var(--accent);font-weight:600">CICLO {c.numero}{run_tag}</td>'
            f'<td style="color:var(--text-dim);font-size:11px">{c.start_hhmm} → {c.end_hhmm}</td>'
            f'<td style="text-align:right;color:{esito_col};font-weight:600">{dur_lbl}</td>'
            f'<td style="text-align:right;color:var(--text-dim);font-size:11px">{c.n_istanze} ist</td></tr>'
        )
    return HTMLResponse(
        '<table class="tel-table"><thead><tr>'
        '<th></th><th>ciclo</th><th>finestra</th>'
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
