"""
週次パフォーマンスレビュー（毎週月曜朝に自動実行）
1. 日曜・土曜レースの実際の結果を取得
2. 予想と照合して的中率を計算
3. 改善ポイントをコンソールに出力
4. data/performance/ にレポートを保存
"""
import os
import sys
import json
import io
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from src.validator.results_fetcher import ResultsFetcher
from src.validator.performance_tracker import record_result, generate_weekly_report
from src.validator.weight_optimizer import analyze_misses, adjust_weights, print_weight_history
from src.validator.backtest import run_backtest
from src.pipeline import invalidate_cache

PRED_DIR = os.path.join(os.path.dirname(__file__), "data", "predictions")
PERF_DIR = os.path.join(os.path.dirname(__file__), "data", "performance")


def run_weekly_review():
    print("\n" + "="*60)
    print("[WEEKLY REVIEW] 先週の予想結果を照合中...")
    print("="*60 + "\n")

    fetcher = ResultsFetcher()

    # 先週土曜・日曜分の予想ファイルを対象に
    today = date.today()
    # 先週の土日を計算
    last_sunday  = today - timedelta(days=today.weekday() + 1)
    last_saturday = last_sunday - timedelta(days=1)
    target_dates = [last_saturday, last_sunday]

    processed = 0
    for pred_file in os.listdir(PRED_DIR):
        if not pred_file.endswith(".json"):
            continue
        race_id = pred_file.replace(".json", "")
        race_date_str = race_id[:8]

        # 先週土日のレースのみ対象
        try:
            race_date = date(int(race_date_str[:4]), int(race_date_str[4:6]), int(race_date_str[6:8]))
        except Exception:
            continue

        if race_date not in target_dates:
            continue

        # すでに照合済みならスキップ
        result_path = os.path.join(PERF_DIR, f"{race_id}_result.json")
        if os.path.exists(result_path):
            continue

        print(f"  照合中: {race_id}...")
        result = fetcher.get_race_result(race_id)
        if result and result.get("order"):
            record = record_result(race_id, result["order"])
            top3 = [r["horse_no"] for r in result["order"][:3]]
            honmei = record.get("honmei_no", "?")
            win = "◎" if record.get("honmei_win") else ("△" if record.get("honmei_place") else "×")
            print(f"    1着:{top3[0] if top3 else '?'}番 / ◎本命:{honmei}番 → {win}")
            processed += 1
        import time
        time.sleep(2)

    print(f"\n[照合完了] {processed}レース処理\n")

    # 週次レポート
    report = generate_weekly_report(weeks_back=1)
    print("="*60)
    print("[週次パフォーマンスレポート（回収率重視）]")
    print("="*60)
    if report.get("races_analyzed", 0) == 0:
        print("  データ蓄積中（来週以降に結果が出ます）")
    else:
        n = report["races_analyzed"]
        roi_tan  = report.get("avg_tan_roi", 0)
        roi_sign = "+" if roi_tan >= 0 else ""
        print(f"  対象レース数: {n}レース")
        print(f"  ◎本命 勝率:   {report['honmei_win_rate']}%  （目標 20%以上）")
        print(f"  ◎本命 複勝率: {report['honmei_place_rate']}%  （目標 40%以上）")
        print(f"  馬連 的中率:  {report['exacta_hit_rate']}%  （目標 15%以上）")
        print(f"  3連複 的中率: {report['trifecta_hit_rate']}%")
        print(f"  単勝 回収率:  {roi_sign}{roi_tan}%  （目標 -10%以内）")
        print(f"  馬連 回収率:  {roi_sign}{report.get('avg_exacta_roi',0)}%")
        print(f"  勝ち馬の平均予想順位: {report['avg_winner_predicted_rank']}位")
        print()
        print("[先週ハイライト（高配当的中）]")
        for h in report.get("highlights", []):
            print(f"  ★ {h.get('race_name','')}：◎{h.get('honmei_no','')}番 {h.get('honmei_odds',0)}倍的中")
        print()
        print("[改善提案]")
        for s in report["improvement_suggestions"]:
            print(f"  → {s}")

    # レポートJSON保存
    os.makedirs(PERF_DIR, exist_ok=True)
    report_path = os.path.join(PERF_DIR, f"weekly_{date.today().strftime('%Y%m%d')}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  レポート保存: {report_path}")

    # ---- バックテスト＆重み自動調整 ----
    print("\n" + "="*60)
    print("[バックテスト＆スコア重み自動調整]")
    print("="*60)
    print("先週のレースでモデルを検証中...")
    bt_report = run_backtest(target_dates, max_races=20)  # 最大20レースで高速検証

    if bt_report.get("total_races", 0) >= 5:
        print("\n[敗因分析]")
        bt_records = bt_report.get("records", [])
        misses = [r for r in bt_records if not r.get("honmei_win")]
        if misses:
            from collections import Counter
            reasons = [r.get("defeat_reason", "") for r in misses if r.get("defeat_reason")]
            if reasons:
                print("外れの主因トップ3:")
                for reason, cnt in Counter(reasons).most_common(3):
                    print(f"  → {reason} ({cnt}件)")

        # 重み自動調整
        analysis = analyze_misses(bt_records)
        new_weights = adjust_weights(analysis)
        print_weight_history()

        # === 学びを保存（次回投稿に反映される） ===
        from src.validator.learning_engine import (
            build_learnings, save_learnings, apply_factor_adjustments,
            record_weekly_metrics, get_trend_summary, auto_tune_lr,
        )

        # 週次メトリクスを時系列に記録（毎週の改善トラッキング）
        week_label = date.today().strftime("%Y-W%V")
        # ROIを主指標に（ROI最大化が運用ゴール）
        tan_roi    = report.get("avg_tan_roi", 0)
        exacta_roi = report.get("avg_exacta_roi", 0)
        # 複合ROI = 単勝・馬連・ワイド・3連複の加重平均（ワイド/3連複も統計があれば加味）
        composite_roi = (tan_roi * 0.2 + exacta_roi * 0.8) if exacta_roi else tan_roi
        weekly_metrics = {
            "honmei_win_rate":   report.get("honmei_win_rate", 0),
            "honmei_place_rate": report.get("honmei_place_rate", 0),
            "exacta_hit_rate":   report.get("exacta_hit_rate", 0),
            "trifecta_hit_rate": report.get("trifecta_hit_rate", 0),
            "tan_roi":           tan_roi,
            "exacta_roi":        exacta_roi,
            "composite_roi":     round(composite_roi, 1),
            "races":             report.get("races_analyzed", 0),
        }
        record_weekly_metrics(week_label, weekly_metrics)

        # トレンドベースで次回学習率を自動チューニング
        trend = get_trend_summary()
        next_lr = auto_tune_lr(trend)
        print(f"\n[ROI主導トレンド分析]")
        if trend.get("weeks", 0) >= 2:
            arrow = "↑" if trend["improving"] else "↓"
            print(f"  複合ROI推移:  {trend.get('current_roi',0):+.1f}%  (前週比 {trend.get('delta_roi',0):+.1f}%) {arrow}")
            print(f"  複勝率推移:   {trend.get('current_place_rate',0):.1f}% (前週比 {trend.get('delta_place',0):+.1f}%)")
            print(f"  → 次週の学習率: {next_lr:.3f}（ROI推移ベースで自動調整）")
        else:
            print(f"  データ蓄積中（次週から ROI/精度推移を表示）")
        # 券種別ROI（あれば report から）
        roi_by_kind = {}
        if report.get("avg_tan_roi") is not None:
            roi_by_kind["単勝"] = {
                "stake": report.get("tan_stake", 0),
                "return": report.get("tan_return", 0),
                "roi": report.get("avg_tan_roi", 0),
            }
        if report.get("avg_exacta_roi") is not None:
            roi_by_kind["馬連"] = {
                "stake": report.get("exacta_stake", 0),
                "return": report.get("exacta_return", 0),
                "roi": report.get("avg_exacta_roi", 0),
            }
        learnings = build_learnings(bt_records, roi_by_kind)
        save_learnings(learnings)
        print(f"\n[学び保存] {len(learnings.get('top_lessons', []))}件のレッスンを次回投稿に反映")
        for lesson in learnings.get("top_lessons", []):
            print(f"  💡 {lesson}")

        # 重みに学習補正をかけて再保存（既存最適化結果 × 学習補正）
        from src.validator.weight_optimizer import get_weights, save_weights
        adjusted = apply_factor_adjustments(get_weights(), learnings)
        save_weights(adjusted)
        print(f"  [重み再調整] 学習補正適用後の重みを保存")

        # === 競馬場バイアス更新（前残り/差し優勢の傾向検出）===
        try:
            from src.scraper.multi_source_scraper import update_venue_bias_from_records
            import glob
            raws = glob.glob("data/backtest/historical_raw_*.json")
            if raws:
                with open(raws[-1], encoding="utf-8") as f:
                    raw_records = json.load(f)
                vb = update_venue_bias_from_records(raw_records)
                if vb:
                    print(f"\n[競馬場バイアス] {len(vb)}場のバイアス更新")
                    for v, d in vb.items():
                        print(f"  {v}: {d.get('tendency','-')} (差し率 {int(d.get('back_ratio',0)*100)}%, n={d.get('n_races',0)})")
        except Exception as ex:
            print(f"  [バイアス] 失敗: {ex}")

        # === ML メタモデル再訓練（蓄積データが増えるたびに学習更新）===
        try:
            from src.ml.meta_model import train_and_save
            print("\n[ML再訓練]")
            ml_result = train_and_save()
            if ml_result:
                print(f"  サンプル数: {ml_result.get('n_samples', 0)} / 訓練精度: {ml_result.get('accuracy', 0)*100:.1f}%")
        except Exception as ex:
            print(f"  [ML] 再訓練失敗: {ex}")

        # === ペイアウト較正：先週レースの実払戻から係数更新 ===
        try:
            from src.ml.payout_calibrator import update_calibration
            observations = []
            # 先週土日の予想を再取得して実払戻と照合
            for pred_file in os.listdir(PRED_DIR):
                if not pred_file.endswith(".json"): continue
                race_id = pred_file.replace(".json", "")
                race_date_str = race_id[:8]
                try:
                    race_date = date(int(race_date_str[:4]), int(race_date_str[4:6]), int(race_date_str[6:8]))
                except Exception:
                    continue
                if race_date not in target_dates: continue
                res = fetcher.get_race_result(race_id)
                if not res or not res.get("payouts"): continue
                payouts = res["payouts"]
                # 当時の予想を読み込み、オッズ積を計算
                pred = json.load(open(os.path.join(PRED_DIR, pred_file), encoding="utf-8"))
                horses = pred.get("scores", []) or pred.get("horses", [])
                odds_map = {h.get("horse_no"): h.get("odds", 0) for h in horses if h.get("odds")}
                actual = [r["horse_no"] for r in res["order"][:3]]
                if len(actual) >= 2 and "馬連" in payouts:
                    a, b = actual[0], actual[1]
                    op = odds_map.get(a, 0) * odds_map.get(b, 0)
                    if op > 0:
                        observations.append({"kind": "uren", "odds_product": op, "actual_payout": payouts["馬連"] / 100.0})
                if len(actual) >= 3 and "3連複" in payouts:
                    a, b, c = actual[0], actual[1], actual[2]
                    op = odds_map.get(a, 0) * odds_map.get(b, 0) * odds_map.get(c, 0)
                    if op > 0:
                        observations.append({"kind": "fuku3", "odds_product": op, "actual_payout": payouts["3連複"] / 100.0})
            if observations:
                calib = update_calibration(observations)
                print(f"\n[ペイアウト較正] {len(observations)}件で係数更新")
                for k, v in calib["coefs"].items():
                    print(f"  {k:6s}: {v:.4f} (n={calib['n_samples'].get(k, 0)})")
        except Exception as ex:
            print(f"  [ペイアウト較正] 失敗: {ex}")
    else:
        print("  バックテストデータ不足（5レース未満）→ 重み調整スキップ")

    # キャッシュクリア（翌週の新データ取得のため）
    print("\n[キャッシュクリア] 古い馬データを削除中...")
    invalidate_cache()
    print("[完了]\n")


if __name__ == "__main__":
    run_weekly_review()
