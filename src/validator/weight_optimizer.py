"""
スコア重み自動最適化エンジン
バックテストの外れ分析 → 重み調整 → 毎週自動更新
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "model_weights.json")
ANALYSIS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "miss_analysis")

# デフォルト重み（初期値）
DEFAULT_WEIGHTS = {
    "recent_form":    0.30,
    "surface":        0.15,
    "distance":       0.15,
    "speed_index":    0.12,
    "class_change":   0.08,
    "venue":          0.06,
    "condition":      0.04,
    "rest":           0.05,
    "pace":           0.03,
    "weight_stab":    0.02,
}

# 通常の週次調整幅
LEARNING_RATE = 0.015
# 初回大規模バックテスト時の調整幅（多くのデータを活かして大きく動かす）
LEARNING_RATE_BULK = 0.04
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.50


def load_weights() -> dict:
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_WEIGHTS.copy()


def save_weights(weights: dict):
    os.makedirs(os.path.dirname(WEIGHTS_FILE), exist_ok=True)
    with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)


def analyze_misses(backtest_records: list) -> dict:
    """
    外れたレースを分析し、どの要素が不足していたかを集計
    winner（実際の1着）と predicted_1st（予想◎）のスコア差を各要素で比較
    """
    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    miss_factors = defaultdict(list)   # 要素名 → 不足量のリスト
    hit_factors  = defaultdict(list)   # 的中時の要素スコア

    total = len(backtest_records)
    misses = [r for r in backtest_records if not r.get("honmei_win")]
    hits   = [r for r in backtest_records if r.get("honmei_win")]

    print(f"\n[miss analysis] 外れ分析: {len(misses)}/{total}レース外れ")

    for r in misses:
        wfactors = r.get("winner_factors", {})
        pfactors = r.get("honmei_factors", {})
        if not wfactors or not pfactors:
            continue

        # 各要素で勝ち馬の方が優れていた度合いを記録
        for key in DEFAULT_WEIGHTS:
            wv = wfactors.get(key, 50)
            pv = pfactors.get(key, 50)
            diff = wv - pv
            if diff > 0:
                miss_factors[key].append(diff)  # 勝ち馬の方が高かった要素

    for r in hits:
        wfactors = r.get("winner_factors", {})
        for key in DEFAULT_WEIGHTS:
            hit_factors[key].append(wfactors.get(key, 50))

    # 外れ時に「勝ち馬が◎より高かった」要素 = 重みが不足している要素
    underweighted = {}
    for key, diffs in miss_factors.items():
        if diffs:
            avg_deficit = sum(diffs) / len(diffs)
            frequency   = len(diffs) / max(len(misses), 1)
            underweighted[key] = {
                "avg_deficit": round(avg_deficit, 2),
                "frequency":   round(frequency, 3),
                "impact":      round(avg_deficit * frequency, 3),
            }

    # 保存
    analysis = {
        "analyzed_at": datetime.now().isoformat(),
        "total_races": total,
        "miss_count":  len(misses),
        "hit_rate":    round(len(hits)/total*100, 1) if total > 0 else 0,
        "underweighted_factors": underweighted,
    }
    path = os.path.join(ANALYSIS_DIR, f"miss_{datetime.now().strftime('%Y%m%d')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    return analysis


def adjust_weights(analysis: dict, bulk: bool = False) -> dict:
    """
    外れ分析に基づいて重みを自動調整
    的中に貢献した要素は重みを上げ、貢献しなかった要素は下げる
    bulk=True: 大規模バックテスト時の強い調整（初回最適化用）
    """
    weights = load_weights()
    underweighted = analysis.get("underweighted_factors", {})
    miss_rate = 1 - analysis.get("hit_rate", 50) / 100
    total_races = analysis.get("total_races", 0)

    # データ量に応じて学習率を調整（多ければ信頼度高い）
    if bulk or total_races >= 50:
        lr = LEARNING_RATE_BULK
    elif total_races >= 20:
        lr = LEARNING_RATE * 1.5
    else:
        lr = LEARNING_RATE

    if not underweighted:
        print("[weight] 分析データ不足 → 重み調整なし")
        return weights

    if miss_rate < 0.5:
        print(f"[weight] 的中率良好（miss_rate={miss_rate:.2f}） → 微調整のみ")
        lr = lr * 0.5

    print(f"\n[weight] 重み自動調整 (lr={lr:.4f}, {total_races}レース, 外れ率={miss_rate:.1%}):")

    # impactスコアが高い要素ほど重みを増やす
    total_impact = sum(v["impact"] for v in underweighted.values()) or 1
    total_increase = 0

    adjustments = {}
    for key, info in underweighted.items():
        if key not in DEFAULT_WEIGHTS:
            continue
        impact_ratio = info["impact"] / total_impact
        # 外れ頻度が高く差が大きい要素ほど大幅に増やす
        delta = lr * impact_ratio * miss_rate * (1 + info["avg_deficit"] / 50)
        adjustments[key] = delta
        total_increase += delta

    # 増やした分を全体から差し引いて合計1.0を維持
    non_adjusted = [k for k in weights if k not in adjustments]
    decrease_per_key = total_increase / max(len(non_adjusted), 1)

    for key in adjustments:
        old = weights.get(key, DEFAULT_WEIGHTS.get(key, 0.05))
        new = min(MAX_WEIGHT, old + adjustments[key])
        weights[key] = round(new, 4)
        print(f"  ↑ {key:15s}: {old:.4f} → {new:.4f} (+{adjustments[key]:.4f})")

    for key in non_adjusted:
        old = weights.get(key, DEFAULT_WEIGHTS.get(key, 0.05))
        new = max(MIN_WEIGHT, old - decrease_per_key)
        weights[key] = round(new, 4)

    # 合計を1.0に正規化
    total = sum(weights.values())
    weights = {k: round(v / total, 4) for k, v in weights.items()}

    save_weights(weights)
    print(f"\n[weight] 新しい重み保存: {WEIGHTS_FILE}")
    return weights


def get_weights() -> dict:
    """現在の重みを返す（なければデフォルト）"""
    return load_weights()


def print_weight_history():
    """重みの変遷を表示"""
    w = load_weights()
    print("\n[現在のモデル重み]")
    for k, v in sorted(w.items(), key=lambda x: -x[1]):
        bar = "█" * int(v * 100)
        print(f"  {k:15s}: {v:.4f}  {bar}")
