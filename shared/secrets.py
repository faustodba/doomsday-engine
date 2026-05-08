"""shared/secrets.py — storage segreti applicativi (file separato).

Step F+ — sposta app password Gmail dalla env var nel batch alla dashboard.

Storage: `data/secrets.json` (NON gitignored il path? — vedi .gitignore;
NON appare in dashboard / get_notifications, solo flag bool `has_password`).

Schema:
    {
      "gmail_app_password": "16-char-app-password",
      "gmail_app_password_set_ts": "ISO UTC"
    }

Priority lookup `load_app_password()`:
  1. `data/secrets.json::gmail_app_password` (preferito, modificabile da dashboard)
  2. env var `DOOMSDAY_GMAIL_APP_PASSWORD` (fallback compat)
  3. "" se mancante (consumer fail con log chiaro)

API:
    from shared.secrets import load_app_password, save_app_password, has_app_password

    pw = load_app_password()              # str (può essere "")
    save_app_password("xxxxxxxx...")      # bool
    has_app_password()                    # bool

Sicurezza:
  - File scritto con permessi atomic (tmp + replace)
  - Mai loggato in chiaro
  - Mai esposto in API GET (solo `has_password: bool`)
  - `.gitignore` esclude `data/secrets.json` (manuale, vedi setup utente)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

_SECRET_KEY_GMAIL = "gmail_app_password"


def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _path() -> Path:
    return _root() / "data" / "secrets.json"


def _read_secrets() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("[SECRETS] read fallito: %s", exc)
        return {}


def _write_secrets(data: dict) -> bool:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        _log.error("[SECRETS] write fallito: %s", exc)
        return False


# ─── Gmail app password ────────────────────────────────────────────────────

def load_app_password() -> str:
    """Ritorna app password Gmail. Priorità: secrets.json > env var > "".

    Mai logga il valore in chiaro.
    """
    pw = (_read_secrets().get(_SECRET_KEY_GMAIL) or "").strip()
    if pw:
        return pw
    return os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "").strip()


def has_app_password() -> bool:
    """True se app password configurata (file o env). NO valore esposto."""
    return bool(load_app_password())


def app_password_source() -> str:
    """'secrets' | 'env' | 'none' — utile per UI dashboard."""
    if (_read_secrets().get(_SECRET_KEY_GMAIL) or "").strip():
        return "secrets"
    if os.environ.get("DOOMSDAY_GMAIL_APP_PASSWORD", "").strip():
        return "env"
    return "none"


def save_app_password(pw: str) -> bool:
    """Salva app password in `data/secrets.json`.

    Args:
        pw: stringa 16 caratteri (Google app password). Stripped.
            Stringa vuota → rimuove il segreto (delete key).

    Returns: True se OK.
    """
    pw = (pw or "").strip()
    data = _read_secrets()
    if pw:
        data[_SECRET_KEY_GMAIL] = pw
        data[f"{_SECRET_KEY_GMAIL}_set_ts"] = datetime.now(timezone.utc).isoformat()
    else:
        data.pop(_SECRET_KEY_GMAIL, None)
        data.pop(f"{_SECRET_KEY_GMAIL}_set_ts", None)
    return _write_secrets(data)
