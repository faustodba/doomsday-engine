"""shared/telegram_client.py — thin Telegram Bot API client (stdlib urllib only).

Nessuna dipendenza esterna. Usa long-polling getUpdates + sendMessage.

Storage segreti in `data/secrets.json` (stesso file di Gmail app password):
    {
      "telegram_bot_token": "123456:ABC...",
      "telegram_chat_id":   "987654321"
    }

API pubblica:
    send_message(chat_id, text, parse_mode='HTML', token=None) -> bool
    get_updates(offset, timeout_s, token) -> list[dict]
    get_me(token) -> Optional[dict]
    load_token() -> str
    save_token(token) -> bool
    has_token() -> bool
    load_chat_id() -> str
    save_chat_id(chat_id) -> bool

CLI:
    python -m shared.telegram_client --set-token TOKEN
    python -m shared.telegram_client --set-chat CHAT_ID
    python -m shared.telegram_client --test "messaggio"
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_TG_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_KEY_TOKEN   = "telegram_bot_token"
_KEY_CHAT_ID = "telegram_chat_id"
_TIMEOUT_HTTP = 30  # secondi per richieste non-polling


# ─── Path helpers ─────────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _secrets_path() -> Path:
    return _root() / "data" / "secrets.json"


def _read_secrets() -> dict:
    p = _secrets_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("[TG-CLIENT] read secrets fallito: %s", exc)
        return {}


def _write_secrets(data: dict) -> bool:
    p = _secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.error("[TG-CLIENT] write secrets fallito: %s", exc)
        return False


# ─── Token & chat_id storage ─────────────────────────────────────────────────

def load_token() -> str:
    """Ritorna bot token. Priorità: secrets.json > env var DOOMSDAY_TG_TOKEN > ''."""
    t = (_read_secrets().get(_KEY_TOKEN) or "").strip()
    if t:
        return t
    return os.environ.get("DOOMSDAY_TG_TOKEN", "").strip()


def save_token(token: str) -> bool:
    """Salva token in secrets.json. Stringa vuota = rimuove chiave."""
    token = (token or "").strip()
    data = _read_secrets()
    if token:
        data[_KEY_TOKEN] = token
    else:
        data.pop(_KEY_TOKEN, None)
    return _write_secrets(data)


def has_token() -> bool:
    return bool(load_token())


def load_chat_id() -> str:
    """Ritorna chat_id configurato. Stringa vuota se non configurato."""
    cid = (_read_secrets().get(_KEY_CHAT_ID) or "").strip()
    if cid:
        return cid
    return os.environ.get("DOOMSDAY_TG_CHAT_ID", "").strip()


def save_chat_id(chat_id: str) -> bool:
    """Salva chat_id in secrets.json."""
    chat_id = str(chat_id or "").strip()
    data = _read_secrets()
    if chat_id:
        data[_KEY_CHAT_ID] = chat_id
    else:
        data.pop(_KEY_CHAT_ID, None)
    return _write_secrets(data)


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _api_url(token: str, method: str) -> str:
    return _TG_API_BASE.format(token=token, method=method)


def _post_json(url: str, payload: dict, timeout: int = _TIMEOUT_HTTP) -> Optional[dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _log.warning("[TG-CLIENT] HTTP %s %s: %s", exc.code, url, exc.read()[:200])
        return None
    except Exception as exc:
        _log.warning("[TG-CLIENT] request fallita: %s", exc)
        return None


def _get_json(url: str, timeout: int = _TIMEOUT_HTTP) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _log.warning("[TG-CLIENT] GET fallito: %s", exc)
        return None


# ─── Telegram API calls ───────────────────────────────────────────────────────

def send_message(chat_id: str,
                 text: str,
                 parse_mode: str = "HTML",
                 reply_markup: Optional[dict] = None,
                 token: Optional[str] = None) -> Optional[int]:
    """Invia messaggio a chat_id. Ritorna message_id se ok, None altrimenti.

    Args:
        chat_id:      ID chat/user destinatario.
        text:         testo (HTML o plain a seconda di parse_mode).
        parse_mode:   'HTML' | 'Markdown' | '' (plain).
        reply_markup: dict opzionale (es. ForceReply, InlineKeyboard).
        token:        override token (default: load_token()).
    """
    tok = token or load_token()
    if not tok:
        _log.warning("[TG-CLIENT] send_message: token non configurato")
        return None
    if not chat_id:
        _log.warning("[TG-CLIENT] send_message: chat_id non configurato")
        return None

    payload: dict = {"chat_id": str(chat_id), "text": text[:4096]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        import json as _json
        payload["reply_markup"] = _json.dumps(reply_markup)

    url = _api_url(tok, "sendMessage")
    resp = _post_json(url, payload)
    if resp and resp.get("ok"):
        return resp.get("result", {}).get("message_id")
    _log.warning("[TG-CLIENT] sendMessage failed: %s", resp)
    return None


def send_force_reply(chat_id: str, prompt: str,
                     token: Optional[str] = None) -> Optional[int]:
    """Invia messaggio con ForceReply — apre automaticamente il campo input.

    Ritorna il message_id del messaggio inviato (usato per tracciare la reply).
    """
    markup = {"force_reply": True, "input_field_placeholder": prompt[:64]}
    return send_message(chat_id, prompt, reply_markup=markup, token=token)


def get_updates(offset: int = 0,
                timeout_s: int = 20,
                token: Optional[str] = None) -> list[dict]:
    """Long-polling getUpdates. Ritorna lista di update dict.

    Args:
        offset:    ID del prossimo update atteso (last_update_id + 1).
        timeout_s: secondi di long-polling (0 = polling puro immediato).
        token:     override token.
    """
    tok = token or load_token()
    if not tok:
        return []

    payload = {
        "offset":  offset,
        "timeout": timeout_s,
        "allowed_updates": ["message"],
    }
    url = _api_url(tok, "getUpdates")
    # timeout HTTP = polling_timeout + 5s margin
    resp = _post_json(url, payload, timeout=timeout_s + 10)
    if resp and resp.get("ok"):
        return resp.get("result", [])
    return []


def get_me(token: Optional[str] = None) -> Optional[dict]:
    """Verifica token via getMe. Ritorna dict bot info o None se token non valido."""
    tok = token or load_token()
    if not tok:
        return None
    url = _api_url(tok, "getMe")
    resp = _get_json(url)
    if resp and resp.get("ok"):
        return resp.get("result")
    return None


# ─── CLI helper ──────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Telegram client CLI")
    parser.add_argument("--set-token", metavar="TOKEN",  help="salva bot token")
    parser.add_argument("--set-chat",  metavar="CHAT_ID", help="salva chat_id")
    parser.add_argument("--test",      metavar="MSG",    help="invia messaggio test")
    parser.add_argument("--status",    action="store_true", help="mostra stato config")
    args = parser.parse_args()

    if args.set_token:
        ok = save_token(args.set_token)
        print(f"Token {'salvato' if ok else 'ERRORE salvataggio'}")

    if args.set_chat:
        ok = save_chat_id(args.set_chat)
        print(f"chat_id {'salvato' if ok else 'ERRORE salvataggio'}")

    if args.status or args.set_token or args.set_chat:
        info = get_me()
        print(f"Token configurato: {has_token()}")
        print(f"Chat ID: {load_chat_id() or '(non configurato)'}")
        if info:
            print(f"Bot: @{info.get('username')} ({info.get('first_name')})")
        else:
            print("Bot: non raggiungibile (token errato o rete)")

    if args.test:
        cid = load_chat_id()
        if not cid:
            print("ERRORE: chat_id non configurato. Usa --set-chat CHAT_ID")
            return
        ok = send_message(cid, args.test)
        print(f"Messaggio {'inviato' if ok else 'FALLITO'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
