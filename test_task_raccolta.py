# ==============================================================================
#  test_task_raccolta.py — Test isolato RaccoltaTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_raccolta.py
#
#  Verifica nei log:
#    Raccolta: start — attive=0/4 libere=4
#    Raccolta: navigazione → mappa
#    Raccolta: invio squadra 1/4 → campo
#    Raccolta: LENTE → campo Lv.6
#    Raccolta: pin_gather score=0.8xx — nodo trovato
#    Raccolta: completata — N/4 squadre inviate
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.raccolta import RaccoltaTask

if __name__ == "__main__":
    # Pulisce il log precedente per evitare confusione tra run diversi
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "FAU_00.jsonl")
    if os.path.exists(log_path):
        open(log_path, "w").close()
        print(f"[SETUP] Log pulito: {log_path}")

    ctx = build_ctx("FAU_00", porta=16384)
    attendi_home("RACCOLTA")
    run_task_isolato(RaccoltaTask(), ctx, "raccolta")
