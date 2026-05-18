"""5/16-17 失敗原因分析"""
import json, glob
from collections import Counter
import sys
sys.path.insert(0, ".")
from src.validator.results_fetcher import ResultsFetcher

fetcher = ResultsFetcher()
preds = []
for fp in glob.glob("data/predictions/*.json"):
    try:
        d = json.load(open(fp, encoding="utf-8"))
        if "2026-05-16" in d.get("saved_at", "") or "2026-05-17" in d.get("saved_at", ""):
            preds.append(d)
    except: pass

losses = []
exacta_miss = []
trifecta_miss = []
winner_pop_dist = Counter()
winner_finalscore_rank = Counter()

for p in preds:
    res = fetcher.get_race_result(p["race_id"])
    if not res or not res.get("order"): continue
    actual = [(r["horse_no"], r.get("popularity"), r.get("final_odds")) for r in res["order"][:3]]
    if len(actual) < 3: continue
    winner_no = actual[0][0]
    winner_pop = actual[0][1]
    winner_odds = actual[0][2]
    honmei = p["honmei"][0] if p.get("honmei") else None

    # ranking 内での勝ち馬の順位
    ranking = p.get("ranking", [])
    winner_rank = None
    for i, h in enumerate(ranking):
        if h.get("horse_no") == winner_no:
            winner_rank = i + 1
            break

    winner_pop_dist[winner_pop or 99] += 1
    winner_finalscore_rank[winner_rank or 99] += 1

    if honmei != winner_no:
        losses.append({
            "race": p.get("race_name"),
            "honmei": honmei,
            "winner": winner_no,
            "winner_pop": winner_pop,
            "winner_odds": winner_odds,
            "winner_rank_in_pred": winner_rank,
        })

    # 馬連/3連複の不一致
    actual_top2 = set([actual[0][0], actual[1][0]])
    actual_top3 = set([a[0] for a in actual[:3]])
    has_uren_hit = any(set([a,b]) == actual_top2 for a,b in p.get("exacta_bets", []))
    has_fuku3_hit = any(set(c[:3]) == actual_top3 for c in p.get("trifecta_bets", []))
    if not has_uren_hit:
        exacta_miss.append({
            "race": p.get("race_name"),
            "actual_top2": list(actual_top2),
            "pred_top_pairs": p.get("exacta_bets", [])[:3],
        })
    if not has_fuku3_hit:
        trifecta_miss.append({
            "race": p.get("race_name"),
            "actual_top3": list(actual_top3),
            "pred_first_triples": p.get("trifecta_bets", [])[:3],
        })

print(f"=== 勝者の人気分布 ===")
for pop in sorted(winner_pop_dist):
    print(f"  {pop}番人気: {winner_pop_dist[pop]}回")
print()
print(f"=== 勝者の予想順位（最終評点ランク内）===")
for rank in sorted(winner_finalscore_rank):
    label = f"{rank}位" if rank < 99 else "圏外"
    print(f"  予想{label}: {winner_finalscore_rank[rank]}回")
print()
print(f"=== 本命負けレースのオッズ分布 ===")
odd_buckets = Counter()
for l in losses:
    o = l.get("winner_odds") or 0
    if o < 5: bucket = "本命級(1〜5倍)"
    elif o < 10: bucket = "中穴(5〜10倍)"
    elif o < 30: bucket = "中穴〜大穴(10〜30倍)"
    else: bucket = "大穴(30倍以上)"
    odd_buckets[bucket] += 1
for b, n in odd_buckets.most_common():
    print(f"  {b}: {n}回")

# 馬連/3連複の構造的失敗
print(f"\n=== 馬連 不的中: {len(exacta_miss)}件 ===")
print("（買い目に含まれなかった2着馬の人気）")
for em in exacta_miss[:5]:
    print(f"  {em['race']}: 実1-2着 {em['actual_top2']}")
print(f"\n=== 3連複 不的中: {len(trifecta_miss)}件 ===")
for tm in trifecta_miss[:5]:
    print(f"  {tm['race']}: 実1-3着 {tm['actual_top3']}")
