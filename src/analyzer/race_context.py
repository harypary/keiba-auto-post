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
    # === 隊列シナリオ（深掘り） ===
    num_nige: int = 0          # 純粋な逃げ馬の頭数
    num_senko: int = 0         # 先行馬の頭数
    pace_scenario: str = "標準" # "単騎逃げ" / "ハナ争い" / "逃げ不在" / "標準"
    pace_reasons: list = field(default_factory=list)  # シナリオの根拠（記事用）
    lone_front_no: int = 0     # 単騎逃げ濃厚な馬番（0=該当なし）
    styles: dict = field(default_factory=dict)        # {horse_no: 脚質}


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

    # 2. 隊列シナリオの精緻化（逃げ・先行を分けて数える）
    nige_nos = [hn for hn, s in styles.items() if s == "逃げ"]
    senko_nos = [hn for hn, s in styles.items() if s == "先行"]
    nige_count = len(nige_nos)
    senko_count = len(senko_nos)
    front_count = nige_count + senko_count

    scenario, reasons, lone_no = _classify_pace_scenario(
        nige_nos, senko_nos, speed_indices, race_distance, race_surface
    )

    pace = _predict_pace(front_count, race_distance, race_surface,
                         total=len(horses), nige_count=nige_count, scenario=scenario)

    # 3. 展開恩恵スコア（隊列シナリオを加味）
    pace_advantage = {}
    for horse_no, style in styles.items():
        adv = _pace_advantage(style, pace, race_distance)
        adv += _scenario_adjust(horse_no, style, scenario, lone_no)
        pace_advantage[horse_no] = adv

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
        num_nige=nige_count,
        num_senko=senko_count,
        pace_scenario=scenario,
        pace_reasons=reasons,
        lone_front_no=lone_no,
        styles=styles,
    )


def _classify_pace_scenario(nige_nos, senko_nos, speed_indices, distance, surface):
    """逃げ・先行の頭数と質から隊列シナリオを判定。
    戻り値: (scenario, reasons[list], lone_front_no)
    - 単騎逃げ: 逃げ1頭で番手も手薄 → その馬がペースを支配（強い味方）
    - ハナ争い: 逃げ3頭以上 or 逃げ2頭+先行多数 → 前傾ラップで先行勢総崩れ
    - 逃げ不在: 逃げ0頭 → 誰かが出ざるを得ずスロー必至、位置取り勝負
    - 標準: 上記以外
    """
    nige_count = len(nige_nos)
    senko_count = len(senko_nos)
    reasons = []
    lone_no = 0

    if nige_count == 0:
        reasons.append("明確な逃げ馬が不在。誰かが渋々ハナに立つ形で、前半は緩む公算が大きい。")
        reasons.append("位置を取れる先行・好位差しが恵まれ、後方一気は届きにくい隊列になりやすい。")
        return "逃げ不在", reasons, lone_no

    if nige_count >= 3 or (nige_count >= 2 and senko_count >= 4):
        reasons.append(f"逃げ脚質が{nige_count}頭おり、ハナ争いから前半が速くなる可能性が高い。")
        reasons.append("前が競り合って共倒れ→差し・追込が台頭する『ペース崩壊』シナリオを警戒。")
        return "ハナ争い", reasons, lone_no

    if nige_count == 1 and senko_count <= 2:
        lone_no = nige_nos[0]
        si = speed_indices.get(lone_no, 50.0)
        qual = "能力上位で" if si >= 60 else ""
        reasons.append(f"逃げ馬は{lone_no}番の1頭のみ。番手も手薄で{qual}単騎逃げが濃厚。")
        reasons.append("マイペースに持ち込めれば前残り。この馬を負かすのは差し勢の決め手次第。")
        return "単騎逃げ", reasons, lone_no

    reasons.append(f"逃げ{nige_count}頭・先行{senko_count}頭でハナの主張は標準的。隊列は素直に決まりやすい。")
    return "標準", reasons, lone_no


def _scenario_adjust(horse_no, style, scenario, lone_no) -> float:
    """隊列シナリオに応じた脚質別の追加補正（pace_advantage に加算）。"""
    if scenario == "単騎逃げ":
        if horse_no == lone_no:
            return +8.0   # マイペースの恩恵は絶大
        if style == "先行":
            return +2.0   # 番手も比較的恵まれる
        if style in ("差し", "追込"):
            return -3.0   # 前が止まらず届きにくい
    elif scenario == "ハナ争い":
        if style == "逃げ":
            return -8.0   # 競り合いで消耗、総崩れ濃厚
        if style == "先行":
            return -4.0
        if style in ("差し", "追込"):
            return +6.0   # ペース崩壊の最大受益者
    elif scenario == "逃げ不在":
        if style in ("逃げ", "先行"):
            return +4.0   # スローで前残り
        if style == "追込":
            return -4.0   # 後方一気は届かない
        if style == "差し":
            return -1.0
    return 0.0


def _predict_pace(front_count: int, distance: int, surface: str, total: int = 0,
                  nige_count: int = -1, scenario: str = "") -> str:
    """
    展開予測（実際の JRA 分布に近づける）:
      - 先行馬の比率と距離を主指標に、逃げ馬の頭数・隊列シナリオで上書き
      - JRA実分布: ハイ ~28% / ミドル ~50% / スロー ~22%
    """
    # 隊列シナリオが明確ならそれを優先（逃げ馬の数がペースの最大決定要因）
    if scenario == "ハナ争い":
        return "ハイペース"
    if scenario == "逃げ不在":
        return "スローペース"

    # 先行馬の比率（頭数比） 0〜1
    ratio = front_count / max(total, 1) if total > 0 else front_count / 14.0
    base = ratio * 100  # 0〜100スケール

    # 逃げ馬の頭数を直接加味（先行比率だけより精度が上がる）
    if nige_count >= 0:
        base += max(0, nige_count - 1) * 12   # 2頭目以降の逃げはペースを押し上げる
        if nige_count == 0:
            base -= 12

    # 距離補正
    if distance <= 1200:
        base += 20
    elif distance <= 1600:
        base += 10
    elif distance >= 2400:
        base -= 10

    if surface == "ダート":
        base += 8

    # 単騎逃げはマイペースに落とせるためペースは上がりにくい
    if scenario == "単騎逃げ":
        base -= 10

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
