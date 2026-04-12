# ==============================================================================
#  test_task_messaggi_alleanza.py — Test isolato MessaggiTask + AlleanzaTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_messaggi_alleanza.py
#
#  Verifica nei log:
#    [MSG] Tap icona messaggi (930, 13)
#    [MSG] [PRE-OPEN] score=0.8xx → OK
#    [ALLEANZA] Tap Alleanza (760, 505)
#    [ALLEANZA] Rivendica completato: N tap
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.messaggi import MessaggiTask
from tasks.alleanza import AlleanzaTask

if __name__ == "__main__":
    ctx = build_ctx("FAU_00", porta=16384)

    attendi_home("MESSAGGI + ALLEANZA")

    print("[TEST] === MESSAGGI ===")
    run_task_isolato(MessaggiTask(), ctx, "messaggi")

    print()
    print("[TEST] Riporta manualmente l'istanza in HOME se necessario")
    input(">>> Premi INVIO per lanciare ALLEANZA: ")
    print()

    print("[TEST] === ALLEANZA ===")
    run_task_isolato(AlleanzaTask(), ctx, "alleanza")
