"""core/notifier.py — queue persistente email + dispatcher async.

STEP B del modulo Email Notifier (memoria `project_email_notifier.md`).

Scope:
  - Persistenza queue su `data/mail_queue.jsonl` (append-only, atomic)
  - Retry automatico al ripristino connessione (exponential backoff)
  - Retention 7gg per messaggi pending; sent/failed_perm 24h come audit
  - Dispatcher one-shot + thread background opzionale

Non in scope (step successivi):
  - Schema config dashboard (Step C)
  - Daily report builder (Step D)
  - Scheduler 1×/die (Step E)

API principale:
    from core.notifier import enqueue_email, dispatch_pending, start_dispatcher

    # Aggiungi mail in queue (no blocco rete, scrive solo file)
    # `to` lista letta da config.notifications.recipients dal caller.
    enqueue_email(to=["dest@example.com"],
                  subj="[Doomsday] alert", body="...")

    # Dispatch sincrono (per test/cron):
    stats = dispatch_pending()
    # stats = {"sent": N, "retry": N, "failed_perm": N, "expired": N}

    # Background thread (lifecycle bot):
    start_dispatcher(interval_s=60)
    stop_dispatcher()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

_log = logging.getLogger(__name__)

# ─── Config retention/retry ────────────────────────────────────────────────

MAX_ATTEMPTS         = 5
RETRY_BACKOFF_S      = (60, 300, 900, 3600, 14400)   # 1m, 5m, 15m, 1h, 4h
RETENTION_PENDING_D  = 7      # scarta pending dopo 7gg (status=expired)
RETENTION_AUDIT_D    = 1      # mantiene sent/failed_perm/expired 24h come audit
DEFAULT_INTERVAL_S   = 60     # dispatch ogni 60s in background

STATUS_PENDING     = "pending"
STATUS_SENT        = "sent"
STATUS_FAILED_PERM = "failed_perm"
STATUS_EXPIRED     = "expired"

# ─── Storage path ──────────────────────────────────────────────────────────

def _root() -> Path:
    env = os.environ.get("DOOMSDAY_ROOT")
    if env and Path(env).exists():
        return Path(env)
    return Path(__file__).resolve().parents[1]


def _queue_path() -> Path:
    return _root() / "data" / "mail_queue.jsonl"


# ─── Locks (thread-safe per file IO + dispatcher state) ────────────────────

_io_lock = threading.Lock()
_disp_lock = threading.Lock()
_disp_thread: Optional[threading.Thread] = None
_disp_stop_event = threading.Event()


# ─── Helpers tempo ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ─── IO helpers (atomic) ───────────────────────────────────────────────────

def _read_all() -> list[dict]:
    p = _queue_path()
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    _log.warning("[NOTIFIER] riga corrotta scartata: %s", line[:80])
    except Exception as exc:
        _log.error("[NOTIFIER] lettura queue fallita: %s", exc)
    return out


def _write_all_atomic(records: list[dict]) -> None:
    p = _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, p)
    except Exception as exc:
        _log.error("[NOTIFIER] scrittura queue fallita: %s", exc)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _append_atomic(record: dict) -> None:
    """Append singolo record, atomic via lock + flush."""
    p = _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass


# ─── API: enqueue ──────────────────────────────────────────────────────────

def enqueue_email(to: Union[str, list[str]],
                  subj: str,
                  body: str,
                  html: Optional[str] = None,
                  from_addr: Optional[str] = None) -> str:
    """Aggiunge una mail alla queue. NON blocca su rete.

    Args:
        from_addr: opzionale. Se None, dispatcher al momento dell'invio
                   leggerà `from_addr` dalla config corrente.

    Returns: id del record (uuid4 hex). Utile per tracking esterno.
    """
    if isinstance(to, str):
        to_list = [a.strip() for a in to.split(",") if a.strip()]
    else:
        to_list = [a.strip() for a in to if a and a.strip()]
    if not to_list:
        raise ValueError("destinatario vuoto")

    record = {
        "id": uuid.uuid4().hex,
        "ts_enqueue": _now_iso(),
        "ts_last_attempt": None,
        "attempts": 0,
        "to": to_list,
        "from_addr": from_addr or "",   # "" = legge da config al dispatch
        "subj": subj,
        "body": body,
        "html": html,
        "status": STATUS_PENDING,
        "last_error": None,
    }
    with _io_lock:
        _append_atomic(record)
    _log.info("[NOTIFIER] enqueue id=%s to=%s from=%s subj=%r",
              record["id"], to_list, record["from_addr"] or "(config)", subj)
    return record["id"]


# ─── API: dispatch ─────────────────────────────────────────────────────────

def _next_retry_at(record: dict) -> Optional[datetime]:
    """Calcola il prossimo tempo retry. None se eligible subito."""
    last = _parse_iso(record.get("ts_last_attempt") or "")
    if last is None:
        return None
    n = int(record.get("attempts", 0))
    if n <= 0:
        return None
    idx = min(n - 1, len(RETRY_BACKOFF_S) - 1)
    delay = RETRY_BACKOFF_S[idx]
    return last + timedelta(seconds=delay)


def _is_eligible(record: dict, now: datetime) -> bool:
    """True se record pending e non in cooldown backoff."""
    if record.get("status") != STATUS_PENDING:
        return False
    nxt = _next_retry_at(record)
    if nxt is None:
        return True
    return now >= nxt


def _is_expired(record: dict, now: datetime) -> bool:
    """True se pending da > RETENTION_PENDING_D."""
    if record.get("status") != STATUS_PENDING:
        return False
    enq = _parse_iso(record.get("ts_enqueue") or "")
    if enq is None:
        return True   # corrotto → scarta
    return (now - enq).days >= RETENTION_PENDING_D


def _audit_to_purge(record: dict, now: datetime) -> bool:
    """True se sent/failed_perm/expired da > RETENTION_AUDIT_D."""
    status = record.get("status")
    if status not in (STATUS_SENT, STATUS_FAILED_PERM, STATUS_EXPIRED):
        return False
    last = _parse_iso(record.get("ts_last_attempt") or
                       record.get("ts_enqueue") or "")
    if last is None:
        return True
    return (now - last).days >= RETENTION_AUDIT_D


def dispatch_pending() -> dict:
    """Tenta invio di tutti i pending eligible. Aggiorna queue.

    Returns: dict con conteggi {"sent", "retry", "failed_perm", "expired",
                                  "skipped_cooldown", "purged_audit"}.
    """
    from shared.mailer import send_email   # lazy import (evita ciclo)

    now = datetime.now(timezone.utc)
    stats = {"sent": 0, "retry": 0, "failed_perm": 0, "expired": 0,
             "skipped_cooldown": 0, "purged_audit": 0}

    with _io_lock:
        records = _read_all()

    new_records: list[dict] = []
    for r in records:
        # 1) Audit cleanup
        if _audit_to_purge(r, now):
            stats["purged_audit"] += 1
            continue

        # 2) Pending → check expired prima di tentare
        if r.get("status") == STATUS_PENDING:
            if _is_expired(r, now):
                r["status"] = STATUS_EXPIRED
                r["last_error"] = "retention 7gg superata"
                stats["expired"] += 1
                _log.warning("[NOTIFIER] expired id=%s", r.get("id"))
                new_records.append(r)
                continue

            if not _is_eligible(r, now):
                stats["skipped_cooldown"] += 1
                new_records.append(r)
                continue

            # 3) Tenta invio (rilascia lock IO durante chiamata SMTP per non
            #    bloccare enqueue concorrenti — il send_email può durare s).
            #    from_addr: priorità record > config corrente.
            ok = False
            err: Optional[str] = None
            from_addr = (r.get("from_addr") or "").strip()
            if not from_addr:
                try:
                    from config.config_loader import load_effective_notifications
                    from_addr = load_effective_notifications().get("from_addr", "")
                except Exception:
                    from_addr = ""
            try:
                ok = send_email(r["to"], r["subj"], r["body"],
                                html=r.get("html"),
                                from_addr=from_addr or None)
            except Exception as exc:   # safety net
                err = f"{type(exc).__name__}: {exc}"
                ok = False

            r["attempts"] = int(r.get("attempts", 0)) + 1
            r["ts_last_attempt"] = _now_iso()
            if ok:
                r["status"] = STATUS_SENT
                r["last_error"] = None
                stats["sent"] += 1
                _log.info("[NOTIFIER] sent id=%s attempts=%d",
                          r.get("id"), r["attempts"])
            else:
                r["last_error"] = err or "send_email returned False"
                if r["attempts"] >= MAX_ATTEMPTS:
                    r["status"] = STATUS_FAILED_PERM
                    stats["failed_perm"] += 1
                    _log.error("[NOTIFIER] failed_perm id=%s attempts=%d",
                               r.get("id"), r["attempts"])
                else:
                    stats["retry"] += 1
                    _log.warning("[NOTIFIER] retry id=%s attempts=%d/%d",
                                 r.get("id"), r["attempts"], MAX_ATTEMPTS)
            new_records.append(r)
        else:
            # status terminale (sent/failed_perm/expired) → conserva per audit
            new_records.append(r)

    # Riscrivi queue compattata
    with _io_lock:
        _write_all_atomic(new_records)

    return stats


def queue_stats() -> dict:
    """Conteggi correnti per status nella queue. Best-effort, no lock heavy."""
    records = _read_all()
    counts = {STATUS_PENDING: 0, STATUS_SENT: 0,
              STATUS_FAILED_PERM: 0, STATUS_EXPIRED: 0}
    for r in records:
        s = r.get("status")
        if s in counts:
            counts[s] += 1
    counts["total"] = len(records)
    return counts


# ─── Background dispatcher thread ──────────────────────────────────────────

def _dispatcher_loop(interval_s: int) -> None:
    _log.info("[NOTIFIER] dispatcher avviato (interval=%ds)", interval_s)
    while not _disp_stop_event.is_set():
        try:
            stats = dispatch_pending()
            if stats["sent"] or stats["failed_perm"] or stats["expired"]:
                _log.info("[NOTIFIER] tick stats=%s", stats)
        except Exception as exc:
            _log.error("[NOTIFIER] dispatcher tick error: %s", exc)
        # Wait con check stop event ogni secondo (responsive a stop)
        for _ in range(interval_s):
            if _disp_stop_event.is_set():
                break
            time.sleep(1)
    _log.info("[NOTIFIER] dispatcher fermato")


def start_dispatcher(interval_s: int = DEFAULT_INTERVAL_S) -> bool:
    """Avvia thread background. No-op se già attivo. Returns True se avviato."""
    global _disp_thread
    with _disp_lock:
        if _disp_thread is not None and _disp_thread.is_alive():
            _log.info("[NOTIFIER] dispatcher già attivo")
            return False
        _disp_stop_event.clear()
        _disp_thread = threading.Thread(
            target=_dispatcher_loop, args=(interval_s,),
            name="MailNotifierDispatcher", daemon=True,
        )
        _disp_thread.start()
        return True


def stop_dispatcher(timeout_s: float = 5.0) -> bool:
    """Ferma thread background. Returns True se fermato pulito."""
    global _disp_thread
    with _disp_lock:
        if _disp_thread is None or not _disp_thread.is_alive():
            return True
        _disp_stop_event.set()
        _disp_thread.join(timeout=timeout_s)
        alive = _disp_thread.is_alive()
        if not alive:
            _disp_thread = None
        return not alive


# ─── CLI test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    p = argparse.ArgumentParser(description="Test queue email notifier.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_enq = sub.add_parser("enqueue", help="Aggiungi mail di test alla queue")
    p_enq.add_argument("--to", default=None,
                        help="Destinatario (default: legge da "
                             "globali.notifications.recipients)")
    p_enq.add_argument("--subj", default="[Doomsday] notifier test")
    p_enq.add_argument("--body", default="Test notifier step B")

    sub.add_parser("dispatch", help="Esegue dispatch_pending() one-shot")
    sub.add_parser("stats", help="Conteggi queue per status")

    args = p.parse_args()

    if args.cmd == "enqueue":
        to = args.to
        if not to:
            try:
                from config.config_loader import load_effective_notifications
                recs = load_effective_notifications().get("recipients", [])
                to = recs[0] if recs else None
            except Exception:
                to = None
        if not to:
            print("[ERROR] nessun destinatario (passa --to o configura "
                  "recipients in dashboard)")
            raise SystemExit(2)
        rec_id = enqueue_email(to, args.subj, args.body)
        print(f"enqueued id={rec_id}")
    elif args.cmd == "dispatch":
        stats = dispatch_pending()
        print(f"dispatch stats: {stats}")
    elif args.cmd == "stats":
        print(queue_stats())
