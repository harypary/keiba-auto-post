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

    # 上位7頭（穴馬を含めて広めに取る）
    top_n_objs = sorted_scores[:7]
    top_nos = [s.horse_no for s in top_n_objs]
    if value_horse and value_horse not in top_nos:
        # 穴馬を上位枠の最後（7位扱い）に組み込む
        top_nos = top_nos[:6] + [value_horse]
    # スコア差が小さい場合は広げる（混戦判定）
    score_gap = (sorted_scores[0].total_score - sorted_scores[min(4, len(sorted_scores)-1)].total_score) if len(sorted_scores) >= 5 else 999
    is_open = score_gap < 8  # 上位5頭差 < 8点 → 混戦

    # 馬連: 軸2頭流し（本命×top6, 対抗×top5）。混戦時は本命×top7に拡大
    honmei_no = honmei[0] if honmei else None
    taikou_no = taikou[0] if taikou else None
    exacta_bets = []
    if honmei_no:
        net = top_nos[:7 if is_open else 6]
        for o in net:
            if o != honmei_no:
                exacta_bets.append(tuple(sorted([honmei_no, o])))
    if taikou_no:
        # 対抗軸も追加（本命と被らない範囲で4頭）
        net2 = [n for n in top_nos[:5] if n != honmei_no and n != taikou_no][:4]
        for o in net2:
            pair = tuple(sorted([taikou_no, o]))
            if pair not in exacta_bets:
                exacta_bets.append(pair)
    # 重複排除＆最大10点
    exacta_bets = list(dict.fromkeys(exacta_bets))[:8]

    # ワイド: 本命×top5 + 上位3頭ボックス（穴馬を絡める）
    quinella_bets = []
    if honmei_no:
        for o in top_nos[1:6]:
            if o != honmei_no:
                quinella_bets.append(tuple(sorted([honmei_no, o])))
    # 上位3ボックス
    top3 = top_nos[:3]
    for pair in _box_combinations(top3):
        if pair not in quinella_bets:
            quinella_bets.append(pair)
    # 穴馬絡みで1点追加
    if value_horse and honmei_no and value_horse != honmei_no:
        vp = tuple(sorted([honmei_no, value_horse]))
        if vp not in quinella_bets:
            quinella_bets.append(vp)
    quinella_bets = list(dict.fromkeys(quinella_bets))[:7]

    # 3連複: 本命軸1頭流し（本命×top6から2頭選ぶ全組合せ）+ 軸2頭流し（本命+対抗×top5）
    trifecta_bets = []
    if honmei_no:
        # 軸1頭流し: 本命 + (top6 から 2頭) = C(6,2)=15通り → 上位ペアで絞る
        flow_pool = [n for n in top_nos[:7] if n != honmei_no][:6]
        for i in range(len(flow_pool)):
            for j in range(i + 1, len(flow_pool)):
                triplet = tuple(sorted([honmei_no, flow_pool[i], flow_pool[j]]))
                if triplet not in trifecta_bets:
                    trifecta_bets.append(triplet)
                if len(trifecta_bets) >= 12:
                    break
            if len(trifecta_bets) >= 12:
                break
    # 軸2頭流し（本命+対抗 → top5 から1頭）も追加
    if honmei_no and taikou_no:
        rest_pool = [n for n in top_nos[:5] if n not in (honmei_no, taikou_no)]
        for r in rest_pool[:5]:
            triplet = tuple(sorted([honmei_no, taikou_no, r]))
            if triplet not in trifecta_bets:
                trifecta_bets.append(triplet)
    # 穴馬絡み（本命+対抗+穴馬）も1点
    if value_horse and honmei_no and taikou_no and value_horse not in (honmei_no, taikou_no):
        triplet = tuple(sorted([honmei_no, taikou_no, value_horse]))
        if triplet not in trifecta_bets:
            trifecta_bets.append(triplet)
    trifecta_bets = trifecta_bets[:10]  # 最大10点（的中率と投資効率のバランス）

    # 3連単: 本命1着固定 × top4 → 6点
    trio_heads = [n for n in top_nos[:5] if n != honmei_no][:4] if honmei_no else []
    trio_bets = [(honmei_no, a, b) for a in trio_heads for b in trio_heads if a != b][:8] if honmei_no else []

    # === EV閾値フィルタ：期待値<0.7の買い目をリストから除外（マイナス期待値を排除）===
    odds_map = {s.horse_no: getattr(s, "odds", 0) or 0 for s in scores}
    score_map = {s.horse_no: s.total_score for s in scores}
    import math
    base = max(score_map.values()) if score_map else 0
    exps = {n: math.exp((v - base) / 6.0) for n, v in score_map.items()}
    z = sum(exps.values()) or 1.0
    p_win = {n: e / z for n, e in exps.items()}

    def ev_uren(a, b):
        pa, pb = p_win.get(a, 0), p_win.get(b, 0)
        denom = max(0.05, 1 - min(pa, pb))
        p = min(0.5, 2 * pa * pb / denom)
        oa, ob = odds_map.get(a, 0), odds_map.get(b, 0)
        return p * oa * ob * 0.4 if oa and ob else 1.0  # オッズ未取得は通す

    def ev_wide(a, b):
        pa, pb = p_win.get(a, 0), p_win.get(b, 0)
        denom = max(0.05, 1 - min(pa, pb))
        p = min(0.7, 4 * pa * pb / denom)
        oa, ob = odds_map.get(a, 0), odds_map.get(b, 0)
        return p * max(1.5, oa * ob * 0.15) if oa and ob else 1.0

    def ev_fuku3(combo):
        a, b, c = combo
        pa, pb, pc = p_win.get(a, 0), p_win.get(b, 0), p_win.get(c, 0)
        p = min(0.4, 6 * pa * pb * pc / max(0.05, (1 - pa) * (1 - pb)))
        oa, ob, oc = odds_map.get(a, 0), odds_map.get(b, 0), odds_map.get(c, 0)
        return p * oa * ob * oc * 0.5 if (oa and ob and oc) else 1.0

    EV_THRESHOLD = 0.95   # ほぼプラス期待値の買い目に厳選
    exacta_bets = [b for b in exacta_bets if ev_uren(*b) >= EV_THRESHOLD]
    quinella_bets = [b for b in quinella_bets if ev_wide(*b) >= EV_THRESHOLD]
    trifecta_bets = [b for b in trifecta_bets if ev_fuku3(b) >= EV_THRESHOLD]
    # 最低保証：少なすぎる場合は元のtop3だけは残す
    if len(exacta_bets) < 3 and honmei_no:
        for o in top_nos[1:5]:
            pair = tuple(sorted([honmei_no, o]))
            if pair not in exacta_bets:
                exacta_bets.append(pair)
                if len(exacta_bets) >= 4: break
    if len(trifecta_bets) < 3 and honmei_no and taikou_no:
        for r in top_nos[2:6]:
            triplet = tuple(sorted([honmei_no, taikou_no, r]))
            if triplet not in trifecta_bets and r not in (honmei_no, taikou_no):
                trifecta_bets.append(triplet)
                if len(trifecta_bets) >= 4: break

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
