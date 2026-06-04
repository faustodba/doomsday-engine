"""core/tg_handlers_monitoring.py — Handler comandi di sola lettura.

Comandi: /status /istanze /istanza /ciclo /cicli /produzione /rifornimento
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from core.tg_utils import (
    _check_bot_running, _check_dashboard_running,
    _fmt_drl_line, _fmt_dur, _maintenance_info, _parse_dt,
    _read_cicli, _read_engine_status, _read_instances_cfg,
    _read_last_metrics, _read_all_last_metrics, _read_morfeus_state,
    _read_runtime_overrides, _read_state, _read_truppe_storico, _root,
    _tg_enabled,
)

_log = logging.getLogger(__name__)


# ─── Builders ─────────────────────────────────────────────────────────────────

def _build_status() -> str:
    lines: list[str] = ["<b>Stato Doomsday Engine</b>"]

    msg_on = _tg_enabled()
    lines.append(f"Messaggi: {'🔔 ON' if msg_on else '🔕 OFF'} "
                 f"({'usa /stop_messaggi per disabilitare' if msg_on else 'usa /start_messaggi per abilitare'})")

    maint = _maintenance_info()
    if maint and maint.get("active"):
        lines.append("⏸ <b>MAINTENANCE MODE</b> attivo")
        lines.append(f"  Motivo: {maint.get('motivo', '—')}")

    bot_ok = _check_bot_running()
    lines.append("🟢 <b>Bot: ATTIVO</b>" if bot_ok else "🔴 <b>Bot: SPENTO</b>")

    if bot_ok:
        cicli = _read_cicli()
        if cicli:
            ultimo = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[0]
            n     = ultimo.get("numero", ultimo.get("cycle_n", "?"))
            start = ultimo.get("start_ts", "")
            if start:
                try:
                    dt  = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
                    dur = (now - dt).total_seconds()
                    lines.append(f"Ciclo #{n} in corso da {_fmt_dur(dur)}")
                except Exception:
                    lines.append(f"Ciclo #{n}")

    instances = _read_instances_cfg()
    ov        = _read_runtime_overrides()
    ist_ov    = ov.get("istanze", {})
    n_tot     = len(instances)
    n_ok      = sum(
        1 for cfg in instances
        if ist_ov.get(cfg["nome"], {}).get("abilitata", cfg.get("abilitata", True))
    )
    lines.append(f"Istanze: {n_tot} configurate, {n_ok} abilitate")

    dash_ok = _check_dashboard_running()
    lines.append("🟢 Dashboard: ATTIVA" if dash_ok else "🔴 Dashboard: non avviata")
    lines.append(_fmt_drl_line("DRL master"))

    if not bot_ok or not dash_ok:
        lines.append("")
        lines.append("Usa /avvia_tutto per avviare i servizi spenti")

    return "\n".join(lines)


def _build_istanze() -> str:
    instances   = _read_instances_cfg()
    ov          = _read_runtime_overrides()
    es          = _read_engine_status()
    all_metrics = _read_all_last_metrics()

    if not instances:
        return "⚠ instances.json non disponibile"

    ist_ov     = ov.get("istanze", {})
    ist_status = es.get("istanze", {}) if es else {}
    now        = datetime.now(timezone.utc)

    glob_ov  = ov.get("globali", {})
    adapt_on = bool(glob_ov.get("adaptive_scheduler_enabled", False))
    shadow   = bool(glob_ov.get("adaptive_scheduler_shadow_only", True))
    if adapt_on and not shadow:
        mode_str = "🎯 Adaptive LIVE"
    elif adapt_on and shadow:
        mode_str = "👁 Adaptive SHADOW"
    else:
        mode_str = "📋 Sequenza fissa"

    ciclo_n: object = "?"
    ciclo_start: Optional[datetime] = None
    ciclo_avv_str = ""
    cicli = _read_cicli()
    if cicli:
        ultimo_ciclo = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[0]
        ciclo_n      = ultimo_ciclo.get("numero", ultimo_ciclo.get("cycle_n", "?"))
        ciclo_start  = _parse_dt(ultimo_ciclo.get("start_ts", ""))
        if ciclo_start:
            ciclo_avv_str = ciclo_start.astimezone().strftime("%H:%M")

    live_nome = next(
        (nome for nome, st in ist_status.items() if st.get("stato") == "running"),
        None,
    )

    def _sort_key(cfg: dict) -> str:
        nome = cfg.get("nome", "")
        return all_metrics.get(nome, {}).get("ts", "1970-01-01T00:00:00")

    ordered = sorted(instances, key=_sort_key)

    bot_on  = _check_bot_running()
    bot_str = "🟢 bot attivo" if bot_on else "🔴 bot spento"
    avv_part = f" | avv. {ciclo_avv_str}" if ciclo_avv_str else ""
    lines: list[str] = [
        f"<b>Istanze</b> — ciclo #{ciclo_n}{avv_part} | {mode_str} | {bot_str}",
        "",
    ]

    for idx, cfg in enumerate(ordered, 1):
        nome      = cfg.get("nome", "")
        ov_i      = ist_ov.get(nome, {})
        abilitata = ov_i.get("abilitata", cfg.get("abilitata", True))
        tipologia = ov_i.get("tipologia", cfg.get("profilo", "full"))
        tip_short = {"raccolta_fast": "fast", "raccolta_only": "solo-racc"}.get(tipologia, tipologia)
        on_icon   = "🟢" if abilitata else "🔴"

        mx        = all_metrics.get(nome, {})
        mx_ts     = _parse_dt(mx.get("ts", "")) if mx else None
        mx_out    = mx.get("outcome", "") if mx else ""
        mx_dur_s  = mx.get("tick_total_s", 0) if mx else 0
        out_icon  = {"ok": "✓", "cascade": "⚡", "abort": "✗"}.get(mx_out, "—")
        dur_str   = _fmt_dur(int(mx_dur_s)) if mx_dur_s and mx_dur_s > 0 else "?"

        st = ist_status.get(nome, {})
        if nome == live_nome:
            task_c    = st.get("task_corrente")
            stato_str = "<b>▶ LIVE</b>" + (f" ({task_c})" if task_c else "")
        elif bot_on and ciclo_start and mx_ts and mx_ts >= ciclo_start:
            stato_str = f"{out_icon} {dur_str}"
        elif bot_on:
            stato_str = "⏳ attesa"
        else:
            stato_str = f"{out_icon} {dur_str}"

        lines.append(f"{idx:2}. {on_icon} <b>{nome}</b> [{tip_short}]  {stato_str}")

    return "\n".join(lines)


def _build_ciclo_detail(numero: Optional[int]) -> str:
    cicli = _read_cicli()
    if not cicli:
        return "Nessun ciclo disponibile in data/telemetry/cicli.json"

    if numero is None:
        c = sorted(cicli, key=lambda x: x.get("start_ts", ""), reverse=True)[0]
    else:
        matches = [x for x in cicli if x.get("numero") == numero]
        if not matches:
            nums = sorted({x.get("numero") for x in cicli if x.get("numero")}, reverse=True)
            recenti = ", ".join(f"#{n}" for n in nums[:8])
            return f"⚠ Ciclo #{numero} non trovato.\nDisponibili (recenti): {recenti}"
        c = matches[0]

    n          = c.get("numero", "?")
    completato = c.get("completato", False)
    start_ts   = c.get("start_ts", "")
    end_ts     = c.get("end_ts", "")
    durata_s   = c.get("durata_s", 0)
    istanze    = c.get("istanze", {})
    now        = datetime.now(timezone.utc)

    if not completato:
        dt_start = _parse_dt(start_ts)
        elapsed  = _fmt_dur((now - dt_start).total_seconds()) if dt_start else "?"
        avv_str  = dt_start.astimezone().strftime("%d/%m %H:%M") if dt_start else "?"
        n_done   = sum(1 for v in istanze.values() if v.get("end_ts"))
        n_tot    = len(istanze)
        header   = f"🔄 <b>Ciclo #{n}</b>  —  in corso da {elapsed}\n{avv_str} → in corso  |  {n_done}/{n_tot}"
    else:
        dt_start = _parse_dt(start_ts)
        dt_end   = _parse_dt(end_ts)
        avv_str  = dt_start.astimezone().strftime("%d/%m %H:%M") if dt_start else "?"
        fine_str = dt_end.astimezone().strftime("%H:%M") if dt_end else "?"
        dur_str  = _fmt_dur(durata_s) if durata_s else "?"
        n_ok     = sum(1 for v in istanze.values() if v.get("esito") == "ok")
        n_tot    = len(istanze)
        n_cas    = sum(1 for v in istanze.values() if v.get("esito") == "cascade")
        n_ab     = sum(1 for v in istanze.values() if v.get("esito") == "abort")
        esiti_extra = ("  ⚡" + str(n_cas) if n_cas else "") + ("  ✂" + str(n_ab) if n_ab else "")
        stato_icon  = "✅" if n_ok == n_tot else ("⚠" if n_ok > 0 else "❌")
        header = (
            f"{stato_icon} <b>Ciclo #{n}</b>  —  {dur_str}\n"
            f"{avv_str} → {fine_str}  |  {n_ok}/{n_tot} ok{esiti_extra}"
        )

    _ESITO_ICON = {"ok": "✅", "cascade": "⚡", "abort": "✂", "running": "▶"}
    rows: list[tuple[str, int, str]] = []
    for nome, v in istanze.items():
        d_s  = v.get("durata_s", 0)
        esit = v.get("esito", "?")
        if esit == "running" and v.get("start_ts"):
            dt_i = _parse_dt(v["start_ts"])
            d_s  = int((now - dt_i).total_seconds()) if dt_i else 0
        rows.append((nome, d_s, esit))

    lines: list[str] = [header, "", "<code>Istanza       durata</code>"]
    for nome, d_s, esit in rows:
        icona = _ESITO_ICON.get(esit, "?")
        dur   = _fmt_dur(d_s) if d_s else "—"
        if esit == "running":
            dur += " ▶"
        lines.append(f"<code>{nome:<12} {dur:>6}</code>  {icona}")

    durate = [(nome, d_s) for nome, d_s, esit in rows if d_s > 0 and esit != "running"]
    if len(durate) >= 2:
        mn = min(durate, key=lambda x: x[1])
        mx = max(durate, key=lambda x: x[1])
        lines.append("")
        lines.append(f"min: {mn[0]} {_fmt_dur(mn[1])}  |  max: {mx[0]} {_fmt_dur(mx[1])}")

    return "\n".join(lines)


def _build_cicli() -> str:
    cicli = _read_cicli()
    if not cicli:
        return "Nessun ciclo disponibile in data/telemetry/cicli.json"

    sorted_cicli = sorted(cicli, key=lambda c: c.get("start_ts", ""), reverse=True)[:5]
    lines: list[str] = ["<b>Ultimi cicli</b>"]

    for c in sorted_cicli:
        n          = c.get("numero", "?")
        completato = c.get("completato", False)
        start_ts   = c.get("start_ts", "")
        durata_s   = c.get("durata_s", 0)
        istanze    = c.get("istanze", {})

        avv_str = ""
        if start_ts:
            dt = _parse_dt(start_ts)
            if dt:
                avv_str = dt.astimezone().strftime("%d/%m %H:%M")

        if not completato:
            now = datetime.now(timezone.utc)
            dur_str = ""
            if start_ts:
                dt = _parse_dt(start_ts)
                if dt:
                    dur_str = f" — in corso da {_fmt_dur((now - dt).total_seconds())}"
            n_done  = sum(1 for v in istanze.values() if v.get("esito") not in ("running", None) and v.get("end_ts"))
            n_tot   = len(istanze)
            running = next((k for k, v in istanze.items() if v.get("esito") == "running"), None)
            run_str = f"  ▶ {running}" if running else ""
            lines.append(f"\n🔄 <b>Ciclo #{n}</b>{dur_str}  [{n_done}/{n_tot}]{run_str}")
            if avv_str:
                lines.append(f"   avv. {avv_str}")
        else:
            n_ok      = sum(1 for v in istanze.values() if v.get("esito") == "ok")
            n_cascade = sum(1 for v in istanze.values() if v.get("esito") == "cascade")
            n_abort   = sum(1 for v in istanze.values() if v.get("esito") == "abort")
            n_tot     = len(istanze)
            esiti_str = f"{n_ok}/{n_tot} ok"
            if n_cascade:
                esiti_str += f"  ⚡{n_cascade} cascade"
            if n_abort:
                esiti_str += f"  ✂{n_abort} abort"
            dur_str = _fmt_dur(durata_s) if durata_s else "?"
            lines.append(f"\n✅ <b>Ciclo #{n}</b> — {dur_str}  {esiti_str}")
            if avv_str:
                lines.append(f"   avv. {avv_str}")

    return "\n".join(lines)


def _build_rifornimento() -> str:
    lines: list[str] = ["<b>Rifornimento</b>"]
    lines.append(_fmt_drl_line("DRL FauMorfeus"))

    ov         = _read_runtime_overrides()
    # Usa instances.json come sorgente della lista — runtime_overrides::istanze
    # può essere vuoto ({}) quando nessun override è attivo per-istanza.
    instances  = _read_instances_cfg()
    ist_ov     = ov.get("istanze", {})
    tot_sped   = 0
    righe_ist: list[str] = []
    for cfg in sorted(instances, key=lambda c: c.get("nome", "")):
        nome = cfg.get("nome", "")
        if not nome or nome == "FauMorfeus":
            continue
        # Rispetta abilitata da runtime se presente, altrimenti da static
        abilitata = ist_ov.get(nome, {}).get("abilitata", cfg.get("abilitata", True))
        if not abilitata:
            continue
        st        = _read_state(nome)
        rif       = st.get("rifornimento", {})
        sped_oggi = rif.get("spedizioni_oggi", 0)
        tot_sped += sped_oggi
        if sped_oggi > 0:
            det      = rif.get("dettaglio_oggi", [])
            netto    = sum(v.get("qta_inviata", 0) for v in det) / 1e6
            righe_ist.append(f"  {nome}: {sped_oggi} sped, {netto:.1f}M netti")

    lines.append(f"Spedizioni totali oggi: {tot_sped}")
    if righe_ist:
        lines.extend(righe_ist)
    elif tot_sped == 0:
        lines.append("  (nessuna spedizione ancora oggi)")

    lines.append("")
    lines.append("<b>Config attuale</b>")
    rc  = ov.get("globali", {}).get("rifornimento_comune", {})
    rif = ov.get("globali", {}).get("rifornimento", {})
    mappa_on  = rif.get("mappa_abilitata",  False)
    membri_on = rif.get("membri_abilitati", False)
    if mappa_on and membri_on:
        modo_str = "entrambi"
    elif mappa_on:
        modo_str = "mappa"
    elif membri_on:
        modo_str = "membri"
    else:
        modo_str = "⚠ nessuna"
    lines.append(f"Modalità: {modo_str}")
    ris_labels = [
        ("pomodoro", rc.get("campo_abilitato",    True)),
        ("legno",    rc.get("legno_abilitato",    True)),
        ("acciaio",  rc.get("acciaio_abilitato",  True)),
        ("petrolio", rc.get("petrolio_abilitato", True)),
    ]
    ris_str = "  ".join(f"{'🟢' if on else '🔴'}{r}" for r, on in ris_labels)
    lines.append(f"Risorse: {ris_str}")
    soglie = [
        ("pom", rc.get("soglia_campo_m",    5.0)),
        ("leg", rc.get("soglia_legno_m",    5.0)),
        ("acc", rc.get("soglia_acciaio_m",  3.5)),
        ("pet", rc.get("soglia_petrolio_m", 2.5)),
    ]
    s_str = "  ".join(f"{k}={v:.1f}M" for k, v in soglie)
    lines.append(f"Soglie: {s_str}")
    prov_max = rif.get("provviste_max", 100)
    lines.append(f"Provviste max: {prov_max}M")

    return "\n".join(lines)


def _build_produzione() -> str:
    try:
        from shared.prod_unificata import compute_from_storico, empty_result as _pu_empty
    except Exception as exc:
        return f"⚠ prod_unificata non disponibile: {exc}"

    state_dir = _root() / "state"
    _RICO = {"pomodoro": "🍅", "legno": "🪵", "acciaio": "⚙", "petrolio": "🛢"}

    rows: list[tuple[str, dict]] = []
    farm_pom_eq = 0

    for fp in sorted(state_dir.glob("FAU_*.json")):
        nome    = fp.stem
        d       = _read_state(nome)
        storico = d.get("produzione_storico") or []
        valido  = [s for s in storico if s.get("produzione_qty")]
        pu      = compute_from_storico(valido) if valido else _pu_empty()
        rows.append((nome, pu))
        if pu["prod_unif_h"] > 0:
            farm_pom_eq += pu["pom_eq_totale"]

    if not rows:
        return "⚠ Nessun dato produzione disponibile"

    farm_h = round(farm_pom_eq / 24.0 / 1_000_000, 2) if farm_pom_eq > 0 else -1.0
    rows.sort(key=lambda x: x[1]["prod_unif_h"], reverse=True)

    lines: list[str] = ["<b>📊 Produzione unificata — 24h</b>", ""]
    for nome, pu in rows:
        h  = pu["prod_unif_h"]
        ns = pu.get("n_sessioni", pu.get("n_sped", 0))
        pr = pu.get("per_risorsa") or {}
        if h > 0:
            det = "  ".join(
                f"{_RICO.get(r,'?')}{pr[r]['qta_tot'] / 1e6:.1f}M"
                for r in ("pomodoro", "legno", "acciaio", "petrolio")
                if r in pr and pr[r].get("qta_tot", 0) > 0
            )
            lines.append(
                f"<code>{nome:12s}</code> <b>{h:.2f}</b> M/h"
                + (f"  <i>({det})</i>" if det else "")
                + f"  [{ns}s]"
            )
        else:
            lines.append(f"<code>{nome:12s}</code> —  (nessuna sessione)")

    lines.append("")
    if farm_h >= 0:
        lines.append(f"<b>Farm totale: {farm_h:.2f} M pom-eq/h</b>")
    else:
        lines.append("Farm totale: nessun dato")
    lines.append("<i>🍅×1 🪵×1 ⚙×2 🛢×5 · delta deposito 24h</i>")

    return "\n".join(lines)


def _build_istanza_detail(nome: str) -> str:
    instances    = _read_instances_cfg()
    cfg_map      = {c["nome"]: c for c in instances}
    cfg_map_low  = {k.lower(): k for k in cfg_map}
    nome_resolved = cfg_map_low.get(nome.lower())
    if not nome_resolved:
        available = ", ".join(sorted(cfg_map.keys()))
        return f"⚠ Istanza <code>{nome}</code> non trovata.\nDisponibili: {available}"
    nome = nome_resolved

    cfg  = cfg_map[nome]
    ov   = _read_runtime_overrides()
    ov_i = ov.get("istanze", {}).get(nome, {})

    abilitata = ov_i.get("abilitata", cfg.get("abilitata", True))
    tipologia = ov_i.get("tipologia", cfg.get("profilo", "full"))
    max_sq    = ov_i.get("max_squadre", cfg.get("max_squadre", "?"))
    livello   = ov_i.get("livello", cfg.get("livello", "?"))
    on_icon   = "🟢" if abilitata else "🔴"
    tip_short = {"raccolta_fast": "fast", "raccolta_only": "solo-racc"}.get(tipologia, tipologia)

    lines: list[str] = [f"{on_icon} <b>{nome}</b> [{tip_short}]  sq={max_sq}  lv={livello}"]

    es       = _read_engine_status()
    ist_live = (es.get("istanze", {}) if es else {}).get(nome, {})
    stato    = ist_live.get("stato", "")
    task_c   = ist_live.get("task_corrente")
    if stato == "running":
        lines.append("▶ <b>LIVE</b>" + (f" — {task_c}" if task_c else ""))

    mx = _read_last_metrics(nome)
    if mx:
        outcome  = mx.get("outcome", "")
        boot_s   = mx.get("boot_home_s", 0)
        tick_s   = mx.get("tick_total_s", 0)
        out_icon = {"ok": "✓", "cascade": "⚡", "abort": "✗"}.get(outcome, "—")
        lines.append(
            f"\n🔄 <b>Ultimo ciclo</b>: {out_icon} {outcome}"
            + (f"  durata {_fmt_dur(tick_s)}" if tick_s else "")
            + (f"  boot {_fmt_dur(boot_s)}" if boot_s else "")
        )
        racc       = mx.get("raccolta", {})
        invii_list = racc.get("invii", [])
        n_invii    = len(invii_list)
        att_pre    = racc.get("attive_pre", "?")
        att_post   = racc.get("attive_post", "?")
        tot        = racc.get("totali", "?")
        if n_invii or att_pre != "?":
            tipi = {}
            for inv in invii_list:
                t = inv.get("tipo", "?")
                tipi[t] = tipi.get(t, 0) + 1
            tipi_str = " ".join(f"{v}×{k}" for k, v in tipi.items()) if tipi else "0 marce"
            lines.append(
                f"\n📦 <b>Raccolta</b>: {n_invii} marce  [{tipi_str}]"
                f"\n   slot: {att_pre}→{att_post}/{tot}"
            )
        td = mx.get("task_durations_s", {})
        if td:
            sorted_td = sorted(td.items(), key=lambda x: -x[1])[:6]
            td_str    = "  ".join(f"{k} {_fmt_dur(v)}" for k, v in sorted_td)
            lines.append(f"\n⏱ <b>Task</b>: {td_str}")

    st  = _read_state(nome)
    rif = st.get("rifornimento", {})
    sped = rif.get("spedizioni_oggi", 0)
    if sped or nome != "FauMorfeus":
        inv_oggi = rif.get("inviato_oggi", {})
        _RES     = [("pomodoro","🍅"),("legno","🪵"),("acciaio","⚙"),("petrolio","🛢")]
        tot_m    = sum(inv_oggi.values()) / 1e6 if inv_oggi else 0
        res_str  = "  ".join(
            f"{icon}{v/1e6:.1f}M" for r, icon in _RES
            if (v := inv_oggi.get(r, 0)) > 0
        ) if inv_oggi else "—"
        prov     = rif.get("provviste_residue", -1)
        prov_str = f"  provviste {prov/1e6:.1f}M" if prov >= 0 else ""
        lines.append(
            f"\n🚚 <b>Rifornimento</b>: {sped} sped  {tot_m:.1f}M netti{prov_str}"
            + (f"\n   {res_str}" if res_str != "—" else "")
        )

    arena = st.get("arena", {})
    if arena:
        esaurite = arena.get("esaurite", False)
        lines.append(f"\n🏟 <b>Arena</b>: {'✓ esaurita' if esaurite else '⏳ disponibile'}")

    tr_list = _read_truppe_storico(nome)
    if tr_list:
        last_tr  = tr_list[-1]
        squads   = last_tr.get("total_squads", 0)
        delta    = 0
        if len(tr_list) >= 2:
            delta = squads - tr_list[-2].get("total_squads", squads)
        delta_str = f"  Δ{delta:+,}" if delta else ""
        lines.append(f"\n🪖 <b>Truppe</b>: {squads:,}{delta_str}")

    met = st.get("metrics", {})
    _RES_KEYS = [("pomodoro","🍅"),("legno","🪵"),("acciaio","⚙"),("petrolio","🛢")]
    prod_parts = []
    for r, icon in _RES_KEYS:
        val = met.get(f"{r}_per_ora", 0)
        if val and abs(val) > 100:
            sign = "+" if val > 0 else ""
            prod_parts.append(f"{icon}{sign}{val/1e3:.0f}K/h")
    if prod_parts:
        lines.append(f"\n📈 <b>Prod/h</b>: {' '.join(prod_parts)}")

    return "\n".join(lines)


# ─── Handler functions (signature: text -> str) ───────────────────────────────

def cmd_status(text: str) -> str:
    try:
        return _build_status()
    except Exception as exc:
        return f"⚠ Errore /status: {exc}"


def cmd_istanze(text: str) -> str:
    try:
        return _build_istanze()
    except Exception as exc:
        return f"⚠ Errore /istanze: {exc}"


def cmd_produzione(text: str) -> str:
    try:
        return _build_produzione()
    except Exception as exc:
        return f"⚠ Errore /produzione: {exc}"


def cmd_rifornimento(text: str) -> str:
    try:
        return _build_rifornimento()
    except Exception as exc:
        return f"⚠ Errore /rifornimento: {exc}"


def cmd_cicli(text: str) -> str:
    try:
        return _build_cicli()
    except Exception as exc:
        return f"⚠ Errore /cicli: {exc}"


def cmd_ciclo(text: str) -> str:
    parts  = text.split()
    numero = None
    if len(parts) > 1:
        raw = parts[1].lstrip("#")
        try:
            numero = int(raw)
        except ValueError:
            return "⚠ Uso: /ciclo [N]  Es: /ciclo 184  oppure /ciclo per il più recente"
    try:
        return _build_ciclo_detail(numero)
    except Exception as exc:
        return f"⚠ Errore /ciclo: {exc}"


def cmd_istanza(text: str) -> str:
    parts = text.split()
    if len(parts) < 2:
        return "⚠ Uso: /istanza NOME  (es. /istanza FAU_03)"
    nome = parts[1].upper()
    try:
        return _build_istanza_detail(nome)
    except Exception as exc:
        return f"⚠ Errore /istanza: {exc}"


# ─── /depositi ────────────────────────────────────────────────────────────────

_RES_ICONS = [("pomodoro", "🍅"), ("legno", "🪵"), ("acciaio", "⚙"), ("petrolio", "🛢")]


def _build_depositi() -> str:
    """Mostra i depositi (risorse nel castello) di tutte le istanze ordinarie."""
    instances = _read_instances_cfg()
    now       = datetime.now(timezone.utc)

    rows: list[tuple[str, dict, str]] = []   # (nome, risorse, ts_str)
    totali: dict[str, float] = {}

    for cfg in sorted(instances, key=lambda c: c.get("nome", "")):
        nome = cfg.get("nome", "")
        if not nome or nome == "FauMorfeus":
            continue

        st    = _read_state(nome)
        ris   = None
        ts_s  = ""

        # 1. Sessione corrente (risorse_iniziali della sessione in corso)
        pc = st.get("produzione_corrente", {})
        if pc.get("risorse_iniziali"):
            ris  = pc["risorse_iniziali"]
            ts_i = _parse_dt(pc.get("ts_inizio", ""))
            if ts_i:
                ago   = int((now - ts_i).total_seconds())
                ts_s  = f"{_fmt_dur(ago)} fa"

        # 2. Fallback: ultima sessione completata
        if not ris:
            storico = st.get("produzione_storico", [])
            if storico:
                ult  = storico[-1]
                ris  = ult.get("risorse_finali") or ult.get("risorse_iniziali")
                ts_f = _parse_dt(ult.get("ts_fine") or ult.get("ts_inizio") or "")
                if ts_f:
                    ago   = int((now - ts_f).total_seconds())
                    ts_s  = f"{_fmt_dur(ago)} fa"

        if not ris:
            rows.append((nome, {}, "—"))
            continue

        rows.append((nome, ris, ts_s))
        for res, _ in _RES_ICONS:
            totali[res] = totali.get(res, 0) + ris.get(res, 0)

    if not rows:
        return "⚠ Nessun dato depositi disponibile"

    lines: list[str] = ["<b>💰 Depositi farm</b>", ""]

    for nome, ris, ts_s in rows:
        if not ris:
            lines.append(f"<code>{nome:<12}</code> — n/d")
            continue
        res_parts = [
            f"{icon}{ris.get(res, 0)/1e6:.1f}M"
            for res, icon in _RES_ICONS
            if ris.get(res, 0) > 0
        ]
        ts_note = f"  <i>({ts_s})</i>" if ts_s else ""
        lines.append(f"<code>{nome:<12}</code> {' '.join(res_parts)}{ts_note}")

    # Totali
    lines.append("")
    lines.append("<b>Totale farm</b>")
    tot_parts = [
        f"{icon}<b>{totali.get(res, 0)/1e6:.1f}M</b>"
        for res, icon in _RES_ICONS
        if totali.get(res, 0) > 0
    ]
    lines.append("  " + "  ".join(tot_parts))

    return "\n".join(lines)


def cmd_depositi(text: str) -> str:
    try:
        return _build_depositi()
    except Exception as exc:
        return f"⚠ Errore /depositi: {exc}"
