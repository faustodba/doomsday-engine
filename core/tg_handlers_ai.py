"""core/tg_handlers_ai.py — Handler AI per il Telegram bot.

Due comandi:
  /claude <domanda>  — usa Claude Code CLI installato sulla macchina (abbonamento)
  /haiku  <domanda>  — usa Claude Haiku API pay-per-use con contesto MCP live
  /credit            — utilizzo API Anthropic: costo odierno, totale, storico 7gg

API key: letta in priorità da:
  1. Env var ANTHROPIC_API_KEY
  2. data/secrets.json::anthropic_api_key
  3. d:/dev/trading-engine/.env (condivide abbonamento con bot trading)

Usage tracking: data/ai_usage.json (analogo a advisor:usage Redis del trading bot)

Il contesto iniettato è costruito da monitor/analyzer.py:
  - ciclo corrente (numero, stato, istanza live)
  - anomalie recenti (ultimi 30 minuti)
  - DRL master + spedizioni + produzione/ora farm
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_ROOT_PROD = Path(os.environ.get("DOOMSDAY_ROOT",
                  Path(__file__).resolve().parents[1]))

# Prezzi Claude Haiku 4.5 (USD per milione di token) — fonte: trading bot decision_advisor.py
_HAIKU_MODEL             = "claude-haiku-4-5-20251001"
_HAIKU_PRICE_IN_PER_MTOK  = 0.80   # $0.80 / MTok input
_HAIKU_PRICE_OUT_PER_MTOK = 4.00   # $4.00 / MTok output
_HAIKU_MAX_TOKENS         = 1024


# ==============================================================================
# Context builder
# ==============================================================================

def _build_context() -> str:
    """Costruisce il contesto live della farm da iniettare nel prompt AI."""
    try:
        import sys
        proj_root = str(Path(__file__).resolve().parents[1])
        if proj_root not in sys.path:
            sys.path.insert(0, proj_root)

        from monitor.analyzer import stato_ciclo_completo, farm_stato, rileva_anomalie, leggi_jsonl_da
        from datetime import timedelta

        root_prod = str(_ROOT_PROD)

        # Ciclo corrente
        ciclo    = stato_ciclo_completo(root_prod)
        ciclo_n  = ciclo.get("ciclo_n", "?")
        ciclo_ok = "completato" if ciclo.get("completato") else "in corso"
        ts_str   = str(ciclo.get("ciclo_start_ts", ""))[:16]

        ist_lines = []
        for nome, d in ciclo.get("istanze", {}).items():
            esito     = d.get("esito", "attesa")
            task_live = d.get("task_corrente")
            racc      = d.get("raccolta", {})
            tasks     = d.get("tasks", {})
            parts     = [esito]
            if task_live:
                parts.append(f"→{task_live}")
            if racc.get("inviate"):
                parts.append(f"marce={racc['inviate']}")
            if racc.get("slot_pieni"):
                parts.append("slot_pieni")
            fail_tasks = [k for k, v in tasks.items() if v == "FAIL"]
            if fail_tasks:
                parts.append(f"FAIL={fail_tasks}")
            ist_lines.append(f"  {nome}: {' '.join(parts)}")

        # Farm snapshot
        farm   = farm_stato(root_prod)
        master = farm.get("master", {})
        drl_str = (
            f"DRL={master.get('drl_residuo_m')}M/{master.get('drl_max_m')}M "
            f"({master.get('drl_pct')}%)  tassa={master.get('tassa_pct')}%"
            if master else "DRL: n/d"
        )
        sped_str = f"Spedizioni oggi: {farm.get('spedizioni_totali', 0)}"
        inv      = farm.get("inviato_totale_m", {})
        inv_str  = "  ".join(f"{k}={v}M" for k, v in inv.items()) if inv else "—"
        prod     = farm.get("farm_prod_h_m", {})
        prod_str = "  ".join(f"{k}={v}" for k, v in prod.items()) if prod else "—"

        # Anomalie ultimi 30 min
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        anom_lines: list[str] = []
        logs_dir = os.path.join(root_prod, "logs")
        for fn in sorted(os.listdir(logs_dir)):
            if not fn.endswith(".jsonl"):
                continue
            nome_ist = fn[:-6]
            righe    = leggi_jsonl_da(os.path.join(logs_dir, fn), da_ts=cutoff)
            for a in rileva_anomalie(righe)[-3:]:
                anom_lines.append(
                    f"  [{str(a['ts'])[:16]}] {a['severita']} {nome_ist}: {a['msg'][:80]}"
                )

        anom_str = "\n".join(anom_lines[-10:]) if anom_lines else "  (nessuna)"

        return (
            f"[DOOMSDAY ENGINE V6 — CONTESTO LIVE {datetime.now().strftime('%H:%M')}]\n\n"
            f"CICLO {ciclo_n} — {ciclo_ok} (avv. {ts_str})\n"
            f"Istanze:\n" + "\n".join(ist_lines) + "\n\n"
            f"FARM:\n"
            f"  {drl_str}\n"
            f"  {sped_str}  inviato: {inv_str}\n"
            f"  Produzione/ora: {prod_str}\n\n"
            f"ANOMALIE ultimi 30 min:\n{anom_str}\n"
        )
    except Exception as exc:
        _log.warning("[AI] _build_context fallito: %s", exc)
        return "[CONTESTO NON DISPONIBILE]"


# ==============================================================================
# API key loader — 3 sorgenti in priorità
# ==============================================================================

def _load_anthropic_key() -> Optional[str]:
    """Legge la API key Anthropic in ordine di priorità:
    1. Env var ANTHROPIC_API_KEY
    2. data/secrets.json::anthropic_api_key
    3. d:/dev/trading-engine/.env (condivisione abbonamento)
    """
    # 1. Variabile ambiente
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    # 2. data/secrets.json
    secrets_path = _ROOT_PROD / "data" / "secrets.json"
    try:
        if secrets_path.exists():
            sec = json.loads(secrets_path.read_text(encoding="utf-8"))
            key = sec.get("anthropic_api_key") or sec.get("ANTHROPIC_API_KEY")
            if key:
                return key
    except Exception:
        pass

    # 3. .env del bot trading (condivisione abbonamento)
    trading_env = Path("d:/dev/trading-engine/.env")
    if trading_env.exists():
        try:
            for line in trading_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        return key
        except Exception:
            pass

    return None


# ==============================================================================
# Usage tracker — data/ai_usage.json (analogo a advisor:usage Redis del trading bot)
# ==============================================================================

_USAGE_PATH = _ROOT_PROD / "data" / "ai_usage.json"
_HAIKU_HISTORY_DAYS = 30


def _load_usage() -> dict:
    try:
        if _USAGE_PATH.exists():
            return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_usage(data: dict) -> None:
    try:
        _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _USAGE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _USAGE_PATH)
    except Exception as exc:
        _log.warning("[AI] _save_usage fallito: %s", exc)


def _record_usage(in_tok: int, out_tok: int, cost: float) -> None:
    """Registra una chiamata Haiku in ai_usage.json (struttura identica al trading bot)."""
    data  = _load_usage()
    today = datetime.now(timezone.utc).date().isoformat()

    # Totale storico
    tot = data.get("total", {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    tot["calls"]         += 1
    tot["input_tokens"]  += in_tok
    tot["output_tokens"] += out_tok
    tot["cost_usd"]       = round(tot["cost_usd"] + cost, 6)
    data["total"] = tot

    # Giornaliero (reset se cambio data)
    day = data.get("today", {})
    if day.get("date") != today:
        # archivia il giorno precedente nello storico
        history = data.get("history", [])
        if day.get("date"):
            history.append({
                "date":          day["date"],
                "calls":         day.get("calls", 0),
                "input_tokens":  day.get("input_tokens", 0),
                "output_tokens": day.get("output_tokens", 0),
                "cost_usd":      day.get("cost_usd", 0.0),
            })
        # mantieni solo ultimi N giorni
        data["history"] = history[-_HAIKU_HISTORY_DAYS:]
        day = {"date": today, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    day["calls"]         += 1
    day["input_tokens"]  += in_tok
    day["output_tokens"] += out_tok
    day["cost_usd"]       = round(day["cost_usd"] + cost, 6)
    data["today"] = day

    data["last_call"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save_usage(data)


# ==============================================================================
# Opzione 1 — /claude (Claude Code CLI, abbonamento)
# ==============================================================================

def _find_claude_exe() -> Optional[str]:
    """Cerca il CLI Claude Code sulla macchina."""
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    vscode_ext = Path(os.environ.get("USERPROFILE", "C:/Users/Fausto")) / ".vscode" / "extensions"
    if vscode_ext.exists():
        for d in vscode_ext.glob("anthropic.claude-code*"):
            candidate = d / "resources" / "native-binary" / "claude.exe"
            if candidate.exists():
                return str(candidate)
    for p in [
        Path("C:/Users/Fausto/AppData/Local/Programs/claude/claude.exe"),
        Path("C:/Program Files/claude/claude.exe"),
    ]:
        if p.exists():
            return str(p)
    return None


def cmd_claude(text: str) -> str:
    """Risponde con Claude Code CLI (abbonamento). Inietta contesto farm live."""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return (
            "⚠ Uso: /claude &lt;domanda&gt;\n"
            "Es: /claude perché FAU_09 non raccoglie?\n"
            "Usa il tuo abbonamento Claude — nessun costo aggiuntivo."
        )
    domanda = parts[1].strip()
    exe     = _find_claude_exe()
    if not exe:
        return (
            "⚠ Claude Code CLI non trovato.\n"
            "Installa Claude Code o usa /haiku per la versione API."
        )

    prompt = (
        f"{_build_context()}\n"
        f"DOMANDA: {domanda}\n\n"
        "Rispondi in italiano, conciso e pratico. "
        "Se rilevi anomalie o problemi, suggerisci azioni concrete."
    )
    try:
        result = subprocess.run(
            [exe, "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
        )
        risposta = (result.stdout or "").strip() or (result.stderr or "").strip()[:500]
        if not risposta:
            return "⚠ Claude Code non ha restituito risposta. Controlla che sia loggato."
        return risposta[:3900]
    except subprocess.TimeoutExpired:
        return "⚠ Timeout (120s) — domanda troppo complessa, riprova."
    except Exception as exc:
        return f"⚠ Errore Claude Code CLI: {exc}"


# ==============================================================================
# Opzione 2 — /haiku (Anthropic Haiku API, pay-per-use)
# ==============================================================================

def cmd_haiku(text: str) -> str:
    """Risponde con Claude Haiku API (pay-per-use) + contesto farm live."""
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
            "Aggiungila in <code>data/secrets.json</code>:\n"
            '  <code>{"anthropic_api_key": "sk-ant-..."}</code>\n'
            "Oppure nel <code>.env</code> del bot trading."
        )

    ctx = _build_context()
    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_HAIKU_MAX_TOKENS,
            system=(
                "Sei un assistente esperto di Doomsday Engine V6, un bot di automazione per "
                "il gioco Doomsday: Last Survivors. Analizza i dati della farm e rispondi "
                "in italiano in modo conciso e pratico. Se rilevi anomalie o problemi, "
                "suggerisci azioni concrete. Usa un tono diretto, senza fronzoli."
            ),
            messages=[{"role": "user", "content": f"{ctx}\nDOMANDA: {domanda}"}],
        )
        risposta = response.content[0].text.strip()
        in_tok   = response.usage.input_tokens
        out_tok  = response.usage.output_tokens
        cost     = round(
            in_tok  * _HAIKU_PRICE_IN_PER_MTOK  / 1_000_000 +
            out_tok * _HAIKU_PRICE_OUT_PER_MTOK / 1_000_000,
            6,
        )
        _record_usage(in_tok, out_tok, cost)
        footer = f"\n\n<i>Haiku — {in_tok}+{out_tok} tok — ${cost:.4f}</i>"
        return risposta[:3800] + footer
    except Exception as exc:
        _log.warning("[AI] cmd_haiku errore: %s", exc)
        return f"⚠ Errore Haiku API: {exc}"


# ==============================================================================
# /credit — utilizzo API (analogo al trading bot)
# ==============================================================================

def cmd_credit(text: str) -> str:
    """Mostra utilizzo API Anthropic: costo odierno, totale storico, ultimi 7 giorni."""
    data     = _load_usage()
    today    = data.get("today", {})
    total    = data.get("total", {})
    history  = data.get("history", [])
    last_ts  = data.get("last_call", "—")

    def _fmt_tok(d: dict) -> str:
        return f"{d.get('input_tokens', 0) + d.get('output_tokens', 0):,}"

    lines = [
        "<b>Anthropic API — Utilizzo Haiku</b>", "",
        "<b>Oggi</b>",
        f"  Chiamate: {today.get('calls', 0)}",
        f"  Token: {_fmt_tok(today)}",
        f"  Costo: <b>${today.get('cost_usd', 0):.4f}</b>",
        "",
        "<b>Totale storico</b>",
        f"  Chiamate: {total.get('calls', 0)}",
        f"  Token: {_fmt_tok(total)}",
        f"  Costo: <b>${total.get('cost_usd', 0):.4f}</b>",
    ]

    # Ultimi 7 giorni dallo storico
    history_7 = history[-7:]
    if history_7:
        lines += ["", "<b>Ultimi 7 giorni</b>"]
        for d in reversed(history_7):
            tok_str  = f"{d.get('input_tokens',0)+d.get('output_tokens',0):,}"
            cost_str = f"${d.get('cost_usd', 0):.4f}"
            lines.append(
                f"  {d['date']}  {d.get('calls',0)} call  {tok_str} tok  {cost_str}"
            )

    # Ultima chiamata
    if last_ts and last_ts != "—":
        try:
            dt = datetime.fromisoformat(last_ts).astimezone(timezone.utc)
            lines.append(f"\nUltima chiamata: {dt.strftime('%d/%m %H:%M UTC')}")
        except Exception:
            lines.append(f"\nUltima chiamata: {last_ts}")

    lines.append("\n<i>Saldo reale → console.anthropic.com/settings/billing</i>")
    return "\n".join(lines)
