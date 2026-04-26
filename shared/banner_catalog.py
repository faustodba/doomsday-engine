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

    DUE PATTERN DI CHIUSURA principali (auto-WU22):
      1. PULSANTE — tap su un bottone con scritta variabile (Continue/OK/
         Skip/Confirm/Salta/Annulla/Più tardi/Later/...). Usa
         `dismiss_action="tap_template"` con `dismiss_template` per find_one
         dinamico → tap sulla posizione del match.
      2. X TOP-RIGHT — tap su icona X close in alto a destra (canonico
         (910, 80) ma override possibile via `dismiss_coords`). Usa
         `dismiss_action="tap_x_topright"`.

    Altri dismiss_action legacy: "back", "tap_coords", "tap_center".

    Attributi:
        name:             identificativo univoco (es. "daily_login_calendar")
        template:         path relativo template per DETECTION (es. "pin/pin_daily_login_x.png")
        roi:              (x1, y1, x2, y2) per limitare ricerca → ridurre falsi positivi
        threshold:        soglia score minima per considerare "trovato"
        dismiss_action:   una di:
                            "tap_template"   → find_one(dismiss_template) + tap match
                            "tap_x_topright" → tap su (910,80) o dismiss_coords se set
                            "tap_coords"     → tap su dismiss_coords fisso
                            "tap_center"     → tap (480, 270)
                            "back"           → device.back()
        dismiss_template: path template del PULSANTE da tappare (per "tap_template")
        dismiss_template_roi: ROI ricerca pulsante (default = roi)
        dismiss_template_soglia: soglia match pulsante (default = threshold)
        dismiss_coords:   coords fisse (per "tap_coords" / override "tap_x_topright")
        wait_after_s:     sleep dopo l'azione per consentire animazione UI
        priority:         ordine di check (0=alta priorità)
                          - priorità basse 0-3 = popup MODALI che bloccano UI
                          - priorità medie 4-6 = banner non-modali
                          - priorità alte 7-9 = ultimi tentativi generici
    """
    name: str
    template: str
    roi: tuple[int, int, int, int]
    threshold: float = 0.80
    dismiss_action: str = "tap_x_topright"
    dismiss_template: str | None = None
    dismiss_template_roi: tuple[int, int, int, int] | None = None
    dismiss_template_soglia: float | None = None
    dismiss_coords: tuple[int, int] | None = None
    wait_after_s: float = 1.0
    priority: int = 5


# Coordinate canoniche per X close in alto a destra (override per popup specifici)
DEFAULT_X_TOPRIGHT = (910, 80)


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
    # ==================================================================
    # PRIORITY 0 — CRITICO. "Exit game?" dialog (auto-WU22 discovery).
    # ==================================================================
    # CAUSA ROOT del pattern UNKNOWN persistente vai_in_home FALLITO 8/8:
    # il polling cieco BACK del launcher PREMENDO BACK su HOME apre il dialog
    # di sistema "Exit game?". Senza catalogazione il bot loop su BACK→dialog
    # → BACK→dialog senza progresso fino a timeout. Se per caso seleziona OK
    # il gioco viene CHIUSO (catastrofico).
    # Mitigazione: rilevare il dialog (testo "Exit game?") e tappare il
    # bottone CANCEL (template grigio bordo bottone) per chiuderlo.
    # ROI dialog: testo centrato a (~430, 220) – ROI larga per tolleranza.
    # ROI cancel: bottone (~290-455, 355-405) – ROI dello stesso button.
    BannerSpec(
        name="exit_game_dialog",
        template="pin/pin_exit_game_dialog.png",
        roi=(380, 200, 580, 280),
        threshold=0.80,
        dismiss_action="tap_template",
        dismiss_template="pin/pin_btn_cancel.png",
        dismiss_template_roi=(270, 340, 470, 415),
        dismiss_template_soglia=0.75,
        wait_after_s=1.5,  # animazione chiusura dialog
        priority=0,
    ),

    # ==================================================================
    # PRIORITY 1 — "Auto collect AFK resources" (discovery 26/04/2026)
    # ==================================================================
    # Modale post-launch deterministico: appare alla prima HOME/MAP read
    # quando ci sono risorse AFK accumulate dal Mysterious Merchant.
    # NON ha X in alto a destra → unica via di chiusura: bottone "Confirm"
    # in basso (centrato, giallo arrotondato). BACK funziona ma più lento.
    # Detection: testo "AFK resources" giallo discriminante (ROI banda alta).
    # Dismiss: tap su pulsante Confirm template-matched (varia leggermente
    # in posizione tra versioni, no coords fisse).
    BannerSpec(
        name="auto_collect_afk_banner",
        template="pin/pin_auto_collect_banner.png",
        roi=(530, 60, 780, 115),
        threshold=0.80,
        dismiss_action="tap_template",
        dismiss_template="pin/pin_btn_confirm.png",
        dismiss_template_roi=(480, 460, 730, 515),
        dismiss_template_soglia=0.75,
        wait_after_s=2.0,  # animazione acquisizione risorse
        priority=1,
    ),

    # ==================================================================
    # PRIORITY 5 — banner laterale eventi (HOME, non-modale)
    # ==================================================================
    # DISABILITATO 26/04/2026 (auto-WU16) — il tap di chiusura su (345,63)
    # nascondeva l'icona DS quando questa scivolava sotto la prima riga
    # della barra eventi (FAU_00/04/06 ciclo 22:45-23:25 skip "icona DS
    # non trovata" con HOME score 0.994). Lasciando il banner aperto
    # all'avvio l'icona resta accessibile al task DS.
    # Per riabilitare: decommenta il blocco sotto.
    # BannerSpec(
    #     name="banner_eventi_laterale",
    #     template="pin/pin_banner_aperto.png",
    #     roi=(330, 40, 365, 90),
    #     threshold=0.85,
    #     dismiss_action="tap_coords",
    #     dismiss_coords=(345, 63),
    #     wait_after_s=0.6,
    #     priority=5,
    # ),

    # PLACEHOLDER — popolare dopo discovery screenshot ulteriore:
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
