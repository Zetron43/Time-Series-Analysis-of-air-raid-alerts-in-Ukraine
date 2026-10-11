import json
import os
import sys
from pathlib import Path
from src.evaluation.multi_region_real_eval import evaluate_region_on_real_period

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

regions = ["Kyiv City", "Kharkivska oblast", "Odeska oblast"]
results = []

print("=" * 80)
print("РОЗРАХУНОК ОЦІНКИ МОДЕЛІ НА РЕАЛЬНОМУ ТЕСТОВОМУ ПЕРІОДІ (ЛІТО 2026)")
print("=" * 80)

for reg in regions:
    print(f"\n[+] Обчислення для: {reg}...")
    r = evaluate_region_on_real_period(reg, start_date="2025-06-01", end_date="2026-09-01")
    results.append(r)
    base = r["baseline"]
    lgb = r["lightgbm"]
    print(f"    Частка тривог у тесті: {r['test_alert_prevalence']}%")
    print(f"    LightGBM: PR-AUC = {lgb['pr_auc']:.4f} | Brier = {lgb['brier_score']:.4f} | F1 = {lgb['f1']:.4f} (Rec={lgb['recall']}%, Prec={lgb['precision']}%)")
    print(f"    Baseline: PR-AUC = {base['pr_auc']:.4f} | Brier = {base['brier_score']:.4f} | F1 = {base['f1']:.4f} (Rec={base['recall']}%, Prec={base['precision']}%)")
    print(f"    Прогноз НОВИХ тривог: LightGBM Onset PR-AUC = {lgb['onset_pr_auc']:.4f} (Рівень No-Skill = {r['onset_random_rate']}%)")

out_file = Path("reports/real_test_period_results.json")
out_file.parent.mkdir(parents=True, exist_ok=True)
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=float)

print("\n" + "=" * 80)
print(f"РЕЗУЛЬТАТИ ЗБЕРЕЖЕНО В: {out_file}")
print("=" * 80)
