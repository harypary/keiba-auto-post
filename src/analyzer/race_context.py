"""
レース展開予測 & 競合レベル分析
- 各馬の脚質から展開（ペース）を予測
- 出走メンバーの強さ（敵レベル）を算出
- 展開の恩恵/不利を各馬のスコアに反映
"""
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.history_scraper import FullHorseHistory, build_stats


@dataclass
class RaceContext:
    pace_prediction: str       # "ハイペース" / "ミドルペース" / "スローペース"
    pace_score: float          # ハイ=高, スロー=低
    num_front_runners: int     # 逃げ・先行頭数
    field_level: float         # 出走メンバーの平均レベル（0-100）
    field_level_label: str     # "G1級" / "OP級" / "条件戦"
    pace_advantage: dict       # {horse_no: float}  脚質×展開の恩恵スコア
    rival_pressure: dict       # {horse_no: float}  ライバルからのプレッシャー


def analyze_race_context(
    horses: list,                          # HorseEntry list
    histories: dict[str, FullHorseHistory], # horse_id -> history
    race_distance: int,
    race_surface: str,
) -> RaceContext:
    # 1. 各馬の脚質取得（不明馬は実際のJRA分布に近づくよう確率的に補完）
    import hashlib
    styles = {}
    speed_indices = {}
    for entry in horses:
        hist = histories.get(entry.horse_id)
        if hist and hist.stats:
            styles[entry.horse_no] = hist.stats.get("running_style", "差し")
            speed_indices[entry.horse_no] = hist.stats.get("speed_index", 50.0)
        else:
            # 不明馬の脚質は枠順 & 馬番で擬似的に分布させる
            # JRA 実分布近似: 逃げ12% / 先行30% / 差し38% / 追込20%
            seed = int(hashlib.md5(f"{entry.horse_no}_{entry.horse_id}".encode()).hexdigest()[:8], 16) % 100
            if seed < 12:    styles[entry.horse_no] = "逃げ"
            elif seed < 42:  styles[entry.horse_no] = "先行"
            elif seed < 80:  styles[entry.horse_no] = "差し"
            else:            styles[entry.horse_no] = "追込"
            speed_indices[entry.horse_no] = 45.0

    # 2. 展開予測
    front_count = sum(1 for s in styles.values() if s in ("逃げ", "先行"))
    pace = _predict_pace(front_count, race_distance, race_surface, total=len(horses))

    # 3. 展開恩恵スコア
    pace_advantage = {}
    for horse_no, style in styles.items():
        pace_advantage[horse_no] = _pace_advantage(style, pace, race_distance)

    # 4. フィールドレベル
    si_values = list(speed_indices.values())
    field_level = sum(si_values) / len(si_values) if si_values else 50.0
    field_label = _field_label(field_level)

    # 5. ライバルプレッシャー（上位馬との差）
    rival_pressure = {}
    top_si = sorted(si_values, reverse=True)[:3]
    avg_top = sum(top_si) / len(top_si) if top_si else 50.0
    for horse_no, si in speed_indices.items():
        rival_pressure[horse_no] = max(0, min(20, (si - avg_top) * 0.5))

    return RaceContext(
        pace_prediction=pace,
        pace_score={"ハイペース": 80, "ミドルペース": 50, "スローペース": 20}.get(pace, 50),
        num_front_runners=front_count,
        field_level=round(field_level, 1),
        field_level_label=field_label,
        pace_advantage=pace_advantage,
        rival_pressure=rival_pressure,
    )


def _predict_pace(front_count: int, distance: int, surface: str, total: int = 0) -> str:
    """
    展開予測（実際の JRA 分布に近づける）:
      - 先行馬の比率と距離を主指標に
      - JRA実分布: ハイ ~28% / ミドル ~50% / スロー ~22%
    """
    # 先行馬の比率（頭数比） 0〜1
    ratio = front_count / max(total, 1) if total > 0 else front_count / 14.0
    base = ratio * 100  # 0〜100スケール

    # 距離補正
    if distance <= 1200:
        base += 20
    elif distance <= 1600:
        base += 10
    elif distance >= 2400:
        base -= 10

    if surface == "ダート":
        base += 8

    # JRA実分布: ハイ ~25% / ミドル ~55% / スロー ~20%
    if base >= 65:
        return "ハイペース"
    elif base >= 38:
        return "ミドルペース"
    return "スローペース"


def _pace_advantage(style: str, pace: str, distance: int) -> float:
    """展開×脚質の恩恵（マイナスも有り）"""
    matrix = {
        # pace:           逃げ  先行  差し  追込  不明
        "ハイペース":    {  "逃げ":-8, "先行":-4, "差し":+10, "追込":+12, "不明":0 },
        "ミドルペース":  {  "逃げ": 0, "先行":+5, "差し":+5,  "追込":+3,  "不明":0 },
        "スローペース":  {  "逃げ":+10,"先行":+8, "差し":-3,  "追込":-8,  "不明":0 },
    }
    return matrix.get(pace, {}).get(style, 0)


def _field_label(level: float) -> str:
    if level >= 75: return "G1級メンバー"
    if level >= 65: return "G2-G3級メンバー"
    if level >= 55: return "OP級メンバー"
    if level >= 45: return "上級条件戦"
    return "条件戦メンバー"
