"""
過去5年データから「コンテキスト加点」の最適値を学習する。

ハードコードした +0.5 などではなく、実データで:
- 枠番が内枠だった馬は他より何点分勝率が高かったか
- 前走重賞だった馬は勝率がいくつ上がるか
- 負け内容良の馬の的中寄与度

を回帰的に計測し、最適加点を data/context_weights.json に保存。

毎週月曜の自動更新で常に最新化される。
"""
import os, json
from collections import defaultdict
from glob import glob

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "context_weights.json")
TRAINING_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest", "all_horses_training.jsonl")

DEFAULT_WEIGHTS = {
    "frame_inner_bonus": 1.0,
    "frame_outer_penalty": -0.8,
    "good_loss_bonus": 1.0,
    "bad_loss_penalty": -1.5,
    "grade_exp_bonus": 0.5,
    "condition_fit_bonus": 1.0,
    "condition_mismatch_penalty": -1.0,
    "surface_fit_bonus": 1.0,
    "venue_fit_bonus": 1.0,
}


def calibrate_from_training() -> dict:
    """all_horses_training.jsonl から各コンテキストの勝率寄与を測定"""
    if not os.path.exists(TRAINING_PATH):
        return DEFAULT_WEIGHTS

    # コンテキスト別: 当該条件を満たす馬の勝率 vs ベースライン
    # ベースライン: 全馬の平均勝率（多頭数で約 1 / num_horses）

    bucket_stats = defaultdict(lambda: {"win": 0, "n": 0})
    baseline_win = 0
    baseline_n = 0

    with open(TRAINING_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                race = json.loads(line)
            except Exception:
                continue
            horses = race.get("horses", [])
            if not horses:
                continue

            num = race.get("num_horses", len(horses))
            venue = race.get("venue", "")
            distance = race.get("distance", 0)

            for h in horses:
                baseline_n += 1
                won = bool(h.get("won"))
                if won:
                    baseline_win += 1

                factors = h.get("factors", {})

                # === pace 高い = 末脚良 = "good content"
                pace_sc = factors.get("pace", 50)
                if pace_sc >= 70:
                    bucket_stats["good_loss"]["n"] += 1
                    if won: bucket_stats["good_loss"]["win"] += 1
                elif pace_sc <= 40:
                    bucket_stats["bad_loss"]["n"] += 1
                    if won: bucket_stats["bad_loss"]["win"] += 1

                # === grade_score 高い = 重賞経験豊富 ===
                grade_sc = factors.get("class_change", 50)
                if grade_sc >= 70:
                    bucket_stats["grade_exp"]["n"] += 1
                    if won: bucket_stats["grade_exp"]["win"] += 1

                # === 馬場状態適性（condition score）===
                cond_sc = factors.get("condition", 50)
                if cond_sc >= 65:
                    bucket_stats["condition_fit"]["n"] += 1
                    if won: bucket_stats["condition_fit"]["win"] += 1
                elif cond_sc <= 40:
                    bucket_stats["condition_mismatch"]["n"] += 1
                    if won: bucket_stats["condition_mismatch"]["win"] += 1

                # === 馬場種別（芝/ダート）適性 ===
                surf_sc = factors.get("surface", 50)
                if surf_sc >= 70:
                    bucket_stats["surface_fit"]["n"] += 1
                    if won: bucket_stats["surface_fit"]["win"] += 1

                # === コース適性 ===
                venue_sc = factors.get("venue", 50)
                if venue_sc >= 70:
                    bucket_stats["venue_fit"]["n"] += 1
                    if won: bucket_stats["venue_fit"]["win"] += 1

                # 枠番情報は all_horses_training に明示的に無いため frame は別途
                # （horse_no の前半半分を内枠と仮定する近似）
                hn = h.get("horse_no", 0) or 0
                if hn > 0 and num > 0:
                    if hn <= num * 0.3:  # 内枠寄り
                        bucket_stats["frame_inner"]["n"] += 1
                        if won: bucket_stats["frame_inner"]["win"] += 1
                    elif hn >= num * 0.7:  # 外枠寄り
                        bucket_stats["frame_outer"]["n"] += 1
                        if won: bucket_stats["frame_outer"]["win"] += 1

    base_rate = baseline_win / baseline_n if baseline_n else 0.07
    if base_rate <= 0:
        base_rate = 0.07

    # 各バケットの勝率と基準との差を加点（スコア+1.0が概ね勝率+1%相当の経験則）
    weights = dict(DEFAULT_WEIGHTS)
    for key, stats in bucket_stats.items():
        if stats["n"] < 50:
            continue
        rate = stats["win"] / stats["n"]
        delta = rate - base_rate          # +0.02 など
        boost = round(delta * 100 * 1.0, 2)  # 勝率差1%でスコア+1点
        # クリッピング（強力シグナルを生かすためレンジ拡大）
        boost = max(-8.0, min(8.0, boost))
        mapping = {
            "good_loss":          "good_loss_bonus",
            "bad_loss":           "bad_loss_penalty",
            "grade_exp":          "grade_exp_bonus",
            "frame_inner":        "frame_inner_bonus",
            "frame_outer":        "frame_outer_penalty",
            "condition_fit":      "condition_fit_bonus",
            "condition_mismatch": "condition_mismatch_penalty",
            "surface_fit":        "surface_fit_bonus",
            "venue_fit":          "venue_fit_bonus",
        }
        if key in mapping:
            weights[mapping[key]] = boost

    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "weights": weights,
            "base_win_rate": round(base_rate, 4),
            "samples": baseline_n,
            "bucket_stats": {k: {"n": v["n"], "win_rate": round(v["win"]/v["n"], 4) if v["n"] else 0}
                            for k, v in bucket_stats.items()},
        }, f, ensure_ascii=False, indent=2)
    return weights


def load_weights() -> dict:
    if not os.path.exists(WEIGHTS_PATH):
        return DEFAULT_WEIGHTS
    try:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("weights", DEFAULT_WEIGHTS)
    except Exception:
        return DEFAULT_WEIGHTS


if __name__ == "__main__":
    w = calibrate_from_training()
    print("Calibrated weights:")
    for k, v in w.items():
        print(f"  {k}: {v:+.2f}")
