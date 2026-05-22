"""
スコアから買い目を生成する
"""
import math
from dataclasses import dataclass, field
from typing import Optional
from .race_analyzer import HorseScore


def _ml_probabilities(scores) -> dict:
    """ML or final_score-based 勝率推定（馬番→p）"""
    try:
        from src.ml.meta_model import predict_win_prob, load_model
        model = load_model()
        if model:
            ml = {}
            for s in scores:
                rs = getattr(s, "raw_stat", None)
                if not rs:
                    continue
                ped_raw = getattr(s, "pedigree_bonus", 0) or 0
                ped_norm = min(100, max(0, 50 + ped_raw * 4))
                feats = {
                    "recent_form": getattr(rs, "form_score", 50),
                    "surface": getattr(rs, "surface_score", 50),
                    "distance": getattr(rs, "distance_score", 50),
                    "speed_index": getattr(s, "speed_score", 50),
                    "class_change": getattr(rs, "grade_score", 50),
                    "venue": getattr(rs, "venue_score", 50),
                    "condition": getattr(rs, "condition_score", 50),
                    "rest": getattr(rs, "rest_score", 50),
                    "pace": getattr(rs, "pace_score", 50),
                    "weight_stab": getattr(rs, "weight_score", 50),
                    "pedigree": ped_norm,
                }
                p = predict_win_prob(feats, model)
                if p is not None:
                    ml[s.horse_no] = p
            if ml:
                z = sum(ml.values()) or 1.0
                return {no: p / z for no, p in ml.items()}
    except Exception:
        pass
    # fallback: softmax
    vals = [(s.horse_no, getattr(s, "total_score", 0) or 0) for s in scores]
    base = max(v for _, v in vals) if vals else 0
    exps = [(no, math.exp((v - base) / 6.0)) for no, v in vals]
    z = sum(e for _, e in exps) or 1.0
    return {no: e / z for no, e in exps}


def find_ev_optimal_bets(scores, race=None, max_per_kind: int = 8, ev_threshold: float = 1.0) -> dict:
    """
    全馬の勝率（ML予測）×オッズで全組合せのEVを計算し、
    EV>=ev_threshold の買い目を券種別にトップEV順で返す。
    返却形式: {"exacta_bets": [(a,b), ...], "quinella_bets":..., "trifecta_bets":..., ...}
    """
    p_win = _ml_probabilities(scores)
    odds_of = {s.horse_no: (getattr(s, "odds", 0) or 0) for s in scores}

    # 較正済みの想定配当係数
    try:
        from src.ml.payout_calibrator import get_coefs
        COEF = get_coefs()
    except Exception:
        COEF = {"uren": 0.4, "wide": 0.15, "fuku3": 0.5, "fuku": 0.28}

    horse_nos = [s.horse_no for s in scores]
    n = len(horse_nos)

    out = {"win_bets": [], "place_bets": [], "exacta_bets": [], "quinella_bets": [], "trifecta_bets": []}
    if n < 4:
        return out

    # 単勝 EV: p × odds
    win_cands = []
    for no in horse_nos:
        p = p_win.get(no, 0)
        o = odds_of.get(no, 0)
        if p and o:
            ev = p * o
            if ev >= ev_threshold:
                win_cands.append((ev, no))
    win_cands.sort(reverse=True)
    out["win_bets"] = [no for _, no in win_cands[:3]]

    # 複勝 EV: 三着内確率(p×2.5) × 複勝オッズ
    place_cands = []
    for no in horse_nos:
        p3 = min(0.9, p_win.get(no, 0) * 2.5)
        o = odds_of.get(no, 0)
        if p3 and o:
            ev = p3 * o * COEF["fuku"]
            if ev >= ev_threshold:
                place_cands.append((ev, no))
    place_cands.sort(reverse=True)
    out["place_bets"] = [no for _, no in place_cands[:5]]

    # 馬連 EV（全組合せ）
    uren_cands = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = horse_nos[i], horse_nos[j]
            pa, pb = p_win.get(a, 0), p_win.get(b, 0)
            if pa <= 0 or pb <= 0:
                continue
            denom = max(0.05, 1 - min(pa, pb))
            p_hit = min(0.5, 2 * pa * pb / denom)
            oa, ob = odds_of.get(a, 0), odds_of.get(b, 0)
            if not (oa and ob):
                continue
            est = oa * ob * COEF["uren"]
            ev = p_hit * est
            if ev >= ev_threshold:
                uren_cands.append((ev, tuple(sorted([a, b]))))
    uren_cands.sort(reverse=True)
    out["exacta_bets"] = [pair for _, pair in uren_cands[:max_per_kind]]

    # ワイド EV
    wide_cands = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = horse_nos[i], horse_nos[j]
            pa, pb = p_win.get(a, 0), p_win.get(b, 0)
            if pa <= 0 or pb <= 0:
                continue
            denom = max(0.05, 1 - min(pa, pb))
            p_hit = min(0.7, 4 * pa * pb / denom)
            oa, ob = odds_of.get(a, 0), odds_of.get(b, 0)
            if not (oa and ob):
                continue
            est = max(1.5, oa * ob * COEF["wide"])
            ev = p_hit * est
            if ev >= ev_threshold:
                wide_cands.append((ev, tuple(sorted([a, b]))))
    wide_cands.sort(reverse=True)
    out["quinella_bets"] = [pair for _, pair in wide_cands[:max_per_kind]]

    # 3連複 EV（組合せ多いので軸絞り：上位5頭から×残りを総当たり）
    top_p = sorted(p_win.items(), key=lambda x: -x[1])[:6]
    top_nos = [no for no, _ in top_p]
    fuku3_cands = []
    for i in range(len(top_nos)):
        for j in range(i + 1, len(top_nos)):
            for k in range(j + 1, n):
                a, b, c = top_nos[i], top_nos[j], horse_nos[k]
                if c in (a, b):
                    continue
                pa, pb, pc = p_win.get(a, 0), p_win.get(b, 0), p_win.get(c, 0)
                if pa <= 0 or pb <= 0 or pc <= 0:
                    continue
                p_hit = min(0.4, 6 * pa * pb * pc / max(0.05, (1 - pa) * (1 - pb)))
                oa, ob, oc = odds_of.get(a, 0), odds_of.get(b, 0), odds_of.get(c, 0)
                if not (oa and ob and oc):
                    continue
                est = oa * ob * oc * COEF["fuku3"]
                ev = p_hit * est
                if ev >= ev_threshold:
                    fuku3_cands.append((ev, tuple(sorted([a, b, c]))))
    fuku3_cands.sort(reverse=True)
    seen = set()
    fuku3_unique = []
    for ev, triple in fuku3_cands:
        if triple not in seen:
            seen.add(triple)
            fuku3_unique.append(triple)
    out["trifecta_bets"] = fuku3_unique[:max_per_kind + 2]

    return out


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

    # 深度EV分析: 可変投票額（Kellyベース）とレースグレード
    race_grade: str = "B"          # S/A/B/C/D
    grade_reason: str = ""
    skip_recommended: bool = False  # Grade D は見送り推奨
    stake_map: dict = field(default_factory=dict)   # {bet_key: yen}
    max_edge: float = 0.0
    max_ev: float = 0.0


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

    # === 深度EV分析優先：アンサンブル確率×Plackett-Luce×Kelly+エッジフィルタ ===
    deep_plan = None
    try:
        from src.analyzer.deep_ev_analyzer import find_optimal_bets_deep
        deep_plan = find_optimal_bets_deep(scores, ev_threshold=1.10)
        if deep_plan["exacta_bets"]:
            exacta_bets = deep_plan["exacta_bets"]
        if deep_plan["quinella_bets"]:
            quinella_bets = deep_plan["quinella_bets"]
        if deep_plan["trifecta_bets"]:
            trifecta_bets = deep_plan["trifecta_bets"]
        if deep_plan["win_bets"]:
            win_bets = deep_plan["win_bets"][:1]
        if deep_plan["place_bets"]:
            place_bets = deep_plan["place_bets"][:3]
    except Exception:
        # フォールバック：従来のEV最適化
        try:
            ev_plan = find_ev_optimal_bets(scores, max_per_kind=8, ev_threshold=1.0)
            if ev_plan["exacta_bets"]:    exacta_bets = ev_plan["exacta_bets"]
            if ev_plan["quinella_bets"]:  quinella_bets = ev_plan["quinella_bets"]
            if ev_plan["trifecta_bets"]:  trifecta_bets = ev_plan["trifecta_bets"]
            if ev_plan["win_bets"]:       win_bets = ev_plan["win_bets"][:1]
            if ev_plan["place_bets"]:     place_bets = ev_plan["place_bets"][:3]
        except Exception:
            pass

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

    # === 厳格EVフィルタ: モデル不確実性を考慮しEV>=1.10のみ採用 ===
    # 投資して回収が下回らないことを最優先。買い目0でも負け馬券を出さない。
    EV_THRESHOLD = 1.10   # 10%の安全マージン
    exacta_bets   = [b for b in exacta_bets   if ev_uren(*b)  >= EV_THRESHOLD]
    quinella_bets = [b for b in quinella_bets if ev_wide(*b)  >= EV_THRESHOLD]
    trifecta_bets = [b for b in trifecta_bets if ev_fuku3(b)  >= EV_THRESHOLD]
    # 単勝・複勝も同基準: ev = p × odds が 1.10 以上か
    def _ev_tan(no):
        p, o = p_win.get(no, 0), odds_map.get(no, 0)
        return p * o if o else 0
    def _ev_fuku(no):
        p, o = p_win.get(no, 0), odds_map.get(no, 0)
        if not o: return 0
        return min(0.85, p * 2.6) * max(1.1, o * 0.28)
    win_bets   = [n for n in win_bets   if _ev_tan(n)  >= EV_THRESHOLD]
    place_bets = [n for n in place_bets if _ev_fuku(n) >= 1.00]   # 複勝はやや緩く（的中率高い）

    # === レースグレード & Kelly 配分でステーク決定 ===
    race_grade = "B"
    grade_reason = ""
    skip_recommended = False
    max_edge = 0.0
    max_ev = 0.0
    stake_map = {}

    if deep_plan:
        gi = deep_plan.get("race_grade", {})
        race_grade = gi.get("grade", "B")
        grade_reason = gi.get("reason", "")
        max_edge = float(gi.get("max_edge", 0))
        max_ev = float(gi.get("max_ev", 0))

    # Grade D → 妙味薄いので買い目を最小限に絞る（◎単勝のみ・EVが1.0以上なら）
    if race_grade == "D":
        skip_recommended = True
        # ◎単勝の EV をチェック
        if honmei_no and _ev_tan(honmei_no) >= 1.00:
            win_bets = [honmei_no]
        else:
            win_bets = []
        place_bets, exacta_bets, quinella_bets, trifecta_bets, trio_bets = [], [], [], [], []

    # Grade ごとのレース総予算（円）
    GRADE_BUDGET = {"S": 3000, "A": 2000, "B": 1200, "C": 600, "D": 0}
    race_budget = GRADE_BUDGET.get(race_grade, 1000)

    # 各買い目を EV 比例 + Kelly で配分（100円単位、最小100円）
    def _allocate(bets, ev_map, kind_key):
        if not bets or race_budget == 0:
            return {}
        # EV-1 を edge proxy として配分重み
        weights = []
        for b in bets:
            key = b if isinstance(b, tuple) else (b,)
            ev = ev_map.get(b if isinstance(b, tuple) else b, 1.0)
            weights.append(max(0.05, ev - 0.95))
        wsum = sum(weights) or 1.0
        # 各券種への予算割当：単勝25% / 馬連30% / ワイド15% / 3連複30%
        kind_share = {"win": 0.25, "uren": 0.30, "wide": 0.15, "fuku3": 0.30, "fuku": 0.10}
        share = kind_share.get(kind_key, 0.2)
        kind_budget = race_budget * share
        result = {}
        for b, w in zip(bets, weights):
            yen = int(round(kind_budget * (w / wsum) / 100)) * 100
            if yen >= 100:
                result[b] = yen
        return result

    if deep_plan and not skip_recommended:
        stake_map["win"] = _allocate(win_bets, deep_plan.get("win_evs", {}), "win")
        stake_map["exacta"] = _allocate(exacta_bets, deep_plan.get("exacta_evs", {}), "uren")
        stake_map["quinella"] = _allocate(quinella_bets, deep_plan.get("quinella_evs", {}), "wide")
        stake_map["trifecta"] = _allocate(trifecta_bets, deep_plan.get("trifecta_evs", {}), "fuku3")
        # 複勝はEVで均等
        if place_bets:
            per = max(100, int(race_budget * 0.10 / max(1, len(place_bets)) / 100) * 100)
            stake_map["place"] = {no: per for no in place_bets}

    total_combinations = (
        len(win_bets) + len(place_bets) +
        len(exacta_bets) + len(quinella_bets) +
        len(trifecta_bets) + len(trio_bets)
    )
    # ステーク合計（Kelly反映）。stake_mapが空なら100円フラットにフォールバック
    if stake_map:
        estimated_cost = sum(sum(d.values()) for d in stake_map.values() if d)
    else:
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
        race_grade=race_grade,
        grade_reason=grade_reason,
        skip_recommended=skip_recommended,
        stake_map=stake_map,
        max_edge=max_edge,
        max_ev=max_ev,
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
