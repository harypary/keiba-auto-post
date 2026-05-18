"""
予測勝率のキャリブレーション。

保存された予測 (data/predictions/*.json) と実結果 (data/performance/*_result.json)
を突き合わせ、各馬の予測 ensemble_p に対する実際の勝率を測定。
予測30%なら実勝率は何%か？→ 補正テーブルを構築して deep_ev_analyzer に注入。

データが蓄積するほどキャリブレーション精度向上 → EV計算精度向上 → ROI向上。

手法:
- ビニング: 0-5%, 5-10%, 10-15%, ..., 50-100% の11バケット
- 各バケットで {predicted_avg, actual_win_rate, n_samples}
- 単調性を保つため隣接バケットを Pool Adjacent Violators (PAV) で平滑化
- ストア: data/prob_calibration.json
"""
import os, json
from glob import glob

PRED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "predictions")
PERF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "performance")
CALIB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "prob_calibration.json")

# ビン境界
BIN_EDGES = [0.0, 0.02, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.50, 0.70, 1.01]


def _bin_index(p: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        if BIN_EDGES[i] <= p < BIN_EDGES[i + 1]:
            return i
    return len(BIN_EDGES) - 2


def _pav(values: list, weights: list) -> list:
    """Pool Adjacent Violators で単調増加を保証"""
    if not values:
        return values
    v = list(values)
    w = list(weights)
    i = 0
    while i < len(v) - 1:
        if v[i] > v[i + 1]:
            # プール
            total_w = w[i] + w[i + 1]
            new_v = (v[i] * w[i] + v[i + 1] * w[i + 1]) / max(1, total_w)
            v[i] = new_v
            v[i + 1] = new_v
            w[i] = total_w
            w[i + 1] = total_w
            # 戻ってチェック
            i = max(0, i - 1)
        else:
            i += 1
    return v


def build_calibration() -> dict:
    """予測×結果ペアからキャリブレーション表を構築"""
    if not os.path.isdir(PRED_DIR):
        return {"bins": [], "n_total": 0, "note": "no predictions"}

    # bin index -> [(predicted_p, won)]
    by_bin = {i: [] for i in range(len(BIN_EDGES) - 1)}
    n_total = 0

    for pred_file in os.listdir(PRED_DIR):
        if not pred_file.endswith(".json"):
            continue
        race_id = pred_file.replace(".json", "")
        result_path = os.path.join(PERF_DIR, f"{race_id}_result.json")
        if not os.path.exists(result_path):
            continue
        try:
            with open(os.path.join(PRED_DIR, pred_file), encoding="utf-8") as f:
                pred = json.load(f)
            with open(result_path, encoding="utf-8") as f:
                res = json.load(f)
        except Exception:
            continue

        winner_no = None
        top3 = res.get("actual_top3") or []
        if top3:
            winner_no = top3[0]
        if winner_no is None:
            continue

        for r in pred.get("ranking", []):
            p = r.get("ensemble_p", 0) or 0
            if p <= 0:
                continue
            won = (r.get("horse_no") == winner_no)
            by_bin[_bin_index(p)].append((p, won))
            n_total += 1

    bins_out = []
    raw_rates = []
    raw_counts = []
    for i in sorted(by_bin):
        samples = by_bin[i]
        n = len(samples)
        if n == 0:
            mid = (BIN_EDGES[i] + BIN_EDGES[i + 1]) / 2
            bins_out.append({"lo": BIN_EDGES[i], "hi": BIN_EDGES[i + 1],
                             "predicted_avg": round(mid, 4), "actual_rate": round(mid, 4),
                             "n": 0})
            raw_rates.append(mid)
            raw_counts.append(1)
            continue
        pred_avg = sum(p for p, _ in samples) / n
        win_rate = sum(1 for _, w in samples if w) / n
        bins_out.append({"lo": BIN_EDGES[i], "hi": BIN_EDGES[i + 1],
                         "predicted_avg": round(pred_avg, 4),
                         "actual_rate": round(win_rate, 4),
                         "n": n})
        raw_rates.append(win_rate)
        raw_counts.append(n)

    # PAV で単調平滑化
    smoothed = _pav(raw_rates, raw_counts)
    for b, s in zip(bins_out, smoothed):
        b["calibrated_rate"] = round(s, 4)

    payload = {
        "bins": bins_out,
        "n_total": n_total,
        "version": 1,
    }
    os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def load_calibration() -> dict:
    if not os.path.exists(CALIB_PATH):
        return {"bins": [], "n_total": 0}
    try:
        with open(CALIB_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"bins": [], "n_total": 0}


def calibrate_prob(p: float, calib: dict = None) -> float:
    """予測確率 p を、学習済みキャリブレーションで補正"""
    if calib is None:
        calib = load_calibration()
    bins = calib.get("bins") or []
    if not bins or calib.get("n_total", 0) < 100:
        return p  # データ不足は補正しない
    # 該当ビンを見つけて線形補間
    for b in bins:
        if b["lo"] <= p < b["hi"]:
            lo_pred = b["lo"]
            hi_pred = b["hi"]
            lo_act  = max(0, b["calibrated_rate"] - (b["calibrated_rate"] - 0) * 0.2)
            hi_act  = min(1, b["calibrated_rate"] + (1 - b["calibrated_rate"]) * 0.2)
            # ビン中央の補正レートを使用
            return float(b["calibrated_rate"])
    return p


def calibrate_prob_dict(probs: dict, calib: dict = None) -> dict:
    """馬番→確率 dict を一括補正して正規化"""
    if calib is None:
        calib = load_calibration()
    if calib.get("n_total", 0) < 100:
        return probs  # データ不足
    out = {no: calibrate_prob(p, calib) for no, p in probs.items()}
    z = sum(out.values()) or 1.0
    return {no: p / z for no, p in out.items()}


if __name__ == "__main__":
    res = build_calibration()
    print(f"n_total = {res.get('n_total')}")
    for b in res.get("bins", []):
        print(f"  [{b['lo']:.2f}-{b['hi']:.2f}] n={b['n']:4d} pred_avg={b['predicted_avg']:.3f} "
              f"actual={b['actual_rate']:.3f} calibrated={b['calibrated_rate']:.3f}")
