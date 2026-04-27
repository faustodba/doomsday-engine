# ==============================================================================
#  DOOMSDAY ENGINE V6 - shared/rifornimento_base.py
#
#  Logica condivisa tra rifornimento.py (lista Membri) e
#  rifornimento_mappa.py (navigazione mappa).
#
#  Funzioni:
#    vai_abilitato()       — True se pulsante VAI è giallo
#    leggi_provviste()     — legge provviste giornaliere rimanenti (OCR)
#    leggi_tassa()         — legge tassa invio dalla maschera (OCR)
#    leggi_eta()           — legge ETA viaggio dalla maschera (OCR)
#    leggi_capacita_camion()— legge capacità massima camion (OCR)
#    verifica_destinatario()— verifica nome OCR vs atteso
#    compila_e_invia()     — compila la maschera e preme VAI
#
#  Costanti:
#    COORD_CAMPO, COORD_VAI, OCR_*, VAI_*, QTA_DEFAULT, TASSA_DEFAULT
#
#  Design:
#    - Input: Screenshot (da core.device) — nessun file su disco
#    - Async: compila_e_invia richiede device per tap/screenshot
#    - Nessuna dipendenza da state.py o logger.py — logging opzionale via callback
#    - Porta V5 _compila_e_invia(), _leggi_*(), _vai_abilitato()
# ==============================================================================

from __future__ import annotations

import asyncio
import re
from typing import NamedTuple, TYPE_CHECKING

import cv2
import numpy as np

from shared.ocr_helpers import (
    estrai_numero,
    ocr_intero,
    ocr_zona,
    prepara_crema,
    prepara_otsu,
)

if TYPE_CHECKING:
    from core.device import MuMuDevice, FakeDevice, Screenshot


# ==============================================================================
# Costanti — coordinate maschera invio risorse (960x540)
# ==============================================================================

# Campi quantità nella maschera (calibrati da screenshot reali V5)
COORD_CAMPO: dict[str, tuple[int, int]] = {
    "pomodoro": (757, 224),
    "legno":    (757, 274),
    "acciaio":  (757, 325),
    "petrolio": (757, 375),
}

COORD_VAI: tuple[int, int] = (480, 448)   # pulsante VAI

# Zone OCR nella maschera
OCR_NOME_DEST:        tuple[int, int, int, int] = (265, 90,  620, 138)  # nome destinatario
OCR_DAILY_RECV_LIMIT: tuple[int, int, int, int] = (547, 146, 666, 173)  # "Daily Receiving Limit" — cap intake destinatario
OCR_PROVVISTE:        tuple[int, int, int, int] = (155, 230, 360, 262)  # "Today's Remaining Supplies" — cap output mittente
OCR_TASSA:            tuple[int, int, int, int] = (155, 272, 310, 298)  # "Tasse: 23.0%"
OCR_CAMION:           tuple[int, int, int, int] = (155, 340, 395, 385)  # "0/1,200,000"
OCR_TEMPO:            tuple[int, int, int, int] = (350, 398, 620, 438)  # ETA "00:00:54"

# Zona pulsante VAI (per rilevamento colore giallo)
VAI_ZONA: tuple[int, int, int, int] = (270, 420, 690, 480)

# Soglia pixel gialli per considerare VAI abilitato
VAI_SOGLIA_GIALLI: int = 100

# Tassa default se OCR fallisce
TASSA_DEFAULT: float = 0.24

# Quantità default per singolo invio (unità assolute)
QTA_DEFAULT: dict[str, int] = {
    "pomodoro": 1_000_000,
    "legno":    1_000_000,
    "acciaio":  0,
    "petrolio": 0,
}


# ==============================================================================
# Risultato compila_e_invia
# ==============================================================================

class InvioResult(NamedTuple):
    """Risultato dell'operazione compila_e_invia."""
    ok:              bool    # True se VAI premuto con successo
    eta_sec:         int     # secondi ETA viaggio (0 se non letto)
    quota_esaurita:  bool    # True se provviste = 0
    qta_inviata:     int     # quantità compilata (0 se nulla)
    mismatch_nome:   bool    # True se destinatario OCR ≠ atteso


# ==============================================================================
# Rilevamento stato pulsante VAI
# ==============================================================================

def vai_abilitato(screenshot: "Screenshot") -> bool:
    """
    True se il pulsante VAI è giallo (abilitato).
    False se grigio (disabilitato / campi vuoti / provviste esaurite).

    Logica: conta pixel gialli (R>160, G>120, B<90) nella zona VAI_ZONA.
    Porta la funzione _vai_abilitato() del V5 su Screenshot.
    """
    try:
        arr = screenshot.array  # BGR
        x1, y1, x2, y2 = VAI_ZONA
        roi = arr[y1:y2, x1:x2]
        # BGR: B<90, G>120, R>160
        yellow = (
            (roi[:, :, 2] > 160) &   # R
            (roi[:, :, 1] > 120) &   # G
            (roi[:, :, 0] < 90)      # B
        )
        return int(yellow.sum()) > VAI_SOGLIA_GIALLI
    except Exception:
        return False


# ==============================================================================
# Lettura dati dalla maschera (OCR)
# ==============================================================================

def leggi_provviste(screenshot: "Screenshot") -> int:
    """
    Legge 'Today's Remaining Supplies' dalla maschera (cap output del MITTENTE).

    Returns:
        Valore intero (≥ 0), oppure -1 se OCR fallisce.
    """
    testo = ocr_intero(screenshot, OCR_PROVVISTE, preprocessor="otsu")
    val = estrai_numero(testo)
    if val is None:
        return -1
    return val


def leggi_daily_recv_limit(screenshot: "Screenshot") -> int:
    """
    Legge 'Daily Receiving Limit' dalla maschera — capacità giornaliera residua
    del DESTINATARIO (FauMorfeus) di accettare risorse oggi.

    Valore globale: tutte le istanze inviano alla stessa Morfeus, vedono lo
    stesso numero. Quando arriva a 0 → spedizioni inutili (bloccate dal gioco).

    Returns:
        Valore intero (≥ 0), oppure -1 se OCR fallisce.
    """
    testo = ocr_intero(screenshot, OCR_DAILY_RECV_LIMIT, preprocessor="otsu")
    val = estrai_numero(testo)
    if val is None:
        return -1
    return val


def leggi_tassa(screenshot: "Screenshot") -> float:
    """
    Legge la percentuale di tassa dalla maschera (es. 'Tasse: 23.0%' → 0.23).

    Returns:
        Float 0.0–1.0, TASSA_DEFAULT se OCR fallisce.
    """
    testo = ocr_zona(screenshot, OCR_TASSA, preprocessor="otsu")
    m = re.search(r"([0-9]+\.?[0-9]*)\s*%", testo)
    if m:
        try:
            return float(m.group(1)) / 100.0
        except ValueError:
            pass
    return TASSA_DEFAULT


def leggi_eta(screenshot: "Screenshot") -> int:
    """
    Legge ETA viaggio dalla maschera (es. '00:00:54' → 54).

    Returns:
        Secondi totali (≥ 0), 0 se OCR fallisce.
    """
    testo = ocr_zona(screenshot, OCR_TEMPO, preprocessor="otsu")
    parti = re.sub(r"[^0-9:]", "", testo).split(":")
    try:
        if len(parti) == 3:
            return int(parti[0]) * 3600 + int(parti[1]) * 60 + int(parti[2])
        if len(parti) == 2:
            return int(parti[0]) * 60 + int(parti[1])
    except (ValueError, IndexError):
        pass
    return 0


def leggi_capacita_camion(screenshot: "Screenshot") -> int:
    """
    Legge la capacità massima del camion (es. '0/1,200,000' → 1200000).

    Returns:
        Intero ≥ 0, 0 se OCR fallisce.
    """
    testo = ocr_zona(screenshot, OCR_CAMION, preprocessor="crema")
    if "/" in testo:
        testo = testo.split("/")[-1]
    val = estrai_numero(testo)
    return val if val is not None else 0


def verifica_destinatario(screenshot: "Screenshot", nome_atteso: str) -> tuple[bool, str]:
    """
    Verifica che il nome nella maschera corrisponda al destinatario atteso.
    Confronto case-insensitive con match parziale (nome_atteso in testo_ocr).

    Returns:
        (ok: bool, testo_ocr_pulito: str)
    """
    testo = ocr_zona(screenshot, OCR_NOME_DEST, preprocessor="otsu")
    testo = testo.replace("|", "").replace("_", "").replace("=", "").strip()
    ok = nome_atteso.lower() in testo.lower()
    return ok, testo


# ==============================================================================
# compila_e_invia — logica principale maschera
# ==============================================================================

async def compila_e_invia(
    device: "MuMuDevice | FakeDevice",
    quantita: dict[str, int],
    nome_dest: str = "",
    log_fn=None,
) -> InvioResult:
    """
    Legge la maschera rifornimento, verifica destinatario, compila una
    risorsa e preme VAI.

    Args:
        device:    device ADB dell'istanza
        quantita:  dict {risorsa: quantità_da_inviare} — es. {"pomodoro": 1_000_000}
        nome_dest: nome destinatario atteso (stringa vuota = skip verifica)
        log_fn:    callable opzionale per log: log_fn("msg") → None

    Returns:
        InvioResult con esito dettagliato.
    """
    def log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    _nf = InvioResult(ok=False, eta_sec=0, quota_esaurita=False,
                      qta_inviata=0, mismatch_nome=False)

    # ── Screenshot iniziale ───────────────────────────────────────────────────
    shot = await device.screenshot()

    # ── Verifica nome destinatario ────────────────────────────────────────────
    if nome_dest:
        ok_nome, testo_ocr = verifica_destinatario(shot, nome_dest)
        if not ok_nome:
            log(f"DEST MISMATCH: OCR='{testo_ocr}' atteso='{nome_dest}' — ABORT")
            await device.back()
            await asyncio.sleep(0.8)
            return InvioResult(ok=False, eta_sec=0, quota_esaurita=False,
                               qta_inviata=0, mismatch_nome=True)

    # ── Leggi dati maschera ───────────────────────────────────────────────────
    tassa    = leggi_tassa(shot)
    provviste = leggi_provviste(shot)
    eta_sec  = leggi_eta(shot)
    log(f"Tassa: {tassa*100:.1f}%  Provviste: {provviste}  ETA: {eta_sec}s")

    if provviste == 0:
        log("Provviste giornaliere esaurite")
        await device.back()
        await asyncio.sleep(0.8)
        return InvioResult(ok=False, eta_sec=0, quota_esaurita=True,
                           qta_inviata=0, mismatch_nome=False)

    # ── Seleziona risorsa da inviare ──────────────────────────────────────────
    risorsa_scelta: str | None = None
    qta_scelta: int = 0

    for risorsa, qta in quantita.items():
        if qta <= 0:
            continue
        if risorsa not in COORD_CAMPO:
            continue
        risorsa_scelta = risorsa
        qta_scelta     = qta
        break  # una sola risorsa per viaggio

    if not risorsa_scelta:
        log("Nessuna risorsa da compilare")
        return _nf

    log(f"Compila {risorsa_scelta}: {qta_scelta:,}")

    # ── Compila campo quantità ────────────────────────────────────────────────
    coord = COORD_CAMPO[risorsa_scelta]
    await device.tap(*coord)
    await asyncio.sleep(0.3)
    await device.tap(*coord)
    await asyncio.sleep(0.6)

    # Cancella valore precedente (12 DEL)
    for _ in range(12):
        await device.keyevent("KEYCODE_DEL")
    await asyncio.sleep(0.3)

    await device.input_text(str(qta_scelta))
    await asyncio.sleep(0.5)
    await device.keyevent("KEYCODE_ENTER")
    await asyncio.sleep(0.5)

    # ── Verifica VAI abilitato ────────────────────────────────────────────────
    shot2 = await device.screenshot()
    if not vai_abilitato(shot2):
        log("VAI non abilitato dopo compilazione")
        provviste2 = leggi_provviste(shot2)
        if provviste2 == 0:
            log("Provviste esaurite dopo compilazione")
            await device.back()
            await asyncio.sleep(0.8)
            return InvioResult(ok=False, eta_sec=eta_sec, quota_esaurita=True,
                               qta_inviata=0, mismatch_nome=False)
        log("VAI disabilitato — annullo")
        await device.back()
        return _nf

    # ── Tap VAI ───────────────────────────────────────────────────────────────
    log("Tap VAI")
    await device.tap(*COORD_VAI)
    await asyncio.sleep(2.5)

    return InvioResult(ok=True, eta_sec=eta_sec, quota_esaurita=False,
                       qta_inviata=qta_scelta, mismatch_nome=False)
