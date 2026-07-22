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

from dataclasses import dataclass


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
    wait_open_s:     float = 2.0
    wait_claim_s:    float = 2.0
    wait_close_s:    float = 1.5


# Icona HOME (STEP 0 — pre-check più economico, prima di aprire l'hub)
TAP_HOME_ICON:   tuple[int, int]             = (895, 68)
HOME_BADGE_ROI:  tuple[int, int, int, int]   = (935, 45, 960, 68)

# Uscita hub
TAP_HUB_BACK:    tuple[int, int]             = (30, 30)

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
