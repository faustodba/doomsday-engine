"""
tasks/customization_contest.py — CustomizationContestTask V6
============================================================================
Task custom master (21/07/2026) — evento Special Promo → Customization Contest.
Sottoclasse sottile di tasks/special_promo._SpecialPromoContestBase.

DIFFERENZA da Parts Contest (verificata live 21/07 su FAU_00, confermata
dall'utente): questo contest NON ha i sotto-tab Daily Missions/Challenges — è
una TRACCIA DIRETTA con solo il pulsante "COLLECT ALL" (gratis). Quindi
has_subtabs=False: si va dritto al COLLECT ALL (match testo pin_collect_all,
score 0.935 validato su questa traccia). Il gate pallino rosso sulla voce
sidebar decide se processare (badge presente = ricompense).

Solo master, periodico 12h (via task_overrides + profilo master). Dettagli
logica/sicurezza/discriminanti: vedi tasks/special_promo.py.
"""

from __future__ import annotations

from tasks.special_promo import SpecialPromoContestConfig, _SpecialPromoContestBase


class CustomizationContestTask(_SpecialPromoContestBase):
    """Ritira le ricompense GRATIS di Special Promo → Customization Contest.
    Solo traccia + COLLECT ALL (nessun sotto-tab)."""

    def __init__(self, config: SpecialPromoContestConfig | None = None) -> None:
        super().__init__(config or SpecialPromoContestConfig(
            pin_menu="pin/pin_customization_contest.png",
            menu_nome="Customization Contest",
            has_subtabs=False,
        ))

    def name(self) -> str:
        return "customization_contest"
