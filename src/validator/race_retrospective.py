"""
レース結果の徹底振り返り：勝因を多角的に分析する。
- 最終単勝オッズ・人気
- 上がり3F・タイム
- 予想評点との差分
- 勝因仮説（適性/展開/フォーム/騎手/血統など）

毎週月曜の週次レビューから呼び出される。
"""
import os, json
from glob import glob
from collections import Counter

RETRO_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "retrospective.json")


def analyze_winner(winner_factors: dict, honmei_factors: dict, race_info: dict) -> dict:
    """勝ち馬と本命の因子を比較し、勝因仮説を作る"""
    if not winner_factors or not honmei_factors:
        return {}
    diffs = {k: round(winner_factors.get(k, 50) - honmei_factors.get(k, 50), 1)
             for k in winner_factors if k != "final"}
    # 大きく差がついた要素TOP3
    top_diffs = sorted(diffs.items(), key=lambda x: -abs(x[1]))[:3]
    # 勝因タグ
    tags = []
    for k, v in top_diffs:
        if v > 5:
            tags.append({
                "recent_form": "近走フォーム上昇",
                "surface":     f"{race_info.get('surface','')}適性が優位",
                "distance":    f"{race_info.get('distance','')}m距離適性",
                "speed_index": "絶対スピード",
                "class_change":"クラス慣れ",
                "venue":       f"{race_info.get('venue','')}コース親和性",
                "condition":   f"{race_info.get('condition','')}馬場対応",
                "rest":        "休養明けの仕上がり",
                "pace":        "末脚力（上がり脚）",
                "weight_stab": "馬体重安定",
                "pedigree":    "血統的優位",
            }.get(k, k))
    return {
        "top_diffs": top_diffs,
        "win_tags": tags,
    }


def build_retro_record(race_id: str, prediction: dict, result: dict) -> dict:
    """単レースの振り返りレコードを構築"""
    order = result.get("order", []) if isinstance(result, dict) else []
    if not order:
        return {}
    winner = order[0]
    second = order[1] if len(order) > 1 else {}
    third  = order[2] if len(order) > 2 else {}

    # 予想と比較
    honmei = prediction.get("honmei_no")
    rec = {
        "race_id": race_id,
        "race_name": prediction.get("race_name", ""),
        "venue": prediction.get("venue"),
        "surface": prediction.get("surface"),
        "distance": prediction.get("distance"),
        "condition": prediction.get("condition"),
        # 結果
        "winner_no":     winner.get("horse_no"),
        "winner_name":   winner.get("horse_name", ""),
        "winner_odds":   winner.get("final_odds"),
        "winner_pop":    winner.get("popularity"),
        "winner_time":   winner.get("finish_time"),
        "winner_3f":     winner.get("last_3f"),
        "second_no":     second.get("horse_no"),
        "second_name":   second.get("horse_name", ""),
        "third_no":      third.get("horse_no"),
        "third_name":    third.get("horse_name", ""),
        # 払戻
        "payouts":       result.get("payouts", {}),
        # 予想結果
        "honmei_no":     honmei,
        "honmei_win":    honmei == winner.get("horse_no"),
        "honmei_place":  honmei in [winner.get("horse_no"), second.get("horse_no"), third.get("horse_no")],
    }

    # 勝因仮説
    rec["win_analysis"] = analyze_winner(
        prediction.get("winner_factors", {}),
        prediction.get("honmei_factors", {}),
        {"surface": rec.get("surface"), "distance": rec.get("distance"),
         "venue": rec.get("venue"), "condition": rec.get("condition")}
    )

    # 配当評価
    payouts = rec.get("payouts", {})
    if rec["winner_pop"]:
        if rec["winner_pop"] == 1:
            rec["result_tag"] = "本命決着"
        elif rec["winner_pop"] <= 3:
            rec["result_tag"] = "順当"
        elif rec["winner_pop"] <= 7:
            rec["result_tag"] = "中穴"
        else:
            rec["result_tag"] = "大穴"

    return rec


def save_retro_batch(records: list):
    """振り返りレコードを蓄積保存"""
    existing = []
    if os.path.exists(RETRO_PATH):
        try:
            with open(RETRO_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    # race_id重複排除
    seen = {r["race_id"] for r in existing if r.get("race_id")}
    new = [r for r in records if r.get("race_id") and r["race_id"] not in seen]
    existing.extend(new)
    # 直近1000件のみ保持
    existing = existing[-1000:]
    os.makedirs(os.path.dirname(RETRO_PATH), exist_ok=True)
    with open(RETRO_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return len(new)


def get_recent_retro_summary(n: int = 30) -> dict:
    """直近Nレースの振り返りサマリーを生成"""
    if not os.path.exists(RETRO_PATH):
        return {}
    try:
        with open(RETRO_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    recent = data[-n:]
    if not recent:
        return {}

    win_tags = Counter()
    result_tags = Counter()
    avg_odds = 0
    odds_n = 0
    for r in recent:
        for t in r.get("win_analysis", {}).get("win_tags", []):
            win_tags[t] += 1
        if r.get("result_tag"):
            result_tags[r["result_tag"]] += 1
        if r.get("winner_odds"):
            avg_odds += r["winner_odds"]
            odds_n += 1

    return {
        "n_races": len(recent),
        "top_win_tags": win_tags.most_common(5),
        "result_tag_distribution": dict(result_tags),
        "winner_avg_odds": round(avg_odds / odds_n, 1) if odds_n else 0,
    }
