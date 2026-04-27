"""
Polling-based monitor: scansiona log FAU_*.jsonl ogni 1s.
Quando trova "Rifornimento: RESOURCE SUPPLY trovato" con ts recente (<15s),
attende 1.7s e cattura screenshot via adb.
"""
import json, subprocess, time, sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR  = Path("C:/doomsday-engine-prod/logs")
INST_CFG = Path("C:/doomsday-engine-prod/config/instances.json")
OUT_DIR  = Path("C:/doomsday-engine-prod/temp_screen")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRIGGER = "RESOURCE SUPPLY trovato"
WAIT_AFTER = 1.7
MAX_AGE_S  = 15  # ignora trigger più vecchi di 15s

def load_ports():
    with open(INST_CFG, encoding="utf-8") as f:
        d = json.load(f)
    return {i["nome"]: int(i["porta"]) for i in d if isinstance(i, dict) and "porta" in i}

_ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Programmi\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    "adb",
]
_ADB = next((p for p in _ADB_CANDIDATES if Path(p).exists() or p == "adb"), "adb")

def adb_screencap(port: int, out_path: Path) -> bool:
    serial = f"127.0.0.1:{port}"
    try:
        subprocess.run([_ADB, "connect", serial], capture_output=True, timeout=5)
        cp = subprocess.run(
            [_ADB, "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=10
        )
        if cp.returncode != 0 or len(cp.stdout) < 1000:
            print(f"[ERR] screencap port={port} rc={cp.returncode} bytes={len(cp.stdout)}", flush=True)
            return False
        out_path.write_bytes(cp.stdout)
        return True
    except Exception as e:
        print(f"[ERR] screencap port={port}: {e}", flush=True)
        return False

def parse_ts(ts_str: str) -> float:
    # "2026-04-27T10:55:28.319045+00:00" → epoch
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except Exception:
        return 0.0

def last_lines(fp: Path, last_size: int) -> tuple[list[str], int]:
    try:
        cur = fp.stat().st_size
    except FileNotFoundError:
        return [], last_size
    if cur <= last_size:
        return [], cur
    try:
        with open(fp, "rb") as f:
            f.seek(last_size)
            chunk = f.read().decode("utf-8", errors="replace")
        return chunk.splitlines(), cur
    except Exception:
        return [], cur

def main():
    ports = load_ports()
    print(f"[OK] {len(ports)} istanze caricate", flush=True)

    paths = [LOG_DIR / f"{n}.jsonl" for n in ports if (LOG_DIR / f"{n}.jsonl").exists()]
    print(f"[OK] monitor {len(paths)} log files (poll 1s)", flush=True)

    # inizializzo posizione corrente — saltiamo lo storico
    pos = {p: p.stat().st_size for p in paths}
    captured = set()

    print(f"[OK] in attesa trigger '{TRIGGER}' (max-age {MAX_AGE_S}s)...", flush=True)

    while True:
        time.sleep(1.0)
        now = time.time()
        for p in paths:
            ist = p.stem
            if ist in captured:
                continue
            new_lines, new_pos = last_lines(p, pos[p])
            pos[p] = new_pos
            for line in new_lines:
                if TRIGGER not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts_ev = parse_ts(d.get("ts", ""))
                age = now - ts_ev
                if age > MAX_AGE_S:
                    print(f"[STALE] {ist} ts age={age:.1f}s — skip", flush=True)
                    continue
                port = ports.get(ist)
                if not port:
                    continue
                print(f"\n[TRIGGER] {ist} port={port} ts={d.get('ts','')[11:19]} age={age:.1f}s", flush=True)
                print(f"[WAIT] {WAIT_AFTER}s for popup render...", flush=True)
                time.sleep(WAIT_AFTER)
                out = OUT_DIR / f"maschera_{ist}_{int(now)}.png"
                if adb_screencap(port, out):
                    print(f"[OK] CAPTURED → {out}", flush=True)
                    captured.add(ist)
                    return  # exit on first success
                else:
                    print(f"[FAIL] {ist} screencap fallito", flush=True)

if __name__ == "__main__":
    sys.exit(main() or 0)
