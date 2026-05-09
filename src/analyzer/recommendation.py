"""
スコアから買い目を生成する
"""
from dataclasses import dataclass, field
from typing import Optional
from .race_analyzer import HorseScore


@dataclass
class BettingPlan:
    race_id: str
    race_name: str
    honmei: list[int]           # ◎ 本命
    taikou: list[int]           # ○ 対抗
    tanana: list[int]           # ▲ 単穴
    renka: list[int]            # △ 連下
    omakase: list[int]          # × 穴

    # 買い目
    win_bets: list[int]         # 単勝
    place_bets: list[int]       # 複勝
    exacta_bets: list[tuple]    # 馬連
    quinella_bets: list[tuple]  # ワイド
    trifecta_bets: list[tuple]  # 3連複
    trio_bets: list[tuple]      # 3連単（厳選）

    value_horse: Optional[int] = None   # 穴狙い推奨
    total_combinations: int = 0
    estimated_cost: int = 0


def build_betting_plan_from_stat(race_id: str, race_name: str, scores, num_horses: int) -> BettingPlan:
    return build_betting_plan(race_id, race_name, scores, num_horses)


def build_betting_plan_from_comprehensive(race_id: str, race_name: str, scores, num_horses: int) -> BettingPlan:
    """ComprehensiveScoreからBettingPlan生成（final_scoreを使う）"""
    # ComprehensiveScoreはtotal_scoreでなくfinal_scoreを使うためアダプト
    class _Adapter:
        def __init__(self, s):
            self.horse_no = s.horse_no
            self.frame_no = getattr(s, "frame_no", 0)
            self.total_score = s.final_score
            self.odds = s.odds
            self.form_score = getattr(s.raw_stat, "form_score", 50) if s.raw_stat else 50
    adapted = [_Adapter(s) for s in scores]
    return build_betting_plan(race_id, race_name, adapted, num_horses)


def build_betting_plan(race_id: str, race_name: str, scores, num_horses: int) -> BettingPlan:
    """スコアリング結果から買い目を生成"""
    sorted_scores = sorted(scores, key=lambda x: x.total_score, reverse=True)

    honmei = [sorted_scores[0].horse_no] if len(sorted_scores) >= 1 else []
    taikou = [sorted_scores[1].horse_no] if len(sorted_scores) >= 2 else []
    tanana = [sorted_scores[2].horse_no] if len(sorted_scores) >= 3 else []
    renka = [s.horse_no for s in sorted_scores[3:5]]
    omakase = [s.horse_no for s in sorted_scores[5:7] if s.total_score > 0]

    # 穴馬：スコアは低いがオッズ10倍以上
    value_horse = None
    for s in sorted_scores[3:]:
        if s.odds and s.odds >= 10.0 and s.form_score >= 55:
            value_horse = s.horse_no
            break

    # ---- 買い目構築 ----
    # 単勝: 本命
    win_bets = honmei[:]

    # 複勝: 本命・対抗・穴馬
    place_bets = (honmei + taikou + ([value_horse] if value_horse else []))[:3]

    # 馬連: 本命軸 × 対抗・単穴・連下
    pivot = honmei[0] if honmei else None
    targets = taikou + tanana + renka
    exacta_bets = _axis_box(pivot, targets, max_count=5)

    # ワイド: 上位3頭ボックス
    top3 = honmei + taikou + tanana
    quinella_bets = _box_combinations(top3[:3])

    # 3連複: 本命・対抗軸 × 単穴・連下
    axis2 = honmei + taikou
    rest = tanana + renka
    trifecta_bets = _trifecta_axis(axis2, rest, max_count=6)

    # 3連単: 本命1着固定 × 対抗・単穴
    trio_heads = taikou + tanana
    trio_bets = [(honmei[0], a, b) for a in trio_heads for b in trio_heads if a != b][:6] if honmei else []

    total_combinations = (
        len(win_bets) + len(place_bets) +
        len(exacta_bets) + len(quinella_bets) +
        len(trifecta_bets) + len(trio_bets)
    )
    estimated_cost = total_combinations * 100

    return BettingPlan(
        race_id=race_id,
        race_name=race_name,
        honmei=honmei,
        taikou=taikou,
        tanana=tanana,
        renka=renka,
        omakase=omakase,
        win_bets=win_bets,
        place_bets=place_bets,
        exacta_bets=exacta_bets,
        quinella_bets=quinella_bets,
        trifecta_bets=trifecta_bets,
        trio_bets=trio_bets,
        value_horse=value_horse,
        total_combinations=total_combinations,
        estimated_cost=estimated_cost,
    )


def _axis_box(axis: Optional[int], others: list[int], max_count: int = 5) -> list[tuple]:
    if axis is None:
        return []
    return [(min(axis, o), max(axis, o)) for o in others[:max_count]]


def _box_combinations(horses: list[int]) -> list[tuple]:
    result = []
    for i in range(len(horses)):
        for j in range(i + 1, len(horses)):
            result.append((horses[i], horses[j]))
    return result


def _trifecta_axis(axis_horses: list[int], rest: list[int], max_count: int = 6) -> list[tuple]:
    combos = []
    for r in rest:
        triplet = sorted(axis_horses[:2] + [r])
        if len(triplet) == 3 and triplet not in combos:
            combos.append(tuple(triplet))
        if len(combos) >= max_count:
            break
    return combos
