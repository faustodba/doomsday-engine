# ==============================================================================
#  DOOMSDAY ENGINE V6 — shared/banner_catalog.py
#
#  Catalogo banner/popup post-launch del gioco + dismissal pipeline.
#
#  Scopo:
#    Riduzione UNKNOWN polls in attendi_home identificando banner/popup
#    specifici e applicando l'azione corretta di chiusura (back vs tap X
#    vs tap centro vs tap coordinate fisse).
#
#  Misurato pre-catalog: avg 10.1 UNKNOWN polls/cycle, max 28, std alta
#  tra istanze (FAU_06 4.6 vs FAU_00 15.2 = 3× differenza).
#  Stima impatto: -50% UNKNOWN polls → -35% boot stabilization time.
#
#  Architettura:
#    BannerSpec dataclass (template + ROI + dismiss_action)
#    BANNER_CATALOG list ordinata per priorità
#    dismiss_banners_loop() in shared/ui_helpers.py applica iterativamente.
#
#  Deploy 1 (corrente): framework + 1 banner sicuro (banner_eventi_laterale).
#  Deploy 2 (post-discovery): popolare con template estratti da
#  debug_task/boot_unknown/ dopo 1 round di osservazione.
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BannerSpec:
    """
    Specifica di un banner/popup riconoscibile.

    Attributi:
        name:           identificativo univoco (es. "daily_login_calendar")
        template:       path relativo template (es. "pin/pin_daily_login_x.png")
        roi:            (x1, y1, x2, y2) per limitare ricerca → ridurre falsi positivi
        threshold:      soglia score minima per considerare "trovato"
        dismiss_action: una di:
                          "back"          → device.back()
                          "tap_coords"    → device.tap(*dismiss_coords)
                          "tap_center"    → device.tap(480, 270)
                          "tap_x_topright"→ device.tap(910, 80) (default)
        dismiss_coords: usato solo se dismiss_action == "tap_coords"
        wait_after_s:   sleep dopo l'azione per consentire animazione UI
        priority:       ordine di check (0=alta priorità, controllato per primo)
                        priorità alte = popup MODALI che bloccano UI
                        priorità basse = banner non-modali (come laterale)
    """
    name: str
    template: str
    roi: tuple[int, int, int, int]
    threshold: float = 0.80
    dismiss_action: str = "back"
    dismiss_coords: tuple[int, int] | None = None
    wait_after_s: float = 1.0
    priority: int = 5


# ==============================================================================
#  BANNER_CATALOG
# ==============================================================================
# Ordine di check: priority crescente (0 = primo).
#
# DEPLOY 1: solo banner_eventi_laterale (esistente, sicuro).
# Gli altri sono PLACEHOLDER da popolare dopo discovery via screenshot.
#
# Quando si aggiungono nuovi entry, validare con:
#   1. Esistenza file template in templates/pin/
#   2. ROI ragionevole (non sovrapposta a UI normale gioco)
#   3. Threshold conservativa (>=0.80 per default)
#   4. dismiss_action testato manualmente prima di prod
# ==============================================================================

BANNER_CATALOG: list[BannerSpec] = [
    # PRIORITY 5 — banner laterale eventi (HOME, non-modale)
    # Template esistente, già usato da comprimi_banner_home.
    # Inclusione qui: discovery uniforme via dismiss_banners_loop, ma
    # comprimi_banner_home() resta funzionale come pre-catalog.
    BannerSpec(
        name="banner_eventi_laterale",
        template="pin/pin_banner_aperto.png",
        roi=(330, 40, 365, 90),
        threshold=0.85,
        dismiss_action="tap_coords",
        dismiss_coords=(345, 63),
        wait_after_s=0.6,
        priority=5,
    ),

    # PLACEHOLDER — popolare dopo discovery screenshot
    # BannerSpec(name="daily_login_calendar", ...),
    # BannerSpec(name="welcome_back", ...),
    # BannerSpec(name="news_feed", ...),
    # BannerSpec(name="event_modal", ...),
    # BannerSpec(name="update_optional", ...),
]


def catalog_size() -> int:
    """Numero di banner registrati nel catalogo."""
    return len(BANNER_CATALOG)


def banner_names() -> list[str]:
    """Lista nomi banner (per telemetria/log)."""
    return [b.name for b in BANNER_CATALOG]
