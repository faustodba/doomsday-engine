# ==============================================================================
#  test_task_boost.py — Test isolato BoostTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_boost.py
#
#  Verifica nei log:
#    [BOOST] pin_boost score=0.9xx → tap (142, 47)
#    [BOOST] pin_manage score=0.9xx
#    [BOOST] pin_speed TROVATO cy=XXX
#    [BOOST] Outcome='boost_attivato_8h' oppure 'boost_gia_attivo'
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.boost import BoostTask

if __name__ == "__main__":
    ctx = build_ctx("FAU_00", porta=16384)
    attendi_home("BOOST")
    run_task_isolato(BoostTask(), ctx, "boost")
