# ==============================================================================
#  test_task_store.py — Test isolato StoreTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_store.py
#
#  Verifica nei log:
#    [STORE] Scan griglia 25 posizioni passo=300px
#    [STORE] passo XX → score=0.8xx *** TROVATO ***
#    [STORE] Tap carrello (XXX,XXX)
#    [STORE] Merchant aperto OK
#    [STORE] Completato — acquistati: N
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.store import StoreTask

if __name__ == "__main__":
    ctx = build_ctx("FAU_00", porta=16384)
    attendi_home("STORE")
    run_task_isolato(StoreTask(), ctx, "store")
