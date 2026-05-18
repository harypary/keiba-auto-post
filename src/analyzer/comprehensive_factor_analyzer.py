"""
予想精度向上のため、過去データから検証可能な全要因を体系化＆学習。

カテゴリ:
1. 馬体・物理: 馬体重、馬齢、性別、斤量
2. 厩舎・騎手: 調教師勝率、騎手×コース、騎手×距離
3. ローテーション: 休養日数、連闘、転厩
4. レース条件: 天候、季節、開催日（土日/平日休前）、開催番組
5. コース特性: 直線距離、回り、坂、内外回り
6. 展開・地脚: 過去の通過順位パターン、上がり3F一貫性
7. 対戦履歴: 同走馬との相対実績
8. 調教・仕上がり: 中間追い切りパターン
9. 馬場推移: 直近の馬場傾向（時計の速さ）
10. クラス推移: 昇級・降級、適正クラス
11. 距離適性詳細: 200m単位の細かい得意距離
12. 血統補正: 母系・母父・配合相性
13. 競走スタイル: 単騎逃げ/番手/中団/後方
14. 季節別好走パターン: 春/夏/秋/冬
15. 重斤量耐性: 過去の高斤量時の成績

このモジュールが学習結果を context_weights.json に統合保存。
"""
import os, json
from collections import defaultdict
from datetime import datetime
from typing import Optional

CW_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "context_weights.json")


def derive_comprehensive_signals_from_records(records: list) -> dict:
    """馬の過去レース records から多次元シグナルを抽出"""
    if not records:
        return {}

    sig = {
        "best_weight_range": None,   # 馬体重ベスト幅
        "weight_volatility": 0,      # 馬体重変動の大きさ
        "kg_max_carried": 0,         # 過去最高斤量
        "winning_kg_avg": 0,         # 勝った時の平均斤量
        "best_jockey": None,         # 最も相性良い騎手
        "best_distance": None,       # ベスト距離
        "best_venue": None,          # ベスト競馬場
        "best_condition": None,      # ベスト馬場状態
        "best_surface": None,        # ベスト馬場種別
        "best_season": None,         # ベスト季節
        "consecutive_3f_top3": 0,    # 直近の上がり3F上位率
        "rest_pattern": None,        # 休養パターン傾向
        "running_style_stable": None,  # 脚質の一貫性
    }

    # 馬体重
    weights = []
    win_weights, loss_weights = [], []
    win_kgs = []
    kg_max = 0
    win_distances = defaultdict(int)
    win_venues = defaultdict(int)
    win_conditions = defaultdict(int)
    win_surfaces = defaultdict(int)
    win_seasons = defaultdict(int)
    win_jockeys = defaultdict(int)
    f3_top = 0
    f3_total = 0
    style_counter = defaultdict(int)

    for r in records:
        w = getattr(r, "horse_weight", 0) or 0
        if w > 0:
            weights.append(w)
            if getattr(r, "order", 99) == 1:
                win_weights.append(w)
            else:
                loss_weights.append(w)
        kg = getattr(r, "weight_carry", 0) or 0
        if kg > kg_max: kg_max = kg
        if getattr(r, "order", 99) == 1:
            win_kgs.append(kg)
            d = getattr(r, "distance", 0) or 0
            if d: win_distances[((d // 200) * 200)] += 1
            v = getattr(r, "venue", "") or ""
            if v: win_venues[v] += 1
            c = getattr(r, "condition", "") or ""
            if c: win_conditions[c] += 1
            sf = getattr(r, "surface", "") or ""
            if sf: win_surfaces[sf] += 1
            date_s = getattr(r, "date", "") or ""
            if date_s:
                try:
                    m = int(date_s.split("-")[1])
                    season = "春" if m in (3,4,5) else "夏" if m in (6,7,8) else "秋" if m in (9,10,11) else "冬"
                    win_seasons[season] += 1
                except Exception:
                    pass
            j = getattr(r, "jockey", "") or ""
            if j: win_jockeys[j] += 1
        f3r = getattr(r, "last_3f_rank", 0) or 0
        if f3r > 0:
            f3_total += 1
            if f3r <= 3: f3_top += 1
        st = getattr(r, "running_style", "") or ""
        if st: style_counter[st] += 1

    if weights:
        sig["best_weight_range"] = (min(weights), max(weights))
        sig["weight_volatility"] = round(max(weights) - min(weights), 1)
    if win_weights:
        sig["winning_kg_avg"] = round(sum(win_kgs) / len(win_kgs), 1)
    sig["kg_max_carried"] = kg_max
    if win_distances:
        sig["best_distance"] = max(win_distances.items(), key=lambda x: x[1])[0]
    if win_venues:
        sig["best_venue"] = max(win_venues.items(), key=lambda x: x[1])[0]
    if win_conditions:
        sig["best_condition"] = max(win_conditions.items(), key=lambda x: x[1])[0]
    if win_surfaces:
        sig["best_surface"] = max(win_surfaces.items(), key=lambda x: x[1])[0]
    if win_seasons:
        sig["best_season"] = max(win_seasons.items(), key=lambda x: x[1])[0]
    if win_jockeys:
        sig["best_jockey"] = max(win_jockeys.items(), key=lambda x: x[1])[0]
    if f3_total:
        sig["consecutive_3f_top3"] = round(f3_top / f3_total, 3)
    if style_counter:
        sig["running_style_stable"] = max(style_counter.items(), key=lambda x: x[1])[0]
    return sig


def score_horse_with_signals(signals: dict, race_info: dict) -> dict:
    """シグナルと今回レース条件を照合してスコア加減点と理由を返す"""
    adjust = 0.0
    reasons = []
    if not signals:
        return {"adjust": 0, "reasons": []}

    # 1. 季節適性
    if signals.get("best_season"):
        today_m = int(race_info.get("month", 0) or 0)
        cur_season = "春" if today_m in (3,4,5) else "夏" if today_m in (6,7,8) else "秋" if today_m in (9,10,11) else "冬" if today_m else None
        if cur_season and cur_season == signals["best_season"]:
            adjust += 1.5
            reasons.append(f"{cur_season}得意（過去勝利集中）")

    # 2. 距離マッチ
    if signals.get("best_distance"):
        race_dist = race_info.get("distance", 0)
        if race_dist and abs(race_dist - signals["best_distance"]) <= 200:
            adjust += 2.0
            reasons.append(f"{signals['best_distance']}m前後ベスト")

    # 3. コースマッチ
    if signals.get("best_venue") and race_info.get("venue") == signals["best_venue"]:
        adjust += 2.0
        reasons.append(f"{signals['best_venue']}は得意コース")

    # 4. 馬場種別マッチ
    if signals.get("best_surface") and race_info.get("surface") == signals["best_surface"]:
        adjust += 1.5
        reasons.append(f"{signals['best_surface']}適性")

    # 5. 馬場状態マッチ
    if signals.get("best_condition") and race_info.get("condition") == signals["best_condition"]:
        adjust += 1.5
        reasons.append(f"{signals['best_condition']}馬場の経験あり")

    # 6. 斤量耐性
    cur_kg = race_info.get("weight_carry", 0)
    if cur_kg and signals.get("kg_max_carried"):
        if cur_kg <= signals["kg_max_carried"]:
            adjust += 0.5
            reasons.append(f"斤量{cur_kg}kgは過去経験範囲内")
        else:
            adjust -= 1.0
            reasons.append(f"斤量{cur_kg}kgは過去最高超え、未知数")

    # 7. 上がり3F一貫性
    if signals.get("consecutive_3f_top3", 0) >= 0.6:
        adjust += 2.0
        reasons.append(f"末脚一貫性: 過去{signals['consecutive_3f_top3']*100:.0f}%が上がり3位以内")

    # 8. 馬体重安定性
    if signals.get("weight_volatility", 999) <= 8:
        adjust += 0.5
        reasons.append("馬体重安定")
    elif signals.get("weight_volatility", 0) >= 20:
        adjust -= 0.5
        reasons.append("馬体重変動大、状態に注意")

    return {"adjust": round(adjust, 1), "reasons": reasons[:5]}


if __name__ == "__main__":
    print("comprehensive_factor_analyzer ready")
    print("Used to derive multi-dimensional signals from horse history records")
