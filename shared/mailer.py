"""shared/mailer.py — client SMTP minimale per notifiche bot.

STEP A del modulo Email Notifier (memoria `project_email_notifier.md`).

Scope: funzione `send_email` standalone, no queue, no retry, no scheduling.
Queue persistente arriva in Step B (`core/notifier.py`), scheduler in Step E.

Usage:
    from shared.mailer import send_email
    ok = send_email(
        to=["dest@example.com"],
        subj="[Doomsday] Test",
        body="Ciao, test invio.",
        html="<p>Ciao, <b>test</b>.</p>",   # opzionale (multipart alt)
        from_addr="mittente@example.com",   # opzionale, fallback env DOOMSDAY_GMAIL_FROM
    )

Config:
  - `from_addr`: priorità arg → env `DOOMSDAY_GMAIL_FROM` → ERRORE (no default).
  - `to`: passato dal caller (caller legge da config). Empty → ERRORE.

Env vars (lette ad ogni chiamata, hot-reload):
    DOOMSDAY_GMAIL_APP_PASSWORD   REQUIRED — app password 16 char, NO spazi
    DOOMSDAY_GMAIL_FROM           OPZIONALE — solo se from_addr non passato
    DOOMSDAY_SMTP_HOST            default "smtp.gmail.com"
    DOOMSDAY_SMTP_PORT            default 465 (SSL implicit)
    DOOMSDAY_SMTP_TIMEOUT_S       default 30

Return: True se il server SMTP ha accettato il messaggio, False altrimenti.
Non solleva eccezioni al caller — log dettagliato per debug.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional, Union

_log = logging.getLogger(__name__)

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 465
DEFAULT_TIMEOUT_S = 30


def _norm_recipients(to: Union[str, list[str], tuple[str, ...]]) -> list[str]:
    if isinstance(to, str):
        return [a.strip() for a in to.split(",") if a.strip()]
    return [a.strip() for a in to if a and a.strip()]


def send_email(to: Union[str, list[str]],
               subj: str,
               body: str,
               html: Optional[str] = None,
               from_addr: Optional[str] = None) -> bool:
    """Invio mail via Gmail SMTP SSL.

    Args:
        to: destinatario singolo (str), lista CSV "a@x,b@y" o list[str].
        subj: subject (UTF-8 OK).
        body: testo plain (UTF-8 OK).
        html: alternativa HTML opzionale (multipart/alternative).
        from_addr: override del mittente; default da env / costante.

    Returns:
        True se accettato dal server, False su qualsiasi errore.
    """
    recipients = _norm_recipients(to)
    if not recipients:
        _log.error("[MAILER] nessun destinatario valido")
        return False

    # Priority: data/secrets.json > env var DOOMSDAY_GMAIL_APP_PASSWORD
    try:
        from shared.secrets import load_app_password
        app_pw = load_app_password()
    except Exception:
        app_pw = os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "").strip()
    if not app_pw:
        _log.error("[MAILER] app password non configurata (settala in dashboard "
                   "o env var DOOMSDAY_GMAIL_APP_PASSWORD)")
        return False

    sender = (from_addr
              or os.environ.get("DOOMSDAY_GMAIL_FROM", "").strip())
    if not sender:
        _log.error("[MAILER] from_addr non fornito (passare arg o settare "
                   "globali.notifications.from_addr / env DOOMSDAY_GMAIL_FROM)")
        return False
    host = os.environ.get("DOOMSDAY_SMTP_HOST", "").strip() or DEFAULT_SMTP_HOST
    try:
        port = int(os.environ.get("DOOMSDAY_SMTP_PORT", "") or DEFAULT_SMTP_PORT)
    except ValueError:
        port = DEFAULT_SMTP_PORT
    try:
        timeout = int(os.environ.get("DOOMSDAY_SMTP_TIMEOUT_S", "") or DEFAULT_TIMEOUT_S)
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subj
    msg.set_content(body, charset="utf-8")
    if html:
        msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=timeout) as srv:
            srv.login(sender, app_pw)
            srv.send_message(msg, from_addr=sender, to_addrs=recipients)
        _log.info(
            "[MAILER] inviato '%s' → %s (host=%s:%d)",
            subj, recipients, host, port,
        )
        return True
    except smtplib.SMTPAuthenticationError as exc:
        _log.error(
            "[MAILER] auth fail (controlla app password 16-char senza spazi): %s",
            exc,
        )
    except smtplib.SMTPRecipientsRefused as exc:
        _log.error("[MAILER] destinatario rifiutato: %s", exc)
    except smtplib.SMTPException as exc:
        _log.error("[MAILER] SMTP error: %s: %s", type(exc).__name__, exc)
    except (TimeoutError, ConnectionError, OSError) as exc:
        _log.error("[MAILER] network error: %s: %s", type(exc).__name__, exc)
    except Exception as exc:   # last resort
        _log.error("[MAILER] errore imprevisto: %s: %s", type(exc).__name__, exc)
    return False


# CLI test: `python -m shared.mailer --send --to dest@example.com --from mitt@x.com`
# Senza --to / --from legge da config/global_config.json::notifications
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    p = argparse.ArgumentParser(
        description="Test invio mail SMTP. Default destinatari/mittente "
                    "letti da global_config.json::notifications."
    )
    p.add_argument("--to", default=None,
                   help="Destinatario (default: globali.notifications.recipients)")
    p.add_argument("--from", dest="from_addr", default=None,
                   help="Mittente (default: globali.notifications.from_addr "
                        "o env DOOMSDAY_GMAIL_FROM)")
    p.add_argument("--subj", default="[Doomsday] Test mailer",
                   help="Subject")
    p.add_argument("--body", default="Test invio dal bot Doomsday Engine V6.",
                   help="Body plain text")
    p.add_argument("--html", default=None, help="Body HTML opzionale")
    p.add_argument("--send", action="store_true",
                   help="Invia davvero (richiede env var app password). "
                        "Senza questo flag fa solo dry-run di validazione config.")
    args = p.parse_args()

    # Risolvi da config (merge baseline + runtime_overrides) se arg non passati
    cfg_recipients: list[str] = []
    cfg_from = ""
    try:
        from config.config_loader import load_effective_notifications
        cfg = load_effective_notifications()
        cfg_recipients = cfg.get("recipients", []) or []
        cfg_from = cfg.get("from_addr", "") or ""
    except Exception as exc:
        print(f"[WARN] load config: {exc}")

    to = args.to or (cfg_recipients[0] if cfg_recipients else "")
    sender = (args.from_addr
              or cfg_from
              or os.environ.get("DOOMSDAY_GMAIL_FROM", ""))

    if not args.send:
        try:
            from shared.secrets import load_app_password
            app_pw = load_app_password()
        except Exception:
            app_pw = os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "")
        host = os.environ.get("DOOMSDAY_SMTP_HOST", "") or DEFAULT_SMTP_HOST
        port = os.environ.get("DOOMSDAY_SMTP_PORT", "") or DEFAULT_SMTP_PORT
        print("[DRY-RUN] config rilevata:")
        print(f"  from   = {sender or '(MANCANTE)'}")
        print(f"  to     = {to or '(MANCANTE)'}")
        print(f"  host   = {host}:{port}")
        print(f"  app_pw = {'set (len=' + str(len(app_pw)) + ')' if app_pw else 'NON SETTATA'}")
        print(f"  subj   = {args.subj}")
        missing = []
        if not sender: missing.append("from_addr")
        if not to: missing.append("to")
        if not app_pw: missing.append("DOOMSDAY_GMAIL_APP_PASSWORD")
        if missing:
            print(f"[DRY-RUN] MANCANO: {', '.join(missing)}")
            raise SystemExit(1)
        print("[DRY-RUN] config OK — usa --send per inviare davvero")
        raise SystemExit(0)

    if not to:
        print("[ERROR] nessun destinatario (passa --to o configura recipients in dashboard)")
        raise SystemExit(2)

    ok = send_email(to, args.subj, args.body, html=args.html, from_addr=sender)
    print("OK" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
