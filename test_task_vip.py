# ==============================================================================
#  test_task_vip.py — Test isolato VipTask
#
#  Uso:
#    cd C:\doomsday-engine
#    python test_task_vip.py
#
#  Verifica nei log:
#    [VIP] Tentativo 1/3
#    [PRE-VIP] pin_vip_01_store visibile — maschera aperta OK
#    [POST-C] pin_vip_03 visibile — cassaforte ritirata OK
#    [POST-F] pin_vip_05 visibile — Claim Free ritirato OK
# ==============================================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_base import build_ctx, attendi_home, run_task_isolato
from tasks.vip import VipTask

if __name__ == "__main__":
    ctx = build_ctx("FAU_00", porta=16384)
    attendi_home("VIP")
    run_task_isolato(VipTask(), ctx, "vip")
