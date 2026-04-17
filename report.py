#!/usr/bin/env python3
r"""
DOOMSDAY ENGINE V6 — Report statistiche notturne
Uso: python report.py [--log-dir C:\\doomsday-engine\logs] [--out report.html]
r"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# PARSING
# ─────────────────────────────────────────────

def parse_bot_log(path: Path) -> list[dict]:
    """Legge bot.log e ritorna lista di eventi MAIN/LAUNCHER.r"""
    eventi = []
    pat = re.compile(r'^\[(\\d{2}:\\d{2}:\\d{2})\] (\S+) (.+)$')
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            m = pat.match(line)
            if m:
                eventi.append({
                    'time': m.group(1),
                    'source': m.group(2),
                    'msg': m.group(3)
                })
    except FileNotFoundError:
        pass
    return eventi

def parse_jsonl(path: Path) -> list[dict]:
    """Legge FAU_XX.jsonl e ritorna lista di record.r"""
    records = []
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return records

def hms_to_sec(hms: str) -> int:
    h, m, s = hms.split(':')
    return int(h)*3600 + int(m)*60 + int(s)

# ─────────────────────────────────────────────
# ANALISI
# ─────────────────────────────────────────────

def analizza_istanza(nome: str, records: list[dict], eventi_bot: list[dict]) -> dict:
    """Estrae statistiche per una singola istanza.r"""
    
    # --- Tick timing ---
    tick_starts = []
    tick_ends = []
    for e in eventi_bot:
        if e['source'] == nome:
            if 'Tick --' in e['msg']:
                tick_starts.append(e['time'])
            elif 'Tick completato' in e['msg']:
                tick_ends.append(e['msg'])
    
    tick_durate = []
    n_tick = len(tick_ends)
    
    # --- Task stats da jsonl ---
    task_eseguiti = defaultdict(lambda: {'ok': 0, 'fail': 0, 'skip': 0})
    errori = []
    marce = {'inviate': 0, 'fallite': 0, 'fuori_territorio': 0}
    screenshot_none = 0
    
    for r in records:
        msg = r.get('message', r.get('msg', ''))
        modulo = r.get('module', '')
        
        # Screenshot None
        if 'screenshot None' in msg or 'Screenshot fallito' in msg:
            screenshot_none += 1
        
        # Errori
        if 'ERRORE' in msg or 'fallito' in msg.lower() or 'error' in msg.lower():
            if 'screenshot' not in msg.lower():
                errori.append(msg[:120])
        
        # Task completati
        m = re.search(r"task '(\w+)' completato -- success=(True|False)", msg)
        if m:
            task_name = m.group(1)
            success = m.group(2) == 'True'
            if success:
                task_eseguiti[task_name]['ok'] += 1
            else:
                task_eseguiti[task_name]['fail'] += 1
        
        # Task saltati
        m = re.search(r"\[(\w+)\] should_run=False", msg)
        if m:
            task_eseguiti[m.group(1).lower()]['skip'] += 1
        
        # Marce raccolta
        if 'marcia OK' in msg:
            marce['inviate'] += 1
        if 'marcia FALLITA' in msg or 'ROLLBACK' in msg:
            marce['fallite'] += 1
        if 'FUORI territorio' in msg or 'fuori territorio' in msg:
            marce['fuori_territorio'] += 1
        if 'troppi fallimenti' in msg:
            marce['fallite'] += 1
    
    # Slot medi da raccolta
    slot_readings = []
    for r in records:
        msg = r.get('message', r.get('msg', ''))
        m = re.search(r'slot OCR.*attive=(\\d+)/(\\d+)', msg)
        if m:
            slot_readings.append((int(m.group(1)), int(m.group(2))))
    
    return {
        'nome': nome,
        'n_tick': n_tick,
        'task_eseguiti': dict(task_eseguiti),
        'errori': errori[:20],  # max 20
        'marce': marce,
        'screenshot_none': screenshot_none,
        'slot_readings': slot_readings,
    }

def analizza_launcher(eventi: list[dict]) -> dict:
    """Estrae statistiche launcher da bot.log.r"""
    avvii = defaultdict(int)
    chiusure = defaultdict(int)
    errori_launcher = []
    
    for e in eventi:
        src = e['source']
        msg = e['msg']
        if 'istanza' in msg and 'avviata OK' in msg:
            avvii[src] += 1
        if 'istanza' in msg and 'chiusa' in msg and 'LAUNCHER' not in src:
            chiusure[src] += 1
        if '[ERRORE]' in msg or 'TIMEOUT' in msg:
            errori_launcher.append(f"{src}: {msg[:100]}")
    
    return {
        'avvii': dict(avvii),
        'chiusure': dict(chiusure),
        'errori': errori_launcher[:15],
    }

# ─────────────────────────────────────────────
# HTML GENERATION
# ─────────────────────────────────────────────

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DOOMSDAY ENGINE V6 — Report {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;600;900&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #0a0c10;
  --bg2: #0f1318;
  --bg3: #141922;
  --border: #1e2a3a;
  --accent: #00d4ff;
  --accent2: #ff6b35;
  --green: #00ff88;
  --red: #ff3355;
  --yellow: #ffd700;
  --text: #c8d8e8;
  --text-dim: #5a7a8a;
  --glow: 0 0 20px rgba(0,212,255,0.3);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: 'Exo 2', sans-serif;
  font-weight: 300;
  min-height: 100vh;
  overflow-x: hidden;
}}
body::before {{
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: 
    repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,212,255,0.015) 2px, rgba(0,212,255,0.015) 4px);
  pointer-events: none;
  z-index: 0;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 40px 24px; position: relative; z-index: 1; }}

/* HEADER */
.header {{
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 48px; padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}}
.header-left h1 {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 28px; font-weight: 400;
  color: var(--accent);
  text-shadow: var(--glow);
  letter-spacing: 3px;
  text-transform: uppercase;
}}
.header-left .subtitle {{
  font-size: 12px; color: var(--text-dim);
  letter-spacing: 4px; margin-top: 6px;
  text-transform: uppercase;
}}
.header-right {{
  text-align: right;
  font-family: 'Share Tech Mono', monospace;
  font-size: 13px; color: var(--text-dim);
  line-height: 1.8;
}}
.header-right .ts {{ color: var(--accent); font-size: 15px; }}

/* SUMMARY BAR */
.summary-bar {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px; margin-bottom: 40px;
}}
.stat-card {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-top: 2px solid var(--accent);
  padding: 20px 24px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s;
}}
.stat-card::after {{
  content: '';
  position: absolute; top: 0; right: 0;
  width: 60px; height: 60px;
  background: radial-gradient(circle at top right, rgba(0,212,255,0.08), transparent);
}}
.stat-card.warn {{ border-top-color: var(--yellow); }}
.stat-card.warn::after {{ background: radial-gradient(circle at top right, rgba(255,215,0,0.08), transparent); }}
.stat-card.danger {{ border-top-color: var(--red); }}
.stat-card.danger::after {{ background: radial-gradient(circle at top right, rgba(255,51,85,0.08), transparent); }}
.stat-card.ok {{ border-top-color: var(--green); }}
.stat-card.ok::after {{ background: radial-gradient(circle at top right, rgba(0,255,136,0.08), transparent); }}
.stat-label {{ font-size: 10px; letter-spacing: 3px; text-transform: uppercase; color: var(--text-dim); margin-bottom: 10px; }}
.stat-value {{ font-family: 'Share Tech Mono', monospace; font-size: 36px; color: var(--text); }}
.stat-sub {{ font-size: 11px; color: var(--text-dim); margin-top: 4px; }}

/* SECTIONS */
.section {{ margin-bottom: 40px; }}
.section-title {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 11px; letter-spacing: 5px;
  text-transform: uppercase; color: var(--accent);
  margin-bottom: 16px;
  display: flex; align-items: center; gap: 12px;
}}
.section-title::after {{
  content: ''; flex: 1; height: 1px;
  background: linear-gradient(to right, var(--border), transparent);
}}

/* ISTANZA GRID */
.istanze-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 24px;
}}
.istanza-card {{
  background: var(--bg2);
  border: 1px solid var(--border);
  padding: 0;
  overflow: hidden;
}}
.istanza-header {{
  background: var(--bg3);
  padding: 16px 20px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}}
.istanza-name {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 16px; color: var(--accent);
  letter-spacing: 2px;
}}
.istanza-ticks {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 12px; color: var(--text-dim);
}}
.istanza-body {{ padding: 20px; }}

/* TASK TABLE */
.task-table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 20px; }}
.task-table th {{
  text-align: left; padding: 6px 8px;
  font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
  color: var(--text-dim); border-bottom: 1px solid var(--border);
}}
.task-table td {{ padding: 7px 8px; border-bottom: 1px solid rgba(30,42,58,0.5); }}
.task-table tr:last-child td {{ border-bottom: none; }}
.task-table tr:hover td {{ background: rgba(0,212,255,0.03); }}
.task-name {{ font-family: 'Share Tech Mono', monospace; color: var(--text); }}
.badge {{
  display: inline-block; padding: 2px 8px;
  font-family: 'Share Tech Mono', monospace; font-size: 10px;
  border-radius: 2px; font-weight: 600;
}}
.badge-ok {{ background: rgba(0,255,136,0.15); color: var(--green); }}
.badge-fail {{ background: rgba(255,51,85,0.15); color: var(--red); }}
.badge-skip {{ background: rgba(90,122,138,0.15); color: var(--text-dim); }}
.badge-zero {{ background: rgba(30,42,58,0.5); color: var(--border); }}

/* MARCE */
.marce-row {{
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 12px; margin-bottom: 20px;
}}
.marce-cell {{
  background: var(--bg3);
  padding: 12px 16px;
  text-align: center;
}}
.marce-val {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 28px;
}}
.marce-lbl {{ font-size: 9px; letter-spacing: 2px; color: var(--text-dim); text-transform: uppercase; margin-top: 4px; }}
.val-green {{ color: var(--green); }}
.val-red {{ color: var(--red); }}
.val-yellow {{ color: var(--yellow); }}

/* ERRORI */
.errori-list {{
  list-style: none;
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px;
  line-height: 1.7;
  max-height: 160px;
  overflow-y: auto;
  background: var(--bg3);
  padding: 12px 16px;
}}
.errori-list li {{ color: var(--red); opacity: 0.8; padding: 2px 0; }}
.errori-list li::before {{ content: '! '; color: var(--red); }}
.no-errori {{ color: var(--green); font-family: 'Share Tech Mono', monospace; font-size: 11px; }}

/* SLOT CHART */
.slot-bar {{ margin-bottom: 8px; }}
.slot-label {{ font-size: 10px; color: var(--text-dim); margin-bottom: 4px; }}
.slot-track {{
  height: 6px; background: var(--bg3);
  border-radius: 3px; overflow: hidden;
}}
.slot-fill {{
  height: 100%; border-radius: 3px;
  background: linear-gradient(to right, var(--accent), var(--green));
  transition: width 0.3s;
}}

/* LAUNCHER SECTION */
.launcher-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}}
.launcher-item {{
  background: var(--bg2); border: 1px solid var(--border);
  padding: 16px 20px;
}}
.launcher-name {{ font-family: 'Share Tech Mono', monospace; font-size: 13px; color: var(--accent); margin-bottom: 8px; }}
.launcher-stat {{ font-size: 11px; color: var(--text-dim); display: flex; justify-content: space-between; padding: 3px 0; }}
.launcher-stat span {{ color: var(--text); font-family: 'Share Tech Mono', monospace; }}

/* ERRORI GLOBALI */
.global-errori {{
  background: var(--bg2); border: 1px solid var(--border);
  border-left: 3px solid var(--red);
  padding: 20px;
}}
.errore-line {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 11px; color: var(--red);
  opacity: 0.8; padding: 4px 0;
  border-bottom: 1px solid rgba(255,51,85,0.1);
}}
.errore-line:last-child {{ border-bottom: none; }}

/* FOOTER */
.footer {{
  margin-top: 60px; padding-top: 20px;
  border-top: 1px solid var(--border);
  text-align: center;
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: var(--text-dim);
  letter-spacing: 2px;
}}

/* SCROLLBAR */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: var(--bg3); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}

@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.section {{ animation: fadeIn 0.4s ease both; }}
.section:nth-child(2) {{ animation-delay: 0.1s; }}
.section:nth-child(3) {{ animation-delay: 0.2s; }}
.section:nth-child(4) {{ animation-delay: 0.3s; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <div class="header-left">
    <h1>&#9888; Doomsday Engine V6</h1>
    <div class="subtitle">Night Run Report &mdash; Analisi automatica log</div>
  </div>
  <div class="header-right">
    <div class="ts">{date}</div>
    <div>Generato: {generated}</div>
    <div>Istanze: {n_istanze}</div>
    <div>Log: {log_file}</div>
  </div>
</div>

<!-- SUMMARY BAR -->
<div class="summary-bar">
  <div class="stat-card ok">
    <div class="stat-label">Tick Totali</div>
    <div class="stat-value">{total_tick}</div>
    <div class="stat-sub">su tutte le istanze</div>
  </div>
  <div class="stat-card ok">
    <div class="stat-label">Marce Inviate</div>
    <div class="stat-value">{total_marce}</div>
    <div class="stat-sub">raccolta risorse</div>
  </div>
  <div class="stat-card {errori_class}">
    <div class="stat-label">Errori Totali</div>
    <div class="stat-value">{total_errori}</div>
    <div class="stat-sub">anomalie rilevate</div>
  </div>
  <div class="stat-card warn">
    <div class="stat-label">Screenshot None</div>
    <div class="stat-value">{total_screenshot_none}</div>
    <div class="stat-sub">frame persi ADB</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Task Eseguiti</div>
    <div class="stat-value">{total_task_ok}</div>
    <div class="stat-sub">completati con successo</div>
  </div>
</div>

<!-- ISTANZE -->
<div class="section">
  <div class="section-title">Dettaglio per Istanza</div>
  <div class="istanze-grid">
    {istanze_html}
  </div>
</div>

<!-- LAUNCHER -->
<div class="section">
  <div class="section-title">Statistiche Launcher</div>
  <div class="launcher-grid">
    {launcher_html}
  </div>
</div>

<!-- ERRORI GLOBALI LAUNCHER -->
{errori_launcher_html}

<div class="footer">
  DOOMSDAY ENGINE V6 &mdash; REPORT AUTOMATICO &mdash; NESSUN INTERVENTO UMANO RICHIESTO
</div>

</div>
</body>
</html>'''

def genera_istanza_html(stats: dict) -> str:
    nome = stats['nome']
    n_tick = stats['n_tick']
    marce = stats['marce']
    errori = stats['errori']
    screenshot_none = stats['screenshot_none']
    slot_readings = stats['slot_readings']
    
    # Task table
    task_rows = ''
    task_order = ['boost','vip','messaggi','alleanza','store','arena','arena_mercato',
                  'zaino','radar','radar_census','rifornimento','raccolta']
    all_tasks = set(stats['task_eseguiti'].keys()) | set(task_order)
    
    for t in task_order:
        if t not in all_tasks:
            continue
        d = stats['task_eseguiti'].get(t, {'ok': 0, 'fail': 0, 'skip': 0})
        ok = d.get('ok', 0)
        fail = d.get('fail', 0)
        skip = d.get('skip', 0)
        
        ok_b = f'<span class="badge badge-ok">{ok}</span>' if ok else '<span class="badge badge-zero">0</span>'
        fail_b = f'<span class="badge badge-fail">{fail}</span>' if fail else '<span class="badge badge-zero">0</span>'
        skip_b = f'<span class="badge badge-skip">{skip}</span>' if skip else '<span class="badge badge-zero">0</span>'
        
        task_rows += f'''
        <tr>
          <td class="task-name">{t}</td>
          <td>{ok_b}</td>
          <td>{fail_b}</td>
          <td>{skip_b}</td>
        </tr>'''
    
    # Slot chart
    slot_html = ''
    if slot_readings:
        avg_attive = sum(r[0] for r in slot_readings) / len(slot_readings)
        max_slot = slot_readings[0][1] if slot_readings else 5
        pct = int((avg_attive / max_slot) * 100) if max_slot else 0
        slot_html = f'''
        <div style="margin-bottom:20px">
          <div class="slot-label">Slot medi occupati: {avg_attive:.1f}/{max_slot} (media su {len(slot_readings)} letture)</div>
          <div class="slot-track"><div class="slot-fill" style="width:{pct}%"></div></div>
        </div>'''
    
    # Errori
    if errori:
        err_items = ''.join(f'<li>{e}</li>' for e in errori[:10])
        errori_html = f'<ul class="errori-list">{err_items}</ul>'
    else:
        errori_html = '<div class="no-errori">&#10003; Nessun errore rilevato</div>'
    
    scr_color = 'val-yellow' if screenshot_none > 5 else ('val-red' if screenshot_none > 20 else 'val-green')
    
    return f'''
    <div class="istanza-card">
      <div class="istanza-header">
        <div class="istanza-name">{nome}</div>
        <div class="istanza-ticks">{n_tick} tick completati</div>
      </div>
      <div class="istanza-body">
        
        <div class="marce-row">
          <div class="marce-cell">
            <div class="marce-val val-green">{marce["inviate"]}</div>
            <div class="marce-lbl">Marce Inviate</div>
          </div>
          <div class="marce-cell">
            <div class="marce-val val-red">{marce["fallite"]}</div>
            <div class="marce-lbl">Fallite</div>
          </div>
          <div class="marce-cell">
            <div class="marce-val val-yellow">{marce["fuori_territorio"]}</div>
            <div class="marce-lbl">Fuori Territorio</div>
          </div>
        </div>
        
        {slot_html}
        
        <table class="task-table">
          <thead><tr>
            <th>Task</th><th>OK</th><th>Fail</th><th>Skip</th>
          </tr></thead>
          <tbody>{task_rows}</tbody>
        </table>
        
        <div style="margin-bottom:12px">
          <div class="slot-label">Screenshot persi: <span class="{scr_color}" style="font-family:Share Tech Mono,monospace">{screenshot_none}</span></div>
        </div>
        
        <div class="slot-label" style="margin-bottom:8px">Anomalie e Errori</div>
        {errori_html}
        
      </div>
    </div>'''

def genera_launcher_html(launcher: dict, istanze: list[str]) -> str:
    items = ''
    all_src = set(launcher['avvii'].keys()) | set(launcher['chiusure'].keys()) | set(istanze)
    for src in sorted(all_src):
        if src in ('MAIN',):
            continue
        avvii = launcher['avvii'].get(src, 0)
        chiusure = launcher['chiusure'].get(src, 0)
        items += f'''
        <div class="launcher-item">
          <div class="launcher-name">{src}</div>
          <div class="launcher-stat">Avvii <span>{avvii}</span></div>
          <div class="launcher-stat">Chiusure <span>{chiusure}</span></div>
          <div class="launcher-stat">Bilanciato <span>{"&#10003;" if avvii == chiusure else "&#9888;"}</span></div>
        </div>'''
    return items

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Doomsday Engine V6 — Report notturno')
    ap.add_argument('--log-dir', default='.', help='Directory dei log (default: .)')
    ap.add_argument('--out', default='report.html', help='File output HTML')
    args = ap.parse_args()
    
    log_dir = Path(args.log_dir)
    bot_log = log_dir / 'bot.log'
    
    print(f"[REPORT] Lettura log da: {log_dir}")
    
    # Leggi bot.log
    eventi = parse_bot_log(bot_log)
    print(f"[REPORT] bot.log: {len(eventi)} eventi")
    
    # Trova istanze da jsonl
    jsonl_files = list(log_dir.glob('*.jsonl'))
    istanze_nomi = [f.stem for f in jsonl_files]
    print(f"[REPORT] Istanze trovate: {istanze_nomi}")
    
    # Analisi per istanza
    stats_list = []
    for jsonl_file in sorted(jsonl_files):
        nome = jsonl_file.stem
        records = parse_jsonl(jsonl_file)
        print(f"[REPORT] {nome}: {len(records)} record jsonl")
        stats = analizza_istanza(nome, records, eventi)
        stats_list.append(stats)
    
    # Analisi launcher
    launcher = analizza_launcher(eventi)
    
    # Totali
    total_tick = sum(s['n_tick'] for s in stats_list)
    total_marce = sum(s['marce']['inviate'] for s in stats_list)
    total_errori = sum(len(s['errori']) for s in stats_list)
    total_screenshot_none = sum(s['screenshot_none'] for s in stats_list)
    total_task_ok = sum(
        sum(v.get('ok', 0) for v in s['task_eseguiti'].values())
        for s in stats_list
    )
    
    errori_class = 'danger' if total_errori > 20 else ('warn' if total_errori > 5 else 'ok')
    
    # HTML
    istanze_html = '\n'.join(genera_istanza_html(s) for s in stats_list)
    launcher_html = genera_launcher_html(launcher, istanze_nomi)
    
    errori_launcher_html = ''
    if launcher['errori']:
        items = ''.join(f'<div class="errore-line">{e}</div>' for e in launcher['errori'])
        errori_launcher_html = f'''
        <div class="section">
          <div class="section-title">Errori Launcher</div>
          <div class="global-errori">{items}</div>
        </div>'''
    
    now = datetime.now()
    html = HTML_TEMPLATE.format(
        date=now.strftime('%d/%m/%Y'),
        generated=now.strftime('%H:%M:%S'),
        n_istanze=len(stats_list),
        log_file=str(bot_log),
        total_tick=total_tick,
        total_marce=total_marce,
        total_errori=total_errori,
        total_screenshot_none=total_screenshot_none,
        total_task_ok=total_task_ok,
        errori_class=errori_class,
        istanze_html=istanze_html,
        launcher_html=launcher_html,
        errori_launcher_html=errori_launcher_html,
    )
    
    out_path = Path(args.out)
    out_path.write_text(html, encoding='utf-8')
    print(f"[REPORT] Report generato: {out_path.resolve()}")
    print(f"[REPORT] Apri nel browser: file:///{out_path.resolve()}")

if __name__ == '__main__':
    main()
