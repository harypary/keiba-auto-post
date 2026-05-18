"""
深度の深いEV分析: 期待値最大化のため複数手法を統合

1. 市場暗示確率（オッズ→確率、控除率20%補正）
2. エッジ計算（モデル確率 / 市場確率 - 1）
3. Plackett-Luce による正確な複合券種確率
4. Kelly フラクションでの最適投票配分
5. レース単位の "賭ける価値" 判定（最大エッジ・最大EV・確信度）
6. アンサンブル確率（ML + final_score softmax + 市場の3者重み付き平均）

買い目評価: 強推奨 / 推奨 / 様子見 / 見送り
"""
import math
from typing import Iterable, Optional


# === 市場暗示確率 ===
def implied_from_odds(odds_map: dict, overround: float = 0.80) -> dict:
    """単勝オッズから市場の暗示確率を推定（控除率約20%補正）

    overround=0.80 は払戻率（中央競馬の単勝は約80%）。
    raw_p = overround / odds、合計を 1.0 に正規化。
    """
    raw = {}
    for no, o in odds_map.items():
        if not o or o <= 0:
            continue
        raw[no] = overround / o
    z = sum(raw.values()) or 1.0
    return {no: p / z for no, p in raw.items()}


# === エッジ計算 ===
def compute_edges(model_p: dict, market_p: dict) -> dict:
    """各馬の edge = model_p / market_p - 1（プラス=過小評価=妙味）"""
    out = {}
    for no, mp in model_p.items():
        kp = market_p.get(no, 0)
        if kp > 0:
            out[no] = mp / kp - 1
        else:
            out[no] = 0
    return out


# === アンサンブル確率 ===
def ensemble_probabilities(scores, w_ml: float = 0.45, w_score: float = 0.35, w_market: float = 0.20) -> tuple:
    """ML / final_score softmax / 市場暗示 の3者を重み付き平均

    重みデフォルト: ML=45%, score=35%, market=20%。
    （データ蓄積で ML 重みを段階的に上げる）
    返却: (ensemble_p, ml_p, score_p, market_p)
    """
    from src.analyzer.recommendation import _ml_probabilities  # 既存活用

    ml_p = _ml_probabilities(scores)
    # score softmax
    vals = [(s.horse_no, getattr(s, "total_score", None) or getattr(s, "final_score", 0) or 0) for s in scores]
    base = max(v for _, v in vals) if vals else 0
    exps = [(no, math.exp((v - base) / 6.0)) for no, v in vals]
    z = sum(e for _, e in exps) or 1.0
    score_p = {no: e / z for no, e in exps}
    # market
    odds_map = {s.horse_no: getattr(s, "odds", 0) or 0 for s in scores}
    market_p = implied_from_odds(odds_map)

    horse_nos = [s.horse_no for s in scores]
    ens = {}
    for no in horse_nos:
        p = (
            w_ml * ml_p.get(no, 0)
            + w_score * score_p.get(no, 0)
            + w_market * market_p.get(no, 0)
        )
        ens[no] = p
    z2 = sum(ens.values()) or 1.0
    ens = {no: p / z2 for no, p in ens.items()}
    # === キャリブレーション適用（実勝率データから学習済みのカーブで補正）===
    try:
        from src.ml.probability_calibrator import calibrate_prob_dict
        ens = calibrate_prob_dict(ens)
    except Exception:
        pass
    return ens, ml_p, score_p, market_p


# === Plackett-Luce 複合券種確率 ===
def pl_quinella_prob(pa: float, pb: float) -> float:
    """馬連（a,b が1-2着、順序問わず）の確率を Plackett-Luce で計算"""
    if pa <= 0 or pb <= 0:
        return 0.0
    # a→b の順列 + b→a の順列
    p1 = pa * pb / max(1e-6, 1 - pa)
    p2 = pb * pa / max(1e-6, 1 - pb)
    return min(0.55, p1 + p2)


def pl_wide_prob(pa: float, pb: float, all_probs: list) -> float:
    """ワイド（両方とも3着以内）の確率を計算

    両方 3着以内 = (a 1着 ∧ b 2-3着) ∪ (a 2着 ∧ b 1or3着) ∪ ...
    簡易: P(a in top3) × P(b in top3 | a in top3)
    """
    if pa <= 0 or pb <= 0:
        return 0.0
    # 単勝→3着内変換（実証的に 2.5〜2.8 倍）
    pa3 = min(0.85, pa * 2.6)
    pb3 = min(0.85, pb * 2.6)
    # 独立性の仮定で積（少し下方修正）
    return min(0.65, pa3 * pb3 * 1.05)


def pl_trifecta_prob(pa: float, pb: float, pc: float) -> float:
    """3連複（a,b,c が1-3着、順序問わず）の確率を Plackett-Luce 6順列で和"""
    ps = [pa, pb, pc]
    if any(p <= 0 for p in ps):
        return 0.0
    from itertools import permutations
    total = 0.0
    for perm in permutations(ps):
        p1, p2, p3 = perm
        denom1 = max(1e-6, 1 - p1)
        denom2 = max(1e-6, 1 - p1 - p2)
        total += p1 * (p2 / denom1) * (p3 / denom2)
    return min(0.45, total)


# === Kelly 最適配分 ===
def kelly_fraction(p: float, odds: float, fraction: float = 0.25) -> float:
    """Kelly基準で投票比率（破産防止のため 0.25-Kelly 推奨）"""
    if p <= 0 or odds <= 1:
        return 0.0
    b = odds - 1
    k = (p * b - (1 - p)) / b
    if k <= 0:
        return 0.0
    return min(0.05, k * fraction)  # 1点あたり最大5%


# === レース単位の "賭ける価値" 判定 ===
def race_betting_grade(edges: dict, model_p: dict, odds_map: dict) -> dict:
    """レースの賭け価値を総合判定

    returns:
      {"grade": "S/A/B/C/D", "max_edge": float, "max_ev": float,
       "confidence": float, "reason": str}

    S: 最大エッジ>=40% & 最大EV>=1.5  → 大勝負
    A: 最大エッジ>=25% & 最大EV>=1.3
    B: 最大エッジ>=15% & 最大EV>=1.15
    C: 最大エッジ>=5%  & 最大EV>=1.05
    D: 上記未満 → 見送り推奨
    """
    if not edges:
        return {"grade": "D", "max_edge": 0, "max_ev": 0, "confidence": 0, "reason": "データなし"}

    max_edge_no, max_edge = max(edges.items(), key=lambda x: x[1])
    max_ev = 0
    for no, p in model_p.items():
        o = odds_map.get(no, 0) or 0
        ev = p * o
        if ev > max_ev:
            max_ev = ev

    # 確信度: 上位3頭の確率集中度（Herfindahl）
    top3_p = sorted(model_p.values(), reverse=True)[:3]
    confidence = sum(p * p for p in top3_p)  # 0.05(完全分散) - 0.3(超集中)

    if max_edge >= 0.40 and max_ev >= 1.5:
        grade = "S"; reason = f"#{max_edge_no} エッジ{max_edge*100:.0f}% EV{max_ev:.2f}（大幅過小評価）"
    elif max_edge >= 0.25 and max_ev >= 1.3:
        grade = "A"; reason = f"#{max_edge_no} エッジ{max_edge*100:.0f}% EV{max_ev:.2f}"
    elif max_edge >= 0.15 and max_ev >= 1.15:
        grade = "B"; reason = f"#{max_edge_no} エッジ{max_edge*100:.0f}% EV{max_ev:.2f}"
    elif max_edge >= 0.05 and max_ev >= 1.05:
        grade = "C"; reason = f"#{max_edge_no} エッジ{max_edge*100:.0f}% EV{max_ev:.2f}（軽め）"
    else:
        grade = "D"; reason = f"妙味薄い（最大エッジ{max_edge*100:.0f}%、最大EV{max_ev:.2f}）"

    return {
        "grade": grade,
        "max_edge": round(max_edge, 3),
        "max_edge_horse": max_edge_no,
        "max_ev": round(max_ev, 2),
        "confidence": round(confidence, 3),
        "reason": reason,
    }


# === 強化EV計算（buybudget配分付き） ===
def find_optimal_bets_deep(scores, race=None, ev_threshold: float = 1.05) -> dict:
    """深度の深いEV分析で最適買い目を生成

    - Plackett-Luce で正確な複合確率
    - アンサンブル確率（ML+score+market）
    - エッジ>=10% のみ採用（市場過小評価を狙う）
    - 各買い目に Kelly フラクション付き
    """
    try:
        from src.ml.payout_calibrator import get_coefs
        COEF = get_coefs()
    except Exception:
        COEF = {"uren": 0.4, "wide": 0.15, "fuku3": 0.5, "fuku": 0.28}

    odds_map = {s.horse_no: getattr(s, "odds", 0) or 0 for s in scores}
    ens_p, ml_p, score_p, market_p = ensemble_probabilities(scores)
    edges = compute_edges(ens_p, market_p)
    grade_info = race_betting_grade(edges, ens_p, odds_map)

    horse_nos = [s.horse_no for s in scores]
    n = len(horse_nos)

    out = {
        "win_bets": [], "place_bets": [],
        "exacta_bets": [], "quinella_bets": [], "trifecta_bets": [],
        "win_evs": {}, "exacta_evs": {}, "quinella_evs": {}, "trifecta_evs": {},
        "race_grade": grade_info,
        "kelly_alloc": {},     # {bet_key: fraction}
        "edges": edges,
        "ensemble_p": ens_p,
    }
    if n < 4:
        return out

    EDGE_MIN = 0.05  # 5% 以上の過小評価を狙う

    # --- 単勝 ---
    win_cands = []
    for no in horse_nos:
        p, o = ens_p.get(no, 0), odds_map.get(no, 0)
        e = edges.get(no, 0)
        if not (p and o): continue
        ev = p * o
        if ev >= ev_threshold and e >= EDGE_MIN:
            win_cands.append((ev, no, e))
            out["win_evs"][no] = round(ev, 2)
            out["kelly_alloc"][f"win_{no}"] = round(kelly_fraction(p, o), 4)
    win_cands.sort(reverse=True)
    out["win_bets"] = [no for _, no, _ in win_cands[:3]]

    # --- 複勝 ---
    place_cands = []
    for no in horse_nos:
        p, o = ens_p.get(no, 0), odds_map.get(no, 0)
        if not (p and o): continue
        p3 = min(0.85, p * 2.6)
        est_payout = max(1.1, o * COEF["fuku"])
        ev = p3 * est_payout
        if ev >= ev_threshold:
            place_cands.append((ev, no))
    place_cands.sort(reverse=True)
    out["place_bets"] = [no for _, no in place_cands[:5]]

    # --- 馬連（Plackett-Luce）---
    uren_cands = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = horse_nos[i], horse_nos[j]
            pa, pb = ens_p.get(a, 0), ens_p.get(b, 0)
            p_hit = pl_quinella_prob(pa, pb)
            oa, ob = odds_map.get(a, 0), odds_map.get(b, 0)
            if not (p_hit and oa and ob): continue
            est = oa * ob * COEF["uren"]
            ev = p_hit * est
            # マーケットエッジ（馬連市場暗示確率の近似 = pa*pb*市場補正）
            mp_uren = pl_quinella_prob(market_p.get(a, 0), market_p.get(b, 0))
            edge = (p_hit / mp_uren - 1) if mp_uren > 0 else 0
            if ev >= ev_threshold and edge >= EDGE_MIN:
                pair = tuple(sorted([a, b]))
                uren_cands.append((ev, pair, edge))
                out["exacta_evs"][pair] = round(ev, 2)
    uren_cands.sort(reverse=True)
    out["exacta_bets"] = [pair for _, pair, _ in uren_cands[:8]]

    # --- ワイド ---
    wide_cands = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = horse_nos[i], horse_nos[j]
            pa, pb = ens_p.get(a, 0), ens_p.get(b, 0)
            p_hit = pl_wide_prob(pa, pb, list(ens_p.values()))
            oa, ob = odds_map.get(a, 0), odds_map.get(b, 0)
            if not (p_hit and oa and ob): continue
            est = max(1.5, oa * ob * COEF["wide"])
            ev = p_hit * est
            if ev >= ev_threshold:
                pair = tuple(sorted([a, b]))
                wide_cands.append((ev, pair))
                out["quinella_evs"][pair] = round(ev, 2)
    wide_cands.sort(reverse=True)
    out["quinella_bets"] = [pair for _, pair in wide_cands[:8]]

    # --- 3連複（Plackett-Luce）---
    top_p = sorted(ens_p.items(), key=lambda x: -x[1])[:7]
    top_nos = [no for no, _ in top_p]
    fuku3_cands = []
    seen = set()
    for i in range(len(top_nos)):
        for j in range(i + 1, len(top_nos)):
            for k in range(n):
                c = horse_nos[k]
                a, b = top_nos[i], top_nos[j]
                if c in (a, b): continue
                triple = tuple(sorted([a, b, c]))
                if triple in seen: continue
                pa, pb, pc = ens_p.get(a, 0), ens_p.get(b, 0), ens_p.get(c, 0)
                p_hit = pl_trifecta_prob(pa, pb, pc)
                oa, ob, oc = odds_map.get(a, 0), odds_map.get(b, 0), odds_map.get(c, 0)
                if not (p_hit and oa and ob and oc): continue
                est = oa * ob * oc * COEF["fuku3"]
                ev = p_hit * est
                mp_a, mp_b, mp_c = market_p.get(a, 0), market_p.get(b, 0), market_p.get(c, 0)
                mp_trip = pl_trifecta_prob(mp_a, mp_b, mp_c)
                edge = (p_hit / mp_trip - 1) if mp_trip > 0 else 0
                if ev >= ev_threshold and edge >= EDGE_MIN:
                    seen.add(triple)
                    fuku3_cands.append((ev, triple, edge))
                    out["trifecta_evs"][triple] = round(ev, 2)
    fuku3_cands.sort(reverse=True)
    out["trifecta_bets"] = [t for _, t, _ in fuku3_cands[:10]]

    return out


if __name__ == "__main__":
    print("deep_ev_analyzer ready: ensemble probs + Plackett-Luce + Kelly + race grading")
