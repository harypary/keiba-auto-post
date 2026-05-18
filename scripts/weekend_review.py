"""5/16-17 土日の予想結果サマリー"""
import sys, os, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.validator.results_fetcher import ResultsFetcher

PRED_DIR = "data/predictions"

# 土日のレース race_id を抽出（saved_at から 2026-05-16 or 2026-05-17）
preds = []
for fp in glob.glob(f"{PRED_DIR}/*.json"):
    try:
        d = json.load(open(fp, encoding="utf-8"))
        sat = d.get("saved_at", "")
        if "2026-05-16" in sat or "2026-05-17" in sat:
            preds.append(d)
    except Exception:
        pass

print(f"対象予想: {len(preds)}件")
fetcher = ResultsFetcher()

honmei_win = 0
honmei_place = 0
exacta_hit = 0
trifecta_hit = 0
total = 0
total_stake = 0
total_return = 0

for p in preds:
    res = fetcher.get_race_result(p["race_id"])
    if not res or not res.get("order"):
        continue
    actual = [r["horse_no"] for r in res["order"][:3]]
    if len(actual) < 3:
        continue
    total += 1
    honmei = p["honmei"][0] if p.get("honmei") else None
    if honmei == actual[0]:
        honmei_win += 1
    if honmei in actual:
        honmei_place += 1

    payouts = res.get("payouts", {})

    # 馬連
    for a, b in p.get("exacta_bets", []):
        total_stake += 100
        if set([a, b]) <= set(actual[:2]):
            exacta_hit += 1
            total_return += payouts.get("馬連", 0)
    # 3連複
    for combo in p.get("trifecta_bets", []):
        if len(combo) < 3: continue
        total_stake += 100
        if set(combo[:3]) <= set(actual[:3]):
            trifecta_hit += 1
            total_return += payouts.get("3連複", 0)
    # 単勝（◎本命）
    if honmei:
        total_stake += 100
        if honmei == actual[0]:
            total_return += payouts.get("単勝", 0)

print(f"\n=== 集計結果（{total}レース）===")
if total > 0:
    print(f"◎本命 勝率:   {honmei_win}/{total} = {honmei_win/total*100:.1f}%")
    print(f"◎本命 複勝率: {honmei_place}/{total} = {honmei_place/total*100:.1f}%")
    print(f"馬連 的中:    {exacta_hit}")
    print(f"3連複 的中:   {trifecta_hit}")
    if total_stake > 0:
        print(f"\n投資: {total_stake:,}円 / 回収: {total_return:,}円 / ROI: {total_return/total_stake*100:.1f}%")
