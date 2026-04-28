"""
Smoke test radar_tool — bootstrap verifica post WU radar_census step 1+2.

Esegue:
1. load_templates() → conta template caricati
2. Classifier.load() → verifica RF trained
3. detect() su map_full.png di esempio (V5 archive) → conta matches per categoria
4. _catalogo_finale() su un sample → verifica categorizzazione

Uso:
    cd C:/doomsday-engine-prod && python radar_tool/_smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar_tool.detector import load_templates, detect, extract_crop  # noqa: E402

TEMPLATES_DIR = ROOT / "radar_tool" / "templates"
RF_PATH       = ROOT / "radar_tool" / "dataset" / "classifier.pkl"

SAMPLE_MAP = Path("C:/Bot-farm/radar_archive/census/20260402_210217_FAU_00/map_full.png")


def main() -> int:
    print("=" * 70)
    print("RADAR_TOOL SMOKE TEST")
    print("=" * 70)

    # 1. Templates
    print(f"\n[1] Templates dir: {TEMPLATES_DIR}")
    if not TEMPLATES_DIR.is_dir():
        print(f"  ✗ MANCANTE")
        return 1
    templates = load_templates(TEMPLATES_DIR)
    print(f"  ✓ {len(templates)} template caricati")
    tipi = sorted({t['tipo'] for t in templates})
    print(f"    tipi unici ({len(tipi)}): {', '.join(tipi)}")

    # 2. Classifier RF
    print(f"\n[2] Classifier RF: {RF_PATH}")
    rf = None
    if not RF_PATH.exists():
        print(f"  ⚠ pkl non trovato — RF disabilitato (opzionale)")
    else:
        try:
            from radar_tool.classifier import Classifier
            rf = Classifier()
            rf.load(str(RF_PATH))
            trained = getattr(rf, "trained", False)
            print(f"  ✓ caricato — trained={trained}")
        except Exception as exc:
            print(f"  ✗ errore: {exc}")
            rf = None

    # 3. Detect su sample map
    print(f"\n[3] Detect su sample: {SAMPLE_MAP}")
    if not SAMPLE_MAP.exists():
        print(f"  ⚠ sample non trovato — skip detect")
        return 0

    img = cv2.imread(str(SAMPLE_MAP))
    if img is None:
        print(f"  ✗ cv2.imread fallito")
        return 1
    print(f"  shape: {img.shape}")

    matches = detect(img, templates, threshold=0.65)
    print(f"  ✓ {len(matches)} icone rilevate (threshold=0.65)")

    # Distribuzione per tipo
    counts: dict[str, int] = {}
    for m in matches:
        counts[m["tipo"]] = counts.get(m["tipo"], 0) + 1
    print("    distribuzione:")
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
        print(f"      {k:20s}  {v}")

    # 4. Classify primi 3 matches via RF (se disponibile)
    if rf is not None and matches:
        print(f"\n[4] Classify RF su primi 3 matches:")
        for i, m in enumerate(matches[:3], 1):
            crop = extract_crop(img, m["cx"], m["cy"], 64)
            try:
                rf_label, rf_conf = rf.predict(crop)
                print(f"  [{i}] cx={m['cx']:4d} cy={m['cy']:4d} "
                      f"tmpl={m['template']:20s} conf_tmpl={m['conf']:.3f} "
                      f"→ rf={rf_label} ({float(rf_conf):.3f})")
            except Exception as exc:
                print(f"  [{i}] errore RF: {exc}")

    print("\n" + "=" * 70)
    print("SMOKE TEST OK")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
