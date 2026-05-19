"""
dashboard/routers/api_notifications.py — endpoint email notifier (Step F).

Endpoints:
  GET   /api/notifications                 — config + queue stats
  PATCH /api/notifications                 — modifica config (merge superficiale)
  POST  /api/notifications/test-send       — invio mail test immediato
  POST  /api/notifications/dispatch-now    — forza dispatch della queue subito

Schema config (vedi `config/global_config.json::notifications`):
    {
      "enabled": bool,
      "daily_report_enabled": bool,
      "daily_report_hour_utc": int (0-23),
      "from_addr": str,
      "recipients": list[str],
      "smtp": {"host": str, "port": int}
    }
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["notifications"])


# ─── Path resolver ─────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _runtime_overrides_path() -> Path:
    return _root() / "config" / "runtime_overrides.json"


def _global_config_path() -> Path:
    return _root() / "config" / "global_config.json"


def _read_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json_atomic(p: Path, data: dict) -> bool:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _get_effective_config() -> dict:
    """Config attiva (baseline + runtime_overrides)."""
    from config.config_loader import load_effective_notifications
    return load_effective_notifications()


# ─── GET /api/notifications ────────────────────────────────────────────────

@router.get("/notifications")
def get_notifications() -> dict:
    """Ritorna config corrente + queue stats + state daily report."""
    cfg = _get_effective_config()

    queue_stats = {}
    try:
        from core.notifier import queue_stats as _qs
        queue_stats = _qs()
    except Exception as exc:
        queue_stats = {"error": str(exc)}

    daily_state = {}
    try:
        sp = _root() / "data" / "daily_report_state.json"
        if sp.exists():
            daily_state = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        pass

    # App password — MAI esporre il valore. Solo flag + sorgente per UI.
    try:
        from shared.secrets import has_app_password, app_password_source
        app_pw_set = has_app_password()
        app_pw_source = app_password_source()
    except Exception:
        app_pw_set = bool(os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "").strip())
        app_pw_source = "env" if app_pw_set else "none"

    return {
        "config":              cfg,
        "app_password_set":    app_pw_set,
        "app_password_source": app_pw_source,
        "queue_stats":         queue_stats,
        "daily_state":         daily_state,
    }


# ─── PATCH /api/notifications ──────────────────────────────────────────────

class NotificationsPatch(BaseModel):
    """Patch parziale della config notifications. Tutti i field opzionali."""
    enabled: Optional[bool] = None
    daily_report_enabled: Optional[bool] = None
    daily_report_hour_utc: Optional[int] = None
    # WU137 fase 2 — alert real-time master toggle + lista event_type silenziati
    alerts_enabled: Optional[bool] = None
    alerts_disabled: Optional[list[str]] = None
    from_addr: Optional[str] = None
    recipients: Optional[list[str]] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None


def _global_config_path() -> Path:
    return _root() / "config" / "global_config.json"


@router.patch("/notifications")
def patch_notifications(payload: NotificationsPatch) -> dict:
    """Merge superficiale dei field non-None su `global_config.json` (STATIC).

    08/05: regola architetturale "config modifica solo static". Questa card
    è in `/ui/config/global` → scrive su global_config.json. Le modifiche
    diventano attive al prossimo bootstrap o reset (banner UI lo specifica).
    """
    gc_path = _global_config_path()
    gc = _read_json(gc_path)
    notif = gc.setdefault("notifications", {})

    changed: dict = {}
    if payload.enabled is not None:
        notif["enabled"] = bool(payload.enabled)
        changed["enabled"] = notif["enabled"]
    if payload.daily_report_enabled is not None:
        notif["daily_report_enabled"] = bool(payload.daily_report_enabled)
        changed["daily_report_enabled"] = notif["daily_report_enabled"]
    if payload.daily_report_hour_utc is not None:
        h = int(payload.daily_report_hour_utc)
        if not (0 <= h <= 23):
            raise HTTPException(status_code=400,
                                detail="daily_report_hour_utc fuori range 0-23")
        notif["daily_report_hour_utc"] = h
        changed["daily_report_hour_utc"] = h
    # WU137 fase 2 — alert real-time
    if payload.alerts_enabled is not None:
        notif["alerts_enabled"] = bool(payload.alerts_enabled)
        changed["alerts_enabled"] = notif["alerts_enabled"]
    if payload.alerts_disabled is not None:
        notif["alerts_disabled"] = [
            str(s).strip() for s in payload.alerts_disabled if str(s).strip()
        ]
        changed["alerts_disabled"] = notif["alerts_disabled"]
    if payload.from_addr is not None:
        addr = payload.from_addr.strip()
        if "@" not in addr:
            raise HTTPException(status_code=400, detail="from_addr non valido")
        notif["from_addr"] = addr
        changed["from_addr"] = addr
    if payload.recipients is not None:
        recs = [r.strip() for r in payload.recipients if r and r.strip()]
        if not recs:
            raise HTTPException(status_code=400,
                                detail="recipients deve avere almeno 1 indirizzo")
        for r in recs:
            if "@" not in r:
                raise HTTPException(status_code=400,
                                    detail=f"recipient non valido: {r}")
        notif["recipients"] = recs
        changed["recipients"] = recs
    if payload.smtp_host is not None or payload.smtp_port is not None:
        smtp = notif.setdefault("smtp", {})
        if payload.smtp_host is not None:
            smtp["host"] = payload.smtp_host.strip()
        if payload.smtp_port is not None:
            smtp["port"] = int(payload.smtp_port)
        changed["smtp"] = dict(smtp)

    if not changed:
        return {"ok": True, "changed": {}, "msg": "nessuna modifica"}

    if not _write_json_atomic(gc_path, gc):
        raise HTTPException(status_code=500,
                            detail="scrittura global_config.json fallita")

    return {"ok": True, "changed": changed,
            "target": "static", "applies_after": "bootstrap_or_reset"}


# ─── POST /api/notifications/test-send ─────────────────────────────────────

@router.post("/notifications/test-send")
def test_send() -> dict:
    """Invio sincrono mail di test (NO queue, diretto SMTP).

    Usa app password da env. Risposta indica successo/errore SMTP.
    """
    try:
        from shared.secrets import has_app_password
        pw_ok = has_app_password()
    except Exception:
        pw_ok = bool(os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "").strip())
    if not pw_ok:
        raise HTTPException(
            status_code=400,
            detail="app password non configurata. Inseriscila nel campo "
                   "'app password' della card e clicca 'salva password'.",
        )

    cfg = _get_effective_config()
    recipients = cfg.get("recipients") or []
    from_addr = cfg.get("from_addr") or ""
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="recipients vuoto: configura almeno 1 destinatario nel campo "
                   "'destinatari' della card e salva.",
        )
    if not from_addr:
        raise HTTPException(
            status_code=400,
            detail="from_addr vuoto: configura il mittente nel campo 'mittente' "
                   "della card e salva.",
        )

    try:
        from shared.mailer import send_email
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"import mailer fallito: {exc}")

    # Test send sincrono. Catturiamo gli errori SMTP per esporli alla UI
    # (più utile di "fallito, vedi log").
    import smtplib
    import ssl as _ssl
    from email.message import EmailMessage as _EmailMessage
    from shared.secrets import load_app_password

    ts = datetime.now(timezone.utc).isoformat()
    msg = _EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = "[Doomsday] test send dashboard"
    msg.set_content(
        f"Test invio dalla dashboard.\n\n"
        f"Timestamp: {ts}\n"
        f"From: {from_addr}\n"
        f"To:   {recipients}\n\n"
        f"Se ricevi questa mail, il modulo notifier funziona."
    )
    msg.add_alternative(
        f"<h2>Doomsday — test send dashboard</h2>"
        f"<p>Test invio dalla dashboard.</p>"
        f"<p><b>Timestamp:</b> {ts}<br>"
        f"<b>From:</b> {from_addr}<br>"
        f"<b>To:</b> {', '.join(recipients)}</p>"
        f"<p>Se ricevi questa mail, il modulo notifier funziona.</p>",
        subtype="html",
    )

    smtp_cfg = cfg.get("smtp") or {}
    host = smtp_cfg.get("host", "smtp.gmail.com")
    port = int(smtp_cfg.get("port", 465))
    pw = load_app_password()

    try:
        ctx = _ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as srv:
            srv.login(from_addr, pw)
            srv.send_message(msg, from_addr=from_addr, to_addrs=recipients)
        return {"ok": True, "to": recipients, "ts": ts}
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=(f"Auth Gmail fallita: {exc.smtp_code} "
                    f"{exc.smtp_error.decode('utf-8', errors='replace') if isinstance(exc.smtp_error, bytes) else exc.smtp_error}. "
                    f"Verifica che (1) 2FA è attivo su {from_addr}, "
                    f"(2) la password è una App Password generata su "
                    f"myaccount.google.com/apppasswords (NON la password normale), "
                    f"(3) la lunghezza salvata è {len(pw)} char (atteso 16)."),
        )
    except smtplib.SMTPRecipientsRefused as exc:
        raise HTTPException(status_code=502, detail=f"destinatario rifiutato: {exc}")
    except smtplib.SMTPException as exc:
        raise HTTPException(status_code=502,
                            detail=f"SMTP error: {type(exc).__name__}: {exc}")
    except (TimeoutError, ConnectionError, OSError) as exc:
        raise HTTPException(status_code=502,
                            detail=f"network error: {type(exc).__name__}: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"errore imprevisto: {type(exc).__name__}: {exc}")


# ─── PUT/DELETE /api/notifications/app-password ────────────────────────────

class AppPasswordPut(BaseModel):
    password: str


@router.put("/notifications/app-password")
def put_app_password(payload: AppPasswordPut) -> dict:
    """Salva app password Gmail in `data/secrets.json` (write-only).

    La password NON è MAI esposta dalle API. Solo flag `app_password_set`
    e source ('secrets' | 'env' | 'none') in GET /api/notifications.

    Sostituisce env var `DOOMSDAY_GMAIL_APP_PASSWORD` (resta come fallback
    di compat ma non più necessario in `run_prod.bat`).
    """
    pw = (payload.password or "").strip()
    if not pw:
        raise HTTPException(status_code=400, detail="password vuota")
    # Validazione minima Gmail app password = 16 char alfanum (no spaces).
    # Google emette anche varianti sep da spazi che vanno strippate.
    # Strip TUTTI i whitespace (spazi, tab, newline) — Google formatta in
    # gruppi di 4 con spazi ma a volte si copia con \n in coda.
    pw_clean = "".join(pw.split())
    # Range 16-32 — copre Gmail standard (16) e varianti Workspace recenti (20).
    if len(pw_clean) < 12 or len(pw_clean) > 32:
        raise HTTPException(
            status_code=400,
            detail=f"lunghezza password sospetta ({len(pw_clean)} char). "
                   f"Gmail app password tipicamente 16-20 caratteri. "
                   f"Genera una App Password (NON la password normale) su "
                   f"myaccount.google.com/apppasswords.",
        )
    try:
        from shared.secrets import save_app_password, app_password_source
        ok = save_app_password(pw_clean)
        if not ok:
            raise HTTPException(status_code=500, detail="scrittura secrets fallita")
        return {"ok": True, "source": app_password_source(),
                "len": len(pw_clean)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


@router.delete("/notifications/app-password")
def delete_app_password() -> dict:
    """Rimuove app password da `data/secrets.json` (env var resta intatta)."""
    try:
        from shared.secrets import save_app_password, app_password_source
        ok = save_app_password("")   # "" = delete
        if not ok:
            raise HTTPException(status_code=500, detail="scrittura secrets fallita")
        return {"ok": True, "source": app_password_source()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


# ─── POST /api/notifications/dispatch-now ──────────────────────────────────

@router.post("/notifications/dispatch-now")
def dispatch_now() -> dict:
    """Forza dispatch immediato della queue (utile per debug)."""
    try:
        from core.notifier import dispatch_pending
        stats = dispatch_pending()
        return {"ok": True, "stats": stats}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"dispatch error: {exc}")


# ─── Telegram Bot endpoints (WU-Telegram) ─────────────────────────────────────

class TelegramTokenPut(BaseModel):
    token: str


class TelegramConfigPatch(BaseModel):
    enabled:              Optional[bool] = None
    notify_cycle_every_n: Optional[int]  = None
    notify_cascade:       Optional[bool] = None
    notify_drl:           Optional[bool] = None
    notify_daily_report:  Optional[bool] = None


@router.put("/notifications/telegram-token")
def put_telegram_token(payload: TelegramTokenPut) -> dict:
    """Salva Telegram bot token in `data/secrets.json` (write-only).

    Il token NON è MAI esposto dalle API. Solo flag `has_token` in GET.
    """
    tok = (payload.token or "").strip()
    if not tok:
        raise HTTPException(status_code=400, detail="token vuoto")
    if ":" not in tok or len(tok) < 10:
        raise HTTPException(status_code=400,
                            detail="token non valido (formato atteso: 123456:ABC...)")
    try:
        from shared.telegram_client import save_token, get_me
        ok = save_token(tok)
        if not ok:
            raise HTTPException(status_code=500, detail="scrittura secrets fallita")
        info = get_me(token=tok)
        bot_name = f"@{info.get('username')}" if info else "non raggiungibile (verifica token)"
        return {"ok": True, "bot": bot_name, "has_token": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


@router.delete("/notifications/telegram-token")
def delete_telegram_token() -> dict:
    """Rimuove bot token da secrets.json."""
    try:
        from shared.telegram_client import save_token
        save_token("")
        return {"ok": True, "has_token": False}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")


@router.get("/notifications/telegram-status")
def get_telegram_status() -> dict:
    """Stato configurazione Telegram (token, chat_id, bot info)."""
    try:
        from shared.telegram_client import has_token, load_chat_id, get_me
        tok_ok = has_token()
        chat_id = load_chat_id()
        bot_info = None
        if tok_ok:
            info = get_me()
            if info:
                bot_info = {"username": info.get("username"),
                            "first_name": info.get("first_name")}
    except Exception as exc:
        return {"error": str(exc)}

    try:
        from core.telegram_bot import is_running
        running = is_running()
    except Exception:
        running = False

    # Config da runtime_overrides
    ov_path = _root() / "config" / "runtime_overrides.json"
    ov = _read_json(ov_path)
    tg_cfg = ov.get("globali", {}).get("notifications", {}).get("telegram", {})

    return {
        "has_token":  tok_ok,
        "has_chat_id": bool(chat_id),
        "bot_info":   bot_info,
        "running":    running,
        "config":     tg_cfg,
    }


@router.patch("/notifications/telegram")
def patch_telegram(payload: TelegramConfigPatch) -> dict:
    """Aggiorna config Telegram in runtime_overrides.json (DYNAMIC, hot-reload).

    Segue pattern WU139: parse raw + setattr field-by-field (mai sovrascrive
    campi non inviati).
    """
    ov_path = _root() / "config" / "runtime_overrides.json"
    ov = _read_json(ov_path)
    tg = ov.setdefault("globali", {}).setdefault(
        "notifications", {}).setdefault("telegram", {})

    changed: dict = {}
    data = payload.model_dump(exclude_none=True)
    for field, value in data.items():
        tg[field] = value
        changed[field] = value

    if not changed:
        return {"ok": True, "changed": {}, "msg": "nessuna modifica"}

    if not _write_json_atomic(ov_path, ov):
        raise HTTPException(status_code=500,
                            detail="scrittura runtime_overrides.json fallita")

    return {"ok": True, "changed": changed,
            "target": "dynamic", "applies_immediately": True}


@router.post("/notifications/telegram-test")
def telegram_test_send() -> dict:
    """Invia messaggio di test al chat_id configurato."""
    try:
        from shared.telegram_client import has_token, load_chat_id, send_message
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"import fallito: {exc}")

    if not has_token():
        raise HTTPException(status_code=400,
                            detail="token non configurato. Inseriscilo prima.")
    chat_id = load_chat_id()
    if not chat_id:
        raise HTTPException(status_code=400,
                            detail="chat_id non configurato. Avvia il bot e invia /start.")

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = send_message(chat_id, f"<b>Doomsday Engine</b> — test send dashboard\n{ts}")
    if not ok:
        raise HTTPException(status_code=502,
                            detail="invio fallito (token errato o chat_id non valido?)")
    return {"ok": True, "chat_id": chat_id, "ts": ts}


@router.put("/notifications/telegram-chat")
def put_telegram_chat(payload: dict) -> dict:
    """Salva chat_id Telegram (auto-detect da /start oppure manuale)."""
    chat_id = str(payload.get("chat_id") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id vuoto")
    try:
        from shared.telegram_client import save_chat_id
        ok = save_chat_id(chat_id)
        if not ok:
            raise HTTPException(status_code=500, detail="scrittura secrets fallita")
        return {"ok": True, "chat_id": chat_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"errore: {exc}")
