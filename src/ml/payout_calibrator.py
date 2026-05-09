"""
予想配当 vs 実配当の誤差校正器
オッズ積から想定配当を出す際の係数を、実配当データから学習する。
データ蓄積に伴い精度向上。
"""
import os, json
from glob import glob

CALIB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "payout_calibration.json")

DEFAULT_COEFS = {
    "uren":   0.40,   # 馬連: oa * ob * 0.40
    "wide":   0.15,   # ワイド: oa * ob * 0.15
    "fuku3":  0.50,   # 3連複: oa * ob * oc * 0.50
    "fuku":   0.28,   # 複勝: o * 0.28
}


def load_calibration() -> dict:
    if not os.path.exists(CALIB_PATH):
        return {"coefs": dict(DEFAULT_COEFS), "n_samples": {k: 0 for k in DEFAULT_COEFS}}
    try:
        with open(CALIB_PATH, encoding="utf-8") as f:
            d = json.load(f)
        # デフォルト補完
        for k, v in DEFAULT_COEFS.items():
            d.setdefault("coefs", {}).setdefault(k, v)
            d.setdefault("n_samples", {}).setdefault(k, 0)
        return d
    except Exception:
        return {"coefs": dict(DEFAULT_COEFS), "n_samples": {k: 0 for k in DEFAULT_COEFS}}


def update_calibration(observations: list) -> dict:
    """
    observations: [{"kind": "uren", "odds_product": 12.5, "actual_payout": 8.4}, ...]
    実払戻倍率 / オッズ積 を係数として、移動平均で更新
    """
    calib = load_calibration()
    coefs = calib["coefs"]
    counts = calib["n_samples"]
    for obs in observations:
        kind = obs.get("kind")
        op = obs.get("odds_product", 0)
        ap = obs.get("actual_payout", 0)
        if not kind or op <= 0 or ap <= 0:
            continue
        new_coef = ap / op  # 実係数
        n = counts.get(kind, 0)
        # 移動平均更新（直近データを少し重く）
        weight = max(0.1, 1 / (n + 1))
        coefs[kind] = round((1 - weight) * coefs[kind] + weight * new_coef, 4)
        counts[kind] = n + 1
    calib["coefs"] = coefs
    calib["n_samples"] = counts
    os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(calib, f, ensure_ascii=False, indent=2)
    return calib


def get_coefs() -> dict:
    return load_calibration()["coefs"]
