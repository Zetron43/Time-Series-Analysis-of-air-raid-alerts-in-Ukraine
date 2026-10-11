import json
import os
from pathlib import Path
from src.evaluation.multi_region_real_eval import evaluate_region_on_real_period, REGIONS_TO_EVALUATE

results = []
print("Starting evaluation...")
for reg in REGIONS_TO_EVALUATE:
    print(f"--> Evaluating {reg}...")
    r = evaluate_region_on_real_period(reg)
    results.append(r)
    print(f"    Done {reg}: PR-AUC={r['lightgbm']['pr_auc']}, Baseline={r['baseline']['pr_auc']}")

out_file = Path("reports/multi_region_real_results.json").resolve()
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=float)
    f.flush()
    os.fsync(f.fileno())

print(f"FILE WRITTEN TO: {out_file}, exists: {out_file.exists()}, size: {out_file.stat().st_size}")
