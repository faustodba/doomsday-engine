# ==============================================================================
#  test_task_arena.py — Test isolato ArenaTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_arena.py
#
#  Verifica nei log:
#    [ARENA] home confermata via navigator
#    [ARENA] HOME → Campaign
#    [ARENA] [PRE-LISTA] lista aperta OK
#    [ARENA] [PRE-CHALLENGE] START CHALLENGE — tap
#    [ARENA] [POST-BATTAGLIA] Victory / Failure
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.arena import ArenaTask

if __name__ == "__main__":
    ctx = build_ctx("FAU_00", porta=16384)
    attendi_home("ARENA")
    run_task_isolato(ArenaTask(), ctx, "arena")
