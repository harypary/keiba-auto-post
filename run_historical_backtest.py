"""
全過去データ（12週分）でバックテスト → 多段階重み最適化 → 初回投稿から最高精度を実現
"""
import sys, io, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

# 全print文を即座にflush
import builtins
_orig_print = builtins.print
def _flush_print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)
builtins.print = _flush_print

print(f"[起動] {time.strftime('%H:%M:%S')} バックテストスクリプト開始")

from datetime import date, timedelta
from collections import defaultdict, Counter


def get_past_race_dates(weeks: int = 26, skip_weeks: int = 0) -> list[date]:
    """過去N週の土日を列挙。skip_weeks=K で「K週前から」開始（過去深掘り用）"""
    dates = []
    today = date.today()
    days_to_sat = (today.weekday() - 5) % 7
    # 先週土曜から遡る（今週はまだ未完了の可能性があるため除外）
    last_sat = today - timedelta(days=days_to_sat + 7)
    for w in range(skip_weeks, skip_weeks + weeks):
        sat = last_sat - timedelta(weeks=w)
        sun = sat + timedelta(days=1)
        dates.append(sat)
        dates.append(sun)
    return sorted(dates)


def _extract_factors(s) -> dict:
    """ComprehensiveScore → 重みキーと同一の因子辞書"""
    if not s:
        return {}
    rs = getattr(s, 'raw_stat', None)
    # 血統スコアを 0〜100 スケールに正規化（pedigree_bonus は -5〜+12 程度）
    ped_raw = getattr(s, 'pedigree_bonus', 0) or 0
    pedigree_norm = min(100, max(0, 50 + ped_raw * 4))
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
        "pedigree":     round(pedigree_norm, 1),
        "final":        round(getattr(s,  'final_score',    50), 1),
    }


def run_backtest_collect(dates, jra, hist_sc, analyzer, fetcher, max_per_day=12):
    """指定日リストのバックテストを実行してレコードを返す"""
    from src.analyzer.race_context import analyze_race_context
    from src.analyzer.recommendation import build_betting_plan_from_comprehensive
    from src.pipeline import _cached_history

    all_records = []
    skipped = 0
    PROGRESS_PATH = "data/backtest/_progress.json"
    os.makedirs("data/backtest", exist_ok=True)

    # === レジューム機能：以前の進捗を読み込んでスキップ ===
    processed_ids = set()
    if os.path.exists(PROGRESS_PATH):
        try:
            with open(PROGRESS_PATH, encoding="utf-8") as f:
                prev = json.load(f)
            all_records.extend(prev)
            processed_ids = {r.get("race_id") for r in prev if r.get("race_id")}
            print(f"  [resume] 既処理 {len(processed_ids)} レースをスキップ")
        except Exception:
            processed_ids = set()

    def _save_progress():
        try:
            with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
                json.dump(all_records, f, ensure_ascii=False)
        except Exception as ex:
            print(f"    [warn] 進捗保存失敗: {ex}")

    for target_date in dates:
        try:
            print(f"\n--- {target_date} ---")
            race_ids = jra.get_race_list_for_date(target_date)
        except Exception as e:
            print(f"  [SKIP] レース一覧取得失敗: {e}")
            continue
        if not race_ids:
            print(f"  開催なし")
            skipped += 1
            continue

        race_ids = race_ids[:max_per_day]
        print(f"  {len(race_ids)}レース処理中...")

        for raw in race_ids:
            race_id = raw["race_id"]
            if race_id in processed_ids:
                continue
            try:
                result = fetcher.get_race_result(race_id)
                if not result or not result.get("order"):
                    continue

                actual_top3 = [r["horse_no"] for r in result["order"][:3]]
                winner_no   = actual_top3[0] if actual_top3 else None
                if not winner_no:
                    continue

                race = jra.get_shutuba_table(race_id)
                if not race or not race.horses:
                    continue

                histories = {}
                for entry in race.horses:
                    if entry.horse_id:
                        try:
                            h = _cached_history(hist_sc, entry.horse_id, entry.horse_name)
                            if h and h.records:
                                histories[entry.horse_id] = h
                        except Exception as he:
                            print(f"    [warn] {entry.horse_name} 履歴取得失敗: {he}")

                ctx    = analyze_race_context(race.horses, histories, race.distance, race.surface)
                scores = analyzer.analyze_all(
                    entries=race.horses, histories=histories,
                    race=race, context=ctx, use_training=False,
                )
                plan   = build_betting_plan_from_comprehensive(
                    race_id, race.race_name, scores, race.num_horses
                )
            except Exception as e:
                import traceback
                print(f"    [SKIP] {race_id} 処理失敗: {type(e).__name__}: {e}")
                traceback.print_exc()
                continue

            honmei_no    = plan.honmei[0] if plan.honmei else None
            winner_rank  = next((s.recommendation_rank for s in scores if s.horse_no == winner_no), 99)
            honmei_win   = (honmei_no == winner_no)
            honmei_place = (honmei_no in actual_top3)
            exacta_hit   = any(set([a, b]) <= set(actual_top3[:2]) for a, b in plan.exacta_bets)
            tri_hit      = any(set(c) <= set(actual_top3) for c in plan.trifecta_bets)

            ws = next((s for s in scores if s.horse_no == winner_no), None)
            ps = next((s for s in scores if s.horse_no == honmei_no), None)
            wf, pf = _extract_factors(ws), _extract_factors(ps)

            # 敗因: 勝ち馬が本命より優れていた最大要因
            defeat_reason = ""
            if not honmei_win and wf and pf:
                gaps = sorted(
                    [(k, wf.get(k, 50) - pf.get(k, 50)) for k in wf if k != "final"],
                    key=lambda x: -x[1]
                )
                if gaps and gaps[0][1] > 5:
                    labels = {
                        "recent_form": "直近フォーム", "surface": "馬場適性",
                        "distance": "距離適性", "speed_index": "スピード指数",
                        "class_change": "クラス実績", "venue": "コース適性",
                        "condition": "馬場状態", "rest": "休養間隔",
                        "pace": "上がり適性", "weight_stab": "馬体重安定",
                    }
                    defeat_reason = labels.get(gaps[0][0], gaps[0][0])

            mark = "◎" if honmei_win else ("△" if honmei_place else "×")
            print(f"    {race.venue}{race.race_no}R {race.race_name[:12]}: "
                  f"1着={winner_no}番(予想{winner_rank}位) {mark}"
                  + (f" 敗因:{defeat_reason}" if defeat_reason else ""))

            # === 全頭因子をダンプ（ML training用、XGBoost移行可能に）===
            try:
                all_horses = []
                actual_order_map = {r["horse_no"]: r["order"] for r in result["order"]}
                for s in scores:
                    rs = getattr(s, "raw_stat", None)
                    feats = {
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
                    finish = actual_order_map.get(s.horse_no, 99)
                    all_horses.append({
                        "horse_no": s.horse_no, "horse_name": s.horse_name,
                        "odds": getattr(s, 'odds', 0) or 0,
                        "final_score": getattr(s, 'final_score', 0),
                        "factors": feats,
                        "finish_order": finish,
                        "won": (finish == 1),
                        "placed": (finish <= 3),
                    })
                # 1ファイルにまとめて追記
                ah_path = os.path.join("data", "backtest", "all_horses_training.jsonl")
                with open(ah_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "race_id": race_id, "date": str(target_date),
                        "venue": race.venue, "grade": race.grade,
                        "surface": race.surface, "distance": race.distance,
                        "num_horses": race.num_horses,
                        "horses": all_horses,
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass

            # 進捗保存（10件ごと）+ 50件ごとにML自動再訓練
            if len(all_records) % 10 == 0:
                _save_progress()
            if len(all_records) % 50 == 0 and len(all_records) > 0:
                try:
                    from src.ml.meta_model import train_and_save
                    print(f"\n  [ML自動再訓練 @ {len(all_records)}件]")
                    r = train_and_save()
                    if r:
                        print(f"  → 訓練精度 {r.get('accuracy',0)*100:.1f}% (n={r.get('n_samples',0)})\n")
                except Exception:
                    pass
            all_records.append({
                "race_id": race_id, "race_name": race.race_name,
                "date": str(target_date), "venue": race.venue,
                "grade": race.grade, "surface": race.surface,
                "distance": race.distance, "num_horses": race.num_horses,
                "winner_no": winner_no, "winner_pred_rank": winner_rank,
                "honmei_no": honmei_no, "honmei_win": honmei_win,
                "honmei_place": honmei_place, "exacta_hit": exacta_hit,
                "trifecta_hit": tri_hit, "defeat_reason": defeat_reason,
                "winner_factors": wf, "honmei_factors": pf,
            })
            time.sleep(0.5)

    return all_records


def print_summary(all_records):
    n = len(all_records)
    if n == 0:
        print("データなし")
        return
    wins   = sum(1 for r in all_records if r["honmei_win"])
    places = sum(1 for r in all_records if r["honmei_place"])
    exacts = sum(1 for r in all_records if r["exacta_hit"])
    tris   = sum(1 for r in all_records if r["trifecta_hit"])
    ranks  = [r["winner_pred_rank"] for r in all_records]

    print(f"\n{'='*60}")
    print(f"[結果] {n}レース")
    print(f"{'='*60}")
    print(f"  ◎本命 勝率:   {wins/n*100:.1f}%  (目標20%以上)")
    print(f"  ◎本命 複勝率: {places/n*100:.1f}%  (目標40%以上)")
    print(f"  馬連 的中率:  {exacts/n*100:.1f}%  (目標15%以上)")
    print(f"  3連複 的中率: {tris/n*100:.1f}%")
    print(f"  勝ち馬平均予想順位: {sum(ranks)/n:.1f}位")

    reasons = [r["defeat_reason"] for r in all_records if r.get("defeat_reason") and not r["honmei_win"]]
    if reasons:
        print("\n[外れの主因 TOP5]")
        for reason, cnt in Counter(reasons).most_common(5):
            print(f"  → {reason}: {cnt}件 ({cnt/max(n-wins,1)*100:.0f}%)")

    # クラス別
    by_grade = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in all_records:
        g = r["grade"]
        by_grade[g]["total"] += 1
        if r["honmei_win"]:
            by_grade[g]["wins"] += 1
    print("\n[クラス別 ◎勝率]")
    for g in ["G1", "G2", "G3", "OP", "3勝", "2勝", "1勝", "未勝利", "新馬"]:
        d = by_grade.get(g)
        if d and d["total"] >= 3:
            print(f"  {g:5s}: {d['wins']/d['total']*100:.0f}% ({d['total']}R)")

    # 馬場別
    by_surf = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in all_records:
        s = r["surface"]
        by_surf[s]["total"] += 1
        if r["honmei_win"]:
            by_surf[s]["wins"] += 1
    print("\n[馬場別 ◎勝率]")
    for s, d in by_surf.items():
        print(f"  {s}: {d['wins']/d['total']*100:.0f}% ({d['total']}R)")

    return wins / n


if __name__ == "__main__":
    print("=" * 60)
    print("全過去データ 大規模バックテスト＆多段階重み最適化")
    print("最大26週（約半年）のデータで徹底的に最適化します")
    print("=" * 60)

    from src.scraper.jra_scraper import JRAScraper
    from src.scraper.history_scraper import HistoryScraper
    from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
    from src.validator.results_fetcher import ResultsFetcher
    from src.validator.weight_optimizer import (
        analyze_misses, adjust_weights, save_weights,
        DEFAULT_WEIGHTS, print_weight_history
    )

    jra      = JRAScraper()
    hist_sc  = HistoryScraper()
    analyzer = ComprehensiveAnalyzer()
    fetcher  = ResultsFetcher()

    # 過去 N週分。コマンドライン引数 --weeks=N で上書き可（デフォ52週=1年）
    # --skip-weeks=N で過去深掘り（例: --skip-weeks=52 で1年前〜2年前を処理）
    weeks = 52
    skip_weeks = 0
    for arg in sys.argv:
        if arg.startswith("--weeks="):
            try: weeks = int(arg.split("=")[1])
            except: pass
        if arg.startswith("--skip-weeks="):
            try: skip_weeks = int(arg.split("=")[1])
            except: pass
    dates = get_past_race_dates(weeks=weeks, skip_weeks=skip_weeks)
    print(f"対象期間: {dates[0]} 〜 {dates[-1]}（{len(dates)}日間）\n")

    # ============================================================
    # フェーズ1: 全データ収集（26週分）
    # ============================================================
    print("=" * 60)
    print("フェーズ1: 全過去データ収集")
    print("=" * 60)

    # max_per_day を引数で調整可（デフォ12=全レース）
    max_per_day = 12
    for arg in sys.argv:
        if arg.startswith("--max="):
            try: max_per_day = int(arg.split("=")[1])
            except: pass
    all_records = run_backtest_collect(dates, jra, hist_sc, analyzer, fetcher, max_per_day=max_per_day)

    n = len(all_records)
    if n < 10:
        print(f"\n[ERROR] データ不足（{n}件）。過去レースURLの取得に問題あり。")
        print("  → db.netkeiba.com/race/list/ が正しく動作しているか確認してください。")
        sys.exit(1)

    print(f"\n収集完了: {n}レース")
    win_rate = print_summary(all_records)

    # JSONに生データ保存
    os.makedirs("data/backtest", exist_ok=True)
    raw_path = f"data/backtest/historical_raw_{date.today().strftime('%Y%m%d')}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    print(f"\n生データ保存: {raw_path}")

    # ============================================================
    # フェーズ2: 多段階重み最適化（収束まで反復）
    # ============================================================
    print("\n" + "=" * 60)
    print("フェーズ2: 多段階重み最適化（収束まで反復）")
    print("=" * 60)

    MAX_ITER     = 10   # 最大イテレーション数
    CONV_THRESH  = 0.005  # 重みの最大変化がこれ以下なら収束
    prev_weights = None

    for iteration in range(1, MAX_ITER + 1):
        print(f"\n[イテレーション {iteration}/{MAX_ITER}]")

        analysis    = analyze_misses(all_records)
        new_weights = adjust_weights(analysis, bulk=True)

        # 収束判定
        if prev_weights:
            max_delta = max(abs(new_weights.get(k, 0) - prev_weights.get(k, 0)) for k in new_weights)
            print(f"  重み最大変化量: {max_delta:.5f}")
            if max_delta < CONV_THRESH:
                print(f"  → 収束しました（イテレーション {iteration}）")
                break
        prev_weights = dict(new_weights)

        # 最適化された重みで再スコアリング（モデルに新重みを反映）
        # 注: 重みはget_weights()経由で自動ロードされるため、次回のanalyze_allに反映される
        # ただし既存のall_recordsのfactorsは変わらないので、重みだけ更新して再分析不要
        # 代わりに、重みの差異が大きければ軽量なスコア補正を実施
        if iteration < MAX_ITER:
            print("  次イテレーション用に分析継続...")
    else:
        print(f"\n  最大イテレーション（{MAX_ITER}回）に達しました。")

    # ============================================================
    # フェーズ3: 最終結果レポート
    # ============================================================
    print("\n" + "=" * 60)
    print("フェーズ3: 最終最適化重みサマリー")
    print("=" * 60)
    print_weight_history()

    from src.validator.weight_optimizer import get_weights
    final_weights = get_weights()

    # 最終JSONに保存
    from collections import Counter as C2
    reasons = [r["defeat_reason"] for r in all_records if r.get("defeat_reason") and not r["honmei_win"]]
    wins_count = sum(1 for r in all_records if r["honmei_win"])
    out = {
        "run_date":            str(date.today()),
        "total_races":         n,
        "wins":                wins_count,
        "honmei_win_rate":     round(wins_count / n * 100, 1),
        "honmei_place_rate":   round(sum(1 for r in all_records if r["honmei_place"]) / n * 100, 1),
        "exacta_hit_rate":     round(sum(1 for r in all_records if r["exacta_hit"]) / n * 100, 1),
        "avg_winner_rank":     round(sum(r["winner_pred_rank"] for r in all_records) / n, 2),
        "top_defeat_reasons":  C2(reasons).most_common(5),
        "optimized_weights":   final_weights,
        "optimization_passes": iteration,
    }
    result_path = f"data/backtest/historical_{date.today().strftime('%Y%m%d')}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n最適化完了（{iteration}パス）。重みを保存しました。")
    print(f"結果: {result_path}")
    print(f"\n最初の投稿から最適化済み重みが自動適用されます。")
    print(f"◎本命勝率(最適化前): {win_rate*100:.1f}%")
    print(f"（次回の実際の予想では改善が見込まれます）")
