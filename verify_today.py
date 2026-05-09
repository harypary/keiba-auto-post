"""今日の予測vs実結果を検証"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from src.scraper.jra_scraper import JRAScraper
from src.validator.results_fetcher import ResultsFetcher
from collections import Counter

target = date(2026, 5, 9)
predictions = json.load(open("today_predictions.json", encoding="utf-8"))
jra = JRAScraper()
fetcher = ResultsFetcher()

# race_id mapを作成
race_ids = jra.get_race_list_for_date(target)
key_to_id = {}
for r in race_ids:
    info = jra.get_shutuba_table(r["race_id"])
    if info:
        key_to_id[f"{info.venue}{info.race_no}"] = r["race_id"]

results = []
hit_honmei_win = 0
hit_honmei_place = 0
hit_top3 = 0
total_completed = 0
factor_misses = Counter()

for p in predictions:
    key = f"{p['venue']}{p['no']}"
    rid = key_to_id.get(key)
    if not rid:
        continue
    res = fetcher.get_race_result(rid)
    if not res or not res.get("order"):
        results.append({**p, "status": "未確定"})
        continue
    actual = [r["horse_no"] for r in res["order"][:3]]
    if not actual:
        results.append({**p, "status": "未確定"})
        continue
    total_completed += 1

    honmei_no = p["honmei"][0][0] if p["honmei"] else None
    taikou_no = p["taikou"][0][0] if p["taikou"] else None
    tanana_no = p["tanana"][0][0] if p["tanana"] else None
    top3_pred = [t[0] for t in p["top6"][:3]]

    is_win = (honmei_no == actual[0])
    is_place = (honmei_no in actual) if honmei_no else False
    top3_overlap = len(set(top3_pred) & set(actual))

    if is_win: hit_honmei_win += 1
    if is_place: hit_honmei_place += 1
    if top3_overlap >= 2: hit_top3 += 1

    name_of = {t[0]: t[1] for t in p["top6"]}
    actual_names = [name_of.get(n, str(n)) for n in actual]

    results.append({
        "venue": p["venue"], "no": p["no"], "name": p["name"],
        "honmei": (honmei_no, name_of.get(honmei_no, "")),
        "taikou": (taikou_no, name_of.get(taikou_no, "")),
        "tanana": (tanana_no, name_of.get(tanana_no, "")),
        "actual": actual,
        "actual_names": actual_names,
        "is_win": is_win, "is_place": is_place,
        "top3_overlap": top3_overlap,
        "status": "確定",
    })

with open("today_verification.json", "w", encoding="utf-8") as f:
    json.dump({
        "completed": total_completed,
        "honmei_win_rate": (hit_honmei_win / total_completed * 100) if total_completed else 0,
        "honmei_place_rate": (hit_honmei_place / total_completed * 100) if total_completed else 0,
        "top3_hit": hit_top3,
        "details": results,
    }, f, ensure_ascii=False, indent=2)
print(f"完了レース数: {total_completed}/{len(predictions)}")
print(f"◎本命勝率: {hit_honmei_win}/{total_completed}")
print(f"◎本命複勝率: {hit_honmei_place}/{total_completed}")
