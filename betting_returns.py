"""今日の買い目別回収率分析（推奨買い目を100円ずつ買った場合の概算）"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from collections import defaultdict

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

def odds_of(scores, no):
    for s in scores:
        if s.horse_no == no:
            return getattr(s, "odds", 0) or 0
    return 0

def name_of(scores, no):
    for s in scores:
        if s.horse_no == no:
            return s.horse_name
    return str(no)

# 概算配当（オッズ積に係数）
PAYOUT_COEF = {"uren": 0.4, "wide": 0.15, "fuku3": 0.5, "fuku": 0.28}

races = jra.get_race_list_for_date(target)

per_race_results = []
totals = defaultdict(lambda: {"stake": 0, "return": 0, "hits": 0, "n": 0})

for r in races:
    rid = r["race_id"]
    res = fetcher.get_race_result(rid)
    if not res or not res.get("order"): continue
    actual = [x["horse_no"] for x in res["order"][:3]]
    if not actual or len(actual) < 3: continue

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
    except Exception as ex:
        continue

    rrec = {"race": f"{race.venue}{race.race_no}R {race.race_name}", "actual": actual,
            "bets": []}

    # 単勝
    for no in (plan.win_bets or []):
        stake = 100
        hit = (no == actual[0])
        payout = round(odds_of(scores, no) * 100) if hit else 0
        totals["単勝"]["stake"] += stake
        totals["単勝"]["return"] += payout
        totals["単勝"]["n"] += 1
        if hit:
            totals["単勝"]["hits"] += 1
            rrec["bets"].append(f"単勝{no}番 ◎的中 {payout:,}円")

    # 複勝
    for no in (plan.place_bets or []):
        stake = 100
        hit = (no in actual)
        payout = round(odds_of(scores, no) * PAYOUT_COEF["fuku"] * 100) if hit else 0
        totals["複勝"]["stake"] += stake
        totals["複勝"]["return"] += payout
        totals["複勝"]["n"] += 1
        if hit:
            totals["複勝"]["hits"] += 1

    # 馬連
    for a, b in (plan.exacta_bets or []):
        stake = 100
        hit = (set([a, b]) <= set(actual[:2]))
        oa, ob = odds_of(scores, a), odds_of(scores, b)
        payout = round(oa * ob * PAYOUT_COEF["uren"] * 100) if hit else 0
        totals["馬連"]["stake"] += stake
        totals["馬連"]["return"] += payout
        totals["馬連"]["n"] += 1
        if hit:
            totals["馬連"]["hits"] += 1
            rrec["bets"].append(f"馬連{a}-{b} 的中 約{payout:,}円")

    # ワイド
    for a, b in (plan.quinella_bets or []):
        stake = 100
        hit = (a in actual and b in actual)
        oa, ob = odds_of(scores, a), odds_of(scores, b)
        payout = round(oa * ob * PAYOUT_COEF["wide"] * 100) if hit else 0
        totals["ワイド"]["stake"] += stake
        totals["ワイド"]["return"] += payout
        totals["ワイド"]["n"] += 1
        if hit:
            totals["ワイド"]["hits"] += 1
            rrec["bets"].append(f"ワイド{a}-{b} 的中 約{payout:,}円")

    # 3連複
    for combo in (plan.trifecta_bets or []):
        if len(combo) < 3: continue
        stake = 100
        hit = (set(combo) <= set(actual))
        oa, ob, oc = odds_of(scores, combo[0]), odds_of(scores, combo[1]), odds_of(scores, combo[2])
        payout = round(oa * ob * oc * PAYOUT_COEF["fuku3"] * 100) if hit else 0
        totals["3連複"]["stake"] += stake
        totals["3連複"]["return"] += payout
        totals["3連複"]["n"] += 1
        if hit:
            totals["3連複"]["hits"] += 1
            rrec["bets"].append(f"3連複{combo[0]}-{combo[1]}-{combo[2]} 的中 約{payout:,}円")

    per_race_results.append(rrec)

print(f"\n=== 買い目別 回収率レビュー（{len(per_race_results)}レース） ===\n")
print(f"{'券種':<6}{'購入数':<7}{'的中':<5}{'的中率':<8}{'投資':<10}{'回収':<10}{'回収率':<8}")
print('-'*60)
grand_stake = 0
grand_return = 0
for kind, d in totals.items():
    if d["n"] == 0: continue
    roi = (d["return"] / d["stake"] * 100) if d["stake"] else 0
    hit_rate = (d["hits"] / d["n"] * 100) if d["n"] else 0
    print(f"{kind:<6}{d['n']:<7}{d['hits']:<5}{hit_rate:<7.1f}%{d['stake']:<9,}円{d['return']:<9,}円{roi:<7.1f}%")
    grand_stake += d["stake"]
    grand_return += d["return"]
total_roi = (grand_return / grand_stake * 100) if grand_stake else 0
print('-'*60)
print(f"{'合計':<6}{'':<7}{'':<5}{'':<8}{grand_stake:<9,}円{grand_return:<9,}円{total_roi:<7.1f}%")

print("\n[的中レース詳細]")
for r in per_race_results:
    if r["bets"]:
        print(f"\n  {r['race']} 着順:{'-'.join(map(str, r['actual']))}")
        for b in r["bets"]:
            print(f"    {b}")

with open("today_returns.json", "w", encoding="utf-8") as f:
    json.dump({"totals": dict(totals), "races": per_race_results, "roi": total_roi}, f, ensure_ascii=False, indent=2)
print(f"\nSAVED: today_returns.json")
