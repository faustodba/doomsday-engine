# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_log.py
#
#  Endpoint per tail bot.log e logs/FAU_XX.jsonl.
#  Prefix: /api/log
# ==============================================================================

from fastapi import APIRouter

from dashboard.services.log_reader import (
    get_bot_log, get_instance_log,
    get_instance_log_filtered, get_instance_errors,
)

router = APIRouter(prefix="/api/log", tags=["log"])


@router.get("/bot")
def bot_log(n: int = 100):
    """Ultime n righe di bot.log."""
    return {"lines": get_bot_log(n)}


@router.get("/{nome}")
def instance_log(nome: str, n: int = 200,
                 level: str = None, module: str = None):
    """Ultime n entry di logs/FAU_XX.jsonl con filtri opzionali."""
    if level or module:
        return get_instance_log_filtered(nome, n=n,
                                         level=level, module=module)
    return get_instance_log(nome, n)


@router.get("/{nome}/errors")
def instance_errors(nome: str, n: int = 100):
    """Shortcut: solo entry ERROR di FAU_XX.jsonl."""
    return get_instance_errors(nome, n)
