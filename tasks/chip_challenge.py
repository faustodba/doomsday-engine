"""
tasks/chip_challenge.py — ChipChallengeTask V6
============================================================================
Task custom master (21/07/2026) — evento Special Promo → Chip Challenge.
Sottoclasse sottile di tasks/special_promo._SpecialPromoContestBase.

Struttura verificata live 21/07 sul master: identica a Customization/Vehicle —
TRACCIA DIRETTA con solo "COLLECT ALL" (gratis), NESSUN sotto-tab Daily
Missions/Challenges → has_subtabs=False. pin_collect_all riusato (score 0.935).
Il gate pallino rosso sulla voce sidebar decide se processare.

Solo master, periodico 12h (via task_overrides + profilo master). Dettagli
logica/sicurezza/discriminanti: vedi tasks/special_promo.py.
"""

from __future__ import annotations

from tasks.special_promo import SpecialPromoContestConfig, _SpecialPromoContestBase


class ChipChallengeTask(_SpecialPromoContestBase):
    """Ritira le ricompense GRATIS di Special Promo → Chip Challenge.
    Solo traccia + COLLECT ALL (nessun sotto-tab)."""

    def __init__(self, config: SpecialPromoContestConfig | None = None) -> None:
        super().__init__(config or SpecialPromoContestConfig(
            pin_menu="pin/pin_chip_challenge.png",
            menu_nome="Chip Challenge",
            has_subtabs=False,
        ))

    def name(self) -> str:
        return "chip_challenge"
