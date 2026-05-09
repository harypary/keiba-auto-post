"""今日の外れレースの敗因分析（どのスコア要素が判断を誤らせたか）"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from collections import Counter, defaultdict

from src.scraper.jra_scraper import JRAScraper
from src.scraper.history_scraper import HistoryScraper
from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
from src.analyzer.race_context import analyze_race_context
from src.analyzer.recommendation import build_betting_plan_from_comprehensive
from src.validator.results_fetcher import ResultsFetcher
from src.pipeline import _cached_history

target = date(2026, 5, 9)
jra = JRAScraper()
hist_sc = HistoryScraper()
analyzer = ComprehensiveAnalyzer()
fetcher = ResultsFetcher()

LABELS = {
    "recent_form": "近走フォーム", "surface": "馬場適性",
    "distance": "距離適性", "speed_index": "スピード指数",
    "class_change": "クラス実績", "venue": "コース適性",
    "condition": "馬場状態", "rest": "休養間隔",
    "pace": "上がり適性", "weight_stab": "馬体重安定",
}

def factors_of(s):
    rs = getattr(s, "raw_stat", None)
    return {
        "recent_form":  getattr(rs, 'form_score', 50) if rs else 50,
        "surface":      getattr(rs, 'surface_score', 50) if rs else 50,
        "distance":     getattr(rs, 'distance_score', 50) if rs else 50,
        "speed_index":  getattr(s, 'speed_score', 50),
        "class_change": getattr(rs, 'grade_score', 50) if rs else 50,
        "venue":        getattr(rs, 'venue_score', 50) if rs else 50,
        "condition":    getattr(rs, 'condition_score', 50) if rs else 50,
        "rest":         getattr(rs, 'rest_score', 50) if rs else 50,
        "pace":         getattr(rs, 'pace_score', 50) if rs else 50,
        "weight_stab":  getattr(rs, 'weight_score', 50) if rs else 50,
    }

races = jra.get_race_list_for_date(target)
miss_factors = Counter()
miss_by_venue = defaultdict(lambda: {"total":0, "wins":0, "places":0, "trifecta":0})
all_misses = []
trifecta_hits = 0
total = 0

for r in races:
    rid = r["race_id"]
    res = fetcher.get_race_result(rid)
    if not res or not res.get("order"): continue
    actual = [x["horse_no"] for x in res["order"][:3]]
    if not actual: continue
    winner_no = actual[0]

    race = jra.get_shutuba_table(rid)
    if not race or not race.horses: continue

    histories = {}
    for e in race.horses:
        if e.horse_id:
            try:
                h = _cached_history(hist_sc, e.horse_id, e.horse_name)
                if h and h.records: histories[e.horse_id] = h
            except: pass

    try:
        ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)
        scores = analyzer.analyze_all(entries=race.horses, histories=histories, race=race, context=ctx, use_training=False)
        plan = build_betting_plan_from_comprehensive(rid, race.race_name, scores, race.num_horses)
    except Exception as e:
        print(f"[skip] {rid}: {e}")
        continue

    total += 1
    honmei_no = plan.honmei[0] if plan.honmei else None
    is_win = (honmei_no == winner_no)
    is_place = (honmei_no in actual) if honmei_no else False
    tri_hit = any(set(c) <= set(actual) for c in plan.trifecta_bets)
    if tri_hit: trifecta_hits += 1

    miss_by_venue[race.venue]["total"] += 1
    if is_win:    miss_by_venue[race.venue]["wins"] += 1
    if is_place:  miss_by_venue[race.venue]["places"] += 1
    if tri_hit:   miss_by_venue[race.venue]["trifecta"] += 1

    if not is_win:
        ws = next((s for s in scores if s.horse_no == winner_no), None)
        ps = next((s for s in scores if s.horse_no == honmei_no), None)
        if ws and ps:
            wf, pf = factors_of(ws), factors_of(ps)
            gaps = sorted([(k, wf[k] - pf[k]) for k in wf], key=lambda x: -x[1])
            top_gap = gaps[0]
            if top_gap[1] > 5:
                miss_factors[top_gap[0]] += 1
                all_misses.append({
                    "race": f"{race.venue}{race.race_no}R {race.race_name}",
                    "honmei": f"{honmei_no}番({getattr(ps,'horse_name','')})",
                    "winner": f"{winner_no}番({getattr(ws,'horse_name','')})",
                    "primary_reason": LABELS.get(top_gap[0], top_gap[0]),
                    "gap_score": round(top_gap[1], 1),
                    "all_gaps": [(LABELS.get(k,k), round(v,1)) for k,v in gaps[:3] if v > 0],
                })

print(f"\n=== 検証完了: {total}レース ===")
print(f"◎本命勝率: {sum(1 for r in all_misses if False) }, ロケーション集計を表示\n")

print("[敗因 TOP5]")
for k, v in miss_factors.most_common(5):
    print(f"  {LABELS.get(k,k):10s}: {v}件 ({v/max(1,total-7)*100:.0f}%)")  # 7=今日の的中数

print("\n[競馬場別精度]")
for v, d in miss_by_venue.items():
    if d["total"]:
        print(f"  {v}: ◎勝率{d['wins']/d['total']*100:.0f}% / 複勝率{d['places']/d['total']*100:.0f}% / 3連複{d['trifecta']/d['total']*100:.0f}% ({d['total']}R)")

print("\n[個別外れの主因]")
for m in all_misses[:15]:
    print(f"  {m['race'][:30]:30s} ◎{m['honmei'][:18]:18s} → 勝者{m['winner'][:18]:18s} 主因:{m['primary_reason']}(差{m['gap_score']})")

# 保存
with open("today_factor_analysis.json", "w", encoding="utf-8") as f:
    json.dump({
        "total_completed": total,
        "trifecta_hits": trifecta_hits,
        "miss_factors": dict(miss_factors),
        "miss_by_venue": dict(miss_by_venue),
        "details": all_misses,
    }, f, ensure_ascii=False, indent=2)
print(f"\nSAVED: today_factor_analysis.json")
