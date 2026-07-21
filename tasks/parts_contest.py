"""
tasks/parts_contest.py — PartsContestTask V6
============================================================================
Task custom master (21/07/2026) — evento Special Promo → Parts Contest.
Sottoclasse sottile di tasks/special_promo._SpecialPromoContestBase (logica
comune ai contest): questo contest HA i sotto-tab Daily Missions/Challenges
(claim VERDI) oltre alla traccia (COLLECT ALL).

Validato end-to-end live 21/07 su FAU_00: claim verdi → level up traccia →
COLLECT ALL → box ritirati, badge azzerato, nessun pulsante a pagamento.

Solo master, periodico 12h (via task_overrides + profilo master). Dettagli
logica/sicurezza/discriminanti: vedi tasks/special_promo.py.
"""

from __future__ import annotations

from tasks.special_promo import SpecialPromoContestConfig, _SpecialPromoContestBase


class PartsContestTask(_SpecialPromoContestBase):
    """Ritira le ricompense GRATIS di Special Promo → Parts Contest.
    HA i sotto-tab (claim verdi) + traccia (COLLECT ALL)."""

    def __init__(self, config: SpecialPromoContestConfig | None = None) -> None:
        super().__init__(config or SpecialPromoContestConfig(
            pin_menu="pin/pin_parts_contest.png",
            menu_nome="Parts Contest",
            has_subtabs=True,
        ))

    def name(self) -> str:
        return "parts_contest"
