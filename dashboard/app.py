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

    # raccolta esclusa: è sempre attiva, non controllabile da UI
    ORDER = [
        "rifornimento", "vip", "boost", "arena", "store",
        "alleanza", "donazione", "messaggi", "radar", "zaino",
        "arena_mercato", "district_showdown",
    ]

    # auto-WU22 (27/04): rewrite as 2-col checkbox rows (style rifornimento .rr-cb)
    # auto-WU23 (27/04): abbreviazione nomi >10 char + compound span 2 cols.
    ABBREV = {
        "messaggi":          "msg",
        "alleanza":          "alleanza",
        "rifornimento":      "rifor",
        "donazione":         "donaz",
        "arena_mercato":     "arenaM",
        "district_showdown": "DS",
        "radar_census":      "radCens",
    }
    rows     = []
    rendered = set()

    for name in ORDER:
        if name in rendered:
            continue
        rendered.add(name)

        on      = flags.get(name, True)
        on_cls  = "on" if on else "off"
        checked = "checked" if on else ""
        # Abbreviato se nome > 10 char
        display = ABBREV.get(name, name) if len(name) > 10 else name

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
            rows.append(f'''<label class="task-row compound {on_cls}" title="{name}">
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
        stato       = ist_status.stato if ist_status else ("idle" if not abilitata else "unknown")

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
    prov_lbl = _fmt_m(farm.provviste_residue)

    # Dettaglio per istanza (compact)
    _ZERO_INVIATO = {r: 0 for r in ("pomodoro", "legno", "petrolio", "acciaio")}

    detail_rows = ""
    for d in sorted(farm.istanze_detail, key=lambda x: x.nome):
        # Skip istanze senza mai spedizioni (es. raccolta_only come FauMorfeus)
        if d.inviato_oggi == _ZERO_INVIATO and d.spedizioni_oggi == 0:
            continue
        esaurita_css = "color:var(--red)" if d.provviste_esaurite else "color:var(--text-dim)"
        prov_ist     = _fmt_m(d.provviste_residue)
        inv_str      = " · ".join(
            f"{ico}{_fmt_m(d.inviato_oggi.get(r, 0))}"
            for r, ico in RISORSE
            if d.inviato_oggi.get(r, 0) > 0
        ) or "—"
        detail_rows += f'''
        <div class="res-row" style="font-size:9px">
          <span class="res-name" style="color:var(--accent);min-width:52px">{d.nome}</span>
          <span style="flex:1;color:var(--text-dim)">{inv_str}</span>
          <span style="{esaurita_css}">{prov_ist}</span>
        </div>'''

    html = f'''
    <div class="res-sub">inviato oggi — tutte le istanze</div>
    {rows_inviato}
    <div class="res-sub" style="margin-top:10px;display:flex;justify-content:space-between;align-items:center">
      <span>spedizioni oggi</span>
      <span style="color:var(--accent)">{farm.spedizioni_oggi}
        <span style="color:var(--text-dim);font-size:9px">· {farm.quota_max_per_ciclo}/ciclo</span>
      </span>
    </div>
    <div class="res-sub" style="display:flex;justify-content:space-between;align-items:center">
      <span>provviste residue</span>
      <span style="color:var(--accent)">{prov_lbl}</span>
    </div>
    <div class="res-sub" style="margin-top:10px">dettaglio istanze</div>
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
        # Avvio in formato HH:MM (UTC dell'ts_inizio)
        avvio_lbl  = ts_inizio[11:16] if ts_inizio and len(ts_inizio) >= 16 else "—"

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

        provv_lbl = "esaurita" if provv == 0 else (f"{provv}" if provv > 0 else "—")

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
                f"{r}: corrente ini={ini} inv={inv} tassa={tax} zaino={zd}"
                f" | precedente ini={ini_p} fin={fin_p} inv={inv_p}"
            )
            curr_cell = f'{ini}<span style="color:var(--accent);font-size:9px"> +{inv}</span>'
            prec_cell = (
                f'{ini_p}<span style="color:var(--text-dim);font-size:9px"> → {fin_p}</span>'
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

        # auto-WU19: header completo (assorbe inst-grid). 2 righe:
        # 1) avvio + task corrente|ultimo + errori
        # 2) ts ultimo task + msg ultimo task (se presente)
        err_color = "var(--red,#f87171)" if errori_live > 0 else "var(--text-dim)"
        # task color: rosso se ultimo esito err, accent altrimenti
        task_col = "var(--red,#f87171)" if ut_esito == "err" else "var(--accent)"
        header_status = (
            f'<div style="display:flex;justify-content:space-between;'
            f'gap:6px;font-size:11px;color:var(--text-dim);margin-bottom:2px">'
            f'<span>avvio <b style="color:var(--text)">{avvio_lbl}</b></span>'
            f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
            f'text-align:center">task: <b style="color:{task_col}">{task_lbl}</b></span>'
            f'<span style="color:{err_color}">err:{errori_live}</span>'
            f'</div>'
        )
        # Riga ts + msg (solo se presenti)
        if ut_ts or ut_msg:
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

        # Riga corrente: durata, truppe (raccoglitori), quota rifornimento + flag esaurita
        quota_flag = " 🔴" if quota_esau else ""
        sess_corr_line = (
            f'<div title="{tasks_curr_tip}" style="font-size:11px;color:var(--text-dim);'
            f'margin-top:4px;display:flex;justify-content:space-between;gap:4px">'
            f'<span><b style="color:var(--accent)">corrente</b> · {durata_curr_m}m · '
            f'racc:{truppe} · q:{quota_lbl}{quota_flag}</span>'
            f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
            f'max-width:55%;text-align:right">{tasks_curr_short}</span>'
            f'</div>'
        )

        if has_prec:
            errori_prec = int(precedente.get("errori_count", 0) or 0)
            err_prec_color = "var(--red,#f87171)" if errori_prec > 0 else "var(--text-dim)"
            sess_prec_line = (
                f'<div title="{tasks_prec_tip}" style="font-size:11px;color:var(--text-dim);'
                f'display:flex;justify-content:space-between;gap:4px">'
                f'<span><b style="color:#7cf">precedente</b> · {durata_prec_m}m · '
                f'racc:{truppe_prec} · <span style="color:{err_prec_color}">err:{errori_prec}</span></span>'
                f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
                f'max-width:55%;text-align:right">{tasks_prec_short}</span>'
                f'</div>'
            )
        else:
            sess_prec_line = (
                '<div style="font-size:11px;color:var(--text-dim);text-align:center">'
                '<b>precedente</b> · in attesa</div>'
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
            <span style="color:var(--text-dim);font-weight:normal;font-size:11px">
              P:{provv_lbl}
            </span>
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
          {sess_corr_line}
          {sess_prec_line}
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
    <div style="color:var(--text-dim);font-size:9px;margin-top:6px;text-align:right">
      aggiornato ad ogni ciclo raccolta
    </div>
    '''
    return HTMLResponse(html)
