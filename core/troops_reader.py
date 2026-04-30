"""
core/troops_reader.py — Lettura giornaliera del numero totale truppe (1x/die).

WU65 (29/04/2026) — Snapshot quotidiano del campo "Total Squads" da
Commander Info → tab Squads. Storico persistito in
`data/storico_truppe.json` (granularità giornaliera UTC, retention 365gg).
Permette di tracciare la crescita truppe per istanza nel tempo.

Flow (~10s/istanza, 1 volta/die):
    1. HOME → tap Avatar (48, 37)            → COMMANDER INFO
    2. → tap Squads (895, 509)               → pannello Squads
    3. → OCR _ZONE_TOTAL_SQUADS (830,60,945,90)
    4. → append a `data/storico_truppe.json[nome]`
    5. → BACK × 2                            → HOME

Coordinate calibrate su FAU_10 il 29/04. Schermo MuMu 960×540.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Costanti (display 960×540)
# ──────────────────────────────────────────────────────────────────────────────

_TAP_AVATAR     = (48,  37)   # Avatar profilo HOME
_TAP_SQUADS_TAB = (895, 509)  # Tab "Squads" in basso-dx Commander Info

_ZONE_TOTAL_SQUADS = (830, 60, 945, 90)  # x0,y0,x1,y1 — header "Total Squads:"

_DELAY_NAV  = 4.5  # tap → render (allineato a settings_helper PC lento)
_DELAY_BACK = 3.0

_RETENTION_DAYS = 365  # ~1.5KB/istanza/anno

# Sanity OCR — Total Squads atteso 1k..999M
_TOTAL_MIN = 1_000
_TOTAL_MAX = 999_000_000


# ──────────────────────────────────────────────────────────────────────────────
# API pubblica
# ──────────────────────────────────────────────────────────────────────────────

def leggi_truppe_se_necessario(
    ctx,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Esegue il flow di lettura solo se NON già fatto oggi (UTC) per `ctx.instance_name`.
    Returns True se la lettura è stata eseguita o saltata correttamente, False
    se errore.
    PRECONDIZIONE: ctx in HOME stabile.
    POSTCONDIZIONE: ctx torna in HOME (anche su errore).
    """
    log = log_fn or (lambda m: None)
    nome = getattr(ctx, "instance_name", None) or "_unknown"

    if _truppe_lette_oggi(nome):
        log(f"[TROOPS] già lette oggi per {nome} — skip")
        return True

    if ctx.device is None:
        log("[TROOPS] device assente — skip")
        return False

    log(f"[TROOPS] avvio lettura giornaliera per {nome}")
    try:
        # Step 1: tap Avatar → COMMANDER INFO
        log("[TROOPS] tap Avatar (48, 37)")
        ctx.device.tap(*_TAP_AVATAR);     time.sleep(_DELAY_NAV)

        # Step 2: tap Squads → pannello Squads
        log("[TROOPS] tap Squads (895, 509)")
        ctx.device.tap(*_TAP_SQUADS_TAB); time.sleep(_DELAY_NAV)

        # Step 3: OCR Total Squads (cascade otsu→binary, sanity check)
        total = _ocr_total_squads(ctx, log)
        if total is None:
            log("[TROOPS] OCR Total Squads fallito — skip mark, no append")
            ok = False
        else:
            _append_storico(nome, total)
            log(f"[TROOPS] {nome}: total_squads={total:,} — registrato")
            ok = True

        # Step 4: BACK × 2 → HOME (Squads → Commander → HOME)
        for i in (1, 2):
            log(f"[TROOPS] BACK {i}/2")
            ctx.device.back();             time.sleep(_DELAY_BACK)

        return ok

    except Exception as exc:
        log(f"[TROOPS] ERRORE: {exc}")
        # Best effort recovery: 2 BACK comunque per tornare a HOME
        try:
            for _ in (1, 2):
                ctx.device.back(); time.sleep(_DELAY_BACK)
        except Exception:
            pass
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────────

def _storico_path() -> Path:
    """Path di `data/storico_truppe.json` (rispetta env DOOMSDAY_ROOT)."""
    root = os.environ.get("DOOMSDAY_ROOT", os.getcwd())
    return Path(root) / "data" / "storico_truppe.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _truppe_lette_oggi(nome: str) -> bool:
    """True se l'ultima entry storica per `nome` ha `data == oggi UTC`."""
    try:
        path = _storico_path()
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get(nome) or []
        if not entries:
            return False
        return entries[-1].get("data") == _today_utc()
    except Exception:
        return False


def _append_storico(nome: str, total_squads: int) -> None:
    """
    Append snapshot in `data/storico_truppe.json[nome]`. Atomic write.
    Retention: trim entries più vecchie di `_RETENTION_DAYS` giorni.
    """
    try:
        path = _storico_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}

        entries = data.get(nome) or []
        oggi = _today_utc()
        ts   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Se già c'è entry oggi: aggiorna invece di duplicare (idempotenza re-run)
        if entries and entries[-1].get("data") == oggi:
            entries[-1] = {"data": oggi, "total_squads": total_squads, "ts": ts}
        else:
            entries.append({"data": oggi, "total_squads": total_squads, "ts": ts})

        # Retention: drop entries più vecchie di _RETENTION_DAYS
        if len(entries) > _RETENTION_DAYS:
            entries = entries[-_RETENTION_DAYS:]

        data[nome] = entries

        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# OCR
# ──────────────────────────────────────────────────────────────────────────────

def _ocr_total_squads(ctx, log: Callable[[str], None]) -> Optional[int]:
    """
    OCR del campo "Total Squads" con cascade otsu→binary e sanity check.
    Returns int valido o None se entrambi i preprocessor falliscono o
    il valore è fuori range plausibile.
    """
    try:
        from shared.ocr_helpers import ocr_cifre
    except Exception as exc:
        log(f"[TROOPS] import ocr_helpers errore: {exc}")
        return None

    try:
        screen = ctx.device.screenshot()
        if screen is None:
            log("[TROOPS] screenshot None")
            return None
        frame = screen.frame
    except Exception as exc:
        log(f"[TROOPS] screenshot errore: {exc}")
        return None

    for prep in ("otsu", "binary"):
        try:
            txt = ocr_cifre(frame, zone=_ZONE_TOTAL_SQUADS, preprocessor=prep) or ""
        except Exception as exc:
            log(f"[TROOPS] OCR errore (prep={prep}): {exc}")
            continue
        digits = re.sub(r"[^0-9]", "", txt)
        if not digits:
            log(f"[TROOPS] OCR prep={prep} no digits in {txt!r}")
            continue
        try:
            val = int(digits)
        except ValueError:
            log(f"[TROOPS] OCR prep={prep} parse fail su {digits!r}")
            continue
        if _TOTAL_MIN <= val <= _TOTAL_MAX:
            log(f"[TROOPS] OCR prep={prep} -> {val:,}")
            return val
        log(f"[TROOPS] OCR prep={prep} valore {val} fuori range "
            f"[{_TOTAL_MIN:,}..{_TOTAL_MAX:,}]")
    return None
