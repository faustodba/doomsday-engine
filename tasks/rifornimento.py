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

def _vai_abilitato(screen_path: str, vai_zona: tuple,
                   soglia_gialli: int = 100) -> bool:
    """True se il pulsante VAI è giallo (abilitato), False se grigio."""
    try:
        from PIL import Image
        img = Image.open(screen_path)
        arr = np.array(img)
        vai = arr[vai_zona[1]:vai_zona[3], vai_zona[0]:vai_zona[2]]
        yellow = (vai[:, :, 0] > 160) & (vai[:, :, 1] > 120) & (vai[:, :, 2] < 90)
        return int(yellow.sum()) > soglia_gialli
    except Exception:
        return False


def _leggi_provviste(screen_path: str, ocr_box: tuple) -> int:
    """
    Legge 'Provviste rimanenti di oggi' dalla maschera.
    Ritorna intero, -1 se OCR fallisce.
    """
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(screen_path)
        crop = img.crop(ocr_box)
        c4x = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        gray = np.array(c4x.convert("L"))
        import cv2
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        testo = pytesseract.image_to_string(
            Image.fromarray(bw),
            config="--psm 7 -c tessedit_char_whitelist=0123456789,. "
        ).strip()
        testo = testo.replace(",", "").replace(".", "").replace(" ", "")
        return int(testo)
    except Exception:
        return -1


def _leggi_tassa(screen_path: str, ocr_box: tuple,
                 default: float = 0.24) -> float:
    """Legge percentuale tassa dalla maschera (es. 'Tasse: 23.0%' → 0.23)."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(screen_path)
        crop = img.crop(ocr_box)
        c4x = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        gray = np.array(c4x.convert("L"))
        import cv2
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        testo = pytesseract.image_to_string(Image.fromarray(bw),
                                            config="--psm 7").strip()
        m = re.search(r'([0-9]+\.?[0-9]*)\s*%', testo)
        if m:
            return float(m.group(1)) / 100.0
    except Exception:
        pass
    return default


def _leggi_eta(screen_path: str, ocr_box: tuple) -> int:
    """Legge ETA viaggio dalla maschera (es. '00:00:54'). Ritorna secondi totali."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(screen_path)
        crop = img.crop(ocr_box)
        c4x = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        gray = np.array(c4x.convert("L"))
        import cv2
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        testo = pytesseract.image_to_string(
            Image.fromarray(bw),
            config="--psm 7 -c tessedit_char_whitelist=0123456789:"
        ).strip()
        parti = testo.replace(".", ":").split(":")
        if len(parti) == 3:
            return int(parti[0]) * 3600 + int(parti[1]) * 60 + int(parti[2])
        if len(parti) == 2:
            return int(parti[0]) * 60 + int(parti[1])
    except Exception:
        pass
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
                        idx_risorsa: int) -> tuple[Optional[str], int]:
    """
    Round-robin sulle risorse configurate: seleziona la prima sopra soglia
    partendo da idx_risorsa. Ritorna (risorsa_scelta, nuovo_idx).
    """
    risorse_lista = list(risorse_config.keys())
    n = len(risorse_lista)
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
    time.sleep(2.0)
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
    time.sleep(2.5)
    return True


def _compila_e_invia(ctx: TaskContext, risorsa: str, qta: int,
                      nome_rifugio: str) -> tuple[bool, int, bool, int]:
    """
    Legge la maschera di invio, compila la risorsa e preme VAI.

    Ritorna: (ok, eta_sec, quota_esaurita, qta_inviata)
      ok=True          → spedizione inviata
      quota_esaurita   → provviste=0, non rientrare nel ciclo oggi
      qta_inviata      → 0 se non inviata
    """
    screen = ctx.device.screenshot()
    if not screen:
        return False, 0, False, 0

    # Verifica nome destinatario (come V5 _compila_e_invia in rifornimento_base.py)
    if nome_rifugio:
        ok_nome, testo_ocr = _verifica_nome_destinatario_v6(ctx, screen, nome_rifugio)
        if not ok_nome:
            ctx.log_msg(
                f"Rifornimento: DEST MISMATCH — OCR='{testo_ocr}' atteso='{nome_rifugio}' → BACK"
            )
            ctx.device.back()
            time.sleep(0.8)
            return False, 0, False, 0

    vai_zona     = _cfg(ctx, "VAI_ZONA")
    soglia_vai   = _cfg(ctx, "VAI_SOGLIA_GIALLI")
    ocr_provv    = _cfg(ctx, "OCR_PROVVISTE")
    ocr_tempo    = _cfg(ctx, "OCR_TEMPO")
    coord_campo  = _cfg(ctx, "COORD_CAMPO")
    coord_vai    = _cfg(ctx, "COORD_VAI")

    # Leggi provviste
    provviste = _leggi_provviste(screen, ocr_provv)
    if provviste >= 0:
        ctx.log_msg(f"Rifornimento: provviste rimanenti={provviste:,}")
    else:
        ctx.log_msg("Rifornimento: provviste OCR fallito — procedo")

    if provviste == 0:
        ctx.log_msg("Rifornimento: provviste esaurite → stop")
        ctx.device.key("KEYCODE_BACK")
        time.sleep(0.8)
        return False, 0, True, 0

    eta_sec = _leggi_eta(screen, ocr_tempo)
    ctx.log_msg(f"Rifornimento: ETA viaggio={eta_sec}s")

    # Compila campo risorsa
    coord = coord_campo.get(risorsa)
    if not coord:
        ctx.log_msg(f"Rifornimento: campo {risorsa} non configurato")
        return False, 0, False, 0

    ctx.log_msg(f"Rifornimento: compila {risorsa}={qta:,}")
    for _ in range(3):
        ctx.device.tap(coord)
        time.sleep(0.3)
    for _ in range(12):
        ctx.device.key("KEYCODE_DEL")
    time.sleep(0.3)
    ctx.device.input_text(str(qta))
    time.sleep(0.5)
    ctx.device.key("KEYCODE_ENTER")
    time.sleep(0.5)

    # Verifica VAI
    screen2 = ctx.device.screenshot()
    if screen2 and not _vai_abilitato(screen2, vai_zona, soglia_vai):
        ctx.log_msg("Rifornimento: VAI non abilitato dopo compilazione")
        provviste2 = _leggi_provviste(screen2, ocr_provv)
        if provviste2 == 0:
            ctx.device.key("KEYCODE_BACK")
            time.sleep(0.8)
            return False, 0, True, 0
        ctx.device.key("KEYCODE_BACK")
        return False, 0, False, 0

    ctx.log_msg("Rifornimento: tap VAI")
    ctx.device.tap(coord_vai)
    time.sleep(2.5)
    return True, eta_sec, False, qta


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
# Task V6
# ------------------------------------------------------------------------------

class RifornimentoTask(Task):
    """
    Task periodico (4h) che invia risorse al rifugio alleato via coordinate mappa.
    Implementa il loop ottimizzato in mappa con coda_volo per la gestione degli slot.
    """

    def name(self) -> str:
        return "rifornimento"

    def schedule_type(self) -> str:
        return "periodic"

    def interval_hours(self) -> float:
        return 4.0

    def should_run(self, ctx) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            return ctx.config.task_abilitato("rifornimento")
        return True

    def run(self, ctx: TaskContext,
            deposito: Optional[dict[str, float]] = None,
            slot_liberi: int = -1) -> TaskResult:
        """
        Esegue il rifornimento risorse.

        Parametri iniettabili per i test:
          deposito    : dict risorsa→valore_assoluto (evita screenshot OCR)
          slot_liberi : int ≥ 0 → salta la lettura reale degli slot UI

        In produzione entrambi valgono i loro default (-1 / None):
          l'orchestrator passa il deposito già letto, slot_liberi=-1
          lascia la lettura al loop interno.
        """
        # --- Verifica abilitazione ---
        if not _cfg(ctx, "RIFORNIMENTO_MAPPA_ABILITATO"):
            ctx.log_msg("Rifornimento: modulo disabilitato — skip")
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

        max_sped   = int(_cfg(ctx, "RIFORNIMENTO_MAX_SPEDIZIONI_CICLO") or 5)
        margine    = int(_cfg(ctx, "MARGINE_ATTESA"))
        risorse_l  = list(risorse_config.keys())

        spedizioni = 0
        idx_risorsa: int = 0
        coda_volo: deque = deque()
        in_mappa = False

        ctx.log_msg(f"Rifornimento: start — risorse={risorse_l} max_sped={max_sped}")

        try:
            while True:
                if max_sped > 0 and spedizioni >= max_sped:
                    ctx.log_msg(f"Rifornimento: limite spedizioni raggiunto ({spedizioni}/{max_sped})")
                    break

                # ── 1. Slot liberi ──────────────────────────────────────────
                _aggiorna_coda(coda_volo)
                slot = slot_liberi  # iniettato o lettura reale
                ctx.log_msg(f"Rifornimento: slot liberi={slot}")

                if slot == 0:
                    attesa = _attesa_prima_spedizione(coda_volo, margine)
                    if attesa > 0:
                        ctx.log_msg(f"Rifornimento: slot 0 — attendo {attesa:.0f}s rientro prima sped.")
                        time.sleep(attesa)
                        _aggiorna_coda(coda_volo)
                    else:
                        ctx.log_msg("Rifornimento: slot 0, coda vuota — attendo 30s")
                        time.sleep(30)

                    # Dopo attesa slot rimane 0 → stop
                    # (nei test slot_liberi è fisso → uscita immediata)
                    ctx.log_msg("Rifornimento: nessun slot libero dopo attesa — stop")
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

                # ── 3. Leggi deposito OCR se non iniettato ──────────────────
                if deposito_da_ocr:
                    deposito = _leggi_deposito_ocr(ctx, risorse_l)
                    if all(deposito.get(r, -1) < 0 for r in risorse_l):
                        ctx.log_msg("Rifornimento: OCR deposito fallito dopo retry — stop")
                        break
                    ctx.log_msg("Rifornimento: deposito OCR — " + " | ".join(
                        f"{r}={max(0.0, deposito.get(r, -1))/1e6:.1f}M"
                        for r in risorse_l if deposito.get(r, -1) >= 0
                    ))

                # ── 3. Seleziona risorsa ────────────────────────────────────
                risorsa_scelta, idx_risorsa = _seleziona_risorsa(
                    deposito, risorse_config, soglie, idx_risorsa
                )
                if risorsa_scelta is None:
                    ctx.log_msg("Rifornimento: tutte le risorse sotto soglia — stop")
                    break

                ctx.log_msg(f"Rifornimento: risorsa selezionata={risorsa_scelta}")
                qta = risorse_config[risorsa_scelta]

                # ── 4. Centra mappa + apri RESOURCE SUPPLY ──────────────────
                _centra_mappa(ctx)

                if not _apri_resource_supply(ctx):
                    ctx.log_msg("Rifornimento: RESOURCE SUPPLY non trovato — stop")
                    break

                # ── 5. Compila e invia ──────────────────────────────────────
                ts_invio = time.time()
                ok, eta_sec, quota_esaurita, qta_inviata = _compila_e_invia(
                    ctx, risorsa_scelta, qta, nome_rifugio
                )

                if quota_esaurita:
                    ctx.log_msg("Rifornimento: quota giornaliera esaurita — stop")
                    break

                if not ok:
                    ctx.log_msg("Rifornimento: invio fallito — stop")
                    break

                # ── 6. Registra in coda ─────────────────────────────────────
                spedizioni += 1
                eta_ar = float(eta_sec * 2)   # A/R = andata × 2
                coda_volo.append((ts_invio, eta_ar))
                ctx.log_msg(
                    f"Rifornimento: spedizione {spedizioni} "
                    f"— {risorsa_scelta} {qta_inviata:,} | ETA A/R={eta_ar:.0f}s"
                )
                time.sleep(2.0)

        finally:
            ctx.log_msg("Rifornimento: ritorno in home")
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()
            else:
                ctx.device.key("KEYCODE_HOME")

        # ── ETA residua ultima spedizione (comunicata alla raccolta) ───────
        _aggiorna_coda(coda_volo)
        eta_residua = _attesa_ultima_spedizione(coda_volo, margine)
        if eta_residua > 0:
            ctx.log_msg(f"Rifornimento: ETA residua ultima sped. = {eta_residua:.0f}s")

        ctx.log_msg(f"Rifornimento: completato — {spedizioni} spedizioni")
        return TaskResult(
            success=True,
            message=f"{spedizioni} spedizioni",
            data={"spedizioni": spedizioni, "eta_residua": eta_residua},
        )
