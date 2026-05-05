# ==============================================================================
#  DOOMSDAY ENGINE V6 — tasks/rifornimento.py                       Step 20
#
#  Invio risorse al rifugio alleato via coordinate mappa (Resource Supply).
#  Unifica la logica di rifornimento_mappa.py + rifornimento_base.py in un
#  unico Task V6 testabile con FakeDevice + FakeMatcher, zero ADB reale.
#
#  Flusso (ottimizzato in mappa — da V5 rifornimento_mappa.py):
#    HOME → Mappa (una sola volta)
#    Loop spedizioni:
#      1. Leggi slot liberi (da ctx.device o iniettato nei test)
#      2. Se slot == 0: aspetta rientro prima spedizione in coda → rileggi
#      3. Leggi deposito risorse → seleziona risorsa sopra soglia
#      4. Centra mappa → tap castello → RESOURCE SUPPLY → compila → VAI
#      5. Registra (timestamp_invio, eta_ar) in coda_volo
#      6. Ripeti fino a saturazione slot o risorse esaurite
#    Fine → ritorna in home, comunica eta_residua ultima spedizione
#
#  FIX 14/04/2026 — da analisi V5 rifornimento_mappa.py + rifornimento_base.py:
#    - _apri_resource_supply(): find() → find_one() (API V6 standard)
#    - run(): deposito non più obbligatorio — se None, letto via OCR in mappa
#             come V5 _leggi_risorse_mappa() (con retry 1 volta)
#    - _compila_e_invia(): aggiunta verifica nome destinatario come V5
#    - Navigazione ritorno HOME: ctx.navigator.vai_in_home() (con fallback key)
#    - Navigazione vai in mappa: ctx.navigator.vai_in_mappa() (con fallback key)
#    - Aggiunte _leggi_deposito_ocr() e _verifica_nome_destinatario_v6()
#    coda_volo[0]  = prima spedizione partita = prima che rientra → libera 1 slot
#    coda_volo[-1] = ultima spedizione partita = ultima che rientra
#
#  COORDINATE DEFAULT (960x540):
#    TAP_LENTE_MAPPA      = (334,  13)   — lente coordinate mappa
#    TAP_CAMPO_X          = (484, 135)   — campo X nella lente
#    TAP_CAMPO_Y          = (601, 135)   — campo Y nella lente
#    TAP_CONFERMA_LENTE   = (670, 135)   — conferma → centra mappa
#    TAP_CASTELLO_CENTER  = (480, 270)   — centro schermo dopo centratura
#    COORD_VAI            = (480, 448)   — pulsante VAI
#    COORD_CAMPO          = {pomodoro:(757,224), legno:(757,274),
#                             acciaio:(757,325),  petrolio:(757,375)}
#    VAI_ZONA             = (270, 420, 690, 480)
#    OCR_PROVVISTE        = (155, 230, 360, 262)
#    OCR_TASSA            = (155, 272, 310, 298)
#    OCR_CAMION           = (155, 340, 395, 385)
#    OCR_TEMPO            = (350, 398, 620, 438)
#
#  CONFIG (ctx.config — chiavi con fallback ai default di modulo):
#    RIFORNIMENTO_MAPPA_ABILITATO        bool   default False
#    RIFORNIMENTO_CAMPO_ABILITATO        bool   default True
#    RIFORNIMENTO_LEGNO_ABILITATO        bool   default True
#    RIFORNIMENTO_ACCIAIO_ABILITATO      bool   default False
#    RIFORNIMENTO_PETROLIO_ABILITATO     bool   default True
#    RIFORNIMENTO_SOGLIA_CAMPO_M         float  default 5.0
#    RIFORNIMENTO_SOGLIA_LEGNO_M         float  default 5.0
#    RIFORNIMENTO_SOGLIA_ACCIAIO_M       float  default 3.5
#    RIFORNIMENTO_SOGLIA_PETROLIO_M      float  default 2.5
#    RIFORNIMENTO_QTA_POMODORO           int    default 1_000_000
#    RIFORNIMENTO_QTA_LEGNO              int    default 1_000_000
#    RIFORNIMENTO_QTA_ACCIAIO            int    default 0
#    RIFORNIMENTO_QTA_PETROLIO           int    default 0
#    RIFORNIMENTO_MAX_SPEDIZIONI_CICLO   int    default 5
#    MARGINE_ATTESA                      int    default 8   (secondi extra)
#    RIFUGIO_X                           int    default 684
#    RIFUGIO_Y                           int    default 532
#    DOOMS_ACCOUNT                       str    default ""
#    TEMPLATE_RESOURCE_SUPPLY            str    default "pin/btn_resource_supply_map.png"
#    TEMPLATE_RESOURCE_SUPPLY_SOGLIA     float  default 0.75
#    VAI_SOGLIA_GIALLI                   int    default 100
#    TASSA_DEFAULT                       float  default 0.24
# ==============================================================================

from __future__ import annotations

import time
import re
from collections import deque
from typing import Optional

import numpy as np

from core.task import Task, TaskContext, TaskResult
from shared.ui_helpers import attendi_template

# ------------------------------------------------------------------------------
# Default costanti UI (960x540)
# ------------------------------------------------------------------------------

_DEFAULTS: dict = {
    # Navigazione mappa
    "TAP_LENTE_MAPPA":      (334,  13),
    "TAP_CAMPO_X":          (484, 135),
    "TAP_CAMPO_Y":          (601, 135),
    "TAP_CONFERMA_LENTE":   (670, 135),
    "TAP_CASTELLO_CENTER":  (480, 270),
    # Maschera invio
    "COORD_VAI":            (480, 448),
    "COORD_CAMPO": {
        "pomodoro": (757, 224),
        "legno":    (757, 274),
        "acciaio":  (757, 325),
        "petrolio": (757, 375),
    },
    # Zone OCR maschera
    # auto-WU12: OCR per leggere valore CLAMPED nel campo input (gioco
    # auto-aggiusta 999_999_999 al massimo disponibile). Stima ±60x ±15y
    # attorno al tap center COORD_CAMPO. Da affinare con screenshot reale.
    "OCR_CAMPO_INPUT": {
        "pomodoro": (690, 208, 825, 240),
        "legno":    (690, 258, 825, 290),
        "acciaio":  (690, 308, 825, 341),
        "petrolio": (690, 358, 825, 391),
    },
    "OCR_PROVVISTE":        (155, 230, 360, 262),
    "OCR_TASSA":            (155, 272, 310, 298),
    "OCR_CAMION":           (155, 340, 395, 385),
    "OCR_TEMPO":            (350, 398, 620, 438),
    "OCR_NOME_DEST":        (265,  90, 620, 138),
    "VAI_ZONA":             (270, 420, 690, 480),
    # Soglie e flag
    "VAI_SOGLIA_GIALLI":                100,
    "TASSA_DEFAULT":                    0.24,
    "MARGINE_ATTESA":                   8,
    "RIFORNIMENTO_MAPPA_ABILITATO":     False,
    "RIFORNIMENTO_MEMBRI_ABILITATO":    False,
    "AVATAR_TEMPLATE":                  "pin/avatar.png",
    "RIFORNIMENTO_CAMPO_ABILITATO":     True,
    "RIFORNIMENTO_LEGNO_ABILITATO":     True,
    "RIFORNIMENTO_ACCIAIO_ABILITATO":   False,
    "RIFORNIMENTO_PETROLIO_ABILITATO":  True,
    "RIFORNIMENTO_SOGLIA_CAMPO_M":      5.0,
    "RIFORNIMENTO_SOGLIA_LEGNO_M":      5.0,
    "RIFORNIMENTO_SOGLIA_ACCIAIO_M":    3.5,
    "RIFORNIMENTO_SOGLIA_PETROLIO_M":   2.5,
    "RIFORNIMENTO_QTA_POMODORO":        1_000_000,
    "RIFORNIMENTO_QTA_LEGNO":           1_000_000,
    "RIFORNIMENTO_QTA_ACCIAIO":         0,
    "RIFORNIMENTO_QTA_PETROLIO":        0,
    "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO": 5,
    # 05/05: target proporzioni per risorsa (analoga raccolta.allocazione).
    # Default uniforme 25/25/25/25. Se utente configura via dashboard
    # (rifornimento.allocazione = {pomodoro:30, legno:30, acciaio:20, petrolio:20}),
    # il bot fa selezione weighted-deficit: gap = ratio_target - perc_att(inviato_oggi).
    # Soglie minime invariate (rispettate da check valore >= soglia).
    "RIFORNIMENTO_ALLOCAZIONE":         None,   # None -> uniforme 25/25/25/25
    "RIFUGIO_X":                        684,
    "RIFUGIO_Y":                        532,
    "DOOMS_ACCOUNT":                    "",
    "TEMPLATE_RESOURCE_SUPPLY":         "pin/btn_resource_supply_map.png",
    "TEMPLATE_RESOURCE_SUPPLY_SOGLIA":  0.75,
}


def _cfg(ctx: TaskContext, key: str):
    """Legge ctx.config con fallback al default di modulo."""
    return ctx.config.get(key, _DEFAULTS[key])


# ------------------------------------------------------------------------------
# OCR helpers — puri (no ADB), testabili con immagini sintetiche
# ------------------------------------------------------------------------------

def _vai_abilitato(screen, vai_zona: tuple,
                   soglia_gialli: int = 100) -> bool:
    """
    True se il pulsante VAI è giallo (abilitato), False se grigio.
    API V6: screen è Screenshot con .frame (BGR numpy array).
    Logica identica a V5 rifornimento_base._vai_abilitato().
    """
    try:
        # screen.frame = BGR numpy array (AdbDevice screenshot)
        arr = screen.frame
        vai = arr[vai_zona[1]:vai_zona[3], vai_zona[0]:vai_zona[2]]
        # BGR: B<90, G>120, R>160 → pixel gialli
        yellow = (arr[vai_zona[1]:vai_zona[3], vai_zona[0]:vai_zona[2], 2] > 160) & \
                 (arr[vai_zona[1]:vai_zona[3], vai_zona[0]:vai_zona[2], 1] > 120) & \
                 (arr[vai_zona[1]:vai_zona[3], vai_zona[0]:vai_zona[2], 0] < 90)
        return int(yellow.sum()) > soglia_gialli
    except Exception:
        return False


def _leggi_provviste(screen, ocr_box: tuple) -> int:
    """
    Legge 'Provviste rimanenti di oggi' dalla maschera.
    Usa shared.rifornimento_base.leggi_provviste() — API V6 con Screenshot.
    """
    try:
        from shared.rifornimento_base import leggi_provviste
        return leggi_provviste(screen)
    except Exception:
        return -1


def _leggi_tassa(screen, ocr_box: tuple, default: float = 0.24) -> float:
    """
    Legge percentuale tassa dalla maschera.
    Usa shared.rifornimento_base.leggi_tassa() — API V6 con Screenshot.
    """
    try:
        from shared.rifornimento_base import leggi_tassa
        return leggi_tassa(screen)
    except Exception:
        return default


def _leggi_eta(screen, ocr_box: tuple) -> int:
    """
    Legge ETA viaggio dalla maschera.
    Usa shared.rifornimento_base.leggi_eta() — API V6 con Screenshot.
    """
    try:
        from shared.rifornimento_base import leggi_eta
        return leggi_eta(screen)
    except Exception:
        return 0


# ------------------------------------------------------------------------------
# Logica coda_volo (pura, zero I/O)
# ------------------------------------------------------------------------------

def _aggiorna_coda(coda_volo: deque) -> None:
    """Rimuove dalla testa le spedizioni certamente già rientrate."""
    now = time.time()
    while coda_volo:
        ts_invio, eta_ar = coda_volo[0]
        if (now - ts_invio) >= eta_ar:
            coda_volo.popleft()
        else:
            break


def _attesa_prima_spedizione(coda_volo: deque, margine: int = 8) -> float:
    """
    Secondi da attendere per il rientro della PRIMA spedizione in coda.
    coda_volo[0] = partita prima = ritorna prima → libera 1 slot.
    """
    if not coda_volo:
        return 0.0
    ts_invio, eta_ar = coda_volo[0]
    return max(0.0, eta_ar - (time.time() - ts_invio)) + margine


def _attesa_ultima_spedizione(coda_volo: deque, margine: int = 8) -> float:
    """
    Secondi da attendere per il rientro dell'ULTIMA spedizione in coda.
    Usato a fine loop per comunicare alla raccolta quanto aspettare.
    """
    if not coda_volo:
        return 0.0
    ts_invio, eta_ar = coda_volo[-1]
    return max(0.0, eta_ar - (time.time() - ts_invio)) + margine


# ------------------------------------------------------------------------------
# Selezione risorsa da inviare
# ------------------------------------------------------------------------------

def _seleziona_risorsa(risorse_reali: dict[str, float],
                        risorse_config: dict[str, int],
                        soglie: dict[str, float],
                        idx_risorsa: int,
                        inviato_oggi: Optional[dict[str, float]] = None,
                        ratio_target: Optional[dict[str, float]] = None,
                        ) -> tuple[Optional[str], int]:
    """
    Selezione risorsa per spedizione rifornimento.

    Modalita' WEIGHTED-DEFICIT (05/05 - default se `inviato_oggi` fornito):
      Algoritmo analogo a raccolta._calcola_sequenza_allocation:
        perc_att[r] = inviato_oggi[r] / sum(inviato_oggi)
        gap[r]      = ratio_target[r] - perc_att[r]
      Sort gap DESC -> priorita' a risorse sotto target. Sceglie la prima
      sopra soglia.

      `ratio_target` (configurabile da dashboard, key `rifornimento.allocazione`):
        - default 25/25/25/25 se non fornito (equita' uniforme)
        - es. 30/30/20/20 se l'utente vuole piu' acciaio/petrolio
        - somma deve essere = 1.0 (frazioni) o 100 (percentuali)

      A inizio giornata (inviato_oggi tutti=0) il gap e' uguale per tutti
      con ratio uniforme, oppure proporzionale alle percentuali config con
      ratio non-uniforme. Stable sort conserva ordine config.

      Soglia minima rispettata: solo risorse con `valore >= soglia_M*1e6`
      sono candidabili. Il deficit-weighting opera SU TOP delle soglie.

    Modalita' ROUND-ROBIN classica (fallback se `inviato_oggi=None`):
      Parte da `idx_risorsa` e itera ciclico. Mantenuto per compat back.

    Ritorna: (risorsa_scelta, nuovo_idx).
    nuovo_idx: in modalita' weighted non e' usato (ritorna 0). Mantenuto per
    compat con call site esistenti.
    """
    risorse_lista = list(risorse_config.keys())
    n = len(risorse_lista)

    # ── Modalita' WEIGHTED-DEFICIT (preferita) ─────────────────────────────
    if inviato_oggi is not None:
        # Default ratio: equita' 25/25/25/25 se non fornito
        if ratio_target is None:
            ratio_target = {r: 1.0 / n for r in risorse_lista}
        else:
            # Normalizza: accetta sia frazioni (somma~1) che percentuali (somma~100)
            tot_ratio = sum(ratio_target.get(r, 0) for r in risorse_lista)
            if tot_ratio > 1.5:   # probabilmente percentuali (es. 35+35+20+10=100)
                ratio_target = {r: ratio_target.get(r, 0) / 100.0
                                for r in risorse_lista}
            elif tot_ratio < 0.01:   # tutti zero, fallback uniforme
                ratio_target = {r: 1.0 / n for r in risorse_lista}

        # Calcola gap = ratio_target - perc_att
        totale_inviato = sum(inviato_oggi.get(r, 0) for r in risorse_lista)
        if totale_inviato <= 0:
            # Nessun invio oggi: gap = ratio_target (sort DESC = ordine ratio)
            # A parita' (es. uniforme) stable sort conserva ordine config -> pom first
            gap = {r: ratio_target.get(r, 0.0) for r in risorse_lista}
        else:
            gap = {}
            for r in risorse_lista:
                perc_att = inviato_oggi.get(r, 0) / totale_inviato
                gap[r] = ratio_target.get(r, 0.0) - perc_att

        # Sort gap DESC: priorita' a risorse sotto target
        ordinate = sorted(risorse_lista, key=lambda r: gap[r], reverse=True)
        for r in ordinate:
            valore = risorse_reali.get(r, -1.0)
            soglia_abs = soglie.get(r, float("inf")) * 1e6
            if valore >= soglia_abs:
                return r, 0   # idx non rilevante in modalita' weighted
        return None, 0

    # ── Modalita' round-robin classica (fallback) ──────────────────────────
    for i in range(n):
        r = risorse_lista[(idx_risorsa + i) % n]
        valore = risorse_reali.get(r, -1.0)
        soglia_abs = soglie.get(r, float("inf")) * 1e6
        if valore >= soglia_abs:
            return r, (idx_risorsa + i + 1) % n
    return None, idx_risorsa


# ------------------------------------------------------------------------------
# Navigazione mappa UI (via ctx.device)
# ------------------------------------------------------------------------------

def _centra_mappa(ctx: TaskContext) -> None:
    """
    Centra la mappa sul rifugio configurato tramite la lente coordinate.
    Usa ctx.device.tap() — testabile con FakeDevice.
    """
    rx = _cfg(ctx, "RIFUGIO_X")
    ry = _cfg(ctx, "RIFUGIO_Y")
    ctx.log_msg(f"Rifornimento: centratura mappa sul rifugio X:{rx} Y:{ry}")

    ctx.device.tap(_cfg(ctx, "TAP_LENTE_MAPPA"))
    time.sleep(1.5)

    ctx.device.tap(_cfg(ctx, "TAP_CAMPO_X"))
    time.sleep(0.4)
    for _ in range(6):
        ctx.device.key("KEYCODE_DEL")
    time.sleep(0.2)
    ctx.device.input_text(str(rx))
    time.sleep(0.4)

    ctx.device.tap(_cfg(ctx, "TAP_CAMPO_Y"))
    time.sleep(0.4)
    for _ in range(6):
        ctx.device.key("KEYCODE_DEL")
    time.sleep(0.2)
    ctx.device.input_text(str(ry))
    time.sleep(0.4)

    ctx.device.tap(_cfg(ctx, "TAP_CONFERMA_LENTE"))
    time.sleep(2.5)

    ctx.device.tap(_cfg(ctx, "TAP_CASTELLO_CENTER"))
    time.sleep(2.0)  # attesa apertura popup castello (da V5)
    ctx.log_msg("Rifornimento: mappa centrata e castello tappato")


def _leggi_deposito_ocr(ctx: TaskContext, risorse_lista: list) -> dict[str, float]:
    """
    Legge il deposito risorse via OCR dalla barra superiore (visibile anche in mappa).
    Speculare a V5 _leggi_risorse_mappa() — usato quando il deposito non è iniettato.
    Usa shared.ocr_helpers.ocr_risorse() — API V6 corretta.
    Ritorna dict {risorsa: valore_assoluto} o {} se OCR fallisce.
    Riprova una volta in caso di fallimento (come V5).
    """
    from shared.ocr_helpers import ocr_risorse

    def _tenta() -> dict:
        screen = ctx.device.screenshot()
        if screen is None:
            return {}
        try:
            risultato = ocr_risorse(screen)
            return {
                "pomodoro": risultato.pomodoro,
                "legno":    risultato.legno,
                "acciaio":  risultato.acciaio,
                "petrolio": risultato.petrolio,
            }
        except Exception as exc:
            ctx.log_msg(f"Rifornimento: OCR deposito eccezione: {exc}")
            return {}

    risorse = _tenta()
    if all(risorse.get(r, -1) < 0 for r in risorse_lista):
        ctx.log_msg("Rifornimento: OCR deposito fallito — retry tra 3s")
        time.sleep(3.0)
        risorse = _tenta()
    return risorse


def _verifica_nome_destinatario_v6(ctx: TaskContext, screen, nome_atteso: str) -> tuple[bool, str]:
    """
    Verifica che il nome nella maschera corrisponda al destinatario atteso.
    Usa shared.rifornimento_base.verifica_destinatario() — API V6 corretta.
    Ritorna (ok, testo_ocr).
    """
    if not nome_atteso:
        return True, ""
    try:
        from shared.rifornimento_base import verifica_destinatario
        return verifica_destinatario(screen, nome_atteso)
    except Exception as exc:
        ctx.log_msg(f"Rifornimento: OCR nome destinatario fallito: {exc} — procedo")
        return True, ""


def _apri_resource_supply(ctx: TaskContext) -> bool:
    """
    Cerca il pulsante RESOURCE SUPPLY via template matching e lo tappa.
    Ritorna True se trovato e tappato, False altrimenti.
    API V6: find_one(screen, path, threshold, zone) — non esiste find().
    """
    screen = ctx.device.screenshot()
    if not screen:
        ctx.log_msg("Rifornimento: screenshot fallito dopo tap castello")
        return False

    template = _cfg(ctx, "TEMPLATE_RESOURCE_SUPPLY")
    soglia   = _cfg(ctx, "TEMPLATE_RESOURCE_SUPPLY_SOGLIA")
    result   = ctx.matcher.find_one(screen, template, threshold=soglia)
    ctx.log_msg(f"Rifornimento: RESOURCE SUPPLY score={result.score:.3f} soglia={soglia}")
    if not result.found:
        ctx.log_msg("Rifornimento: RESOURCE SUPPLY non trovato")
        return False

    ctx.log_msg(f"Rifornimento: RESOURCE SUPPLY trovato ({result.cx},{result.cy}) → tap")
    ctx.device.tap(result.cx, result.cy)
    time.sleep(1.5)  # attesa rendering popup invio risorse
    return True


def _compila_e_invia(ctx: TaskContext, risorsa: str, qta: int,
                      nome_rifugio: str) -> tuple[bool, int, bool, int, int, int]:
    """
    Legge la maschera di invio, compila la risorsa e preme VAI.

    Ritorna: (ok, eta_sec, quota_esaurita, qta_effettiva, qta_lordo, provviste_lette)
      ok=True          → spedizione inviata
      quota_esaurita   → provviste=0, non rientrare nel ciclo oggi
      qta_effettiva    → quantità NETTA arrivata al destinatario (clamped × (1-tassa))
      qta_lordo        → quantità LORDA uscita dal castello (OCR campo input,
                          fallback al valore nominale `qta` se OCR fallisce)
      provviste_lette  → provviste rimanenti lette dalla maschera (-1 se OCR fallito)
    """
    screen = ctx.device.screenshot()
    if not screen:
        return False, 0, False, 0, 0, -1

    # Verifica nome destinatario (come V5 _compila_e_invia in rifornimento_base.py)
    # Retry una volta se OCR restituisce stringa vuota (popup ancora in rendering)
    if nome_rifugio:
        ok_nome, testo_ocr = _verifica_nome_destinatario_v6(ctx, screen, nome_rifugio)
        if not ok_nome and testo_ocr == "":
            ctx.log_msg("Rifornimento: OCR nome vuoto — retry tra 1s")
            time.sleep(1.0)
            screen = ctx.device.screenshot()
            if screen:
                ok_nome, testo_ocr = _verifica_nome_destinatario_v6(ctx, screen, nome_rifugio)
        if not ok_nome:
            ctx.log_msg(
                f"Rifornimento: DEST MISMATCH — OCR='{testo_ocr}' atteso='{nome_rifugio}' → BACK"
            )
            ctx.device.back()
            time.sleep(0.8)
            return False, 0, False, 0, 0, -1

    vai_zona     = _cfg(ctx, "VAI_ZONA")
    soglia_vai   = _cfg(ctx, "VAI_SOGLIA_GIALLI")
    ocr_provv    = _cfg(ctx, "OCR_PROVVISTE")
    ocr_tempo    = _cfg(ctx, "OCR_TEMPO")
    coord_campo  = _cfg(ctx, "COORD_CAMPO")
    coord_vai    = _cfg(ctx, "COORD_VAI")

    # Leggi provviste (mittente)
    provviste = _leggi_provviste(screen, ocr_provv)
    if provviste >= 0:
        ctx.log_msg(f"Rifornimento: provviste rimanenti={provviste:,}")
    else:
        ctx.log_msg("Rifornimento: provviste OCR fallito — procedo")

    # Leggi Daily Receiving Limit del destinatario (cap intake giornaliero
    # FauMorfeus). Valore globale: salvato in data/morfeus_state.json,
    # condiviso tra tutte le istanze, mostrato in dashboard.
    try:
        from shared.rifornimento_base import leggi_daily_recv_limit
        from shared import morfeus_state
        recv_limit = leggi_daily_recv_limit(screen)
        if recv_limit >= 0:
            ctx.log_msg(
                f"Rifornimento: Daily Receiving Limit {nome_rifugio}={recv_limit:,}"
            )
            tassa_pct = None
            try:
                tassa_pct = float(ctx.state.rifornimento.tassa_pct_avg)
            except Exception:
                pass
            morfeus_state.save(
                daily_recv_limit=recv_limit,
                letto_da=ctx.instance_name,
                tassa_pct=tassa_pct,
            )
        else:
            ctx.log_msg("Rifornimento: Daily Receiving Limit OCR fallito — skip salvataggio")
    except Exception as exc:
        ctx.log_msg(f"Rifornimento: errore lettura Daily Receiving Limit: {exc}")

    if provviste == 0:
        ctx.log_msg("Rifornimento: provviste esaurite → stop")
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.8)
        return False, 0, True, 0, 0, 0

    eta_sec = _leggi_eta(screen, ocr_tempo)
    ctx.log_msg(f"Rifornimento: ETA viaggio={eta_sec}s")

    # Compila campo risorsa
    coord = coord_campo.get(risorsa)
    if not coord:
        ctx.log_msg(f"Rifornimento: campo {risorsa} non configurato")
        return False, 0, False, 0, 0, provviste

    ctx.log_msg(f"Rifornimento: compila {risorsa}={qta:,}")

    # Sequenza identica a V5 rifornimento_base._compila_e_invia():
    #   tap1 delay=300ms, tap2 delay=300ms, tap3 delay=600ms → seleziona testo
    ctx.device.tap(coord)
    time.sleep(0.3)
    ctx.device.tap(coord)
    time.sleep(0.3)
    ctx.device.tap(coord)
    time.sleep(0.6)

    # 12 DEL per cancellare valore precedente
    for _ in range(12):
        ctx.device.key("KEYCODE_DEL")
    time.sleep(0.3)

    # Input testo + tap TAP_OK_TASTIERA (879,487) — come V5 config.TAP_OK_TASTIERA
    ctx.device.input_text(str(qta))
    time.sleep(0.5)
    ctx.device.tap(879, 487)
    time.sleep(0.5)

    # Verifica VAI
    screen2 = ctx.device.screenshot()
    if screen2 and not _vai_abilitato(screen2, vai_zona, soglia_vai):
        ctx.log_msg("Rifornimento: VAI non abilitato dopo compilazione")
        provviste2 = _leggi_provviste(screen2, ocr_provv)
        if provviste2 == 0:
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.8)
            return False, 0, True, 0, 0, 0
        ctx.device.key("KEYCODE_BACK")
        return False, 0, False, 0, 0, provviste

    # auto-WU12: leggi valore reale CLAMPED dal campo input + applica tassa.
    # User: "L'input 999_999_999 il sistema auto-aggiusta sul max, e il valore
    # effettivo mandato è (input clamped) - tassa". Tassa è %, formula:
    # qta_effettiva = qta_clamped * (1 - tassa).
    # screen2 è già il post-tap_OK_TASTIERA, contiene il valore clamped.
    qta_effettiva     = qta  # fallback se OCR fallisce
    qta_clamped_real  = qta  # valore totale uscito dal castello
    tassa_amount      = 0
    if screen2 is not None:
        ocr_input_dict = _cfg(ctx, "OCR_CAMPO_INPUT") or {}
        ocr_input_zone = ocr_input_dict.get(risorsa)
        if ocr_input_zone:
            try:
                from shared.ocr_helpers import ocr_intero, estrai_numero
                testo_in = ocr_intero(screen2, ocr_input_zone, preprocessor="otsu")
                qta_clamped = estrai_numero(testo_in)
                tassa_pct  = _leggi_tassa(screen2, _cfg(ctx, "OCR_TASSA"))
                if qta_clamped is not None and qta_clamped > 0:
                    qta_effettiva    = int(qta_clamped * (1.0 - tassa_pct))
                    qta_clamped_real = qta_clamped
                    tassa_amount     = qta_clamped_real - qta_effettiva
                    ctx.log_msg(
                        f"Rifornimento: input clamped={qta_clamped:,} "
                        f"tassa={tassa_pct*100:.1f}% → effettiva={qta_effettiva:,}"
                    )
                else:
                    ctx.log_msg(
                        f"Rifornimento: OCR input fallito (testo='{testo_in}') "
                        f"— fallback qta={qta:,}"
                    )
            except Exception as exc:
                ctx.log_msg(f"Rifornimento: errore OCR input: {exc} — fallback qta={qta:,}")

    ctx.log_msg("Rifornimento: tap VAI")
    ctx.device.tap(coord_vai)
    time.sleep(2.5)

    # auto-WU14 step2: hook produzione corrente
    try:
        if hasattr(ctx, "state") and ctx.state and ctx.state.produzione_corrente:
            ctx.state.produzione_corrente.aggiungi_rifornimento(
                risorsa, qta_clamped_real, tassa_amount
            )
            if provviste >= 0:
                ctx.state.produzione_corrente.rifornimento_provviste_residue = provviste
    except Exception as exc:
        ctx.log_msg(f"[PROD] hook rifornimento: {exc}")

    return True, eta_sec, False, qta_effettiva, qta_clamped_real, provviste


# ------------------------------------------------------------------------------
# Configurazione risorse (da ctx.config)
# ------------------------------------------------------------------------------

def _build_risorse_config(ctx: TaskContext) -> tuple[dict, dict, dict]:
    """
    Legge da ctx.config le risorse abilitate, le soglie e le quantità.
    Ritorna (risorse_config, soglie, abilitati).
    """
    abilitati = {
        "pomodoro": _cfg(ctx, "RIFORNIMENTO_CAMPO_ABILITATO"),
        "legno":    _cfg(ctx, "RIFORNIMENTO_LEGNO_ABILITATO"),
        "acciaio":  _cfg(ctx, "RIFORNIMENTO_ACCIAIO_ABILITATO"),
        "petrolio": _cfg(ctx, "RIFORNIMENTO_PETROLIO_ABILITATO"),
    }
    soglie = {
        "pomodoro": _cfg(ctx, "RIFORNIMENTO_SOGLIA_CAMPO_M"),
        "legno":    _cfg(ctx, "RIFORNIMENTO_SOGLIA_LEGNO_M"),
        "acciaio":  _cfg(ctx, "RIFORNIMENTO_SOGLIA_ACCIAIO_M"),
        "petrolio": _cfg(ctx, "RIFORNIMENTO_SOGLIA_PETROLIO_M"),
    }
    quantita = {
        "pomodoro": _cfg(ctx, "RIFORNIMENTO_QTA_POMODORO"),
        "legno":    _cfg(ctx, "RIFORNIMENTO_QTA_LEGNO"),
        "acciaio":  _cfg(ctx, "RIFORNIMENTO_QTA_ACCIAIO"),
        "petrolio": _cfg(ctx, "RIFORNIMENTO_QTA_PETROLIO"),
    }
    risorse_config = {
        r: q for r, q in quantita.items()
        if q > 0 and abilitati.get(r, True)
    }
    return risorse_config, soglie, abilitati


# ------------------------------------------------------------------------------
# Navigazione via Membri — costanti (da V5 rifornimento.py)
# ------------------------------------------------------------------------------

_COORD_ALLEANZA_BTN  = (760, 505)   # pulsante Alleanza in home
_COORD_MEMBRI        = (46, 188)    # tab Membri nel menu Alleanza

# Swipe lista membri (960x540)
# AVANZARE = swipe verso l'ALTO (dito sale: start basso → end alto)
# SCROLL-TO-TOP = swipe verso il BASSO (dito scende: start alto → end basso)
_SWIPE_SU_X    = 480
_SWIPE_SU_Y1   = 430    # avanza lista: dito parte da basso
_SWIPE_SU_Y2   = 240    # avanza lista: dito arriva in alto
_SWIPE_GIU_X   = 480
_SWIPE_GIU_Y1  = 240    # scroll-to-top: dito parte da alto
_SWIPE_GIU_Y2  = 460    # scroll-to-top: dito arriva in basso

_LISTA_ZONA    = (130, 165, 940, 540)  # zona lista membri (escluso sidebar e header)
_AVATAR_ZONA   = (130, 155, 540, 490)  # zona ricerca avatar

# Template paths (relativi a templates/)
_TMPL_ARROW_DOWN = "pin/arrow_down.png"
_TMPL_ARROW_UP   = "pin/arrow_up.png"
_TMPL_BADGE = {
    "R4": "pin/badge_R4.png",
    "R3": "pin/badge_R3.png",
    "R2": "pin/badge_R2.png",
    "R1": "pin/badge_R1.png",
}
_TMPL_BTN_RISORSE = "pin/btn_risorse_approv.png"

# Soglie template matching (da V5)
_BADGE_SOGLIA       = 0.85
_FRECCIA_SOGLIA     = 0.85
_AVATAR_SOGLIA      = 0.75
_BTN_RISORSE_SOGLIA = 0.75

# Zone badge e freccia nella schermata (colonna badge e zona freccia toggle)
_BADGE_X1      = 130
_BADGE_X2      = 220
_BADGE_Y_START = 165    # offset Y per la zona lista
_BARRA_ALTEZZA = 43     # altezza barra R in pixel
_FRECCIA_X1    = 860
_FRECCIA_X2    = 930

# Limiti scroll
_MAX_SWIPE_TOP     = 6
_MAX_SWIPE_TOGGLE  = 12
_MAX_SWIPE_RICERCA = 25


# ------------------------------------------------------------------------------
# Navigazione via Membri — funzioni helper (traduzione fedele V5 in API V6)
# ------------------------------------------------------------------------------

def _membri_scroll_to_top(ctx: TaskContext) -> None:
    """Porta la lista all'inizio con swipe verso il basso."""
    for _ in range(_MAX_SWIPE_TOP):
        ctx.device.swipe(_SWIPE_GIU_X, _SWIPE_GIU_Y1,
                         _SWIPE_GIU_X, _SWIPE_GIU_Y2, duration_ms=350)
        time.sleep(0.4)
    time.sleep(0.8)


def _membri_scroll_avanti(ctx: TaskContext) -> None:
    """Avanza nella lista di un passo (swipe verso l'alto)."""
    ctx.device.swipe(_SWIPE_SU_X, _SWIPE_SU_Y1,
                     _SWIPE_SU_X, _SWIPE_SU_Y2, duration_ms=500)
    time.sleep(1.0)


def _membri_trova_badge(screen, ctx: TaskContext, rango: str) -> int:
    """
    Cerca il badge del rango nella colonna sinistra della lista.
    Ritorna Y assoluta del centro, -1 se non trovato.
    """
    tmpl_name = _TMPL_BADGE.get(rango, "")
    if not tmpl_name:
        return -1
    try:
        zona = (_BADGE_X1, _BADGE_Y_START, _BADGE_X2, screen.height)
        result = ctx.matcher.find_one(screen, tmpl_name,
                                      threshold=_BADGE_SOGLIA, zone=zona)
        if result.found:
            return result.cy
    except Exception:
        pass
    return -1


def _membri_stato_toggle(screen, ctx: TaskContext, y_barra: int) -> str:
    """
    Determina se una barra R è aperta o chiusa tramite freccia su/giù.
    Ritorna 'aperto' | 'chiuso' | 'sconosciuto'.
    """
    y1 = max(0, y_barra - _BARRA_ALTEZZA // 2)
    y2 = min(screen.height, y_barra + _BARRA_ALTEZZA // 2)
    zona = (_FRECCIA_X1, y1, _FRECCIA_X2, y2)
    try:
        score_down = ctx.matcher.score(screen, _TMPL_ARROW_DOWN, zone=zona)
        score_up   = ctx.matcher.score(screen, _TMPL_ARROW_UP,   zone=zona)
        if score_down < _FRECCIA_SOGLIA and score_up < _FRECCIA_SOGLIA:
            return "sconosciuto"
        return "aperto" if score_up > score_down else "chiuso"
    except Exception:
        return "sconosciuto"


def _membri_trova_avatar(screen, ctx: TaskContext,
                          avatar_template: str) -> tuple | None:
    """
    Cerca l'avatar nella zona lista.
    Ritorna (tap_x, cy) se trovato, None altrimenti.
    tap_x = 290 (metà sinistra) o 680 (metà destra) per non tappare l'avatar stesso.
    """
    try:
        result = ctx.matcher.find_one(screen, avatar_template,
                                      threshold=_AVATAR_SOGLIA,
                                      zone=_LISTA_ZONA)
        if result.found:
            tap_x = 290 if result.cx < 490 else 680
            return (tap_x, result.cy)
    except Exception:
        pass
    return None


def _membri_apri_tutti_toggle(ctx: TaskContext,
                               avatar_template: str) -> tuple | None:
    """
    Scorre la lista aprendo tutti i toggle R4/R3/R2/R1 chiusi.
    Cerca l'avatar in parallelo — se trovato ritorna subito (tap_x, cy).
    Traduzione fedele V5 _apri_tutti_toggle().
    """
    ranghi_tutti   = {"R4", "R3", "R2", "R1"}
    ranghi_gestiti = set()

    ctx.log_msg("Rifornimento membri: scroll-to-top iniziale")
    _membri_scroll_to_top(ctx)

    for swipe_n in range(_MAX_SWIPE_TOGGLE):
        screen = ctx.device.screenshot()
        if screen is None:
            time.sleep(1.0)
            continue

        # Cerca avatar in parallelo durante apertura toggle
        coord_tap = _membri_trova_avatar(screen, ctx, avatar_template)
        if coord_tap:
            ctx.log_msg(f"Rifornimento membri: avatar trovato durante toggle swipe {swipe_n} → {coord_tap}")
            time.sleep(1.2)
            return coord_tap

        # Cerca e gestisci badge
        trovati_ora = {}
        for rango in ranghi_tutti:
            y = _membri_trova_badge(screen, ctx, rango)
            if y >= 0:
                trovati_ora[rango] = y

        ctx.log_msg(f"Rifornimento membri: swipe {swipe_n} badge={list(trovati_ora.keys())}")

        rescansiona = False
        for rango, y_barra in list(trovati_ora.items()):
            if rango in ranghi_gestiti:
                continue
            stato_r = _membri_stato_toggle(screen, ctx, y_barra)
            ctx.log_msg(f"Rifornimento membri: {rango} y={y_barra} stato={stato_r}")

            if stato_r == "chiuso":
                ctx.log_msg(f"Rifornimento membri: apro toggle {rango}")
                ctx.device.tap(480, y_barra)
                time.sleep(0.8)
                ranghi_gestiti.add(rango)
                time.sleep(1.5)
                screen2 = ctx.device.screenshot()
                if screen2 is None:
                    break
                # Verifica avatar dopo apertura toggle
                coord_tap = _membri_trova_avatar(screen2, ctx, avatar_template)
                if coord_tap:
                    ctx.log_msg(f"Rifornimento membri: avatar trovato post-{rango} → {coord_tap}")
                    time.sleep(1.2)
                    return coord_tap
                rescansiona = True
                break
            elif stato_r == "aperto":
                ranghi_gestiti.add(rango)

        if rescansiona:
            continue

        if ranghi_tutti.issubset(ranghi_gestiti):
            ctx.log_msg("Rifornimento membri: tutti i toggle aperti")
            break

        _membri_scroll_avanti(ctx)

    ctx.log_msg("Rifornimento membri: scroll-to-top per ricerca avatar")
    _membri_scroll_to_top(ctx)
    return None


def _membri_cerca_avatar_scroll(ctx: TaskContext,
                                 avatar_template: str) -> tuple | None:
    """
    Scorre la lista cercando l'avatar con template matching.
    Fine lista rilevata da screen identici consecutivi (frame hash).
    Ritorna (tap_x, cy) o None.
    Traduzione fedele V5 _cerca_avatar_scroll().
    """
    import hashlib
    prev_hash = ""

    for swipe_n in range(_MAX_SWIPE_RICERCA + 1):
        screen = ctx.device.screenshot()
        if screen is None:
            time.sleep(1.0)
            continue

        coord_tap = _membri_trova_avatar(screen, ctx, avatar_template)
        if coord_tap:
            ctx.log_msg(f"Rifornimento membri: avatar trovato dopo {swipe_n} swipe → {coord_tap}")
            time.sleep(1.2)
            return coord_tap

        # Rilevamento fine lista via hash del frame
        try:
            frame_hash = hashlib.md5(screen.frame.tobytes()).hexdigest()
        except Exception:
            frame_hash = ""

        if frame_hash and frame_hash == prev_hash:
            ctx.log_msg(f"Rifornimento membri: fine lista dopo {swipe_n} swipe — avatar non trovato")
            return None
        prev_hash = frame_hash

        if swipe_n < _MAX_SWIPE_RICERCA:
            ctx.log_msg(f"Rifornimento membri: swipe {swipe_n + 1}/{_MAX_SWIPE_RICERCA}")
            _membri_scroll_avanti(ctx)

    ctx.log_msg(f"Rifornimento membri: avatar non trovato dopo {_MAX_SWIPE_RICERCA} swipe")
    return None


def _membri_trova_pulsante_risorse(ctx: TaskContext) -> tuple | None:
    """
    Cerca il pulsante 'Risorse di approvvigionamento' nel popup azioni.
    Usa template matching su btn_risorse_approv.png e btn_supply_resources.png.
    Ritorna (cx, cy) o None.
    """
    templates_da_provare = [
        ("pin/btn_risorse_approv.png",  _BTN_RISORSE_SOGLIA),
        ("pin/btn_supply_resources.png", _BTN_RISORSE_SOGLIA),
    ]
    screen = ctx.device.screenshot()
    if screen is None:
        return None

    for tmpl_name, soglia in templates_da_provare:
        try:
            result = ctx.matcher.find_one(screen, tmpl_name, threshold=soglia)
            if result.found:
                ctx.log_msg(f"Rifornimento membri: pulsante risorse trovato score={result.score:.3f}")
                return (result.cx, result.cy)
        except FileNotFoundError:
            continue
        except Exception:
            continue

    return None


def _esegui_via_membri(ctx: TaskContext, risorse_config: dict,
                        soglie: dict, nome_rifugio: str,
                        max_sped: int, margine: int) -> tuple[int, float]:
    """
    Esegue il rifornimento via lista Membri alleanza.
    Traduzione fedele V5 esegui_rifornimento() con navigazione lista.

    Flusso per ogni spedizione:
      HOME → Alleanza → Membri → toggle R4/R3/R2/R1 → avatar
      → tap → popup → btn risorse → maschera → compila → VAI

    Ritorna: (spedizioni, eta_residua)
    """
    avatar_template = _cfg(ctx, "AVATAR_TEMPLATE") or "pin/avatar.png"
    risorse_l = list(risorse_config.keys())
    spedizioni = 0
    idx_risorsa = 0
    coda_volo: deque = deque()
    # 05/05: copia mutabile per skip risorse falliti questo tick (vedi
    # rationale in _esegui_mappa). Pre-fix: break cieco al primo fail.
    risorse_attive = dict(risorse_config)

    # Leggi deposito OCR dalla HOME prima di navigare
    ctx.log_msg("Rifornimento membri: lettura deposito OCR da HOME")
    deposito = _leggi_deposito_ocr(ctx, risorse_l)
    if all(deposito.get(r, -1) < 0 for r in risorse_l):
        ctx.log_msg("Rifornimento membri: OCR deposito fallito — stop")
        return 0, 0.0

    ctx.log_msg("Rifornimento membri: deposito OCR — " + " | ".join(
        f"{r}={max(0.0, deposito.get(r, -1))/1e6:.1f}M"
        for r in risorse_l if deposito.get(r, -1) >= 0
    ))

    while True:
        if max_sped > 0 and spedizioni >= max_sped:
            ctx.log_msg(f"Rifornimento membri: limite spedizioni ({spedizioni}/{max_sped})")
            break

        # ── Slot liberi ──────────────────────────────────────────────────────
        _aggiorna_coda(coda_volo)
        slot = _MAX_SWIPE_TOP  # assume slot liberi, non legge UI (siamo in HOME)
        if slot == 0:
            ctx.log_msg("Rifornimento membri: nessun slot — stop")
            break

        # ── Seleziona risorsa (weighted-deficit 05/05) ───────────────────────
        if not risorse_attive:
            ctx.log_msg("Rifornimento membri: tutte le risorse hanno fallito invio — stop")
            break
        inviato_oggi = {}
        try:
            inviato_oggi = dict(ctx.state.rifornimento.inviato_oggi or {})
        except Exception:
            pass
        ratio_target = _cfg(ctx, "RIFORNIMENTO_ALLOCAZIONE")
        risorsa_scelta, idx_risorsa = _seleziona_risorsa(
            deposito, risorse_attive, soglie, idx_risorsa,
            inviato_oggi=inviato_oggi,
            ratio_target=ratio_target,
        )
        if risorsa_scelta is None:
            ctx.log_msg("Rifornimento membri: tutte le risorse sotto soglia — stop")
            break

        ctx.log_msg(f"Rifornimento membri: risorsa selezionata={risorsa_scelta} "
                    f"(inviato_oggi={inviato_oggi.get(risorsa_scelta, 0):,})")
        qta = risorse_attive[risorsa_scelta]

        # ── Naviga HOME → Alleanza → Membri → avatar ─────────────────────────
        # Standard V6: usa tap_barra("alliance") come arena/arena_mercato
        ctx.log_msg("Rifornimento membri: tap Alliance via tap_barra")
        if ctx.navigator is not None:
            ctx.navigator.tap_barra(ctx, "alliance")
        else:
            ctx.device.tap(_COORD_ALLEANZA_BTN)
        time.sleep(1.5)
        ctx.log_msg("Rifornimento membri: tap Membri")
        ctx.device.tap(_COORD_MEMBRI)
        time.sleep(2.5)   # attesa rendering lista badge R

        # Apri toggle e cerca avatar
        coord_tap = _membri_apri_tutti_toggle(ctx, avatar_template)
        if not coord_tap:
            coord_tap = _membri_cerca_avatar_scroll(ctx, avatar_template)
        if not coord_tap:
            ctx.log_msg("Rifornimento membri: avatar non trovato — BACK e stop")
            ctx.device.back()
            time.sleep(0.8)
            break

        # ── Tap membro → popup ───────────────────────────────────────────────
        ctx.log_msg(f"Rifornimento membri: tap membro {coord_tap}")
        ctx.device.tap(*coord_tap)
        time.sleep(1.5)

        # ── Trova pulsante risorse ───────────────────────────────────────────
        btn_coord = None
        for tentativo in range(3):
            btn_coord = _membri_trova_pulsante_risorse(ctx)
            if btn_coord:
                break
            time.sleep(0.8)

        if not btn_coord:
            ctx.log_msg("Rifornimento membri: pulsante risorse non trovato — BACK e stop")
            ctx.device.back()
            time.sleep(0.8)
            break

        ctx.log_msg(f"Rifornimento membri: tap pulsante risorse {btn_coord}")
        ctx.device.tap(*btn_coord)
        time.sleep(2.0)

        # ── Compila e invia ──────────────────────────────────────────────────
        # FIX 23/04: ts_invio catturato DOPO _compila_e_invia. L'OCR deposito +
        # compila quantità + tap VAI richiedono ~15-20s; se ts_invio fosse preso
        # prima, la coda_volo sottostimerebbe il tempo residuo delle spedizioni
        # in corso, causando uscite "nessun slot dopo attesa" sbagliate.
        ok, eta_sec, quota_esaurita, qta_effettiva, qta_lordo, provviste_lette = _compila_e_invia(
            ctx, risorsa_scelta, qta, nome_rifugio
        )
        ts_invio = time.time()

        if quota_esaurita:
            ctx.log_msg("Rifornimento membri: quota giornaliera esaurita — stop")
            break

        if not ok:
            # 05/05: vedi rationale in _esegui_mappa
            ctx.log_msg(
                f"Rifornimento membri: invio {risorsa_scelta} fallito — escludo "
                f"da questo tick e proseguo con altre risorse"
            )
            risorse_attive.pop(risorsa_scelta, None)
            continue

        # ── Snapshot POST-VAI (per aggiornare deposito tracking) ────────────
        time.sleep(1.5)
        ctx.navigator.vai_in_home()   # torna home per OCR deposito
        time.sleep(1.0)

        snapshot_post = _leggi_deposito_ocr(ctx, risorse_l)

        # ── Registra ─────────────────────────────────────────────────────────
        # FIX 26/04: tracking nello state usa qta_effettiva (NETTO arrivato
        # al destinatario), non il delta deposito (LORDO con tassa).
        spedizioni += 1
        eta_ar = float(eta_sec * 2)
        coda_volo.append((ts_invio, eta_ar))

        if ctx.state is not None:
            # WU106: cap individuale alla prima spedizione del giorno
            if ctx.state.rifornimento.spedizioni_oggi == 0 and provviste_lette >= 0:
                ctx.state.rifornimento.registra_cap_giornaliero(
                    cap_invio=int(provviste_lette),
                    qta_max_lordo=int(qta_lordo),
                )
                ctx.log_msg(
                    f"Rifornimento membri: [WU106] cap istanza giornaliero="
                    f"{provviste_lette/1e6:.1f}M netti | "
                    f"qta max singolo invio={qta_lordo/1e6:.2f}M lordo"
                )

            # auto-WU34 (27/04): registra anche LORDO + TASSA daily
            tassa_amt = max(0, qta_lordo - qta_effettiva)
            ctx.state.rifornimento.registra_spedizione(
                risorsa=risorsa_scelta,
                qta_inviata=qta_effettiva,
                provviste_residue=provviste_lette,
                qta_lorda=qta_lordo,
                tassa_amount=tassa_amt,
            )

        # Hook istanza_metrics — predictor 5-invii
        try:
            from core.istanza_metrics import aggiungi_invio_rifornimento
            aggiungi_invio_rifornimento(
                ctx.instance_name, risorsa_scelta,
                int(qta_effettiva), int(eta_ar),
            )
        except Exception:
            pass

        tassa_pct = ((qta_lordo - qta_effettiva) / qta_lordo * 100) if qta_lordo > 0 else 0.0
        provv_str = f" | provviste={provviste_lette:,}" if provviste_lette >= 0 else ""
        ctx.log_msg(
            f"Rifornimento membri: spedizione {spedizioni} "
            f"— {risorsa_scelta} netto={qta_effettiva:,} "
            f"(lordo {qta_lordo:,}, tassa {tassa_pct:.1f}%)"
            f" | ETA A/R={eta_ar:.0f}s{provv_str}"
        )

        # Aggiorna deposito con snapshot post
        if all(snapshot_post.get(r, -1) >= 0 for r in risorse_l):
            deposito = snapshot_post
        time.sleep(0.5)

    # ETA residua
    _aggiorna_coda(coda_volo)
    eta_residua = _attesa_ultima_spedizione(coda_volo, margine)
    return spedizioni, eta_residua


# ------------------------------------------------------------------------------
# Storico farm giornaliero — data/storico_farm.json
# ------------------------------------------------------------------------------

def _aggiorna_storico_farm(ctx, nome_istanza: str) -> None:
    """
    Aggiorna data/storico_farm.json con i dati odierni dell'istanza.
    Chiamato a fine run() dopo ogni ciclo rifornimento.
    Scrittura atomica — sicuro perché bot è sequenziale.

    Struttura:
      {
        "YYYY-MM-DD": {
          "FAU_00": {"legno": N, "petrolio": N, ..., "spedizioni": N,
                     "provviste_residue": N},
          ...
        },
        ...
      }
    Retention: ultimi 90 giorni.
    """
    import json as _json
    import os as _os
    from datetime import date

    storico_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "data", "storico_farm.json"
    )
    oggi = date.today().isoformat()  # "2026-04-23"

    # Leggi inviato_oggi da state
    rif = ctx.state.rifornimento
    inviato    = dict(getattr(rif, "inviato_oggi", {}))
    spedizioni = int(getattr(rif, "spedizioni_oggi", 0))
    provviste  = int(getattr(rif, "provviste_residue", 0))

    # Leggi storico esistente
    try:
        with open(storico_path, encoding="utf-8") as f:
            storico = _json.load(f)
    except Exception:
        storico = {}

    # Aggiorna entry oggi per questa istanza
    if oggi not in storico:
        storico[oggi] = {}
    storico[oggi][nome_istanza] = {
        "legno":             inviato.get("legno", 0),
        "petrolio":          inviato.get("petrolio", 0),
        "pomodoro":          inviato.get("pomodoro", 0),
        "acciaio":           inviato.get("acciaio", 0),
        "spedizioni":        spedizioni,
        "provviste_residue": provviste,
    }

    # Mantieni solo ultimi 90 giorni
    if len(storico) > 90:
        chiavi_ordinate = sorted(storico.keys())
        for k in chiavi_ordinate[:-90]:
            del storico[k]

    # Scrittura atomica
    _os.makedirs(_os.path.dirname(storico_path), exist_ok=True)
    tmp = storico_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(storico, f, ensure_ascii=False, indent=2)
    _os.replace(tmp, storico_path)


# ------------------------------------------------------------------------------
# Task V6
# ------------------------------------------------------------------------------

class RifornimentoTask(Task):
    """
    Task periodico che invia risorse al rifugio alleato.
    Modalità selezionabile da global_config.json:
      rifornimento_mappa.abilitato   = true  → via coordinate mappa (default)
      rifornimento_membri.abilitato  = true  → via lista Membri (backup)
    Le due modalità sono mutualmente esclusive — ha precedenza la mappa.
    """

    def name(self) -> str:
        return "rifornimento"

    def schedule_type(self) -> str:
        return "periodic"

    def interval_hours(self) -> float:
        return 4.0

    def should_run(self, ctx) -> bool:
        if not ctx.config.task_abilitato("rifornimento"):
            return False
        if ctx.device is None or ctx.matcher is None:
            return False
        if ctx.state is not None and not ctx.state.rifornimento.should_run():
            ctx.log_msg("Rifornimento: provviste esaurite oggi → skip")
            return False
        # 05/05: master saturo (Daily Receiving Limit del rifugio destinatario
        # = 0). Inutile aprire mappa+rifugio se master non può ricevere altro.
        # Saving: ~80s × N istanze ad ogni tick post-saturazione master.
        # Pattern detector telemetria: risultato no più "skip chain" fuorviante.
        #
        # Freshness: il valore DRL si azzera in giornata e si resetta alle
        # 00:00 UTC dal gioco. Se accettassimo DRL=0 senza guardare ts, dopo
        # il reset nessuna istanza tenterebbe più → OCR mai più aggiornato →
        # guard eterno. Fix: skip solo se DRL=0 AND ts >= mezzanotte UTC odierna.
        try:
            from shared import morfeus_state
            from datetime import datetime, timezone
            ms = morfeus_state.load() or {}
            drl = int(ms.get("daily_recv_limit", -1))
            if drl == 0:
                ts_iso = ms.get("ts", "")
                ts_dt = None
                try:
                    ts_dt = datetime.fromisoformat(ts_iso) if ts_iso else None
                except Exception:
                    pass
                now = datetime.now(timezone.utc)
                midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if ts_dt is not None and ts_dt >= midnight_utc:
                    ctx.log_msg(
                        f"Rifornimento: Daily Receiving Limit master=0 (saturo, "
                        f"ts={ts_dt.strftime('%H:%M')} UTC) → skip"
                    )
                    return False
                # ts stale (pre-reset 00:00 UTC) → tenta per refresh OCR
                ctx.log_msg(
                    f"Rifornimento: DRL=0 ma ts={ts_iso} antecedente reset 00:00 UTC "
                    f"— tenta per refresh OCR"
                )
        except Exception:
            pass   # best-effort, su errore non blocca
        return True

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None,
            slot_liberi: int = -1) -> TaskResult:
        """
        Esegue il rifornimento risorse nella modalità configurata.

        Parametri iniettabili per i test:
          deposito    : dict risorsa→valore_assoluto (evita screenshot OCR)
          slot_liberi : int ≥ 0 → salta la lettura reale degli slot UI
        """
        # --- Selezione modalità ---
        mappa_abilitata   = _cfg(ctx, "RIFORNIMENTO_MAPPA_ABILITATO")
        membri_abilitati  = _cfg(ctx, "RIFORNIMENTO_MEMBRI_ABILITATO")

        if not mappa_abilitata and not membri_abilitati:
            ctx.log_msg("Rifornimento: nessuna modalità abilitata — skip")
            return TaskResult(
                success=True,
                message="disabilitato",
                data={"spedizioni": 0, "eta_residua": 0.0},
            )

        # --- Verifica account destinatario ---
        nome_rifugio = _cfg(ctx, "DOOMS_ACCOUNT")
        if not nome_rifugio:
            ctx.log_msg("Rifornimento: DOOMS_ACCOUNT non configurato — skip")
            return TaskResult(
                success=False,
                message="DOOMS_ACCOUNT mancante",
                data={"spedizioni": 0, "eta_residua": 0.0},
            )

        # --- Configurazione risorse ---
        risorse_config, soglie, _ = _build_risorse_config(ctx)
        if not risorse_config:
            ctx.log_msg("Rifornimento: nessuna risorsa configurata — skip")
            return TaskResult(
                success=True,
                message="nessuna risorsa configurata",
                data={"spedizioni": 0, "eta_residua": 0.0},
            )

        # --- Verifica deposito ---
        # In produzione: se non iniettato dall'orchestrator, legge OCR direttamente
        # come V5 _leggi_risorse_mappa(). L'OCR viene letto in mappa dopo vai_in_mappa().
        # Il flag deposito_da_ocr indica che la lettura avverrà nel loop al passo 3.
        deposito_da_ocr = deposito is None
        if deposito_da_ocr:
            ctx.log_msg("Rifornimento: deposito non iniettato — lettura OCR in mappa")

        _max_sped_raw = _cfg(ctx, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO")
        max_sped = int(_max_sped_raw) if _max_sped_raw is not None else 5
        margine    = int(_cfg(ctx, "MARGINE_ATTESA"))
        risorse_l  = list(risorse_config.keys())

        spedizioni = 0
        idx_risorsa: int = 0
        coda_volo: deque = deque()
        in_mappa = False

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.rifornimento)
        from shared.debug_buffer import DebugBuffer
        _dbg = DebugBuffer.for_task("rifornimento", getattr(ctx, "instance_name", "_unknown"))
        if _dbg.enabled:
            _dbg.snap("00_pre_rifornimento", ctx.device.screenshot() if ctx.device else None)

        ctx.log_msg(f"Rifornimento: start — risorse={risorse_l} max_sped={max_sped}")

        # --- Selezione modalità di esecuzione ---
        # Mappa ha precedenza su Membri (più veloce, è il default)
        mode_used = "mappa" if mappa_abilitata else "membri"
        if mappa_abilitata:
            ctx.log_msg("Rifornimento: modalità=MAPPA")
            # Guard: max_sped=0 → skip immediato
            if max_sped == 0:
                ctx.log_msg("Rifornimento: max_spedizioni_ciclo=0 — skip")
                return TaskResult(success=True, message="max_spedizioni=0",
                                  data={"spedizioni": 0, "eta_residua": 0.0,
                                        "mode": mode_used, "skip_reason": "max_sped_0"})
            spedizioni, eta_residua = self._esegui_mappa(
                ctx, deposito, deposito_da_ocr, slot_liberi,
                risorse_config, soglie, nome_rifugio,
                max_sped, margine, risorse_l
            )
        else:
            ctx.log_msg("Rifornimento: modalità=MEMBRI (backup)")
            # Guard: max_sped=0 → skip immediato
            if max_sped == 0:
                ctx.log_msg("Rifornimento: max_spedizioni_ciclo=0 — skip")
                return TaskResult(success=True, message="max_spedizioni=0",
                                  data={"spedizioni": 0, "eta_residua": 0.0,
                                        "mode": mode_used, "skip_reason": "max_sped_0"})
            spedizioni, eta_residua = _esegui_via_membri(
                ctx, risorse_config, soglie, nome_rifugio, max_sped, margine
            )

        # Riepilogo statistiche
        if ctx.state is not None:
            rif = ctx.state.rifornimento
            if rif.inviato_oggi:
                riepilogo = " | ".join(
                    f"{r}={v/1e6:.1f}M" for r, v in rif.inviato_oggi.items()
                )
                ctx.log_msg(f"Rifornimento: inviato oggi — {riepilogo}")
            if rif.provviste_residue >= 0:
                ctx.log_msg(f"Rifornimento: provviste residue={rif.provviste_residue:,}")

        ctx.log_msg(f"Rifornimento: completato — {spedizioni} spedizioni")

        # Issue #64 — salva ETA rientro ultima spedizione nel state.
        # RaccoltaTask leggerà questo valore prima di leggere slot per evitare
        # di vedere slot occupati da rifornimento ancora in volo.
        try:
            if ctx.state is not None and eta_residua > 0:
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                ts_rientro = _dt.now(_tz.utc) + _td(seconds=float(eta_residua))
                ctx.state.rifornimento.eta_rientro_ultima = ts_rientro.isoformat()
                ctx.log_msg(
                    f"Rifornimento: eta_rientro_ultima = {ts_rientro.isoformat()} "
                    f"(+{eta_residua:.0f}s)"
                )
        except Exception as exc:
            ctx.log_msg(f"[WARN] save eta_rientro_ultima: {exc}")

        # Aggiorna storico farm giornaliero
        try:
            _aggiorna_storico_farm(ctx, ctx.instance_name)
        except Exception as exc:
            ctx.log_msg(f"[WARN] storico_farm: {exc}")

        # Output telemetria — Issue #53 Step 3
        out_data = {
            "spedizioni":      spedizioni,
            "eta_residua":     eta_residua,
            "mode":            mode_used,
            "max_sped_ciclo":  max_sped,
        }
        try:
            if ctx.state is not None and getattr(ctx.state, "rifornimento", None):
                rif = ctx.state.rifornimento
                out_data["provviste_residue"] = int(rif.provviste_residue)
                out_data["tassa_pct_avg"]     = round(float(rif.tassa_pct_avg), 4)
                out_data["spedizioni_oggi"]   = int(rif.spedizioni_oggi)
        except Exception:
            pass

        # WU115 — flush debug. Anomalia: max_sped>0 ma 0 spedizioni effettive
        if _dbg.enabled:
            _dbg.snap("99_post_rifornimento", ctx.device.screenshot() if ctx.device else None)
        anomalia = (max_sped > 0 and spedizioni == 0)
        _dbg.flush(success=True, force=anomalia, log_fn=ctx.log_msg)

        return TaskResult(
            success=True,
            message=f"{spedizioni} spedizioni",
            data=out_data,
        )

    def _esegui_mappa(self, ctx, deposito, deposito_da_ocr, slot_liberi,
                      risorse_config, soglie, nome_rifugio,
                      max_sped, margine, risorse_l) -> tuple[int, float]:
        """Loop rifornimento via coordinate mappa."""
        spedizioni  = 0
        idx_risorsa = 0
        coda_volo: deque = deque()
        in_mappa    = False
        # 05/05: copia mutabile delle risorse abilitate. Se _compila_e_invia
        # fallisce per una risorsa (campo greyed-out, coord errata, ecc.),
        # la rimuoviamo da questo set per non ritentarla nello stesso tick.
        # Reset al prossimo tick. Pre-fix: break al primo fail → 0 invii
        # acciaio/petrolio per giorni perché 1 fail bloccava tutto il loop.
        risorse_attive = dict(risorse_config)

        try:
            while True:
                if max_sped > 0 and spedizioni >= max_sped:
                    ctx.log_msg(f"Rifornimento: limite spedizioni raggiunto ({spedizioni}/{max_sped})")
                    break

                # ── 1. Slot liberi ──────────────────────────────────────────
                _aggiorna_coda(coda_volo)
                slot = slot_liberi

                if slot == -1:
                    try:
                        from shared.ocr_helpers import leggi_contatore_slot
                        max_sq = getattr(ctx.config, "max_squadre", 4)
                        # Iterazioni successive: siamo in mappa → torna in HOME
                        # prima della lettura slot per garantire OCR corretto.
                        # Step 2 rientrerà in mappa perché in_mappa=False.
                        if in_mappa and ctx.navigator is not None:
                            ctx.navigator.vai_in_home()
                            in_mappa = False
                            time.sleep(1.0)
                        screen_slot = ctx.device.screenshot()
                        if screen_slot is not None:
                            attive, totale = leggi_contatore_slot(screen_slot, totale_noto=max_sq)
                            slot = max_sq if attive == -1 else max(0, totale - attive)
                        else:
                            slot = max_sq
                    except Exception:
                        slot = getattr(ctx.config, "max_squadre", 4)

                ctx.log_msg(f"Rifornimento: slot liberi={slot}")

                if slot == 0:
                    # Caso A: coda nostra non vuota → aspetta rientro nostre spedizioni
                    # e RIPROVA (lo slot si libera, possiamo inviare la prossima).
                    # Caso B: coda vuota → tutte le squadre sono fuori per altri task
                    # (raccolta ciclo precedente), tempi ignoti → stop.
                    attesa = _attesa_prima_spedizione(coda_volo, margine)
                    if attesa > 0:
                        ctx.log_msg(f"Rifornimento: slot 0 — attendo {attesa:.0f}s e ritento")
                        time.sleep(attesa)
                        _aggiorna_coda(coda_volo)
                        continue   # rilegge slot al prossimo giro del loop
                    ctx.log_msg("Rifornimento: slot 0, coda vuota — squadre fuori per altri task → stop")
                    break

                # ── 2. Vai in mappa (solo prima volta) ──────────────────────
                if not in_mappa:
                    ctx.log_msg("Rifornimento: navigazione → mappa")
                    if ctx.navigator is not None:
                        ctx.navigator.vai_in_mappa()
                    else:
                        ctx.device.key("KEYCODE_MAP")
                    in_mappa = True
                    time.sleep(1.5)

                # ── 3. Leggi deposito OCR ───────────────────────────────────
                if deposito_da_ocr:
                    deposito = _leggi_deposito_ocr(ctx, risorse_l)
                    if all(deposito.get(r, -1) < 0 for r in risorse_l):
                        ctx.log_msg("Rifornimento: OCR deposito fallito dopo retry — stop")
                        break
                    ctx.log_msg("Rifornimento: deposito OCR — " + " | ".join(
                        f"{r}={max(0.0, deposito.get(r, -1))/1e6:.1f}M"
                        for r in risorse_l if deposito.get(r, -1) >= 0
                    ))

                # ── 4. Seleziona risorsa (weighted-deficit 05/05) ───────────
                # Selezione weighted-deficit (analoga a raccolta): usa
                # ratio_target da config (rifornimento.allocazione, default
                # uniforme 25/25/25/25 se non configurato) e inviato_oggi
                # cumulato. Sort DESC per gap = ratio_target - perc_att, primo
                # sopra soglia.
                if not risorse_attive:
                    ctx.log_msg("Rifornimento: tutte le risorse hanno fallito invio — stop")
                    break
                inviato_oggi = {}
                try:
                    inviato_oggi = dict(ctx.state.rifornimento.inviato_oggi or {})
                except Exception:
                    pass
                ratio_target = _cfg(ctx, "RIFORNIMENTO_ALLOCAZIONE")
                risorsa_scelta, idx_risorsa = _seleziona_risorsa(
                    deposito, risorse_attive, soglie, idx_risorsa,
                    inviato_oggi=inviato_oggi,
                    ratio_target=ratio_target,
                )
                if risorsa_scelta is None:
                    ctx.log_msg("Rifornimento: tutte le risorse sotto soglia — stop")
                    break
                ctx.log_msg(
                    f"Rifornimento: risorsa selezionata={risorsa_scelta} "
                    f"(inviato_oggi={inviato_oggi.get(risorsa_scelta, 0):,})"
                )

                ctx.log_msg(f"Rifornimento: risorsa selezionata={risorsa_scelta}")
                qta = risorse_attive[risorsa_scelta]

                # ── 5. Centra mappa + apri RESOURCE SUPPLY ──────────────────
                _centra_mappa(ctx)
                if not _apri_resource_supply(ctx):
                    ctx.log_msg("Rifornimento: RESOURCE SUPPLY non trovato — stop")
                    break

                # ── 6. Compila e invia ──────────────────────────────────────
                # FIX 23/04: ts_invio catturato DOPO _compila_e_invia (~15-20s
                # di OCR + compila + tap VAI). Prima era PRIMA, causando coda_volo
                # ottimistica → "nessun slot dopo attesa" sbagliato (FAU_01 tick
                # 2/5 sped con slot=0 dopo attesa 55s, ma sped 1 ancora in volo).
                ok, eta_sec, quota_esaurita, qta_effettiva, qta_lordo, provviste_lette = _compila_e_invia(
                    ctx, risorsa_scelta, qta, nome_rifugio
                )
                ts_invio = time.time()

                if quota_esaurita:
                    ctx.log_msg("Rifornimento: provviste giornaliere esaurite — stop")
                    if ctx.state is not None:
                        ctx.state.rifornimento.segna_provviste_esaurite()
                        ctx.log_msg("Rifornimento: RifornimentoState.provviste_esaurite=True")
                    break
                if not ok:
                    # 05/05: pre-fix `break` cieco bloccava tutto il loop al primo
                    # fail (es. acciaio campo greyed-out → 0 invii pet anche se OK).
                    # Post-fix: rimuovi la risorsa da risorse_attive e prosegui.
                    # Se rimaste 0 risorse → la prossima iterazione hardcoded break.
                    ctx.log_msg(
                        f"Rifornimento: invio {risorsa_scelta} fallito — escludo "
                        f"da questo tick e proseguo con altre risorse"
                    )
                    risorse_attive.pop(risorsa_scelta, None)
                    continue

                # ── 7. Snapshot POST-VAI (per aggiornare deposito tracking) ─
                time.sleep(1.5)
                snapshot_post = _leggi_deposito_ocr(ctx, risorse_l)

                # ── 8. Registra ─────────────────────────────────────────────
                # FIX 26/04: tracking nello state usa qta_effettiva (NETTO arrivato
                # al destinatario), non il delta deposito (LORDO con tassa).
                spedizioni += 1
                eta_ar = float(eta_sec * 2)
                coda_volo.append((ts_invio, eta_ar))

                if ctx.state is not None:
                    # WU106: alla PRIMA spedizione del giorno, cristallizza il cap
                    # individuale dell'istanza (provviste_residue letto = cap netto
                    # iniziale, qta_lordo = max per singolo invio).
                    if ctx.state.rifornimento.spedizioni_oggi == 0 and provviste_lette >= 0:
                        ctx.state.rifornimento.registra_cap_giornaliero(
                            cap_invio=int(provviste_lette),
                            qta_max_lordo=int(qta_lordo),
                        )
                        ctx.log_msg(
                            f"Rifornimento: [WU106] cap istanza giornaliero="
                            f"{provviste_lette/1e6:.1f}M netti | "
                            f"qta max singolo invio={qta_lordo/1e6:.2f}M lordo"
                        )

                    # auto-WU34 (27/04): registra anche LORDO + TASSA daily
                    tassa_amt = max(0, qta_lordo - qta_effettiva)
                    ctx.state.rifornimento.registra_spedizione(
                        risorsa=risorsa_scelta,
                        qta_inviata=qta_effettiva,
                        provviste_residue=provviste_lette,
                        qta_lorda=qta_lordo,
                        tassa_amount=tassa_amt,
                    )

                # Hook istanza_metrics — predictor 5-invii
                try:
                    from core.istanza_metrics import aggiungi_invio_rifornimento
                    aggiungi_invio_rifornimento(
                        ctx.instance_name, risorsa_scelta,
                        int(qta_effettiva), int(eta_ar),
                    )
                except Exception:
                    pass

                tassa_pct = ((qta_lordo - qta_effettiva) / qta_lordo * 100) if qta_lordo > 0 else 0.0
                provv_str = f" | provviste={provviste_lette:,}" if provviste_lette >= 0 else ""
                ctx.log_msg(
                    f"Rifornimento: spedizione {spedizioni} "
                    f"— {risorsa_scelta} netto={qta_effettiva:,} "
                    f"(lordo {qta_lordo:,}, tassa {tassa_pct:.1f}%)"
                    f" | ETA A/R={eta_ar:.0f}s{provv_str}"
                )

                if all(snapshot_post.get(r, -1) >= 0 for r in risorse_l):
                    deposito = snapshot_post
                time.sleep(0.5)

        finally:
            ctx.log_msg("Rifornimento: ritorno in home")
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            else:
                ctx.device.key("KEYCODE_HOME")

        _aggiorna_coda(coda_volo)
        eta_residua = _attesa_ultima_spedizione(coda_volo, margine)
        if eta_residua > 0:
            ctx.log_msg(f"Rifornimento: ETA residua ultima sped. = {eta_residua:.0f}s")
        return spedizioni, eta_residua
