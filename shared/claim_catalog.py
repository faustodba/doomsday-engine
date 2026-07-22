# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/claim_catalog.py
#
#  Catalogo dichiarativo dei claim gratuiti nell'hub "Event Center" (icona
#  rotante in alto a destra su HOME, alterna label "Event Center"/"Water
#  War"/"Arms Race"/ecc. a seconda dell'evento in vetrina — stesso tap
#  target indipendentemente dalla label mostrata).
#
#  Scopo: stesso pattern di shared/banner_catalog.py — una voce per ogni
#  sottomenu VERIFICATO A MANO come claim gratuito (mai scoperta automatica
#  alla cieca: un pallino rosso da solo NON basta, es. "Match Predictions"
#  ha il pallino ma è un pronostico/scelta, non un claim — resta fuori dal
#  catalogo finché non esiste una logica dedicata).
#
#  Architettura a 3 livelli di gate (dal più economico al più costoso):
#    1. Pallino rosso sull'icona HOME stessa — se assente, skip totale,
#       nessuna navigazione.
#    2. Pallino rosso sulla riga sidebar della voce catalogata — se assente,
#       skip quella voce, provo la successiva.
#    3. Template del pulsante CLAIM verde SPECIFICO della voce (verificato
#       a mano) — unico segnale che autorizza il tap. Il pallino rosso è
#       solo un pre-filtro di velocità, mai l'unico segnale per agire.
#
#  22/07/2026 — prima voce: Login Rewards (calendario accesso 7 giorni,
#  verificato dal vivo su FAU_00, 3/7 claim riscossi con successo).
# ==============================================================================

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ClaimMenuSpec:
    """
    Specifica di un sottomenu con claim gratuito nell'hub Event Center.

    Attributi:
        name:            identificativo univoco (es. "login_rewards")
        tap_sidebar:     coordinate tap sulla voce nella sidebar dell'hub
        badge_roi:       (x1,y1,x2,y2) ROI del pallino rosso sulla riga
                         sidebar di questa voce (pre-filtro STEP 2)
        claim_template:  path template del pulsante CLAIM verde SPECIFICO
                         di questo sottomenu (mai un template generico —
                         stili diversi da menu a menu, verificato che non
                         dia falsi positivi su altri sottomenu dell'hub)
        claim_zone:      ROI di ricerca del claim dentro il sottomenu
        claim_threshold: soglia match claim
        tap_close_safe:  coordinate tap per chiudere il popup ricompensa —
                         DEVE essere in una zona vuota, mai sovrapposta a
                         un pulsante claim successivo (rischio doppio-claim
                         accidentale)
        max_claims:      loop safety — numero massimo di claim consecutivi
                         per questa voce in un singolo run
        n_scroll:        numero di swipe "avanti" (SIDEBAR_SCROLL_FWD) da
                         applicare DOPO aver riportato la sidebar in cima
                         (SIDEBAR_SCROLL_RESET), per rivelare voci sotto la
                         piega. 0 = voce già visibile in cima (nessuno
                         scroll, es. Login Rewards).
        wait_open_s:     attesa dopo il tap sulla voce sidebar
        wait_claim_s:    attesa dopo il tap sul claim (animazione popup)
        wait_close_s:    attesa dopo la chiusura del popup
    """
    name:            str
    tap_sidebar:     tuple[int, int]
    badge_roi:       tuple[int, int, int, int]
    claim_template:  str
    claim_zone:      tuple[int, int, int, int]
    claim_threshold: float = 0.80
    tap_close_safe:  tuple[int, int] = (100, 450)
    max_claims:      int = 10
    n_scroll:        int = 0
    wait_open_s:     float = 2.0
    wait_claim_s:    float = 2.0
    wait_close_s:    float = 1.5


# Icona HOME (STEP 0 — pre-check più economico, prima di aprire l'hub)
TAP_HOME_ICON:   tuple[int, int]             = (895, 68)
HOME_BADGE_ROI:  tuple[int, int, int, int]   = (935, 45, 960, 68)

# Uscita hub
TAP_HUB_BACK:    tuple[int, int]             = (30, 30)

# Scroll sidebar: alcune voci catalogate sono sotto la piega (es. Survival
# Preparations, Titan Approaches...), la sidebar va scorsa per rivelarle.
# RESET riporta sempre in cima (overshoot sicuro: il rebound si ferma da
# solo a inizio lista), FWD rivela un "blocco" di voci più in basso.
# Calibrato live su FAU_00 22/07 (swipe (105,450)->(105,250) = 1 blocco).
SIDEBAR_SCROLL_RESET_N:  int = 4   # ripetizioni overshoot per garantire la cima
SIDEBAR_SCROLL_RESET:    tuple[int, int, int, int, int] = (105, 250, 105, 450, 500)
SIDEBAR_SCROLL_FWD:      tuple[int, int, int, int, int] = (105, 450, 105, 250, 600)

# Soglia frazione pixel rossi per considerare un pallino "presente"
# (stesso ordine di grandezza di _ha_badge_rosso in tasks/special_promo.py)
BADGE_RED_S_MIN:   int   = 100
BADGE_RED_V_MIN:   int   = 100
BADGE_RED_MIN_FRAC: float = 0.08


CLAIM_CATALOG: list[ClaimMenuSpec] = [
    ClaimMenuSpec(
        name="login_rewards",
        tap_sidebar=(118, 318),
        badge_roi=(185, 288, 215, 312),
        claim_template="pin/pin_login_rewards_claim.png",
        claim_zone=(780, 150, 925, 520),
        claim_threshold=0.80,
        tap_close_safe=(100, 450),
        max_claims=7,
    ),
    # 22/07 — "Survival Preparations — Plan for the future": stesso
    # identico pulsante CLAIM di Login Rewards (verificato: score 1.0 sulla
    # sorgente, riusa lo stesso template). Missioni gratuite guidate dal
    # gameplay normale (Daily Check-In, Empty N Resource Nodes — matura da
    # sola con raccolta; Use Normal Search Map; Buy from Mysterious
    # Merchant — matura con store). Verificato dal vivo: un tap ha claimato
    # in batch Daily Check-In + Empty 1/2/5 Resource Nodes insieme (il gioco
    # risolve tutti i claim pronti in un colpo, non serve un tap per riga).
    # Sotto la piega della sidebar: 1 blocco di scroll da cima.
    ClaimMenuSpec(
        name="survival_preparations",
        tap_sidebar=(105, 105),
        badge_roi=(185, 85, 215, 105),
        claim_template="pin/pin_login_rewards_claim.png",
        claim_zone=(780, 150, 925, 520),
        claim_threshold=0.80,
        tap_close_safe=(100, 450),
        max_claims=6,
        n_scroll=1,
    ),
]


def catalog_names() -> list[str]:
    """Lista nomi voci catalogate (per telemetria/log)."""
    return [c.name for c in CLAIM_CATALOG]


def frazione_pallino_rosso(frame, roi: tuple[int, int, int, int]) -> float:
    """Frazione di pixel rossi (pallino notifica) nella ROI data.
    Stesso metodo HSV di tasks/special_promo.py::_ha_badge_rosso, estratto
    qui come utility standalone riusabile (frame numpy BGR, no I/O)."""
    import cv2
    x0, y0, x1, y1 = roi
    sub = frame[y0:y1, x0:x1]
    if sub.size == 0:
        return 0.0
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]; s = hsv[..., 1]; v = hsv[..., 2]
    red = ((h <= 8) | (h >= 172)) & (s > BADGE_RED_S_MIN) & (v > BADGE_RED_V_MIN)
    return float(red.mean())


# ==============================================================================
#  DISCOVERY — auto-apprendimento voci sidebar non catalogate (22/07/2026)
# ==============================================================================
#
#  Su richiesta utente: "la prima istanza che entra fa anche uno scan completo
#  degli eventi, quando ne trova uno non catalogato impara se c'è un claim e
#  lo clicca ed aggiorna il catalogo". Stesso principio di
#  shared/banner_learner.py (WU93/WU190) ma con un margine di sicurezza in
#  più: non si tappa MAI un pulsante mai visto — si cerca solo il widget
#  CLAIM verde GIÀ VERIFICATO (oggi: pin_login_rewards_claim.png, dimostrato
#  riusato identico su 2 sistemi eventi diversi, score 1.0 su entrambi). Se
#  in un nuovo menu quel widget non matcha, la voce viene imparata come
#  "non claimabile" e non più ri-visitata — mai un tap esplorativo su
#  qualcosa di sconosciuto.
#
#  Rilevamento pallini GENERICO (a differenza di badge_roi, fisso per voce
#  nota): scansiona l'intera colonna sidebar via blob HSV rosso, filtrato
#  per colonna X (dove il gioco disegna sempre i badge numerici) e area
#  minima (scarta il rumore di icone con tinte rosse/arancioni nell'artwork
#  — calibrato live: badge reali area>=150, rumore icone area<80).

SIDEBAR_ZONE_ROI:  tuple[int, int, int, int] = (0, 60, 220, 520)
BADGE_COLUMN_X:    tuple[int, int]           = (185, 215)
BADGE_MIN_AREA:    int                       = 150
MAX_SCROLL_DEPTH:  int                       = 6   # margine oltre le ~5 profondità osservate
TITLE_OCR_ZONE:    tuple[int, int, int, int] = (40, 15, 500, 55)
ROW_TAP_X:         int                       = 105
DISCOVERY_CLAIM_TEMPLATE: str                = "pin/pin_login_rewards_claim.png"
DISCOVERY_CLAIM_ZONE:     tuple[int, int, int, int] = (780, 150, 925, 520)
DISCOVERY_CLAIM_THRESHOLD: float             = 0.80

_DATA_DIR             = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_LEARNED_PATH          = os.path.join(_DATA_DIR, "claim_catalog_learned.json")
_DISCOVERY_STATE_PATH  = os.path.join(_DATA_DIR, "claim_discovery_state.json")


def trova_pallini_sidebar(frame) -> list[tuple[int, int]]:
    """Trova tutti i pallini rossi (badge notifica) nella colonna sidebar,
    filtrando il rumore delle icone (area minima + colonna X dei badge,
    calibrato live su screenshot reale: 3/3 badge veri isolati, rumore
    icone scartato). Ritorna centroidi (x,y) in coordinate ASSOLUTE frame."""
    import cv2
    x0, y0, x1, y1 = SIDEBAR_ZONE_ROI
    roi = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]; s = hsv[..., 1]; v = hsv[..., 2]
    mask = (((h <= 8) | (h >= 172)) & (s > BADGE_RED_S_MIN) & (v > BADGE_RED_V_MIN)).astype("uint8") * 255
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < BADGE_MIN_AREA:
            continue
        cx = centroids[i][0] + x0
        cy = centroids[i][1] + y0
        if BADGE_COLUMN_X[0] <= cx <= BADGE_COLUMN_X[1]:
            out.append((int(cx), int(cy)))
    return out


def carica_appreso() -> dict:
    """Catalogo appreso (voci scoperte in discovery, claimabili o no).
    Persistito in data/claim_catalog_learned.json, sopravvive ai restart."""
    try:
        with open(_LEARNED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salva_appreso(catalogo: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp = _LEARNED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _LEARNED_PATH)


def serve_discovery_oggi() -> bool:
    """True se la scansione completa non è ancora stata fatta oggi (UTC).
    'La prima istanza che entra' = la prima che trova questo flag scaduto."""
    oggi = datetime.now(timezone.utc).date().isoformat()
    try:
        with open(_DISCOVERY_STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        return st.get("last_scan_date") != oggi
    except Exception:
        return True


def segna_discovery_fatta() -> None:
    oggi = datetime.now(timezone.utc).date().isoformat()
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp = _DISCOVERY_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"last_scan_date": oggi}, f)
    os.replace(tmp, _DISCOVERY_STATE_PATH)
