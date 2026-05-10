"""
ML メタモデル：既存スコア要素を入力に、勝率を予測する学習モデル。
- 過去レースの (winner_factors, label=1) と (honmei_factors, label=honmei_win) を学習
- ロジスティック回帰で軽量・高解釈性
- データが増えればXGBoost等に置換可能（save/loadインタフェース統一）
- 既存comprehensive_scoreの補正レイヤとして機能
"""
import os, json, math
from glob import glob

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml_meta_model.json")

# 入力特徴量（11要素：血統追加）
FEATURES = [
    "recent_form", "surface", "distance", "speed_index",
    "class_change", "venue", "condition", "rest", "pace", "weight_stab",
    "pedigree",
]


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


def _gather_training_samples() -> list:
    """過去のhistorical_raw_*.json を全部読み、(features, label) ペアを集める"""
    samples = []
    paths = glob(os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest", "historical_raw_*.json"))
    paths += glob(os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest", "_progress.json"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            continue
        for r in records:
            wf = r.get("winner_factors", {})
            pf = r.get("honmei_factors", {})
            if wf:
                samples.append((wf, 1))   # 勝ち馬は確実に勝者
            if pf:
                samples.append((pf, 1 if r.get("honmei_win") else 0))
    return samples


def _gradient_descent(samples, lr=0.05, epochs=600, l2=0.001):
    """軽量ロジスティック回帰（純Python実装）"""
    n_features = len(FEATURES)
    w = [0.0] * n_features
    b = 0.0
    n = len(samples)
    if n == 0:
        return w, b

    # 標準化用に各featureの平均と分散
    means = [sum(s[0].get(k, 50) for s in samples) / n for k in FEATURES]
    variances = [sum((s[0].get(k, 50) - means[i]) ** 2 for s in samples) / n for i, k in enumerate(FEATURES)]
    stds = [math.sqrt(v) if v > 1 else 1 for v in variances]

    def featurize(sample_dict):
        return [(sample_dict.get(k, 50) - means[i]) / stds[i] for i, k in enumerate(FEATURES)]

    X = [featurize(s[0]) for s in samples]
    y = [s[1] for s in samples]

    for epoch in range(epochs):
        gw = [0.0] * n_features
        gb = 0.0
        loss = 0.0
        for x, label in zip(X, y):
            z = sum(w[i] * x[i] for i in range(n_features)) + b
            p = _sigmoid(z)
            err = p - label
            for i in range(n_features):
                gw[i] += err * x[i]
            gb += err
            # ログ損失
            p_clip = min(max(p, 1e-9), 1 - 1e-9)
            loss -= label * math.log(p_clip) + (1 - label) * math.log(1 - p_clip)
        # 更新
        for i in range(n_features):
            w[i] -= lr * (gw[i] / n + l2 * w[i])
        b -= lr * gb / n
        if epoch % 100 == 0:
            print(f"  epoch {epoch:4d}: loss={loss/n:.4f}")

    return w, b, means, stds


def train_and_save() -> dict:
    """学習→重み保存→学習統計を返す"""
    samples = _gather_training_samples()
    if len(samples) < 50:
        print(f"[ML] サンプル不足（{len(samples)}件）。学習スキップ。")
        return {}
    print(f"[ML] サンプル数: {len(samples)} / 学習開始...")
    w, b, means, stds = _gradient_descent(samples)
    # 精度評価（簡易）
    correct = 0
    for s in samples:
        feats = [(s[0].get(k, 50) - means[i]) / stds[i] for i, k in enumerate(FEATURES)]
        z = sum(w[i] * feats[i] for i in range(len(FEATURES))) + b
        pred = 1 if _sigmoid(z) >= 0.5 else 0
        if pred == s[1]:
            correct += 1
    acc = correct / len(samples)
    print(f"[ML] 訓練データ精度: {acc*100:.1f}%")

    # 重要度（標準化済みなので絶対値=影響度）
    importances = sorted(zip(FEATURES, [abs(x) for x in w]), key=lambda x: -x[1])
    print(f"[ML] 特徴量重要度 TOP5:")
    for k, v in importances[:5]:
        print(f"  {k:14s}: {v:.4f}")

    model = {
        "weights":   {FEATURES[i]: w[i] for i in range(len(FEATURES))},
        "bias":      b,
        "means":     {FEATURES[i]: means[i] for i in range(len(FEATURES))},
        "stds":      {FEATURES[i]: stds[i] for i in range(len(FEATURES))},
        "n_samples": len(samples),
        "accuracy":  acc,
        "importances": dict(importances),
    }
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    print(f"[ML] モデル保存: {MODEL_PATH}")
    return model


def load_model() -> dict | None:
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def predict_win_prob(factors: dict, model: dict | None = None) -> float | None:
    """factor辞書（recent_form等）からML勝率推定"""
    if model is None:
        model = load_model()
    if not model:
        return None
    w = model["weights"]
    means = model["means"]
    stds = model["stds"]
    z = model["bias"]
    for k in FEATURES:
        x = (factors.get(k, 50) - means.get(k, 50)) / max(0.1, stds.get(k, 1))
        z += w.get(k, 0) * x
    return _sigmoid(z)
