"""
バックテストエンジン
過去レースに現在のスコアリングモデルを適用して予測精度・回収率を検証する
どのスコア要素が実際の勝率と相関しているかを特定する
"""
import os
import sys
import io
import json
import time
from datetime import date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.scraper.history_scraper import HistoryScraper, build_stats
from src.scraper.jra_scraper import JRAScraper
from src.scraper.netkeiba_scraper import NetkeibaScraper
from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
from src.analyzer.race_context import analyze_race_context
from src.analyzer.recommendation import build_betting_plan_from_comprehensive
from src.pipeline import _cached_history

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest")


def run_backtest(target_dates: list[date], max_races: int = None) -> dict:
    """
    指定日のレースに対してスコアリングを実行し、実際の結果と照合する
    """
    os.makedirs(BACKTEST_DIR, exist_ok=True)
    jra = JRAScraper()
    netkeiba = NetkeibaScraper()
    hist = HistoryScraper()
    analyzer = ComprehensiveAnalyzer()

    all_records = []

    for target_date in target_dates:
        print(f"\n[backtest] {target_date} 処理中...")
        race_ids = jra.get_race_list_for_date(target_date)
        if not race_ids:
            print(f"  レースなし")
            continue

        if max_races:
            race_ids = race_ids[:max_races]

        for raw in race_ids:
            race_id = raw["race_id"]
            race = jra.get_shutuba_table(race_id)
            if not race or not race.horses:
                continue

            # 実際の結果を取得
            from src.validator.results_fetcher import ResultsFetcher
            fetcher = ResultsFetcher()
            result = fetcher.get_race_result(race_id)
            if not result or not result.get("order"):
                print(f"  {race_id}: 結果取得失敗（未終了か取得不可）")
                continue

            actual_top3 = [r["horse_no"] for r in result["order"][:3]]
            winner_no = actual_top3[0] if actual_top3 else None

            # スコアリング実行
            histories = {}
            for entry in race.horses:
                if entry.horse_id:
                    h = _cached_history(hist, entry.horse_id, entry.horse_name)
                    if h and h.records:
                        histories[entry.horse_id] = h

            ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)
            scores = analyzer.analyze_all(
                entries=race.horses, histories=histories,
                race=race, context=ctx, use_training=False,
            )
            plan = build_betting_plan_from_comprehensive(
                race_id, race.race_name, scores, race.num_horses
            )

            # 照合
            honmei_no = plan.honmei[0] if plan.honmei else None
            winner_rank = next(
                (s.recommendation_rank for s in scores if s.horse_no == winner_no), 99
            )
            honmei_win   = (honmei_no == winner_no)
            honmei_place = (honmei_no in actual_top3)
            exacta_hit   = any(set([a, b]) <= set(actual_top3[:2]) for a, b in plan.exacta_bets)
            tri_hit      = any(set(c) <= set(actual_top3) for c in plan.trifecta_bets)

            # 勝ち馬・本命のスコア内訳を記録（外れ要因分析用）
            winner_score = next((s for s in scores if s.horse_no == winner_no), None)
            honmei_score = next((s for s in scores if s.horse_no == honmei_no), None)

            def _extract_factors(s):
                if not s:
                    return {}
                rs = getattr(s, 'raw_stat', None)
                return {
                    "recent_form":  round(getattr(rs, 'form_score',     50), 1) if rs else 50,
                    "surface":      round(getattr(rs, 'surface_score',  50), 1) if rs else 50,
                    "distance":     round(getattr(rs, 'distance_score', 50), 1) if rs else 50,
                    "speed_index":  round(getattr(s,  'speed_score',    50), 1),
                    "class_change": round(getattr(rs, 'grade_score',    50), 1) if rs else 50,
                    "venue":        round(getattr(rs, 'venue_score',    50), 1) if rs else 50,
                    "condition":    round(getattr(rs, 'condition_score',50), 1) if rs else 50,
                    "rest":         round(getattr(rs, 'rest_score',     50), 1) if rs else 50,
                    "pace":         round(getattr(rs, 'pace_score',     50), 1) if rs else 50,
                    "weight_stab":  round(getattr(rs, 'weight_score',   50), 1) if rs else 50,
                    "final":        round(getattr(s,  'final_score',    50), 1),
                }

            # 外れた場合の敗因テキスト生成
            defeat_reason = ""
            if not honmei_win and winner_score and honmei_score:
                wf = _extract_factors(winner_score)
                pf = _extract_factors(honmei_score)
                gaps = [(k, wf.get(k,50) - pf.get(k,50)) for k in wf if k != "final"]
                gaps.sort(key=lambda x: -x[1])
                top_gap = gaps[0] if gaps and gaps[0][1] > 5 else None
                if top_gap:
                    labels = {
                        "recent_form": "直近フォーム",
                        "surface": "馬場適性",
                        "distance": "距離適性",
                        "speed_index": "スピード指数",
                        "class_change": "クラス実績",
                        "venue": "コース適性",
                        "condition": "馬場状態",
                    }
                    defeat_reason = f"勝ち馬は{labels.get(top_gap[0], top_gap[0])}で{top_gap[1]:.1f}pt上回っていた"

            record = {
                "race_id": race_id,
                "race_name": race.race_name,
                "date": str(target_date),
                "venue": race.venue,
                "grade": race.grade,
                "surface": race.surface,
                "distance": race.distance,
                "num_horses": race.num_horses,
                "winner_no": winner_no,
                "winner_pred_rank": winner_rank,
                "honmei_no": honmei_no,
                "honmei_win": honmei_win,
                "honmei_place": honmei_place,
                "exacta_hit": exacta_hit,
                "trifecta_hit": tri_hit,
                "defeat_reason": defeat_reason,
                "winner_factors": _extract_factors(winner_score),
                "honmei_factors": _extract_factors(honmei_score),
                "winner_final": round(winner_score.final_score, 1) if winner_score else 0,
            }
            all_records.append(record)
            status = "◎" if honmei_win else ("△複" if honmei_place else "×")
            print(f"  {race.venue}{race.race_no}R {race.race_name}: 1着={winner_no}番(予想{winner_rank}位) {status}")
            time.sleep(1)

    # 集計
    report = _aggregate(all_records)

    # 保存
    out = {
        "dates": [str(d) for d in target_dates],
        "records": all_records,
        "summary": report,
    }
    fname = f"backtest_{target_dates[0].strftime('%Y%m%d')}_{target_dates[-1].strftime('%Y%m%d')}.json"
    path = os.path.join(BACKTEST_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _print_report(report)
    return report


def _aggregate(records: list[dict]) -> dict:
    if not records:
        return {}

    n = len(records)
    honmei_wins   = sum(1 for r in records if r["honmei_win"])
    honmei_places = sum(1 for r in records if r["honmei_place"])
    exacta_hits   = sum(1 for r in records if r["exacta_hit"])
    tri_hits      = sum(1 for r in records if r["trifecta_hit"])
    winner_ranks  = [r["winner_pred_rank"] for r in records]

    # 勝ち馬予想順位の分布
    rank_dist = defaultdict(int)
    for rank in winner_ranks:
        rank_dist[min(rank, 7)] += 1

    # グレード別・距離別・馬場別の精度
    by_grade   = _split_accuracy(records, "grade")
    by_surface = _split_accuracy(records, "surface")
    by_venue   = _split_accuracy(records, "venue")

    # スコア差の分析（1位と2位のスコア差が大きいほど信頼度高い？）
    high_conf = [r for r in records if r.get("winner_final", 0) > 0]  # 暫定

    return {
        "total_races": n,
        "honmei_win_rate":   round(honmei_wins / n * 100, 1),
        "honmei_place_rate": round(honmei_places / n * 100, 1),
        "exacta_hit_rate":   round(exacta_hits / n * 100, 1),
        "trifecta_hit_rate": round(tri_hits / n * 100, 1),
        "avg_winner_rank":   round(sum(winner_ranks) / n, 2),
        "winner_rank_dist":  dict(rank_dist),
        "by_grade":   by_grade,
        "by_surface": by_surface,
        "by_venue":   by_venue,
        "insights":   _generate_insights(honmei_wins/n, honmei_places/n, by_grade, by_surface, rank_dist),
    }


def _split_accuracy(records, key):
    groups = defaultdict(list)
    for r in records:
        groups[r.get(key, "?")].append(r)
    result = {}
    for group, recs in groups.items():
        n = len(recs)
        if n < 3:
            continue
        result[group] = {
            "races": n,
            "honmei_win_rate":   round(sum(1 for r in recs if r["honmei_win"]) / n * 100, 1),
            "honmei_place_rate": round(sum(1 for r in recs if r["honmei_place"]) / n * 100, 1),
            "avg_winner_rank":   round(sum(r["winner_pred_rank"] for r in recs) / n, 2),
        }
    return result


def _generate_insights(wr, pr, by_grade, by_surface, rank_dist) -> list[str]:
    insights = []

    # 全体精度
    if wr >= 0.25:
        insights.append(f"◎本命の勝率{wr*100:.0f}%は市場平均(約20%)を上回っており、スコアに有効性あり。")
    elif wr >= 0.18:
        insights.append(f"◎本命の勝率{wr*100:.0f}%は市場平均に近い水準。スコアの重み調整が必要。")
    else:
        insights.append(f"◎本命の勝率{wr*100:.0f}%は低い。スコア要素の見直しが必要。")

    # 勝ち馬予想順位1〜2位の割合
    top2 = rank_dist.get(1, 0) + rank_dist.get(2, 0)
    total = sum(rank_dist.values())
    if total > 0:
        top2_rate = top2 / total
        insights.append(f"勝ち馬を1〜2位に予想できた割合: {top2_rate*100:.0f}%")

    # グレード別
    best_grade = max(by_grade.items(), key=lambda x: x[1]["honmei_win_rate"], default=(None, {}))
    if best_grade[0]:
        insights.append(f"最も精度が高いクラス: {best_grade[0]}（◎勝率{best_grade[1]['honmei_win_rate']}%）")

    # 馬場別
    if "芝" in by_surface and "ダート" in by_surface:
        turf_wr = by_surface["芝"]["honmei_win_rate"]
        dirt_wr = by_surface["ダート"]["honmei_win_rate"]
        better = "芝" if turf_wr > dirt_wr else "ダート"
        insights.append(f"芝={turf_wr}% vs ダート={dirt_wr}% → {better}の精度が高い。")

    return insights


def _print_report(report: dict):
    print("\n" + "="*60)
    print("[バックテスト結果]")
    print("="*60)
    n = report.get("total_races", 0)
    if n == 0:
        print("データなし")
        return
    print(f"  対象レース: {n}レース")
    print(f"  ◎本命 勝率:   {report['honmei_win_rate']}%  （目標 20%以上）")
    print(f"  ◎本命 複勝率: {report['honmei_place_rate']}%  （目標 40%以上）")
    print(f"  馬連 的中率:  {report['exacta_hit_rate']}%  （目標 15%以上）")
    print(f"  3連複 的中率: {report['trifecta_hit_rate']}%")
    print(f"  勝ち馬平均予想順位: {report['avg_winner_rank']}位")
    print()
    print("[洞察]")
    for ins in report.get("insights", []):
        print(f"  → {ins}")
    print()
    print("[グレード別精度]")
    for g, d in sorted(report.get("by_grade", {}).items()):
        print(f"  {g}: 勝率{d['honmei_win_rate']}% 複勝率{d['honmei_place_rate']}% ({d['races']}R)")
    print()
    print("[馬場別精度]")
    for s, d in report.get("by_surface", {}).items():
        print(f"  {s}: 勝率{d['honmei_win_rate']}% 複勝率{d['honmei_place_rate']}% ({d['races']}R)")
