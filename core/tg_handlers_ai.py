"""core/tg_handlers_ai.py — Handler AI per il Telegram bot.

Due comandi:
  /claude <domanda>  — usa Claude Code CLI installato sulla macchina (abbonamento)
  /haiku  <domanda>  — usa Claude Haiku API pay-per-use con contesto MCP live

Il contesto iniettato in entrambi i casi è costruito da monitor/analyzer.py:
  - ciclo corrente (numero, stato, istanza live)
  - anomalie recenti (ultimi 30 minuti)
  - DRL master + spedizioni
  - produzione/ora farm
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_ROOT_PROD = Path(os.environ.get("DOOMSDAY_ROOT",
                  Path(__file__).resolve().parents[1]))


# ==============================================================================
# Context builder — usa monitor/analyzer.py direttamente (zero overhead)
# ==============================================================================

def _build_context() -> str:
    """Costruisce il contesto live della farm da iniettare nel prompt AI."""
    try:
        import sys
        root = str(_ROOT_PROD.parent if _ROOT_PROD.name == "core" else _ROOT_PROD)
        # Aggiunge root del progetto al path se non presente
        proj_root = str(Path(__file__).resolve().parents[1])
        if proj_root not in sys.path:
            sys.path.insert(0, proj_root)

        from monitor.analyzer import stato_ciclo_completo, farm_stato, rileva_anomalie, leggi_jsonl_da
        from datetime import datetime, timezone, timedelta

        root_prod = str(_ROOT_PROD)

        # 1. Ciclo corrente
        ciclo = stato_ciclo_completo(root_prod)
        ciclo_n   = ciclo.get("ciclo_n", "?")
        ciclo_ok  = "completato" if ciclo.get("completato") else "in corso"
        ts_str    = str(ciclo.get("ciclo_start_ts", ""))[:16]

        ist_lines = []
        for nome, d in ciclo.get("istanze", {}).items():
            esito = d.get("esito", "attesa")
            task_live = d.get("task_corrente")
            racc = d.get("raccolta", {})
            tasks = d.get("tasks", {})
            parts = [f"{esito}"]
            if task_live:
                parts.append(f"→{task_live}")
            if racc.get("inviate"):
                parts.append(f"marce={racc['inviate']}")
            if racc.get("slot_pieni"):
                parts.append("slot_pieni")
            if tasks:
                fail_tasks = [k for k, v in tasks.items() if v == "FAIL"]
                if fail_tasks:
                    parts.append(f"FAIL={fail_tasks}")
            ist_lines.append(f"  {nome}: {' '.join(parts)}")

        # 2. Farm stato (DRL, spedizioni, produzione)
        farm = farm_stato(root_prod)
        master = farm.get("master", {})
        drl_str = (f"DRL={master.get('drl_residuo_m')}M/{master.get('drl_max_m')}M "
                   f"({master.get('drl_pct')}%) tassa={master.get('tassa_pct')}%"
                   if master else "DRL: n/d")
        sped_str = f"Spedizioni oggi: {farm.get('spedizioni_totali', 0)}"
        inv = farm.get("inviato_totale_m", {})
        inv_str = "  ".join(f"{k}={v}M" for k, v in inv.items()) if inv else "—"
        prod = farm.get("farm_prod_h_m", {})
        prod_str = "  ".join(f"{k}={v}" for k, v in prod.items()) if prod else "—"

        # 3. Anomalie ultimi 30 min
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        anomalie_tot: list[str] = []
        logs_dir = os.path.join(root_prod, "logs")
        for fn in os.listdir(logs_dir):
            if not fn.endswith(".jsonl"):
                continue
            nome_ist = fn[:-6]
            righe = leggi_jsonl_da(os.path.join(logs_dir, fn), da_ts=cutoff)
            anomalie = rileva_anomalie(righe)
            for a in anomalie[-3:]:
                anomalie_tot.append(
                    f"  [{str(a['ts'])[:16]}] {a['severita']} {nome_ist}: {a['msg'][:80]}"
                )

        anom_str = "\n".join(anomalie_tot[-10:]) if anomalie_tot else "  (nessuna)"

        return f"""[DOOMSDAY ENGINE V6 — CONTESTO LIVE {datetime.now().strftime('%H:%M')}]

CICLO {ciclo_n} — {ciclo_ok} (avv. {ts_str})
Istanze:
{chr(10).join(ist_lines) if ist_lines else '  (nessun dato)'}

FARM:
  {drl_str}
  {sped_str}  inviato: {inv_str}
  Produzione/ora: {prod_str}

ANOMALIE ultimi 30 min:
{anom_str}
"""
    except Exception as exc:
        _log.warning("[AI] _build_context fallito: %s", exc)
        return "[CONTESTO NON DISPONIBILE]"


# ==============================================================================
# Opzione 1 — Claude Code CLI (abbonamento)
# ==============================================================================

def _find_claude_exe() -> Optional[str]:
    """Cerca l'eseguibile Claude Code CLI."""
    import shutil
    # 1. Percorso da PATH
    found = shutil.which("claude")
    if found:
        return found
    # 2. VSCode extension (Windows)
    vscode_ext = Path(os.environ.get("USERPROFILE", "C:/Users/Fausto")) / ".vscode" / "extensions"
    if vscode_ext.exists():
        for d in vscode_ext.glob("anthropic.claude-code*"):
            candidate = d / "resources" / "native-binary" / "claude.exe"
            if candidate.exists():
                return str(candidate)
    # 3. Installazione standalone Windows
    for p in [
        Path("C:/Users/Fausto/AppData/Local/Programs/claude/claude.exe"),
        Path("C:/Program Files/claude/claude.exe"),
    ]:
        if p.exists():
            return str(p)
    return None


def cmd_claude(text: str) -> str:
    """Risponde usando Claude Code CLI (abbonamento). Inietta contesto farm live."""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return (
            "⚠ Uso: /claude &lt;domanda&gt;\n"
            "Es: /claude perché FAU_09 non raccoglie?\n"
            "Usa il tuo abbonamento Claude — nessun costo aggiuntivo."
        )
    domanda = parts[1].strip()

    exe = _find_claude_exe()
    if not exe:
        return (
            "⚠ Claude Code CLI non trovato.\n"
            "Installa Claude Code o usa /haiku per la versione API."
        )

    ctx = _build_context()
    prompt = f"""{ctx}

DOMANDA: {domanda}

Rispondi in italiano, in modo conciso e pratico. Se rilevi anomalie o problemi, suggerisci azioni concrete."""

    try:
        result = subprocess.run(
            [exe, "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
        )
        risposta = (result.stdout or "").strip()
        if not risposta and result.stderr:
            risposta = result.stderr.strip()[:500]
        if not risposta:
            return "⚠ Claude Code non ha restituito risposta. Controlla che sia loggato."
        # Tronca a limite Telegram
        return risposta[:3900]
    except subprocess.TimeoutExpired:
        return "⚠ Timeout (120s) — domanda troppo complessa, riprova con una più specifica."
    except Exception as exc:
        _log.warning("[AI] cmd_claude errore: %s", exc)
        return f"⚠ Errore Claude Code CLI: {exc}"


# ==============================================================================
# Opzione 2 — Claude Haiku API (pay-per-use)
# ==============================================================================

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_HAIKU_MAX_TOKENS = 1024


def _load_anthropic_key() -> Optional[str]:
    """Legge la API key Anthropic da data/secrets.json o env."""
    # 1. Variabile ambiente
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # 2. data/secrets.json
    secrets_path = _ROOT_PROD / "data" / "secrets.json"
    try:
        if secrets_path.exists():
            sec = json.loads(secrets_path.read_text(encoding="utf-8"))
            return sec.get("anthropic_api_key") or sec.get("ANTHROPIC_API_KEY")
    except Exception:
        pass
    return None


def cmd_haiku(text: str) -> str:
    """Risponde usando Claude Haiku API con contesto MCP live (pay-per-use ~$0.002/query)."""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return (
            "⚠ Uso: /haiku &lt;domanda&gt;\n"
            "Es: /haiku il rifornimento è ottimale?\n"
            "Usa Claude Haiku API — ~$0.002 per query."
        )
    domanda = parts[1].strip()

    api_key = _load_anthropic_key()
    if not api_key:
        return (
            "⚠ API key Anthropic non trovata.\n"
            "Aggiungila in data/secrets.json come:\n"
            '  {"anthropic_api_key": "sk-ant-..."}\n'
            "Oppure imposta la variabile ANTHROPIC_API_KEY."
        )

    ctx = _build_context()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_HAIKU_MAX_TOKENS,
            system=(
                "Sei un assistente esperto di Doomsday Engine V6, un bot di automazione per "
                "il gioco Doomsday: Last Survivors. Analizza i dati della farm e rispondi "
                "in italiano in modo conciso e pratico. Se rilevi anomalie o problemi, "
                "suggerisci azioni concrete. Usa un tono diretto, senza fronzoli."
            ),
            messages=[{
                "role": "user",
                "content": f"{ctx}\n\nDOMANDA: {domanda}",
            }],
        )
        risposta = response.content[0].text.strip()
        # Aggiungi info costo approssimativo
        in_tok  = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        costo   = round((in_tok * 0.00000025 + out_tok * 0.00000125), 4)
        footer  = f"\n\n<i>Haiku — {in_tok}+{out_tok} tok — ~${costo}</i>"
        return risposta[:3800] + footer
    except Exception as exc:
        _log.warning("[AI] cmd_haiku errore: %s", exc)
        return f"⚠ Errore Haiku API: {exc}"
